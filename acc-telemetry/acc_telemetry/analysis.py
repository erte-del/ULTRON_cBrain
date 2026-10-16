"""Lap maths: resampling to a fixed grid, distance-aligned delta, per-corner metrics, comparison.

A saved lap is a dict of equal-length lists ("channels") sampled on a grid of lap position
p_i = i / (n - 1), so p = 0 is the line and p = 1 is the line again. "t" is elapsed lap time in
seconds (t[0] = 0, t[-1] = the lap time). Comparing two laps is then index-by-index, which is what
makes the delta distance-aligned: delta_i = t_a[i] - t_b[i], positive where A is behind B.
"""

from __future__ import annotations

from typing import Optional

from .tracks import Corner, Track

# order of one raw sample, as the sampler records it at ~30 Hz
SAMPLE_FIELDS = ("pos", "t", "speed", "throttle", "brake", "steer", "gear", "rpm",
                 "lat_g", "lon_g", "tc", "abs", "slip", "x", "z")
CHANNELS = SAMPLE_FIELDS[1:]
STEP_CHANNELS = ("gear",)          # held, not interpolated
DECIMALS = {"t": 3, "speed": 2, "throttle": 3, "brake": 3, "steer": 3, "gear": 0, "rpm": 0,
            "lat_g": 3, "lon_g": 3, "tc": 3, "abs": 3, "slip": 3, "x": 1, "z": 1}


def rnd(x: Optional[float], d: int = 2):
    return None if x is None else round(float(x), d)


def idx(p: float, n: int) -> int:
    return min(n - 1, max(0, int(round(p * (n - 1)))))


# --- resampling ------------------------------------------------------------------------------


def resample(samples: list, lap_time_s: float, n: int = 500) -> dict:
    """Raw samples (tuples in SAMPLE_FIELDS order, pos rising) -> channels on the n-point grid.

    The grid is pinned to the line at both ends: t = 0 at p = 0 and t = lap_time at p = 1, so the
    last point always equals the official lap time.
    """
    rows = []
    last = -1.0
    for s in samples:  # strictly rising position only
        if s[0] > last:
            rows.append(s)
            last = s[0]
    if len(rows) < 2:
        raise ValueError("not enough samples to build a lap")
    first, final = rows[0], rows[-1]
    if first[0] > 0.0:
        rows.insert(0, (0.0, 0.0) + tuple(first[2:]))
    else:
        rows[0] = (0.0, 0.0) + tuple(first[2:])
    if final[0] < 1.0:
        rows.append((1.0, lap_time_s) + tuple(final[2:]))
    else:
        rows[-1] = (1.0, lap_time_s) + tuple(final[2:])
    out = {name: [] for name in CHANNELS}
    j = 0
    for i in range(n):
        p = i / (n - 1)
        while j < len(rows) - 2 and rows[j + 1][0] < p:
            j += 1
        a, b = rows[j], rows[j + 1]
        span = b[0] - a[0]
        f = 0.0 if span <= 0 else min(1.0, max(0.0, (p - a[0]) / span))
        for k, name in enumerate(CHANNELS, start=1):
            out[name].append(a[k] if name in STEP_CHANNELS else a[k] + (b[k] - a[k]) * f)
    out["t"][0], out["t"][-1] = 0.0, lap_time_s
    return {k: [round(v, DECIMALS[k]) for v in vals] for k, vals in out.items()}


def downsample(trace: dict, points: int, channels: Optional[list] = None) -> dict:
    n = len(trace["t"])
    points = max(2, min(points, n))
    ids = [round(i * (n - 1) / (points - 1)) for i in range(points)]
    names = [c for c in (channels or CHANNELS) if c in trace]
    return {"pos": [round(i / (n - 1), 4) for i in ids], **{c: [trace[c][i] for i in ids] for c in names}}


def time_at(trace: dict, p: float) -> float:
    """Elapsed lap time at lap position p (linear between grid points)."""
    t = trace["t"]
    x = min(1.0, max(0.0, p)) * (len(t) - 1)
    i = min(len(t) - 2, int(x))
    return t[i] + (t[i + 1] - t[i]) * (x - i)


# --- delta -----------------------------------------------------------------------------------


def delta_curve(a: dict, b: dict) -> list:
    """t_a - t_b at every grid point. Positive: A is behind B there."""
    ta, tb = a["t"], b["t"]
    if len(ta) != len(tb):
        raise ValueError("laps have different resolutions")
    return [x - y for x, y in zip(ta, tb)]


