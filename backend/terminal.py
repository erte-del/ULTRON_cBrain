"""/ws/terminal: a real shell in a canvas tab, for you to type in (e.g. to run Claude Code).

Ultron can open the tab (open_terminal) and read what it shows (read_terminal: the page
sends a plain-text snapshot of the screen after output settles), but never types in it:
the shell only gets what you type in that tab. Only pages on this Mac may connect, not your phone through
Tailscale: a shell is more than the rest of Ultron can do.

The shell lives as long as the tab's connection: closing the tab or reloading the
page ends it.
"""

import asyncio
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import subprocess
import termios
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

import config

log = logging.getLogger("ultron.terminal")

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


async def serve(ws: WebSocket) -> None:
    origin = ws.headers.get("origin")
    if origin not in LOCAL_ORIGINS:
        log.warning("Rejected terminal from origin %r", origin)
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        number = int(ws.query_params.get("n", "0"))
    except ValueError:
        number = 0

    master, slave = pty.openpty()
    shell = os.environ.get("SHELL") or "/bin/zsh"
    # A login shell, so PATH etc. come from your profile (Ultron.app starts without them).
    # Plain Popen, not asyncio's: under uvicorn's uvloop, preexec_fn runs before the new
    # session and the pty are set up, so taking the terminal fails.
    try:
        proc = subprocess.Popen(
            [shell, "-l"],
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
