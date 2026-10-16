"""Track data: named corner windows per track (JSON), plus a fallback that finds corners itself.

A corner window is {start, apex, end} as fractions of the lap (normalizedCarPosition). Windows
include the braking zone, so "time lost in a corner" means entry + apex + exit. The gaps between
windows are straights (named in the JSON when known). Tracks without a JSON file get corners
detected from a lap's speed trace and are called T1, T2, ...

Add a track: copy tracks/spa.json to <data dir>/tracks/<name>.json and edit it. Files in the data
dir win over the built-in ones.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import PACKAGE_DIR


def norm_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


@dataclass(frozen=True)
class Corner:
    name: str
    start: float
    apex: float
    end: float
    direction: str = ""
    ref_min_kmh: float = 0.0


@dataclass(frozen=True)
class Segment:
    name: str
    start: float
    end: float
    kind: str  # "corner" | "straight"


def _inside(pos: float, start: float, end: float) -> bool:
    return start <= pos <= end if start <= end else (pos >= start or pos <= end)  # end < start: wraps the line


@dataclass
class Track:
    key: str
    name: str
    length_m: float = 0.0
    sectors: list = field(default_factory=lambda: [1 / 3, 2 / 3, 1.0])
    corners: list = field(default_factory=list)
    straights: list = field(default_factory=list)   # [{name, start, end}]
    map_points: list = field(default_factory=list)  # [[x, z], ...] fallback outline
    auto: bool = False                              # corners were detected, not from a file

    def corner_at(self, pos: float) -> Optional[Corner]:
        for c in self.corners:
            if _inside(pos, c.start, c.end):
                return c
        return None

    def name_at(self, pos: float) -> Optional[str]:
        """Corner name at a lap position, else the straight's name (None if the track is unnamed)."""
        c = self.corner_at(pos)
        if c:
            return c.name
        for s in self.straights:
            if _inside(pos, s["start"], s["end"]):
                return s["name"]
        return None

    def segments(self) -> list[Segment]:
        """Corners and straights in lap order, covering 0..1 with no gaps."""
        out: list[Segment] = []
        cursor, prev = 0.0, None
        for c in sorted(self.corners, key=lambda c: c.start):
            if c.start > cursor + 1e-6:
                out.append(self._straight(cursor, c.start, prev))
            out.append(Segment(c.name, c.start, c.end, "corner"))
            cursor, prev = max(cursor, c.end), c.name
        if cursor < 1.0 - 1e-6:
            out.append(self._straight(cursor, 1.0, prev))
        return out

    def _straight(self, a: float, b: float, prev: Optional[str]) -> Segment:
        mid = (a + b) / 2
        for s in self.straights:
            if _inside(mid, s["start"], s["end"]):
                return Segment(s["name"], a, b, "straight")
        return Segment(f"Straight after {prev}" if prev else "Start/finish straight", a, b, "straight")

    def sector_edges(self) -> list[tuple[float, float]]:
        edges, a = [], 0.0
        for m in self.sectors:
            edges.append((a, m))
            a = m
        return edges


def _from_json(key: str, d: dict) -> Track:
    return Track(
        key=key, name=d.get("name", key), length_m=float(d.get("length_m", 0)),
        sectors=[float(x) for x in d.get("sectors", [1 / 3, 2 / 3, 1.0])],
        corners=[Corner(c["name"], c["start"], c["apex"], c["end"], c.get("direction", ""), c.get("ref_min_kmh", 0))
                 for c in d.get("corners", [])],
        straights=d.get("straights", []), map_points=d.get("map", []),
    )


def load_track(name: str, user_dir: Optional[Path] = None) -> Optional[Track]:
    """The track whose file name or alias matches `name` (user dir first), or None."""
    want = norm_key(name)
    if not want:
        return None
    dirs = ([user_dir] if user_dir else []) + [PACKAGE_DIR / "tracks"]
    for d in dirs:
        if not d or not d.is_dir():
            continue
        for path in sorted(d.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            keys = {norm_key(path.stem), norm_key(data.get("name", ""))} | {norm_key(a) for a in data.get("aliases", [])}
            if want in keys:
                return _from_json(norm_key(path.stem), data)
    return None


def auto_corners(speed: list, min_prominence_kmh: float = 14.0, search: float = 0.2) -> list[Corner]:
    """Find corners as speed minima that stand out by at least `min_prominence_kmh`."""
    n = len(speed)
    if n < 20:
        return []
    sm = [sum(speed[max(0, i - 2):i + 3]) / len(speed[max(0, i - 2):i + 3]) for i in range(n)]
    reach = max(5, int(search * n))
    found = []
    for i in range(2, n - 2):
        if not (sm[i] <= sm[i - 1] and sm[i] < sm[i + 1]):
            continue
        lp = rp = sm[i]
        j = i
        while j > max(0, i - reach) and sm[j - 1] >= sm[i]:
            j -= 1
            lp = max(lp, sm[j])
        k = i
        while k < min(n - 1, i + reach) and sm[k + 1] >= sm[i]:
            k += 1
            rp = max(rp, sm[k])
        prom = min(lp, rp) - sm[i]
        if prom < min_prominence_kmh:
            continue
        a = i
        while a > 0 and sm[a] < sm[i] + 0.8 * prom:
            a -= 1
        b = i
        while b < n - 1 and sm[b] < sm[i] + 0.8 * prom:
            b += 1
        found.append([a, i, b])
    for prev, cur in zip(found, found[1:]):  # neighbours share the ground between their apexes
        if prev[2] > cur[0]:
            prev[2] = cur[0] = (prev[1] + cur[1]) // 2
    d = n - 1
    return [Corner(f"T{k + 1}", a / d, i / d, b / d, "", sm[i]) for k, (a, i, b) in enumerate(found)]


def auto_track(name: str, speed: list, length_m: float = 0.0) -> Track:
    return Track(key=norm_key(name), name=name, length_m=length_m, corners=auto_corners(speed), auto=True)