def _span_delta(delta: list, start: float, end: float) -> float:
    n = len(delta)
    return delta[idx(end, n)] - delta[idx(start, n)]


def segment_deltas(delta: list, track: Track) -> list:
    """Time gained (-) or lost (+) per named stretch of track; the pieces add up to the lap delta."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for seg in track.segments():
        row = merged.get(seg.name)
        if row is None:
            row = merged[seg.name] = {"name": seg.name, "kind": seg.kind, "start": seg.start, "end": seg.end, "delta_s": 0.0}
            order.append(seg.name)
        row["delta_s"] += _span_delta(delta, seg.start, seg.end)
    return [merged[k] for k in order]


# --- per-corner metrics ----------------------------------------------------------------------


def corner_metrics(tr: dict, c: Corner, length_m: float, brake_on: float = 0.10) -> dict:
    """What happened in one corner window: entry/minimum speed, brake point, trail braking, pickup, peak G."""
    n = len(tr["t"])
    i0, i1 = idx(c.start, n), idx(c.end, n)
    speed, brake, throttle, steer = tr["speed"], tr["brake"], tr["throttle"], tr["steer"]
    imin = min(range(i0, i1 + 1), key=lambda i: speed[i])
    window = range(i0, i1 + 1)
    # braking run: the last braking sample before the slowest point, then back to where that run began
    reach = int(0.06 * (n - 1))
    kb_end = next((k for k in range(imin, max(0, i0 - reach) - 1, -1) if brake[k] > brake_on), None)
    brake_start = peak = trail = None
    if kb_end is not None and imin - kb_end <= max(3, int(0.02 * (n - 1))):
        k, gap, b0 = kb_end, 0, kb_end
        while k >= max(0, i0 - reach):
            if brake[k] > brake_on:
                b0, gap = k, 0
            else:
                gap += 1
                if gap > 2:
                    break
            k -= 1
        peak = max(brake[b0:kb_end + 1])
        brake_start = b0 / (n - 1)
        top_steer = max((abs(steer[i]) for i in window), default=0.0) or 1.0
        trail = sum(tr["t"][k + 1] - tr["t"][k] for k in range(b0, min(kb_end, n - 2) + 1)
                    if brake[k] > brake_on and abs(steer[k]) > 0.25 * top_steer)
    pickup = next((k for k in range(imin, min(n - 3, i1 + reach)) if all(throttle[k + d] > 0.3 for d in range(3))), None)
    return {
        "name": c.name,
        "entry_kmh": rnd(speed[i0], 1),
        "min_kmh": rnd(speed[imin], 1),
        "min_pos": rnd(imin / (n - 1), 4),
        "brake_start_pos": rnd(brake_start, 4),
        "brake_dist_m": rnd((c.apex - brake_start) * length_m, 0) if brake_start is not None and length_m else None,
        "brake_peak": rnd(peak, 2),
        "trail_s": rnd(trail, 2),
        "throttle_pickup_pos": rnd(pickup / (n - 1), 4) if pickup is not None else None,
        "pickup_after_min_m": rnd((pickup - imin) / (n - 1) * length_m, 0) if pickup is not None and length_m else None,
        "peak_lat_g": rnd(max(abs(tr["lat_g"][i]) for i in window), 2),
        "peak_lon_g": rnd(max(abs(tr["lon_g"][i]) for i in window), 2),
        "time_s": rnd(tr["t"][i1] - tr["t"][i0], 3),
    }


def lap_corners(tr: dict, track: Track, length_m: float, brake_on: float = 0.10) -> list:
    return [corner_metrics(tr, c, length_m, brake_on) for c in sorted(track.corners, key=lambda c: c.start)]


def sector_times(tr: dict, track: Track) -> list:
    """Sector durations in seconds, from the trace and the track's sector markers."""
    n = len(tr["t"])
    return [rnd(tr["t"][idx(b, n)] - tr["t"][idx(a, n)], 3) for a, b in track.sector_edges()]


# --- comparison ------------------------------------------------------------------------------

NOISE_S = 0.02         # differences smaller than this aren't worth naming
BRAKE_EARLIER_M = 5.0   # brake points closer than this are within the trace's resolution


def brake_flag(diff_m: Optional[float]) -> str:
    if diff_m is None:
        return ""
    return "earlier" if diff_m >= BRAKE_EARLIER_M else "later" if diff_m <= -BRAKE_EARLIER_M else "same"


