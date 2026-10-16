"""Driving events found live from the telemetry stream: lockups, wheelspin, slides, off-tracks, curbs.

Each kind has a trigger (a condition on one Frame) and a minimum duration, so a single noisy
sample doesn't count. An event is reported when its condition ends, with the position where it
started, the corner there, how long it lasted and its peak. Thresholds live in config.Settings.
"""

from __future__ import annotations

from typing import Optional

from .acc_shm import Frame
from .config import Settings

# kind: (minimum duration in seconds, same-kind cooldown in seconds)
KINDS = {"lockup": (0.12, 1.0), "wheelspin": (0.20, 1.0), "slide": (0.25, 1.5),
         "offtrack": (0.30, 2.0), "curb": (0.08, 0.6)}


def _conditions(f: Frame, cfg: Settings) -> dict:
    """kind -> peak magnitude while the condition holds, absent otherwise."""
    out = {}
    if f.brake > 3 * cfg.brake_on and f.speed_kmh > 40 and min(f.slip_ratio) < cfg.lockup_slip:
        out["lockup"] = -min(f.slip_ratio)
    if f.gas > 0.5 and f.speed_kmh > 20 and max(f.slip_ratio[2], f.slip_ratio[3]) > cfg.wheelspin_slip:
        out["wheelspin"] = max(f.slip_ratio[2], f.slip_ratio[3])
    rear_angle = max(abs(f.slip_angle[2]), abs(f.slip_angle[3]))
    if f.speed_kmh > 40 and rear_angle > cfg.slide_angle:
        out["slide"] = rear_angle
    if f.tyres_out >= cfg.tyres_out_offtrack and f.speed_kmh > 20:
        out["offtrack"] = float(f.tyres_out)
    if f.kerb_vib > cfg.curb_vibration:
        out["curb"] = f.kerb_vib
    return out


class EventDetector:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._open: dict = {}        # kind -> running event
        self._last_emit: dict = {}   # kind -> frame time of the last report

    def feed(self, f: Frame, lap: int, corner: Optional[str]) -> list:
        """Events that ended with this frame."""
        now = _conditions(f, self.cfg)
        done = []
        for kind, peak in now.items():
            ev = self._open.get(kind)
            if ev is None:
                self._open[kind] = {"type": kind, "lap": lap, "pos": f.pos, "corner": corner,
                                    "lap_time_s": f.current_ms / 1000, "t0": f.t, "peak": peak}
            else:
                ev["peak"] = max(ev["peak"], peak)
        for kind in [k for k in self._open if k not in now]:
            ev = self._open.pop(kind)
            done.extend(self._close(ev, f.t))
        return done

    def flush(self, t: float) -> list:
        """End everything still open (lap or session ended)."""
        done = []
        for kind in list(self._open):
            done.extend(self._close(self._open.pop(kind), t))
        return done

    def _close(self, ev: dict, t: float) -> list:
        min_dur, cooldown = KINDS[ev["type"]]
        dur = t - ev.pop("t0")
        if dur < min_dur or t - self._last_emit.get(ev["type"], -1e9) < cooldown:
            return []
        self._last_emit[ev["type"]] = t
        ev["duration_s"] = round(dur, 2)
        ev["peak"] = round(ev["peak"], 2)
        ev["pos"] = round(ev["pos"], 4)
        ev["lap_time_s"] = round(ev["lap_time_s"], 1)
        ev["severity"] = "major" if dur >= 3 * min_dur else "minor"
        return [ev]
