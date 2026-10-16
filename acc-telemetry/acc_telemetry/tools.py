"""The telemetry service: every question the MCP tools and the dashboard ask, answered compactly.

Each public method returns a small JSON-able dict (summaries first; traces only when asked for)
so the MCP server and /api/tool/<name> are thin wrappers over the same code.
"""

from __future__ import annotations

from typing import Optional, Union

from . import analysis
from .acc_shm import FLAG_NAMES, GRIP_NAMES, RAIN_NAMES, SESSION_NAMES, STATUS_LIVE, Frame
from .config import Settings
from .sampler import Sampler
from .store import Store, fmt_ms
from .tracks import Track, auto_track, load_track

WHEELS = ("FL", "FR", "RL", "RR")
LapRef = Union[int, str, None]
r1, r2 = (lambda x: analysis.rnd(x, 1)), (lambda x: analysis.rnd(x, 2))


def _wheels(values, f=r1) -> dict:
    return {w: f(v) for w, v in zip(WHEELS, values)}


def _slope(ys: list) -> Optional[float]:
    """Least-squares slope per step; None with fewer than 3 points."""
    n = len(ys)
    if n < 3:
        return None
    mx, my = (n - 1) / 2, sum(ys) / n
    den = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / den


class Telemetry:
    def __init__(self, sampler: Sampler, store: Store, cfg: Settings):
        self.sampler, self.store, self.cfg = sampler, store, cfg
        self._auto: dict = {}

    # --- helpers ----------------------------------------------------------------------------

    def _context(self) -> tuple:
        """(track, car) of the live session, else of the most recent saved lap."""
        f = self.sampler.latest
        if f and f.track:
            return f.track, f.car
        last = self.store.list_laps(limit=1)
        return (last[0]["track"], last[0]["car"]) if last else (None, None)

    def track_for(self, track_name: str, car: Optional[str], length_m: float, fallback_trace: dict) -> Track:
        """The track's corner table; for tracks without a file, corners found on the best lap (cached)."""
        t = load_track(track_name, self.cfg.user_tracks_dir)
        if t:
            return t
        key = (track_name.lower(), car)
        if key not in self._auto:
            best = self.store.best_lap(track_name, car)
            self._auto[key] = auto_track(track_name, (best["trace"] if best else fallback_trace)["speed"], length_m)
        return self._auto[key]

    def resolve_lap(self, ref: LapRef, with_trace: bool = True) -> Optional[dict]:
        """A lap id, or 'last' / 'previous' / 'best' on the current track and car."""
        if isinstance(ref, str) and ref.strip().lstrip("-").isdigit():
            ref = int(ref)
        if isinstance(ref, int):
            return self.store.get_lap(ref, with_trace)
        track, car = self._context()
        word = (ref or "last").strip().lower()
        if word == "best":
            return self.store.best_lap(track, car, with_trace) if track else None
        laps = self.store.list_laps(track, car, limit=2)
        if word in ("last", "latest"):
            return self.store.get_lap(laps[0]["id"], with_trace) if laps else None
        if word in ("previous", "prev"):
            return self.store.get_lap(laps[1]["id"], with_trace) if len(laps) > 1 else None
        return None

    def _lap_head(self, lap: dict) -> dict:
        return {"id": lap["id"], "lap_number": lap["lap_number"], "lap_time": lap["lap_time"], "valid": lap["valid"],
                "clean": lap["clean"], "track": lap["track"], "car": lap["car"]}

    @staticmethod
    def _corner_row(c: dict) -> dict:
        return {k: c[k] for k in ("name", "entry_kmh", "min_kmh", "brake_dist_m", "brake_peak", "trail_s",
                                  "throttle_pickup_pos", "peak_lat_g", "peak_lon_g", "time_s")}

    # --- live ---------------------------------------------------------------------------------

    def _not_live(self) -> Optional[dict]:
        s, f = self.sampler, self.sampler.latest
        if f is None or s.status in ("acc_not_running", "starting"):
            return {"running": False, "status": s.status, "message": s.message if s.status != "starting" else "Starting up; no data yet."}
        if f.status != STATUS_LIVE:
            return {"running": True, "live": False, "status": s.status, "message": s.message}
        return None

    def get_live_state(self) -> dict:
        """Speed, gear, RPM, pedals, tyre temps and pressures, fuel, lap, position, corner, delta to best."""
        if (nl := self._not_live()) is not None:
            return nl
        s, f = self.sampler, self.sampler.latest
        burn = s.fuel_per_lap()
        delta = s.live_delta(f)
        return {
            "running": True, "live": True, "track": f.track, "car": f.car,
            "lap": s.builder.lap_index + 1, "lap_time": fmt_ms(f.current_ms), "lap_pos": analysis.rnd(f.pos, 4),
            "corner": s.track.name_at(f.pos) if s.track else None, "valid_lap": f.valid_lap,
            "speed_kmh": round(f.speed_kmh), "gear": f.gear, "rpm": f.rpm,
            "throttle": r2(f.gas), "brake": r2(f.brake), "steer": analysis.rnd(f.steer, 3),
            "tc_active": r2(f.tc), "abs_active": r2(f.abs), "g_lat": r2(f.g_lat), "g_lon": r2(f.g_lon),
            "tyre_temp_c": _wheels(f.tyre_temp), "tyre_psi": _wheels(f.tyre_pressure, r2),
            "brake_temp_c": _wheels(f.brake_temp, lambda v: round(v)),
            "fuel_l": r1(f.fuel), "fuel_burn_per_lap_l": r2(burn),
            "fuel_laps_left": r1(f.fuel / burn) if burn else (r1(f.fuel_est_laps) if f.fuel_est_laps else None),
            "delta_to_best_s": analysis.rnd(delta, 3) if delta is not None else (analysis.rnd(f.delta_ms / 1000, 3) if f.delta_ms else None),
            "delta_source": "best saved lap" if delta is not None else "game",
            "best_lap": fmt_ms(f.best_ms), "last_lap": fmt_ms(f.last_ms), "race_position": f.position, "in_pit": f.in_pit,
        }

    def get_session_info(self) -> dict:
        """Track, car, session type, weather and temperatures, laps done."""
        s, f = self.sampler, self.sampler.latest
        track, car = self._context()
        saved = len(self.store.list_laps(track, car, limit=1000)) if track else 0
        out = {"track": track, "car": car, "laps_saved_for_this_combo": saved, "status": s.status}
        if f is None or s.status == "acc_not_running":
            out.update(running=False, message=s.message)
            return out
        out.update({
            "running": True, "player": f.player, "session": SESSION_NAMES.get(f.session, "?"),
            "session_time_left_s": round(f.session_time_left) if f.session_time_left > 0 else None,
            "race_laps": f.number_of_laps or None, "laps_done": f.completed_laps, "position": f.position,
            "air_c": r1(f.air_temp), "road_c": r1(f.road_temp),
            "rain": RAIN_NAMES.get(f.rain_intensity, "?"), "track_grip": GRIP_NAMES.get(f.track_grip, "?"),
            "wind_kmh": r1(f.wind_speed), "flag": FLAG_NAMES.get(f.flag, "?"), "tyre_compound": f.tyre_compound,
            "tc_level": f.tc_level, "abs_level": f.abs_level, "engine_map": f.engine_map, "brake_bias_pct": r1(f.brake_bias),
            "session_best": fmt_ms(f.best_ms), "last_lap": fmt_ms(f.last_ms), "track_known": bool(track and load_track(track, self.cfg.user_tracks_dir)),
        })
        return out

    # --- laps ---------------------------------------------------------------------------------

    def list_laps(self, track: Optional[str] = None, car: Optional[str] = None, limit: int = 20) -> dict:
        """Saved laps, newest first (id, lap time, sectors, validity)."""
        laps = self.store.list_laps(track, car, limit=max(1, min(limit, 100)))
        best = min((l["lap_time_ms"] for l in laps if l["clean"] and l["valid"]), default=None)
        return {"count": len(laps), "laps": [
            {"id": l["id"], "lap": l["lap_number"], "time": l["lap_time"], "sectors": [fmt_ms(x) for x in l["sectors_ms"]],
             "valid": l["valid"], "clean": l["clean"], "best_of_these": l["lap_time_ms"] == best, "track": l["track"],
             "car": l["car"], "at": l["created_at"]} for l in laps]}

    def get_lap(self, lap_id: LapRef, include_trace: bool = False, channels: Optional[list] = None, points: int = 60) -> dict:
        """One lap: times, per-corner numbers, events. A thinned trace only if include_trace."""
        lap = self.resolve_lap(lap_id)
        if lap is None:
            return {"error": f"No lap {lap_id!r} found. Use list_laps."}
        trace = lap["trace"]
        track = self.track_for(lap["track"], lap["car"], lap["length_m"], trace)
        out = {**self._lap_head(lap), "sectors": [fmt_ms(x) for x in lap["sectors_ms"]], "compound": lap["compound"],
               "fuel_used_l": r2(lap["fuel_start"] - lap["fuel_end"]) if lap["fuel_start"] > lap["fuel_end"] else None,
               "air_c": lap["air_temp"], "road_c": lap["road_temp"], "events": lap["events"][:15],
               "corners": [self._corner_row(c) for c in analysis.lap_corners(trace, track, lap["length_m"], self.cfg.brake_on)]}
        if include_trace:
            out["trace"] = analysis.downsample(trace, min(max(points, 2), 200), channels or ["speed", "throttle", "brake"])
        return out

    def get_last_lap_summary(self, lap_id: LapRef = None) -> dict:
        """Lap and sector times, then per corner: entry speed, minimum speed, brake point, throttle pickup, peak G."""
        lap = self.resolve_lap(lap_id or "last")
        if lap is None:
            return {"error": "No saved laps yet. Complete a lap first."}
        out = self.get_lap(lap["id"])
        best = self.store.best_lap(lap["track"], lap["car"])
        if best and best["id"] != lap["id"]:
            out["vs_best_s"] = analysis.rnd(lap["trace"]["t"][-1] - best["trace"]["t"][-1], 3)
            out["best_lap"] = best["lap_time"]
        elif best:
            out["is_best_lap"] = True
        out["brake_dist_m_note"] = "metres before the corner's apex where braking started"
        return out

    def compare_laps(self, lap_a: LapRef = "last", lap_b: LapRef = "best") -> dict:
        """Where lap A gained or lost time against lap B, by sector, corner and straight. Delta > 0: A slower."""
        a, b = self.resolve_lap(lap_a), self.resolve_lap(lap_b)
        if a is None or b is None:
            return {"error": "Need two saved laps: " + ", ".join(n for n, x in (("lap_a", a), ("lap_b", b)) if x is None) + " not found."}
        if a["id"] == b["id"]:
            return {"error": "Both laps are the same lap.", "lap": self._lap_head(a)}
        length = a["length_m"] or b["length_m"]
        track = self.track_for(a["track"], a["car"], length, b["trace"])
        res = analysis.compare(a["trace"], b["trace"], track, length, self.cfg.brake_on)
        table = {r["corner"]: r for r in analysis.braking_table(a["trace"], b["trace"], track, length, self.cfg.brake_on)}
        for row in res["biggest"]:
            t = table.get(row["name"])
            if t:
                row["a"] = {k: t["a"][k] for k in ("brake_dist_m", "brake_peak", "trail_s", "throttle_pickup_pos")}
                row["b"] = {k: t["b"][k] for k in ("brake_dist_m", "brake_peak", "trail_s", "throttle_pickup_pos")}
        res.update({"lap_a": self._lap_head(a), "lap_b": self._lap_head(b), "positive_means": "lap A slower than lap B"})
        if a["track"] != b["track"] or a["car"] != b["car"]:
            res["warning"] = "These laps are from different tracks or cars."
        return res

    # --- tyres, fuel, events ---------------------------------------------------------------------

    def get_tyre_report(self) -> dict:
        """Temps and pressures by corner of the car, hot/cold flags, and how they trend over the last laps."""
        cfg = self.cfg
        track, car = self._context()
        laps = list(reversed(self.store.list_laps(track, car, limit=8, clean_only=True))) if track else []
        trend = {}
        if laps:
            temps = [l["meta"].get("tyre_temp_avg") for l in laps if l["meta"].get("tyre_temp_avg")]
            psis = [l["meta"].get("tyre_psi_avg") for l in laps if l["meta"].get("tyre_psi_avg")]
            for i, w in enumerate(WHEELS):
                st = _slope([t[i] for t in temps])
                sp = _slope([p[i] for p in psis])
                trend[w] = {"temp_c_per_lap": analysis.rnd(st, 2), "psi_per_lap": analysis.rnd(sp, 3)}
        times = [l["lap_time_ms"] / 1000 for l in laps]
        pace = _slope(times)
        out = {"laps_considered": len(laps), "trend_per_lap": trend or None,
               "pace_trend_s_per_lap": analysis.rnd(pace, 3),
               "wear_note": "ACC doesn't publish tyre wear in shared memory; use the temp/pressure trend and the pace trend."}
        if (nl := self._not_live()) is None:
            f = self.sampler.latest
            flags = {}
            for i, w in enumerate(WHEELS):
                t, p = f.tyre_temp[i], f.tyre_pressure[i]
                flags[w] = {"temp_c": r1(t), "psi": r2(p),
                            "temp": "cold" if t < cfg.tyre_temp_cold else "hot" if t > cfg.tyre_temp_hot else "ok",
                            "pressure": "low" if p < cfg.tyre_psi_low else "high" if p > cfg.tyre_psi_high else "ok"}
            out.update(live=True, compound=f.tyre_compound, now=flags, brake_temp_c=_wheels(f.brake_temp, lambda v: round(v)))
        else:
            out.update(live=False, message=nl["message"])
            if laps:
                out["last_lap_averages"] = {"temp_c": _wheels(laps[-1]["meta"].get("tyre_temp_avg", [0] * 4)),
                                            "psi": _wheels(laps[-1]["meta"].get("tyre_psi_avg", [0] * 4), r2)}
        out["limits"] = {"temp_c": [cfg.tyre_temp_cold, cfg.tyre_temp_hot], "psi": [cfg.tyre_psi_low, cfg.tyre_psi_high]}
        return out

    def get_fuel_report(self) -> dict:
        """Burn per lap, laps remaining, and whether (and when) a stop is needed."""
        s, f = self.sampler, self.sampler.latest
        track, car = self._context()
        recent = [l for l in reversed(self.store.list_laps(track, car, limit=6, clean_only=True))
                  if l["fuel_start"] > l["fuel_end"] > 0] if track else []
        burns = [round(l["fuel_start"] - l["fuel_end"], 2) for l in recent]
        avg = sum(burns[-4:]) / len(burns[-4:]) if burns else None
        out = {"burn_per_lap_l": burns, "average_burn_l": r2(avg)}
        if f is None or s.status == "acc_not_running":
            out.update(live=False, message=s.message)
            return out
        burn = avg or (f.fuel_per_lap or None)
        out.update(live=f.status == STATUS_LIVE, fuel_l=r1(f.fuel), tank_l=r1(f.max_fuel),
                   laps_remaining=r1(f.fuel / burn) if burn else None, burn_source="saved laps" if avg else "game estimate")
        to_go = None
        if f.number_of_laps > 0:
            to_go = max(0, f.number_of_laps - f.completed_laps)
        elif f.session_time_left > 0 and f.last_ms > 0:
            to_go = f.session_time_left * 1000 / f.last_ms + 1
        if burn and to_go is not None:
            need = to_go * burn
            out.update(laps_to_finish=r1(to_go), fuel_to_finish_l=r1(need), short_by_l=r1(max(0.0, need - f.fuel)),
                       stop_needed=need > f.fuel)
        if f.pit_window_start or f.pit_window_end:
            out["pit_window_min"] = [f.pit_window_start, f.pit_window_end]
            out["session_time_left_s"] = round(f.session_time_left)
        return out

    def get_recent_events(self, limit: int = 12, lap: Optional[int] = None, kind: Optional[str] = None) -> dict:
        """Lockups, wheelspin, off-tracks, big slides, curb hits, with lap position and corner."""
        evs = list(self.sampler.events)
        source = "this run"
        if not evs:
            track, car = self._context()
            last = self.store.last_lap(track, car, with_trace=False) if track else None
            if last:
                evs, source = last["events"], f"saved lap {last['id']}"
        if lap is not None:
            evs = [e for e in evs if e["lap"] == lap]
        if kind:
            evs = [e for e in evs if e["type"] == kind]
        evs = evs[-max(1, min(limit, 50)):]
        return {"source": source, "count": len(evs), "events": [
            {"lap": e["lap"], "type": e["type"], "corner": e.get("corner"), "lap_pos": e["pos"], "at_lap_time_s": e["lap_time_s"],
             "duration_s": e["duration_s"], "peak": e["peak"], "severity": e["severity"]} for e in reversed(evs)]}

    # --- dashboard-only ----------------------------------------------------------------------------

    def lap_full(self, lap_id: int) -> Optional[dict]:
        lap = self.store.get_lap(lap_id)
        if lap is None:
            return None
        track = self.track_for(lap["track"], lap["car"], lap["length_m"], lap["trace"])
        lap["corners_metrics"] = analysis.lap_corners(lap["trace"], track, lap["length_m"], self.cfg.brake_on)
        lap["track_info"] = self.track_info(lap["track"], track)
        return lap

    def track_info(self, name: str, track: Optional[Track] = None) -> dict:
        track = track or load_track(name, self.cfg.user_tracks_dir)
        saved_map = self.store.get_track_map(name)
        if track is None:
            return {"name": name, "known": False, "corners": [], "segments": [], "map": saved_map or []}
        return {"name": track.name, "known": not track.auto, "length_m": track.length_m, "sectors": track.sectors,
                "corners": [{"name": c.name, "start": c.start, "apex": c.apex, "end": c.end, "direction": c.direction} for c in track.corners],
                "segments": [{"name": s.name, "start": s.start, "end": s.end, "kind": s.kind} for s in track.segments()],
                "map": saved_map or track.map_points}

    def compare_full(self, a_id: LapRef, b_id: LapRef) -> dict:
        a, b = self.resolve_lap(a_id), self.resolve_lap(b_id)
        if a is None or b is None:
            return {"error": "lap not found"}
        length = a["length_m"] or b["length_m"]
        track = self.track_for(a["track"], a["car"], length, b["trace"])
        res = analysis.compare(a["trace"], b["trace"], track, length, self.cfg.brake_on, top=50)
        return {"a": self._lap_head(a), "b": self._lap_head(b), "summary": res,
                "delta": [round(x, 3) for x in analysis.delta_curve(a["trace"], b["trace"])],
                "braking": analysis.braking_table(a["trace"], b["trace"], track, length, self.cfg.brake_on),
                "track_info": self.track_info(a["track"], track)}

    # --- dispatch (used by /api/tool/<name>) -------------------------------------------------------

    NAMES = ("get_live_state", "get_session_info", "get_last_lap_summary", "compare_laps", "get_tyre_report",
             "get_fuel_report", "get_recent_events", "list_laps", "get_lap")

    def call(self, name: str, **kwargs) -> dict:
        if name not in self.NAMES:
            raise KeyError(name)
        return getattr(self, name)(**kwargs)
