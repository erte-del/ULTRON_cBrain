"""Settings. Everything has a default; environment variables (ACC_*) override.

Thresholds below are starting points. Wheel-slip and slip-angle units are the game's own, so check
them on the first real session (README, smoke-test checklist) and adjust here or through the env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


def _env(name: str, default, cast=str):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("ACC_DATA_DIR", PROJECT_DIR / "data", Path)))
    host: str = field(default_factory=lambda: _env("ACC_HOST", "127.0.0.1"))   # never 0.0.0.0 by default
    port: int = field(default_factory=lambda: _env("ACC_PORT", 8765, int))
    trace_hz: float = field(default_factory=lambda: _env("ACC_TRACE_HZ", 30.0, float))      # lap traces
    summary_hz: float = field(default_factory=lambda: _env("ACC_SUMMARY_HZ", 10.0, float))  # live state, alerts
    ring_laps: int = field(default_factory=lambda: _env("ACC_RING_LAPS", 10, int))          # laps kept in memory
    points: int = 500                                                                      # samples per saved lap

    # --- event detection (see events.py) ---
    brake_on: float = 0.10          # brake pedal above this counts as braking
    lockup_slip: float = -0.35      # slip ratio below this while braking = locked wheel
    wheelspin_slip: float = 0.35    # driven-wheel slip ratio above this under power
    slide_angle: float = 0.22       # rear slip angle (game units, radians) above this = big slide
    curb_vibration: float = 0.45    # kerbVibration above this = curb hit
    tyres_out_offtrack: int = 3     # this many tyres off the circuit = off track

    # --- tyre and fuel flags (GT3 rules of thumb; tune per car) ---
    tyre_temp_cold: float = 70.0
    tyre_temp_hot: float = 105.0
    tyre_psi_low: float = 26.0
    tyre_psi_high: float = 28.2

    # --- alerts (phase 2) ---
    alert_fuel_laps: float = 3.0
    alert_delta_loss_s: float = 0.6

    @property
    def db_path(self) -> Path:
        return self.data_dir / "laps.sqlite3"

    @property
    def user_tracks_dir(self) -> Path:
        return self.data_dir / "tracks"
