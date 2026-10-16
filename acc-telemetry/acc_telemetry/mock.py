"""Mock mode: a synthetic car driven round a track, so everything can be tried without the game.

The lap is a speed profile along the track: each corner of the track table limits the speed with a
smooth dip, braking is limited to what the car can decelerate, and acceleration to what it can
pull. From that profile come brake and throttle, gears, steering, G, tyre and fuel numbers, and
optional mistakes (a lockup, wheelspin, a slide, an off-track, a curb) so the event detection has
something to find. Frames are the same type the real reader makes.

Different laps get different LapParams, e.g. a slow Pouhon, which gives compare_laps a known answer.
"""

from __future__ import annotations

import math
from itertools import islice
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .acc_shm import STATUS_LIVE, Frame
from .tracks import Track

DT = 1 / 30                 # virtual time step of one mock frame
V_FREE = 84.0               # m/s, top of the speed limit curve (about 300 km/h)
V_TERMINAL = 92.0           # m/s the engine can't pull beyond
ACCEL0 = 6.2                # m/s^2 from a standstill, tapering with speed
BRAKE_MAX = 13.0            # m/s^2 at the limit
GEAR_UP_KMH = (0, 75, 112, 150, 190, 235)
MOCK_CAR, MOCK_TRACK = "amr_v12_vantage_gt3", "spa"
MAX_FUEL, BURN_PER_LAP = 100.0, 2.9


@dataclass
class LapParams:
    pace: float = 1.0                                       # scales every corner speed
    corner_scale: dict = field(default_factory=dict)        # corner name -> speed scale (<1 = slower there)
    lockup_at: Optional[str] = None
    wheelspin_at: Optional[str] = None
    slide_at: Optional[str] = None
    offtrack_at: Optional[str] = None
    curb_at: Optional[str] = None


# the laps --mock plays in a loop: a baseline, one losing time at Pouhon, one with mistakes, a quick one
DEMO_LAPS = (
    LapParams(),
    LapParams(corner_scale={"Pouhon": 0.93}, slide_at="Pouhon"),
    LapParams(pace=0.985, lockup_at="Les Combes", wheelspin_at="La Source", curb_at="Bus Stop"),
    LapParams(pace=1.012, corner_scale={"Stavelot": 1.03}),
    LapParams(pace=0.99, corner_scale={"Rivage": 0.95}, offtrack_at="Blanchimont"),
)


def _profile(track: Track, length_m: float, p: LapParams, ds: float = 2.0):
    """(speed m/s, accel m/s^2) at every ds metres: the fastest lap the corner limits allow."""
    n = max(50, int(length_m / ds))
    limit = [V_FREE] * n
    for c in track.corners:
        vc = c.ref_min_kmh / 3.6 * p.pace * p.corner_scale.get(c.name, 1.0)
        centre, sigma = c.apex * n, max(2.0, (c.end - c.start) * n * 0.28)
        for i in range(max(0, int(centre - 4 * sigma)), min(n, int(centre + 4 * sigma) + 1)):
            limit[i] = min(limit[i], V_FREE - (V_FREE - vc) * math.exp(-0.5 * ((i - centre) / sigma) ** 2))
    v = limit[:]
    for _ in range(2):                                    # two passes round the loop settle the wrap
        for i in range(2 * n - 1, -1, -1):                # braking: look ahead
            a, b = i % n, (i + 1) % n
            v[a] = min(v[a], math.sqrt(v[b] ** 2 + 2 * BRAKE_MAX * ds))
        for i in range(2 * n):                            # acceleration: look behind
            a, b = i % n, (i + 1) % n
            pull = max(0.4, ACCEL0 * (1 - (v[a] / V_TERMINAL) ** 2))
            v[b] = min(v[b], limit[b], math.sqrt(v[a] ** 2 + 2 * pull * ds))
    acc = [(v[(i + 1) % n] ** 2 - v[i] ** 2) / (2 * ds) for i in range(n)]
    return v, acc, ds


def _steer_sign(track: Track, pos: float) -> float:
    c = track.corner_at(pos)
    if c is None:
        return 0.0
    tokens = [t for t in c.direction.split("-") if t in ("L", "R")] or ["R"]
    k = min(len(tokens) - 1, int((pos - c.start) / max(1e-9, c.end - c.start) * len(tokens)))
    return -1.0 if tokens[k] == "L" else 1.0


def _xz(track: Track, pos: float) -> tuple:
    pts = track.map_points
    if not pts:
        return (pos * 1000.0, 0.0)
    x = pos * len(pts)
    i = int(x) % len(pts)
    j = (i + 1) % len(pts)
    f = x - int(x)
    return (pts[i][0] + (pts[j][0] - pts[i][0]) * f, pts[i][1] + (pts[j][1] - pts[i][1]) * f)


def lap_time_estimate(track: Track, length_m: float, p: LapParams) -> float:
    v, _, ds = _profile(track, length_m, p)
    return sum(ds / ((v[i] + v[(i + 1) % len(v)]) / 2) for i in range(len(v)))


