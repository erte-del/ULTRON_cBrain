"""Small builders shared by the tests."""

import asyncio
import json
import tempfile
from pathlib import Path

from acc_telemetry.acc_shm import STATUS_LIVE, Frame

TRACK, CAR = "spa", "test_car"


def frame(**kw) -> Frame:
    base = dict(status=STATUS_LIVE, track=TRACK, car=CAR, session=0, session_index=0, speed_kmh=150.0, gas=0.5, brake=0.0,
                tyre_temp=(85.0,) * 4, tyre_pressure=(27.0,) * 4, fuel=50.0, track_length_m=7004.0)
    base.update(kw)
    return Frame(**base)


def lap_time(L, lap_ms=100_000):
    """Every lap gets its own time, like a real session (a repeated time can't be told apart from 'not published yet')."""
    return lap_ms + 100 * L


def drive(laps, lap_ms=100_000, frames_per_lap=1000, lag=0, lead=0, first_lap=0, start_pos=0.0, in_pit_lap=None, t0=0.0, last_ms0=0):
    """Frames for `laps` laps. lead: last frames of a lap already show the new lap counter and time;
    lag: first frames of a lap still show the old ones (the line is crossed in either order)."""
    out, t = [], t0
    dt = lap_ms / 1000 / frames_per_lap
    for k in range(laps):
        L = first_lap + k
        for i in range(frames_per_lap):
            p0 = start_pos if k == 0 else 0.0
            pos = p0 + (i / frames_per_lap) * (1 - p0)
            counter, last = L, (lap_time(L - 1, lap_ms) if k > 0 else last_ms0)
            if i < lag and k > 0:
                counter, last = L - 1, (lap_time(L - 2, lap_ms) if k > 1 else last_ms0)
            if i >= frames_per_lap - lead:
                counter, last = L + 1, lap_time(L, lap_ms)
            out.append(frame(pos=min(0.9999, pos), current_ms=int(i * dt * 1000), completed_laps=counter, last_ms=last,
                             t=t, in_pit=(in_pit_lap == k), sector_index=min(2, int(pos * 3))))
            t += dt
    # one frame of the next lap so the last lap is closed
    out.append(frame(pos=0.001, current_ms=20, completed_laps=first_lap + laps, last_ms=lap_time(first_lap + laps - 1, lap_ms), t=t))
    return out


def tmp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="acc-test-"))


def asgi_get(app, path: str, host: str = "127.0.0.1"):
    """GET through the ASGI app without a server or extra packages. Returns (status, parsed body)."""
    path, _, query = path.partition("?")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http", "path": path,
             "raw_path": path.encode(), "query_string": query.encode(), "headers": [(b"host", host.encode())],
             "client": ("127.0.0.1", 1), "server": ("test", 80), "root_path": ""}
    sent = []

    async def run():
        done = False

        async def receive():
            nonlocal done
            if not done:
                done = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.sleep(3600)

        async def send(msg):
            sent.append(msg)

        await app(scope, receive, send)

    asyncio.run(run())
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body


def synth_trace(speed_fn, brake_fn=lambda p: 0.0, throttle_fn=lambda p: 1.0, steer_fn=lambda p: 0.0, length_m=7000.0, n=500) -> dict:
    """A resampled lap built from functions of lap position; t comes from integrating speed over distance."""
    p = [i / (n - 1) for i in range(n)]
    speed = [speed_fn(x) for x in p]
    t = [0.0]
    for i in range(1, n):
        v = max(1.0, (speed[i] + speed[i - 1]) / 2 / 3.6)
        t.append(t[-1] + length_m / (n - 1) / v)
    zeros = [0.0] * n
    return {"t": t, "speed": speed, "throttle": [throttle_fn(x) for x in p], "brake": [brake_fn(x) for x in p],
            "steer": [steer_fn(x) for x in p], "gear": [4.0] * n, "rpm": [7000.0] * n, "lat_g": zeros[:], "lon_g": zeros[:],
            "tc": zeros[:], "abs": zeros[:], "slip": zeros[:], "x": zeros[:], "z": zeros[:]}
