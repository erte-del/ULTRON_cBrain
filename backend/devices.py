"""The machines on your tailnet that Ultron may open a terminal on (devices.json).

Each device is reached with plain OpenSSH over Tailscale: key login only, no passwords, no
forwarding. Nothing new listens anywhere: the target's own sshd does the work, and its
firewall should only allow Tailscale (see REMOTE_TERMINAL_SETUP.md).

devices.json (copy devices.example.json):
  {"devices": [{"name": "mac-mini", "local": true},
               {"name": "windows-pc", "aliases": ["pc"], "os": "windows",
                "host": "windows-pc", "user": "you"}]}
Fields: name, aliases[], os (mac | linux | windows), host (Tailscale name or 100.x address),
user, port (22), key (path of a private key file), tmux (true: the session survives a closed
tab; Mac and Linux targets only, ignored where tmux isn't installed), local (true: this
computer, no SSH).
"""

import ipaddress
import json
import logging
import re
import shlex
import shutil
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path

import config

log = logging.getLogger("ultron.devices")

DEVICES_FILE = config.BACKEND_DIR / "devices.json"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")
OSES = {"mac", "linux", "windows"}
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's addresses (CGNAT range)
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

# Devices opened lately (monotonic seconds): opening one that isn't here asks you first.
_opened: dict[str, float] = {}


@dataclass(frozen=True)
class Device:
    name: str
    os: str = "mac"
    host: str = ""
    user: str = ""
    port: int = 22
    key: str = ""
    tmux: bool = True
    local: bool = False
    aliases: tuple[str, ...] = field(default_factory=tuple)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def load() -> list[Device]:
    """Every device in devices.json. ValueError (readable) if the file is wrong."""
    try:
        raw = json.loads(DEVICES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("No devices.json yet: copy backend/devices.example.json to backend/devices.json "
                         "and edit it.") from None
    except (OSError, ValueError) as e:
        raise ValueError(f"devices.json can't be read: {e}") from None
    devices = []
    for item in raw.get("devices", []) if isinstance(raw, dict) else []:
        try:
            name = str(item["name"])
            local = item.get("local") is True
            os_ = str(item.get("os", "mac")).lower()
            host, user = str(item.get("host", "")), str(item.get("user", ""))
            port = int(item.get("port", 22))
            if not NAME.fullmatch(name) or os_ not in OSES or not 0 < port < 65536:
                raise ValueError("bad name, os or port")
            if not local and not (NAME.fullmatch(host) and USER.fullmatch(user)):
                raise ValueError("needs a host (Tailscale name or address) and a user")
            devices.append(Device(
                name=name, os=os_, host=host, user=user, port=port, key=str(item.get("key", "")),
                tmux=item.get("tmux", True) is True and os_ != "windows", local=local,
                aliases=tuple(str(a) for a in item.get("aliases", []))))
        except (KeyError, TypeError, ValueError) as e:
            log.warning("devices.json: skipped %r (%s)", item, e)
    return devices


def find(wanted: str) -> Device:
    """The device called (or aliased) `wanted`, ignoring case, spaces and dashes.
    ValueError saying what's available if there's none."""
    devices = load()
    want = _key(wanted)
    for d in devices:
        if want and want in {_key(d.name), *map(_key, d.aliases)}:
            return d
    names = ", ".join(d.name for d in devices) or "none set up"
    raise ValueError(f"No device called {wanted!r}. Devices: {names}.")


def on_tailnet(host: str) -> bool:
    """Whether `host` is a Tailscale address, or a name that only resolves to them. This is
    what keeps a mistyped (or tampered) devices.json from sending a login to the open internet."""
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(info[4][0].split("%")[0])
                         for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)}
        except (OSError, ValueError):
            return False
    return bool(addresses) and all(a in TAILNET_V4 or a in TAILNET_V6 for a in addresses)


def ssh_command(d: Device, number: int, claude: bool) -> list[str]:
    """The argv that opens an interactive shell on `d` (never a local shell: d.local has none).
    ValueError if it can't be done safely."""
    if d.local:
        raise ValueError(f"{d.name} is this computer: no SSH needed")
    ssh = shutil.which("ssh")
    if not ssh:
        raise ValueError("ssh isn't installed on this computer.")
    if not on_tailnet(d.host):
        raise ValueError(f"{d.host} isn't a Tailscale address (100.x.y.z, or a name that resolves to one): "
                         "Ultron only connects over Tailscale. Check devices.json and that Tailscale is on.")
    argv = [
        ssh, "-tt", "-F", "/dev/null",  # only the options here: nothing from ~/.ssh/config
        "-e", "none",  # no "~." / "~C" escapes (~C could add port forwards)
        "-p", str(d.port), "-l", d.user,
        "-o", "BatchMode=yes", "-o", "PreferredAuthentications=publickey",
        "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
        "-o", "StrictHostKeyChecking=accept-new",  # trust a host the first time, refuse if it changes
        "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no", "-o", "ForwardX11=no",
        "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
    ]
    if d.key:
        key = Path(d.key).expanduser()
        if not key.is_file():
            raise ValueError(f"The SSH key for {d.name} isn't there: {key}")
        argv += ["-i", str(key), "-o", "IdentitiesOnly=yes"]
    argv += ["--", d.host]
    if remote := remote_command(d, number, claude):
        argv.append(remote)
    return argv


def remote_command(d: Device, number: int, claude: bool) -> str:
    """What the far side runs instead of its plain login shell ("" = just the shell)."""
    if d.os == "windows":  # Windows' default shell may be cmd or PowerShell: powershell is in both
        return "powershell -NoLogo -NoExit -Command claude" if claude else ""
    # Mac / Linux: a login shell (so PATH is yours), in tmux when it's there, so a closed tab
    # or dropped Wi-Fi only detaches. Claude Code starts only when the session is new.
    inner = 'claude; exec "$SHELL" -l' if claude else ""
    session = f"ultron-{_key(d.name)}-{number}"
    tmux = f"exec tmux new-session -A -s {session}" + (f" {shlex.quote(inner)}" if inner else "")
    plain = inner or 'exec "$SHELL" -l'
    script = f"command -v tmux >/dev/null && {tmux} \\; set-option status off || {plain}" if d.tmux else plain
    return 'exec "$SHELL" -lc ' + shlex.quote(script)


def needs_confirmation(name: str) -> bool:
    """Opening `name` asks first unless it's this computer or was opened lately."""
    try:
        d = find(name)
    except ValueError:
        return False  # the tool says so; nothing to approve
    if d.local:
        return False
    last = _opened.get(d.name)
    return last is None or time.monotonic() - last > config.REMOTE_TRUST_MIN * 60


def mark_opened(d: Device) -> None:
    _opened[d.name] = time.monotonic()
