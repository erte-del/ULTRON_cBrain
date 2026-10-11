"""Is someone at this computer? Seconds since the last key press or mouse move."""

import ctypes
import re
import subprocess
import sys


def idle_seconds() -> float | None:
    """None if it can't be told (callers then treat the user as there)."""
    try:
        if sys.platform == "win32":
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
            return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=5).stdout
        return int(re.search(r'"HIDIdleTime" = (\d+)', out).group(1)) / 1e9
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        return None


def active(within_s: float = 120) -> bool:
    idle = idle_seconds()
    return idle is None or idle <= within_s
