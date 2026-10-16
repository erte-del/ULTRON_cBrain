"""SQLite store for completed laps (data/laps.sqlite3). Standard library only.

One row per lap: summary columns for listing, plus the resampled trace as JSON. A lap's
fingerprint (track, car, session, lap number, lap time, day) is unique, so a lap seen twice (two
processes sampling, a re-seeded mock) is stored once.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS laps(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  track TEXT NOT NULL, car TEXT NOT NULL, session TEXT NOT NULL DEFAULT '',
  lap_number INTEGER NOT NULL DEFAULT 0, lap_time_ms INTEGER NOT NULL,
  s1_ms INTEGER, s2_ms INTEGER, s3_ms INTEGER,
  valid INTEGER NOT NULL DEFAULT 1, clean INTEGER NOT NULL DEFAULT 1,
  fuel_start REAL, fuel_end REAL, air_temp REAL, road_temp REAL,
  compound TEXT NOT NULL DEFAULT '', length_m REAL NOT NULL DEFAULT 0,
  meta TEXT NOT NULL DEFAULT '{}', events TEXT NOT NULL DEFAULT '[]', trace TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS laps_track_car ON laps(track, car, lap_time_ms);
CREATE TABLE IF NOT EXISTS track_maps(track TEXT PRIMARY KEY, points TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def fmt_ms(ms: Optional[float]) -> str:
    if ms is None or ms <= 0:
        return "-"
    m, rest = divmod(int(round(ms)), 60000)
    return f"{m}:{rest / 1000:06.3f}"


@dataclass
class LapRecord:
    track: str
    car: str
    lap_time_ms: int
    trace: dict
    lap_number: int = 0
    session: str = ""
    sectors_ms: list = field(default_factory=list)
    valid: bool = True
    clean: bool = True          # whole lap recorded, no pit involved: fit to compare against
    fuel_start: float = 0.0
    fuel_end: float = 0.0
    air_temp: float = 0.0
    road_temp: float = 0.0
    compound: str = ""
    length_m: float = 0.0
    session_index: int = 0
    meta: dict = field(default_factory=dict)     # tyre temps / pressures averaged over the lap, brake temps...
    events: list = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def fingerprint(self) -> str:
        raw = f"{self.track}|{self.car}|{self.session_index}|{self.lap_number}|{self.lap_time_ms}|{self.created_at[:10]}"
        return hashlib.sha1(raw.encode()).hexdigest()


SUMMARY_COLS = ("id, created_at, track, car, session, lap_number, lap_time_ms, s1_ms, s2_ms, s3_ms, valid, clean, "
                "fuel_start, fuel_end, air_temp, road_temp, compound, length_m, meta")


def _summary(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in r.keys() if k not in ("meta", "events", "trace", "s1_ms", "s2_ms", "s3_ms")}
    d["sectors_ms"] = [r["s1_ms"], r["s2_ms"], r["s3_ms"]]
    d["lap_time"] = fmt_ms(r["lap_time_ms"])
    d["valid"], d["clean"] = bool(r["valid"]), bool(r["clean"])
    d["meta"] = json.loads(r["meta"]) if "meta" in r.keys() else {}
    return d


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def save_lap(self, rec: LapRecord) -> Optional[int]:
        """Insert a lap; returns its id, or None if the same lap is already stored."""
        s = (list(rec.sectors_ms) + [None, None, None])[:3]
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO laps(fingerprint, created_at, track, car, session, lap_number, lap_time_ms, "
                "s1_ms, s2_ms, s3_ms, valid, clean, fuel_start, fuel_end, air_temp, road_temp, compound, length_m, "
                "meta, events, trace) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec.fingerprint(), rec.created_at, rec.track, rec.car, rec.session, rec.lap_number, rec.lap_time_ms,
                 s[0], s[1], s[2], int(rec.valid), int(rec.clean), rec.fuel_start, rec.fuel_end, rec.air_temp,
                 rec.road_temp, rec.compound, rec.length_m, json.dumps(rec.meta), json.dumps(rec.events),
                 json.dumps(rec.trace, separators=(",", ":"))))
            self._db.commit()
            return cur.lastrowid if cur.rowcount else None

    def list_laps(self, track: Optional[str] = None, car: Optional[str] = None, limit: int = 50,
                  clean_only: bool = False) -> list:
        sql, args = f"SELECT {SUMMARY_COLS} FROM laps WHERE 1=1", []
        for col, val in (("track", track), ("car", car)):
            if val:
                sql += f" AND lower({col}) = lower(?)"
                args.append(val)
        if clean_only:
            sql += " AND clean = 1 AND valid = 1"
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            return [_summary(r) for r in self._db.execute(sql, (*args, limit))]

    def get_lap(self, lap_id: int, with_trace: bool = True) -> Optional[dict]:
        with self._lock:
            r = self._db.execute(f"SELECT {SUMMARY_COLS}, events, trace FROM laps WHERE id = ?", (lap_id,)).fetchone()
        if r is None:
            return None
        d = _summary(r)
        d["events"] = json.loads(r["events"])
        if with_trace:
            d["trace"] = json.loads(r["trace"])
        return d

    def best_lap(self, track: str, car: Optional[str] = None, with_trace: bool = True) -> Optional[dict]:
        sql = "SELECT id FROM laps WHERE lower(track) = lower(?) AND clean = 1 AND valid = 1"
        args: list = [track]
        if car:
            sql += " AND lower(car) = lower(?)"
            args.append(car)
        with self._lock:
            r = self._db.execute(sql + " ORDER BY lap_time_ms LIMIT 1", args).fetchone()
        return self.get_lap(r["id"], with_trace) if r else None

    def last_lap(self, track: Optional[str] = None, car: Optional[str] = None, with_trace: bool = True) -> Optional[dict]:
        laps = self.list_laps(track, car, limit=1)
        return self.get_lap(laps[0]["id"], with_trace) if laps else None

    def save_track_map(self, track: str, points: list) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO track_maps(track, points, updated_at) VALUES (?,?,?)",
                             (track.lower(), json.dumps(points, separators=(",", ":")), datetime.now().isoformat(timespec="seconds")))
            self._db.commit()

    def get_track_map(self, track: str) -> Optional[list]:
        with self._lock:
            r = self._db.execute("SELECT points FROM track_maps WHERE track = ?", (track.lower(),)).fetchone()
        return json.loads(r["points"]) if r else None

    def tracks(self) -> list:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT track, car, COUNT(*) AS laps, MIN(lap_time_ms) AS best_ms FROM laps GROUP BY track, car ORDER BY track, car")]

    def close(self) -> None:
        with self._lock:
            self._db.close()
