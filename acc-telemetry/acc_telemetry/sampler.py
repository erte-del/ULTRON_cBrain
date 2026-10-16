"""The sampler: reads frames, finds laps, detects events, and saves each finished lap.

LapBuilder is the pure part (frames in, finished laps out) so lap detection can be tested without
a game or a thread. Sampler wraps it in a thread with the source, the store and the live state the
MCP tools and the dashboard read.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from . import analysis
from .acc_shm import (SESSION_NAMES, STATUS_LIVE, STATUS_NAMES, AccNotRunning, Frame)
from .config import Settings
from .events import EventDetector
from .store import LapRecord, Store
from .tracks import Track, auto_track, load_track, norm_key

log = logging.getLogger("acc.sampler")

# a lap counts as fully recorded when it starts and ends near the line with no big hole in between
MAX_START_POS, MIN_END_POS, MAX_POS_GAP = 0.05, 0.95, 0.05
PENDING_TIMEOUT_S = 1.5   # how long to wait for the game to publish the finished lap's time


def sample_of(f: Frame, fallback_t: float) -> tuple:
    """One raw trace sample, in analysis.SAMPLE_FIELDS order."""
    t = f.current_ms / 1000 if f.current_ms > 0 else fallback_t
    return (f.pos, t, f.speed_kmh, f.gas, f.brake, f.steer, f.gear, f.rpm, f.g_lat, f.g_lon, f.tc, f.abs,
            max(abs(v) for v in f.slip_ratio), f.x, f.z)


@dataclass
class LapAcc:
    """Everything collected while one lap is being driven."""
    t0: float
    samples: list = field(default_factory=list)
    events: list = field(default_factory=list)
    sector_marks: list = field(default_factory=list)    # lastSectorTime each time the sector index moved on
    last_sector: Optional[int] = None
    in_pit: bool = False
    valid: bool = True
    n: int = 0
    temp_sum: list = field(default_factory=lambda: [0.0] * 4)
    psi_sum: list = field(default_factory=lambda: [0.0] * 4)
    brake_temp_max: list = field(default_factory=lambda: [0.0] * 4)
    air: float = 0.0
    road: float = 0.0
    fuel_start: Optional[float] = None
    fuel_end: float = 0.0
    compound: str = ""
    max_gap: float = 0.0

    def add(self, f: Frame) -> None:
        if self.samples:
            self.max_gap = max(self.max_gap, f.pos - self.samples[-1][0])
        self.samples.append(sample_of(f, f.t - self.t0))
        self.n += 1
        for i in range(4):
            self.temp_sum[i] += f.tyre_temp[i]
            self.psi_sum[i] += f.tyre_pressure[i]
            self.brake_temp_max[i] = max(self.brake_temp_max[i], f.brake_temp[i])
        self.air += f.air_temp
        self.road += f.road_temp
        if self.fuel_start is None:
            self.fuel_start = f.fuel
        self.fuel_end = f.fuel
        self.compound = f.tyre_compound or self.compound
        self.in_pit = self.in_pit or f.in_pit or f.in_pit_lane
        self.valid = self.valid and f.valid_lap
        if self.last_sector is not None and f.sector_index != self.last_sector and f.last_sector_ms > 0:
            self.sector_marks.append(f.last_sector_ms)
        self.last_sector = f.sector_index

    def covered(self) -> bool:
        s = self.samples
        return len(s) > 30 and s[0][0] <= MAX_START_POS and s[-1][0] >= MIN_END_POS and self.max_gap <= MAX_POS_GAP


@dataclass
class CompletedLap:
    acc: LapAcc
    lap_number: int
    lap_time_ms: int
    session_index: int
    track: str
    car: str
    session: str
    length_m: float
    sector_count: int

    @property
    def clean(self) -> bool:
        return self.acc.covered() and not self.acc.in_pit

    def meta(self) -> dict:
        a, n = self.acc, max(1, self.acc.n)
        return {"tyre_temp_avg": [round(v / n, 1) for v in a.temp_sum], "tyre_psi_avg": [round(v / n, 2) for v in a.psi_sum],
                "brake_temp_max": [round(v) for v in a.brake_temp_max]}


def normalize_sectors(marks: list, lap_time_ms: int, count: int = 3) -> list:
    """Sector durations in ms from the game's lastSectorTime marks, or [] if they don't add up.

    The last sector is whatever is left of the lap, so only count-1 marks are needed.
    """
    if count < 2 or len(marks) != count - 1 or any(m <= 0 for m in marks) or sum(marks) >= lap_time_ms:
        return []
    return list(marks) + [lap_time_ms - sum(marks)]


class LapBuilder:
    """Frames in, finished laps out. Handles the line being crossed in either order (position wraps
    before the lap counter moves, or after), pauses, replays, restarts and joining mid-lap.

    `counter` is the game's completedLaps as last seen; `lap_index` is our own count of finished
    laps. They match, except for the moment after the position wrapped and before the counter did
    (lap_index is then one ahead).
    """

    def __init__(self):
        self.key = None
        self.counter = 0
        self.lap_index = 0
        self.acc: Optional[LapAcc] = None
        self.awaiting_wrap = False
        self.prev_last_ms = 0                  # lastTime of the previous frame, to see when it changes
        self.pending: Optional[tuple] = None   # (acc, lap index, last_ms before, deadline, static info)

    def reset(self) -> None:
        self.key, self.acc, self.pending, self.awaiting_wrap = None, None, None, False

    def add_event(self, ev: dict) -> None:
        if self.acc is not None:
            self.acc.events.append(ev)

    def feed(self, f: Frame) -> list:
        done: list = []
        if f.status != STATUS_LIVE:
            return done
        key = (f.track, f.car, f.session, f.session_index)
        if key != self.key or f.completed_laps < self.counter:   # new session or restart: start over
            self.key, self.counter, self.lap_index = key, f.completed_laps, f.completed_laps
            self.acc, self.pending, self.awaiting_wrap = None, None, False
            self.prev_last_ms = f.last_ms
        last_pos = self.acc.samples[-1][0] if self.acc and self.acc.samples else None
        wrapped = last_pos is not None and f.pos < last_pos - 0.5
        counter_ahead = f.completed_laps > self.lap_index          # the counter moved and the position hasn't wrapped yet
        crossed = wrapped or counter_ahead
        self.counter = f.completed_laps
        if crossed:
            if self.acc is not None:
                self._queue(f)
            self.lap_index = max(self.lap_index + 1, f.completed_laps) if wrapped else f.completed_laps
            self.awaiting_wrap = counter_ahead and not wrapped and f.pos > 0.9
        if self.awaiting_wrap and f.pos < 0.5:
            self.awaiting_wrap = False
        if not self.awaiting_wrap:
            if self.acc is None or crossed:
                self.acc = LapAcc(t0=f.t)
            self.acc.add(f)
        done.extend(self._check_pending(f))
        self.prev_last_ms = f.last_ms
        return done

    def _queue(self, f: Frame) -> None:
        """The lap just ended; wait for the game to publish its time."""
        info = (self.key, f.sector_count, f.track_length_m)
        if self.pending is not None:      # two crossings before the time showed up: keep the newest
            log.warning("lap time not published before the next lap ended; dropping the earlier lap")
        self.pending = (self.acc, self.lap_index, self.prev_last_ms, f.t + PENDING_TIMEOUT_S, info)
        self.acc = None

    def _check_pending(self, f: Frame) -> list:
        if self.pending is None:
            return []
        acc, lap_index, last_before, deadline, (key, sectors, length) = self.pending
        if f.last_ms > 0 and f.last_ms != last_before:
            ms = f.last_ms
        elif f.t >= deadline:
            ms = int(round(acc.samples[-1][1] * 1000)) if acc.samples else 0
        else:
            return []
        self.pending = None
        if ms <= 0:
            return []
        return [CompletedLap(acc=acc, lap_number=lap_index + 1, lap_time_ms=ms, session_index=key[3], track=key[0],
                             car=key[1], session=SESSION_NAMES.get(key[2], str(key[2])), length_m=length,
                             sector_count=sectors)]


class Sampler(threading.Thread):
    def __init__(self, source, store: Store, cfg: Settings):
        super().__init__(daemon=True, name="acc-sampler")
        self.source, self.store, self.cfg = source, store, cfg
        self.builder, self.detector = LapBuilder(), EventDetector(cfg)
        self.lock = threading.RLock()
        self.stop_flag = threading.Event()
        self.latest: Optional[Frame] = None
        self.status, self.message = "starting", "starting"
        self.events: deque = deque(maxlen=200)
        self.alerts: deque = deque(maxlen=200)
        self._alert_seq = 0
        self.recent_laps: deque = deque(maxlen=cfg.ring_laps)   # summaries (with trace) of this run's laps
        self.track: Optional[Track] = None
        self.ctx: Optional[tuple] = None      # (track key, car) the track table and reference lap belong to
        self.ref: Optional[dict] = None       # best clean lap on this track + car, for the live delta
        self.ref_id: Optional[int] = None
        self.laps_saved = 0
        self._tick = 0
        self._low_fuel_told = False
        self._hot_told: set = set()
        self._corner_mark: Optional[tuple] = None   # (corner name, delta at entry)

    # --- thread -----------------------------------------------------------------------------

    def run(self) -> None:
        period = 1.0 / (self.cfg.trace_hz * getattr(self.source, "speedup", 1.0))   # mock plays faster than real time
        while not self.stop_flag.is_set():
            started = time.monotonic()
            try:
                self.process_frame(self.source.read())
            except AccNotRunning as e:
                self._status("acc_not_running", f"{e}. Waiting for the game...")
                self.stop_flag.wait(1.0)
                continue
            except Exception:   # a bad frame must not kill the sampler
                log.exception("sampler error")
                self.stop_flag.wait(1.0)
                continue
            self.stop_flag.wait(max(0.0, period - (time.monotonic() - started)))

    def stop(self) -> None:
        self.stop_flag.set()

    def _status(self, status: str, message: str) -> None:
        with self.lock:
            if status != self.status:
                log.info("%s", message)
            self.status, self.message = status, message

    # --- one frame --------------------------------------------------------------------------

    def process_frame(self, f: Frame) -> list:
        """Handle one reading. Returns the ids of laps saved because of it."""
        self._tick += 1
        with self.lock:
            self.latest = f
        name = STATUS_NAMES.get(f.status, "off")
        if f.status != STATUS_LIVE:
            self._status("menu" if f.status == 0 else name, {0: "ACC is running but not on track (menus).", 1: "Replay: not recording.",
                                                           3: "Paused."}.get(f.status, name))
            return []
        self._status("live", f"{f.track or '?'} / {f.car or '?'}")
        if (norm_key(f.track), f.car) != self.ctx:
            self._new_context(f)
        corner = self.track.name_at(f.pos) if self.track else None
        lap_no = self.builder.lap_index + 1
        for ev in self.detector.feed(f, lap_no, corner):
            self.builder.add_event(ev)
            with self.lock:
                self.events.append(ev)
            self._alert("event", f"{ev['type']} at {corner or round(ev['pos'], 3)}", ev)
        saved = []
        for lap in self.builder.feed(f):
            lap_id = self._save(lap)
            if lap_id is not None:
                saved.append(lap_id)
        if self._tick % max(1, round(self.cfg.trace_hz / self.cfg.summary_hz)) == 0:
            self._summary_tick(f, corner)
        return saved

    def _new_context(self, f: Frame) -> None:
        """Track or car changed: load its corner table and the reference lap."""
        self.ctx = (norm_key(f.track), f.car)
        self.track = load_track(f.track, self.cfg.user_tracks_dir)
        best = self.store.best_lap(f.track, f.car) if f.track else None
        self.ref = best["trace"] if best else None
        self.ref_id = best["id"] if best else None
        if self.track is None and best:
            self.track = auto_track(f.track, best["trace"]["speed"], best["length_m"])
        self._corner_mark, self._low_fuel_told, self._hot_told = None, False, set()

    def _save(self, lap: CompletedLap) -> Optional[int]:
        a = lap.acc
        a.events.extend(self.detector.flush(a.samples[-1][1] if a.samples else 0))
        if not a.covered():
            log.info("lap %s not saved: only part of it was recorded (joined mid-lap?)", lap.lap_number)
            return None
        try:
            trace = analysis.resample(a.samples, lap.lap_time_ms / 1000, self.cfg.points)
        except ValueError:
            return None
        sectors = normalize_sectors(a.sector_marks, lap.lap_time_ms, lap.sector_count)
        if not sectors and self.track:
            sectors = [round(s * 1000) for s in analysis.sector_times(trace, self.track)]
        n = max(1, a.n)
        rec = LapRecord(track=lap.track, car=lap.car, lap_time_ms=lap.lap_time_ms, trace=trace,
                        lap_number=lap.lap_number, session=lap.session, sectors_ms=sectors, valid=a.valid,
                        clean=lap.clean, fuel_start=round(a.fuel_start or 0, 2), fuel_end=round(a.fuel_end, 2),
                        air_temp=round(a.air / n, 1), road_temp=round(a.road / n, 1), compound=a.compound,
                        length_m=lap.length_m, session_index=lap.session_index, meta=lap.meta(), events=a.events)
        lap_id = self.store.save_lap(rec)
        if lap_id is None:
            return None
        self.laps_saved += 1
        with self.lock:
            self.recent_laps.append({"id": lap_id, "lap_number": rec.lap_number, "lap_time_ms": rec.lap_time_ms,
                                     "clean": rec.clean, "valid": rec.valid, "meta": rec.meta, "fuel_start": rec.fuel_start,
                                     "fuel_end": rec.fuel_end})
        if self.store.get_track_map(lap.track) is None or (rec.clean and self.ref is None):
            self.store.save_track_map(lap.track, [[trace["x"][i], trace["z"][i]] for i in range(0, len(trace["x"]), 2)])
        if rec.clean and rec.valid and (self.ref is None or rec.lap_time_ms < round(self.ref["t"][-1] * 1000)):
            self.ref, self.ref_id = trace, lap_id
            if self.track is None or self.track.auto:
                self.track = auto_track(lap.track, trace["speed"], lap.length_m)
        elif self.track is None and rec.clean:
            self.track = auto_track(lap.track, trace["speed"], lap.length_m)
        delta = (rec.lap_time_ms - self.ref["t"][-1] * 1000) / 1000 if self.ref else 0.0
        self._alert("lap", f"Lap {rec.lap_number}: {rec.lap_time_ms / 1000:.3f} s ({delta:+.3f} vs best)",
                    {"lap_id": lap_id, "lap_time_ms": rec.lap_time_ms, "delta_s": round(delta, 3), "valid": rec.valid})
        return lap_id

    # --- live numbers -----------------------------------------------------------------------

    def live_delta(self, f: Optional[Frame] = None) -> Optional[float]:
        """Seconds ahead (-) or behind (+) the reference lap at this point of the lap."""
        f = f or self.latest
        if f is None or self.ref is None or f.current_ms <= 0:
            return None
        return f.current_ms / 1000 - analysis.time_at(self.ref, f.pos)

    def _alert(self, kind: str, message: str, data: dict) -> None:
        with self.lock:
            self._alert_seq += 1
            self.alerts.append({"seq": self._alert_seq, "type": kind, "message": message, "at": datetime.now().isoformat(timespec="seconds"),
                                "data": data})

    def _summary_tick(self, f: Frame, corner: Optional[str]) -> None:
        cfg = self.cfg
        burn = self.fuel_per_lap()
        if burn and f.fuel > 0:
            left = f.fuel / burn
            if left <= cfg.alert_fuel_laps and not self._low_fuel_told:
                self._low_fuel_told = True
                self._alert("low_fuel", f"Low fuel: about {left:.1f} laps left", {"laps_left": round(left, 1), "fuel_l": round(f.fuel, 1)})
            elif left > cfg.alert_fuel_laps + 1:
                self._low_fuel_told = False
        for i, wheel in enumerate(("FL", "FR", "RL", "RR")):
            hot = f.tyre_temp[i] > cfg.tyre_temp_hot
            if hot and wheel not in self._hot_told:
                self._hot_told.add(wheel)
                self._alert("tyre_hot", f"{wheel} tyre is hot ({f.tyre_temp[i]:.0f} °C)", {"wheel": wheel, "temp_c": round(f.tyre_temp[i])})
            elif not hot and f.tyre_temp[i] < cfg.tyre_temp_hot - 5:
                self._hot_told.discard(wheel)
        d = self.live_delta(f)
        if d is not None:   # time lost across a corner window against the reference lap
            if self._corner_mark and corner != self._corner_mark[0]:
                lost = d - self._corner_mark[1]
                if lost >= cfg.alert_delta_loss_s:
                    self._alert("delta_loss", f"Lost {lost:.2f} s in {self._corner_mark[0]} vs best",
                                {"corner": self._corner_mark[0], "lost_s": round(lost, 2)})
                self._corner_mark = None
            if corner and self.track and self.track.corner_at(f.pos) and self._corner_mark is None:
                self._corner_mark = (corner, d)

    def fuel_per_lap(self) -> Optional[float]:
        """Average burn over this run's last laps (clean laps without a refuel), else the game's estimate."""
        burns = [l["fuel_start"] - l["fuel_end"] for l in list(self.recent_laps)[-4:]
                 if l["clean"] and l["fuel_start"] > l["fuel_end"] > 0]
        if burns:
            return sum(burns) / len(burns)
        f = self.latest
        return f.fuel_per_lap if f and f.fuel_per_lap > 0 else None

    def current_lap_trace(self, points: int = 120) -> dict:
        """The lap in progress, thinned, for the live view."""
        with self.lock:
            s = list(self.builder.acc.samples) if self.builder.acc else []
        step = max(1, len(s) // points)
        s = s[::step]
        return {"pos": [round(r[0], 4) for r in s], "speed": [round(r[2], 1) for r in s], "throttle": [round(r[3], 2) for r in s],
                "brake": [round(r[4], 2) for r in s], "steer": [round(r[5], 3) for r in s]}
