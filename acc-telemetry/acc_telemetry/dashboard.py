"""The free local lap viewer: FastAPI serving static pages, JSON endpoints and two WebSockets.

    /                      the app (static/index.html; no build step)
    /api/laps              saved laps (?track=&car=&limit=)
    /api/lap/{id}          one lap with its full trace, corner numbers, events, track outline
    /api/compare?a=&b=     delta curve, per-corner table and braking table for two laps (ids, 'last', 'best')
    /api/track/{name}      corner table + map
    /api/live              what get_live_state returns
    /api/tool/{name}       any MCP tool as plain JSON (query args), e.g. for Ultron over Tailscale
    /ws/live               ~10 Hz: live state and the current lap's trace
    /ws/alerts             low fuel, hot tyres, lockups, time lost in a corner, lap completed

Standalone (no MCP):  python -m acc_telemetry.dashboard [--mock]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import PACKAGE_DIR
from .runtime import Runtime, build
from .tools import Telemetry

STATIC = PACKAGE_DIR / "static"
log = logging.getLogger("acc.dashboard")


def _coerce(value: str):
    return int(value) if value.lstrip("-").isdigit() else {"true": True, "false": False}.get(value.lower(), value)


LOOPBACK = {"127.0.0.1", "localhost"}


def allowed_hosts(bind_host: str) -> list:
    """Host headers the viewer answers to: loopback, plus names in ACC_ALLOWED_HOSTS (e.g. the PC's
    Tailscale name when `tailscale serve` fronts it). Stops a web page in your browser from reading
    your telemetry through DNS rebinding. Binding beyond loopback is your own choice, so then anything goes."""
    if bind_host not in LOOPBACK:
        return ["*"]
    extra = [h.strip() for h in os.environ.get("ACC_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return sorted(LOOPBACK | set(extra))


def _same_origin(ws: WebSocket) -> bool:
    """Browsers don't apply the same-origin rule to WebSockets, so check the Origin header ourselves."""
    origin = ws.headers.get("origin")
    return origin is None or urlparse(origin).netloc == ws.headers.get("host")


def create_app(rt: Runtime, bind_host: str = "127.0.0.1") -> FastAPI:
    tel: Telemetry = rt.telemetry
    sampler = rt.sampler
    app = FastAPI(title="ACC lap viewer", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(bind_host))
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status():
        f = sampler.latest
        return {"mode": "mock" if rt.mock else "live", "status": sampler.status, "message": sampler.message,
                "track": f.track if f else None, "car": f.car if f else None, "laps_saved_this_run": sampler.laps_saved,
                "combos": rt.store.tracks()}

    @app.get("/api/laps")
    def laps(track: Optional[str] = None, car: Optional[str] = None, limit: int = 100):
        return {"laps": rt.store.list_laps(track, car, limit=max(1, min(limit, 500)))}

    @app.get("/api/lap/{lap_id}")
    def lap(lap_id: int):
        data = tel.lap_full(lap_id)
        if data is None:
            raise HTTPException(404, "no such lap")
        return data

    @app.get("/api/compare")
    def compare(a: str, b: str):
        data = tel.compare_full(_coerce(a), _coerce(b))
        if "error" in data:
            raise HTTPException(404, data["error"])
        return data

    @app.get("/api/track/{name}")
    def track(name: str):
        return tel.track_info(name)

    @app.get("/api/live")
    def live():
        return tel.get_live_state()

    @app.get("/api/tool/{name}")
    def tool(name: str, lap_id: Optional[str] = None, lap_a: Optional[str] = None, lap_b: Optional[str] = None,
             track: Optional[str] = None, car: Optional[str] = None, limit: Optional[int] = None,
             lap: Optional[int] = None, kind: Optional[str] = None, include_trace: bool = False, points: int = 60):
        args = {"get_lap": {"lap_id": _coerce(lap_id or "last"), "include_trace": include_trace, "points": points},
                "get_last_lap_summary": {"lap_id": _coerce(lap_id) if lap_id else None},
                "compare_laps": {"lap_a": _coerce(lap_a or "last"), "lap_b": _coerce(lap_b or "best")},
                "list_laps": {"track": track, "car": car, "limit": limit or 20},
                "get_recent_events": {"limit": limit or 12, "lap": lap, "kind": kind}}.get(name, {})
        try:
            return tel.call(name, **args)
        except KeyError:
            raise HTTPException(404, f"unknown tool {name!r}; try one of {', '.join(Telemetry.NAMES)}")

    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        if not _same_origin(ws):
            return await ws.close(code=1008)
        await ws.accept()
        try:
            while True:
                state = await asyncio.to_thread(tel.get_live_state)
                await ws.send_json({"state": state, "trace": sampler.current_lap_trace(150), "ref_id": sampler.ref_id,
                                    "track": sampler.track.name if sampler.track else None})
                await asyncio.sleep(0.1)
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.websocket("/ws/alerts")
    async def ws_alerts(ws: WebSocket):
        if not _same_origin(ws):
            return await ws.close(code=1008)
        await ws.accept()
        seen = max((a["seq"] for a in list(sampler.alerts)[:-10]), default=0)   # replay the last few, then stream
        try:
            while True:
                fresh = [a for a in list(sampler.alerts) if a["seq"] > seen]
                for a in fresh:
                    await ws.send_json(a)
                    seen = a["seq"]
                await asyncio.sleep(0.25)
        except (WebSocketDisconnect, RuntimeError):
            return

    return app


def serve_in_thread(rt: Runtime, host: str, port: int):
    """Run the dashboard inside this process (used by the MCP server). Returns the thread, or None."""
    import socket
    import threading

    import uvicorn

    with socket.socket() as s:
        try:
            s.bind((host, port))
        except OSError:
            log.warning("Dashboard port %s:%s is busy (another instance?); continuing without the dashboard.", host, port)
            return None
    server = uvicorn.Server(uvicorn.Config(create_app(rt, host), host=host, port=port, log_level="warning", access_log=False))
    t = threading.Thread(target=server.run, daemon=True, name="acc-dashboard")
    t.start()
    log.info("Dashboard on http://%s:%s", host, port)
    return t


def main(argv: Optional[list] = None) -> None:
    p = argparse.ArgumentParser(description="ACC lap viewer (no MCP). Reads the game, or --mock.")
    p.add_argument("--mock", action="store_true", help="play a synthetic car instead of reading ACC")
    p.add_argument("--mock-speed", type=float, default=6.0, help="mock laps run this much faster than real time")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--data-dir", default=None)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s: %(message)s")
    import uvicorn
    rt = build(mock=args.mock, data_dir=args.data_dir, mock_speed=args.mock_speed)
    host, port = args.host or rt.cfg.host, args.port or rt.cfg.port
    rt.start()
    print(f"Lap viewer on http://{host}:{port}  ({'mock' if args.mock else 'live'})", file=sys.stderr)
    try:
        uvicorn.run(create_app(rt, host), host=host, port=port, log_level="warning", access_log=False)
    finally:
        rt.stop()


if __name__ == "__main__":
    main()
