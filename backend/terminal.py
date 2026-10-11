"""/ws/terminal: a real shell in a canvas tab, for you to type in (e.g. to run Claude Code).

Ultron can open the tab (open_terminal) and read what it shows (read_terminal: the page
sends a plain-text snapshot of the screen after output settles), but never types in it:
the shell only gets what you type in that tab. Pages on this Mac may connect, and so may
your own Tailscale login (JARVIS_TERMINAL_USER) from your other devices, e.g. your MacBook
at school. Other tailnet logins are refused. Your phone and PC pass too, since they're signed in
as you; a Tailscale ACL is the way to keep them out.

If tmux is installed, the shell runs inside a tmux session named after the tab. Closing the tab
or losing the network only detaches it: reopen the tab and you're back where you were, with
Claude still running. Type `exit` to end the session. Without tmux, closing the tab ends the shell.
Mac (and Linux) only: on Windows the tab says so and closes.
"""

import asyncio
import json
import logging
import os
import signal
import struct
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
if not WINDOWS:  # Unix-only modules: importing them on Windows would stop Ultron starting
    import fcntl
    import pty
    import termios

from fastapi import WebSocket, WebSocketDisconnect

import config

log = logging.getLogger("ultron.terminal")
if not WINDOWS and not shutil.which("tmux"):
    log.info("tmux not installed: terminals end when their tab closes (brew install tmux)")

# Ultron's pages on this Mac: the dev server (npm run dev) and the built page (Ultron.app).
LOCAL_ORIGINS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}
# Terminal tab number -> its latest screen text, while its shell is open.
SCREENS: dict[int, str] = {}
MAX_SCREEN = 100_000  # characters kept per terminal


def _shell_env() -> dict[str, str]:
    """Your normal environment, without the variables that point Ultron's own Claude Code
    at the gateway: `claude` in the terminal uses your own login."""
    env = {k: v for k, v in os.environ.items() if k not in config.CLAUDE_ENV_VARS}
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    return env


def _take_terminal() -> None:
    """In the shell's process, before it starts: make the pty its terminal, so Ctrl-C
    and job control work."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _resize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def may_connect(origin: str | None, login: str | None, funnel: bool = False) -> bool:
    """This Mac's own pages, or your Tailscale login from another device. `tailscale serve`
    sets the login header itself, so a tailnet request can't fake it. Funnel (the public
    internet) carries no real login, so it's refused outright."""
    if origin in LOCAL_ORIGINS:
        return True
    if funnel:
        return False
    return bool(
        config.REMOTE_ORIGIN and config.TERMINAL_USER
        and origin == config.REMOTE_ORIGIN
        and login and login.strip().lower() == config.TERMINAL_USER
    )


def shell_command(shell: str, number: int) -> list[str]:
    """A login shell, or the same shell inside a tmux session that survives the tab closing.
    Ultron's own tmux server (-L ultron): it starts with the tab's filtered environment and
    never mixes with your own tmux sessions."""
    tmux = shutil.which("tmux")
    if not tmux:
        return [shell, "-l"]
    return [tmux, "-L", "ultron", "new-session", "-A", "-s", f"term-{number}", shell, "-l"]  # -A: attach if it exists


async def serve(ws: WebSocket) -> None:
    origin = ws.headers.get("origin")
    if not may_connect(origin, ws.headers.get("tailscale-user-login"), "tailscale-funnel-request" in ws.headers):
        log.warning("Rejected terminal from origin %r", origin)
        await ws.close(code=1008)
        return
    await ws.accept()
    if WINDOWS:
        await ws.send_bytes("The terminal tab isn't available on Windows yet.\r\n".encode())
        await ws.close()
        return
    try:
        number = min(max(int(ws.query_params.get("n", "0")), 0), 99)
    except ValueError:
        number = 0

    master, slave = pty.openpty()
    shell = os.environ.get("SHELL") or "/bin/zsh"
    # A login shell, so PATH etc. come from your profile (Ultron.app starts without them).
    # Plain Popen, not asyncio's: under uvicorn's uvloop, preexec_fn runs before the new
    # session and the pty are set up, so taking the terminal fails.
    try:
        proc = subprocess.Popen(
            shell_command(shell, number),
            stdin=slave, stdout=slave, stderr=slave,
            cwd=Path.home(), env=_shell_env(),
            start_new_session=True, preexec_fn=_take_terminal,
        )
    except OSError:
        os.close(master)
        raise
    finally:
        os.close(slave)
    log.info("Terminal opened (pid %d)", proc.pid)

    loop = asyncio.get_running_loop()
    output: asyncio.Queue[bytes | None] = asyncio.Queue()

    def readable() -> None:
        try:
            data = os.read(master, 65536)
        except OSError:  # EIO: the shell has exited
            data = b""
        if not data:
            loop.remove_reader(master)
        output.put_nowait(data or None)

    loop.add_reader(master, readable)

    async def pump() -> None:
        while (data := await output.get()) is not None:
            await ws.send_bytes(data)
        await ws.close()  # you typed `exit`

    pumping = asyncio.create_task(pump())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "input":
                # ponytail: blocking write; fine for typing and normal pastes, a huge paste
                # into a busy program could stall Ultron for a moment.
                os.write(master, str(msg.get("data", "")).encode())
            elif msg.get("type") == "resize":
                cols, rows = int(msg["cols"]), int(msg["rows"])
                if 0 < cols < 1000 and 0 < rows < 1000:
                    _resize(master, cols, rows)
            elif msg.get("type") == "screen" and number:
                SCREENS[number] = str(msg.get("text", ""))[-MAX_SCREEN:]
    except (WebSocketDisconnect, RuntimeError, OSError, ValueError, KeyError, TypeError):
        pass
    finally:
        SCREENS.pop(number, None)
        pumping.cancel()
        loop.remove_reader(master)
        try:
            os.killpg(proc.pid, signal.SIGHUP)  # the shell and everything started in it
        except OSError:  # already gone (macOS says EPERM while the exited shell isn't reaped)
            pass
        os.close(master)
        try:
            await asyncio.to_thread(proc.wait, 3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        log.info("Terminal closed")
