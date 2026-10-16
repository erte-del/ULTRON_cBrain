"""MCP server (stdio) for ACC live telemetry, with the lap viewer served from the same process.

    python -m acc_telemetry.server [--mock] [--no-dashboard] [--port 8765] [--data-dir DIR]

stdout belongs to the MCP protocol, so everything else (logs, the dashboard's URL) goes to stderr.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional, Union

try:                                        # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                         # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .dashboard import serve_in_thread
from .runtime import Runtime, build
from .tools import Telemetry

INSTRUCTIONS = """Live Assetto Corsa Competizione telemetry for the driver's current session, plus saved laps.
Start with get_live_state for "how is the car right now" and get_last_lap_summary / compare_laps for
"what did I do wrong". Answers are summaries; raw traces are only returned when get_lap is asked for them
(include_trace=true) and stay thin. If ACC isn't running the tools say so: don't guess numbers.
Lap references: an id from list_laps, or 'last', 'previous', 'best'."""

LapRef = Optional[Union[int, str]]


def make_server(tel: Telemetry):
    mcp = _Server("acc-telemetry", instructions=INSTRUCTIONS)

    @mcp.tool()
    def get_live_state() -> dict:
        """Right now: speed, gear, RPM, pedals, tyre temps/pressures, brake temps, fuel and fuel laps left, lap number,
        position on the lap (0-1), current corner name, delta to the best saved lap."""
        return tel.get_live_state()

    @mcp.tool()
    def get_session_info() -> dict:
        """Track, car, session type, weather and track/air temperatures, flag, laps done, session best and last lap."""
        return tel.get_session_info()

    @mcp.tool()
    def get_last_lap_summary(lap_id: LapRef = None) -> dict:
        """Last lap (or a given lap id): lap and sector times, and per corner the entry speed, minimum speed, brake point
        (metres before the apex), peak brake pressure, trail-braking time, throttle pickup position, peak lateral and
        longitudinal G, plus time vs the best lap and events during the lap."""
        return tel.get_last_lap_summary(lap_id)

    @mcp.tool()
    def compare_laps(lap_a: LapRef = "last", lap_b: LapRef = "best") -> dict:
        """Where lap A gained or lost time against lap B (default: last vs best), by sector and by corner/straight,
        with brake points and speeds for the biggest differences. Positive delta = lap A slower."""
        return tel.compare_laps(lap_a, lap_b)

    @mcp.tool()
    def get_tyre_report() -> dict:
        """Tyre temps and pressures per corner of the car with hot/cold/low/high flags, brake temps, and the trend over
        the last laps (ACC doesn't expose tyre wear, so this is temperature, pressure and pace trend)."""
        return tel.get_tyre_report()

    @mcp.tool()
    def get_fuel_report() -> dict:
        """Fuel burn per lap, laps remaining, and whether a stop is needed to finish; the pit window if the session has one."""
        return tel.get_fuel_report()

    @mcp.tool()
    def get_recent_events(limit: int = 12, lap: Optional[int] = None, kind: Optional[str] = None) -> dict:
        """Recent lockups, wheelspin, off-tracks, big slides and curb hits with lap position and corner name.
        kind is one of lockup, wheelspin, slide, offtrack, curb."""
        return tel.get_recent_events(limit, lap, kind)

    @mcp.tool()
    def list_laps(track: Optional[str] = None, car: Optional[str] = None, limit: int = 20) -> dict:
        """Saved laps, newest first: id, lap number, time, sectors, whether valid/clean. Filter by track and/or car."""
        return tel.list_laps(track, car, limit)

    @mcp.tool()
    def get_lap(lap_id: LapRef, include_trace: bool = False, channels: Optional[list[str]] = None, points: int = 60) -> dict:
        """One saved lap by id (or 'last'/'best'): times, corners, events. Set include_trace for a thinned trace
        (channels: speed, throttle, brake, steer, gear, rpm, lat_g, lon_g, tc, abs, slip, t; at most 200 points)."""
        return tel.get_lap(lap_id, include_trace, channels, points)

    return mcp


def main(argv: Optional[list] = None) -> None:
    p = argparse.ArgumentParser(description="ACC telemetry MCP server (stdio)")
    p.add_argument("--mock", action="store_true", help="play a synthetic car instead of reading ACC")
    p.add_argument("--mock-speed", type=float, default=6.0, help="mock laps run this much faster than real time")
    p.add_argument("--no-dashboard", action="store_true", help="don't serve the lap viewer")
    p.add_argument("--host", default=None, help="dashboard host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="dashboard port (default 8765)")
    p.add_argument("--data-dir", default=None, help="where laps.sqlite3 lives (default ./data, ./data/mock with --mock)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s: %(message)s")
    rt: Runtime = build(mock=args.mock, data_dir=args.data_dir, mock_speed=args.mock_speed)
    rt.start()
    if not args.no_dashboard:
        serve_in_thread(rt, args.host or rt.cfg.host, args.port or rt.cfg.port)
    try:
        make_server(rt.telemetry).run(transport="stdio")
    finally:
        rt.stop()


if __name__ == "__main__":
    main()