def braking_table(a: dict, b: dict, track: Track, length_m: float, brake_on: float = 0.10) -> list:
    """Per corner, lap A next to lap B. brake_diff_m > 0: A starts braking earlier than B."""
    rows = []
    for ca, cb in zip(lap_corners(a, track, length_m, brake_on), lap_corners(b, track, length_m, brake_on)):
        diff = None
        if ca["brake_dist_m"] is not None and cb["brake_dist_m"] is not None:
            diff = ca["brake_dist_m"] - cb["brake_dist_m"]
        rows.append({"corner": ca["name"], "a": ca, "b": cb, "brake_diff_m": rnd(diff, 0), "brake": brake_flag(diff)})
    return rows


def _explain(row: dict, ca: dict, cb: dict) -> str:
    bits = []
    d = row["delta_s"]
    if ca and cb:
        if ca["entry_kmh"] is not None and abs(ca["entry_kmh"] - cb["entry_kmh"]) >= 2:
            bits.append(f"entry {ca['entry_kmh'] - cb['entry_kmh']:+.0f} km/h")
        if abs(ca["min_kmh"] - cb["min_kmh"]) >= 2:
            bits.append(f"minimum {ca['min_kmh'] - cb['min_kmh']:+.0f} km/h")
        if ca["brake_dist_m"] is not None and cb["brake_dist_m"] is not None and abs(ca["brake_dist_m"] - cb["brake_dist_m"]) >= BRAKE_EARLIER_M:
            e = ca["brake_dist_m"] - cb["brake_dist_m"]
            bits.append(f"braked {abs(e):.0f} m {'earlier' if e > 0 else 'later'}")
        if ca["pickup_after_min_m"] is not None and cb["pickup_after_min_m"] is not None and abs(ca["pickup_after_min_m"] - cb["pickup_after_min_m"]) >= 8:
            e = ca["pickup_after_min_m"] - cb["pickup_after_min_m"]
            bits.append(f"throttle {abs(e):.0f} m {'later' if e > 0 else 'earlier'}")
    word = "lost" if d > 0 else "gained"
    return f"{row['name']}: {word} {abs(d):.3f} s" + (f" ({', '.join(bits)})" if bits else "")


def compare(a: dict, b: dict, track: Track, length_m: float, brake_on: float = 0.10, top: int = 8) -> dict:
    """Where lap A gained or lost time against lap B, by sector and by corner/straight."""
    delta = delta_curve(a, b)
    rows = segment_deltas(delta, track)
    by_corner = {r["corner"]: (r["a"], r["b"]) for r in braking_table(a, b, track, length_m, brake_on)}
    for r in rows:
        ca, cb = by_corner.get(r["name"], (None, None))
        r["delta_s"] = round(r["delta_s"], 3)
        if ca:
            r.update(a_min_kmh=ca["min_kmh"], b_min_kmh=cb["min_kmh"], a_entry_kmh=ca["entry_kmh"], b_entry_kmh=cb["entry_kmh"])
    loss = max(rows, key=lambda r: r["delta_s"])
    gain = min(rows, key=lambda r: r["delta_s"])
    sectors = [{"sector": i + 1, "delta_s": round(delta[idx(e, len(delta))] - delta[idx(s, len(delta))], 3)}
               for i, (s, e) in enumerate(track.sector_edges())]
    ordered = sorted(rows, key=lambda r: -abs(r["delta_s"]))[:top]
    return {
        "total_delta_s": round(delta[-1], 3),
        "sectors": sectors,
        "most_time_lost": _explain(loss, *by_corner.get(loss["name"], (None, None))) if loss["delta_s"] >= NOISE_S else None,
        "most_time_gained": _explain(gain, *by_corner.get(gain["name"], (None, None))) if gain["delta_s"] <= -NOISE_S else None,
        "biggest": [{k: v for k, v in r.items() if k not in ("start", "end")} for r in ordered],
    }


def delta_points(a: dict, b: dict, points: int = 100) -> dict:
    """Delta curve thinned for charts / the model."""
    d = delta_curve(a, b)
    n = len(d)
    ids = [round(i * (n - 1) / (points - 1)) for i in range(points)]
    return {"pos": [round(i / (n - 1), 4) for i in ids], "delta_s": [round(d[i], 3) for i in ids]}