def simulate_laps(track: Track, length_m: float, params: Iterator[LapParams], t0: float = 0.0, first_lap: int = 0) -> Iterator[Frame]:
    """Endless frames, lap after lap, with params taken from the iterator one lap at a time."""
    t, lap, last_ms, best_ms, last_sector_ms = t0, first_lap, 0, 0, 0
    sectors = track.sectors or [1 / 3, 2 / 3, 1.0]
    while True:
        p = next(params)
        v, acc, ds = _profile(track, length_m, p)
        n = len(v)
        s, k = 0.0, 0
        sector_idx, sector_start = 0, 0
        fuel0 = MAX_FUEL - BURN_PER_LAP * lap
        while s < length_m:
            pos = s / length_m
            i = min(n - 1, int(s / ds))
            speed = v[i]
            a = acc[i]
            kmh = speed * 3.6
            sign = _steer_sign(track, pos)
            in_corner = track.corner_at(pos)
            cname = in_corner.name if in_corner else ""
            lean = max(0.0, min(1.0, (V_FREE - speed) / (V_FREE - 25.0)))
            steer = sign * 0.8 * lean
            lat_g = steer * 2.8 * min(1.0, speed / 45.0)
            heavy_brake = a < -1.2
            brake = min(1.0, -a / BRAKE_MAX) * 1.05 if heavy_brake else 0.0
            if heavy_brake:
                throttle = 0.0
            elif a > 0.5:
                throttle = 1.0
            elif a < -0.2:
                throttle = 0.0
            else:
                throttle = 0.45
            slip = [-0.06 * brake] * 4
            slip_angle = [0.03 * abs(steer)] * 4
            tc = abs_act = 0.0
            tyres_out, kerb = 0, 0.0
            if heavy_brake:
                abs_act = 0.6
            if p.lockup_at == cname and heavy_brake and brake > 0.5:
                slip[0] = -0.55
            if p.wheelspin_at == cname and a > 0.5 and speed < 55:
                slip[2] = slip[3] = 0.5
                tc = 0.4
            if p.slide_at == cname and abs(steer) > 0.15:
                slip_angle[2] = slip_angle[3] = 0.3
            if p.offtrack_at == cname:
                tyres_out = 4
            if p.curb_at == cname:
                kerb = 0.8
            gear = 1 + sum(1 for g in GEAR_UP_KMH[1:] if kmh >= g)
            lo = GEAR_UP_KMH[gear - 1]
            hi = GEAR_UP_KMH[gear] if gear < len(GEAR_UP_KMH) else 300
            rpm = int(4200 + 3800 * min(1.0, (kmh - lo) / max(1, hi - lo)))
            warm = min(lap, 8)
            temp = [84 + 0.8 * warm + 3 * (w < 2) + 4 * lean * (1 if (sign < 0) == (w % 2 == 1) else 0.3) for w in range(4)]
            psi = [26.6 + 0.2 * min(warm, 6) + 0.1 * (w < 2) for w in range(4)]
            x, z = _xz(track, pos)
            while sector_idx < len(sectors) - 1 and pos >= sectors[sector_idx]:
                last_sector_ms = int(round((k * DT) * 1000)) - sector_start
                sector_start += last_sector_ms
                sector_idx += 1
            yield Frame(
                t=t + k * DT, speed_kmh=kmh, gas=throttle, brake=min(1.0, brake), steer=steer, gear=gear, rpm=rpm,
                fuel=fuel0 - BURN_PER_LAP * pos, g_lat=lat_g, g_lon=a / 9.81,
                slip_ratio=tuple(slip), slip_angle=tuple(slip_angle), wheel_slip=tuple(slip),
                tyre_pressure=tuple(psi), tyre_temp=tuple(temp), brake_temp=tuple(300 + 450 * brake for _ in range(4)),
                brake_pressure=tuple(brake for _ in range(4)), susp_travel=(0.03,) * 4, tc=tc, abs=abs_act,
                tyres_out=tyres_out, air_temp=22.0, road_temp=31.0, water_temp=88.0, kerb_vib=kerb, brake_bias=57.0,
                status=STATUS_LIVE, session=0, session_index=0, completed_laps=lap, position=1,
                current_ms=int(round(k * DT * 1000)), last_ms=last_ms, best_ms=best_ms, in_pit=False, in_pit_lane=False,
                sector_index=sector_idx, last_sector_ms=last_sector_ms, number_of_laps=0, tyre_compound="dry_compound",
                pos=min(0.9999, pos), x=x, z=z, valid_lap=True, fuel_per_lap=BURN_PER_LAP,
                fuel_est_laps=(fuel0 - BURN_PER_LAP * pos) / BURN_PER_LAP, session_time_left=3600.0, tc_level=3, abs_level=3,
                car=MOCK_CAR, track=MOCK_TRACK, player="Mock Driver", max_rpm=8000, max_fuel=MAX_FUEL, sector_count=len(sectors),
                track_length_m=length_m)
            s += max(0.5, speed) * DT
            k += 1
        t += k * DT
        last_ms = int(round(k * DT * 1000))
        best_ms = last_ms if best_ms == 0 else min(best_ms, last_ms)
        lap += 1


def demo_params() -> Iterator[LapParams]:
    while True:
        yield from DEMO_LAPS


class MockSource:
    """Plays the demo laps one frame per read(). `speedup` tells the sampler to read that much faster
    than real time (each frame is still 1/30 s of virtual time, so the numbers stay realistic)."""

    def __init__(self, track: Track, length_m: float = 0.0, speedup: float = 6.0, skip_laps: int = 0):
        self.speedup = max(1.0, speedup)
        # skip_laps: carry on after laps that were already seeded, so new laps get new lap numbers
        self._frames = simulate_laps(track, length_m or track.length_m or 7004.0, islice(demo_params(), skip_laps, None),
                                     first_lap=skip_laps)

    def read(self) -> Frame:
        return next(self._frames)

    def close(self) -> None:
        pass


def seed(sampler, track: Track, laps: int = 6) -> list:
    """Run the first few demo laps through the sampler's real pipeline, offline, so the store has laps at once."""
    frames = simulate_laps(track, track.length_m or 7004.0, demo_params())
    saved: list = []
    # one extra frame after the last line crossing is what finishes the final lap
    for f in frames:
        saved.extend(sampler.process_frame(f))
        if len(saved) >= laps:
            break
    return saved
