# ACC telemetry: MCP server + free lap viewer

One Python project for the **Windows PC** that does two things:

1. **MCP server** (stdio). Reads Assetto Corsa Competizione's shared memory live, so an assistant (Ultron, Claude Code, Claude Desktop) can ask "how are my tyres?", "what did I do wrong in Pouhon?" while you race.
2. **Lap viewer** (a local web page, same process). Saved laps, stacked charts, lap comparison with a time delta, a braking table, and a live view. Free, no accounts, no cloud, no build step.

Read-only: it only *opens* the game's shared memory for reading. It never writes to the game or injects anything.

```
 ACC ──shared memory──▶ sampler thread ──▶ SQLite (data/laps.sqlite3) ──▶ MCP tools  (stdio, for the assistant)
 (Windows only)         30 Hz traces                                  └──▶ FastAPI   http://127.0.0.1:8765
                        10 Hz live state, events, alerts
```

## Quick start

Needs Python 3.11+. On Windows:

```powershell
winget install Python.Python.3.12
cd acc-telemetry
py -3.12 -m venv .venv
.venv\Scripts\pip install -e .
```

**Try it without the game** (works on any OS):

```powershell
.venv\Scripts\python -m acc_telemetry.dashboard --mock      # lap viewer only
.venv\Scripts\python -m acc_telemetry.server --mock         # MCP server (+ the same viewer)
```

Open <http://127.0.0.1:8765>. Mock mode keeps its own database (`data\mock`), plays a synthetic car round Spa 6x faster than real time, and starts with six laps already saved. One of them loses time in Pouhon on purpose, so `compare_laps` has a known answer.

**With the game:** start ACC, then run the server (or let your MCP client start it, below). With the game closed the tools answer "ACC not running" and the sampler keeps retrying once a second; start the game whenever.

## Register the MCP server

Command, args, env (all env is optional):

```json
{
  "mcpServers": {
    "acc-telemetry": {
      "command": "C:\\path\\to\\acc-telemetry\\.venv\\Scripts\\python.exe",
      "args": ["-m", "acc_telemetry.server"],
      "env": { "ACC_DATA_DIR": "C:\\path\\to\\acc-telemetry\\data", "ACC_PORT": "8765" }
    }
  }
}
```

Claude Code: `claude mcp add acc-telemetry -- C:\path\to\acc-telemetry\.venv\Scripts\python.exe -m acc_telemetry.server`

Add `--mock` to `args` to test the registration without the game, and `--no-dashboard` if you don't want the viewer started with it. Run it as your normal Windows user, in the same login session as the game: ACC's memory blocks live in the `Local\` namespace.

### Using it from Ultron (on the Mac)

Everything the MCP tools return is also available as plain JSON from the viewer, so Ultron can reach the PC without a second protocol:

```
GET http://<pc>:8765/api/tool/get_live_state
GET http://<pc>:8765/api/tool/compare_laps?lap_a=last&lap_b=best
```

The viewer binds to `127.0.0.1` and has no password (same model as Ultron's own backend). To reach it from the Mac, publish it on your tailnet only, never with `funnel`:

```powershell
tailscale serve --bg 8765
$env:ACC_ALLOWED_HOSTS = "my-pc.tailXXXX.ts.net"   # the name Ultron will use; other Host headers are refused
```

Ultron's read-only `acc_read` tool (`backend/tools/acc.py`) calls these URLs; set `JARVIS_ACC_URL=https://<tailnet name>` in the Mac's `.env`.

## MCP tools

All read-only. Summaries first; raw traces only on request, and always thinned (at most 200 points).

| Tool | Answers |
|---|---|
| `get_live_state()` | Speed, gear, RPM, pedals, tyre temps and pressures, brake temps, fuel and fuel laps left, lap number and time, lap position (0 to 1), current corner name, delta to the best saved lap |
| `get_session_info()` | Track, car, session type, weather, air/road temperature, flag, laps done, session best and last lap |
| `get_last_lap_summary(lap_id?)` | Lap and sector times; per corner entry speed, minimum speed, brake point (metres before the apex), peak brake, trail braking, throttle pickup, peak lateral and longitudinal G; time vs best; events |
| `compare_laps(lap_a="last", lap_b="best")` | Where time was gained or lost by sector and corner/straight (distance-aligned delta), with the brake points and speeds behind the biggest differences. Positive = A slower |
| `get_tyre_report()` | Temps and pressures per tyre with hot/cold/low/high flags, brake temps, trend over the last laps |
| `get_fuel_report()` | Burn per lap, laps remaining, fuel to finish and whether a stop is needed, pit window |
| `get_recent_events(limit, lap?, kind?)` | Lockups, wheelspin, off-tracks, big slides, curb hits, with lap position and corner |
| `list_laps(track?, car?, limit)` | Saved laps: id, time, sectors, valid/clean |
| `get_lap(lap_id, include_trace=false, channels?, points=60)` | One lap; a thin trace only if asked |

Lap references are an id from `list_laps`, or `last`, `previous`, `best`.

## The lap viewer

| Page | What it shows |
|---|---|
| **Laps** (`#/`) | Every saved lap (refreshes every 3 s, so a lap you just finished appears within seconds). Filter by track and car; tick two laps to compare, or click "vs best" |
| **Lap** (`#/lap/ID`) | Stacked charts against lap position, one shared x axis: speed, brake (filled), throttle, steering, gear; optional RPM, tyre slip, TC/ABS, G. Corner names along the top, a track map that follows the cursor, a per-corner table, events |
| **Compare** (`#/compare/A/B`) | A and B overlaid, a time-delta trace underneath (red = A behind), corner names across the top, time lost per corner/straight, and the **braking table**: brake start, peak pressure, trail braking, entry/minimum speed and throttle pickup per corner, with "earlier" / "later" highlighted against the other lap |
| **Live** (`#/live`) | The current lap's speed/brake/throttle drawn as you drive, over the best lap as a dashed reference; delta, fuel, tyres, and the alert feed |

Drag on a chart to zoom, double-click to reset. The charts are a small built-in canvas library (`static/charts.js`), nothing to download.

Endpoints behind it: `/api/laps`, `/api/lap/{id}`, `/api/compare?a=&b=`, `/api/track/{name}`, `/api/live`, `/api/tool/{name}`, `/api/status`, WebSockets `/ws/live` and `/ws/alerts`.

### Alerts (phase 2)

`/ws/alerts` pushes JSON as things happen, so a separate overlay or voice layer doesn't have to poll:

```json
{"seq": 41, "type": "low_fuel", "message": "Low fuel: about 2.9 laps left", "at": "2026-10-16T14:02:11", "data": {"laps_left": 2.9}}
```

Types: `low_fuel`, `tyre_hot`, `delta_loss` (time lost in one corner vs your best lap), `lap` (a lap was completed), and `event` (lockup, wheelspin, slide, offtrack, curb).

## How it works

- **Data**: `Local\acpmf_physics`, `Local\acpmf_graphics`, `Local\acpmf_static`, opened read-only with `OpenFileMappingW` (so it never creates a mapping if the game isn't there). `acc_shm.py` holds the three structs; they were checked field by field against PyAccSharedMemory's reader (physics 800 bytes, graphics 1588, static 820). Strings are UTF-16 and decoded by hand, so parsing is tested on any OS.
- **Sampler** (`sampler.py`): one thread, `ACC_TRACE_HZ` (30) for lap traces and `ACC_SUMMARY_HZ` (10) for live state and alerts. Lap completion is detected from the lap counter *and* the position wrapping past the line, in either order; pauses, replays, restarts and joining mid-lap are handled. A lap is saved as "clean" only if it was recorded start to finish and never touched the pits.
- **Storage** (`store.py`): SQLite in `data/`. Each lap keeps its summary, events, and a trace resampled to 500 points by lap position (channels: time, speed, throttle, brake, steering, gear, rpm, lat/long G, TC, ABS, slip, x, z). The same lap can't be saved twice. A track map (position, x, z) is stored per track.
- **Comparison** (`analysis.py`): both laps sit on the same 500-point grid, so delta = `t_A[i] - t_B[i]`. Per-corner loss is the delta at the corner's end minus at its start; the pieces add up to the lap delta.
- **Corner names** (`tracks/*.json`): named windows (start, apex, end as fractions of the lap) including the braking zone. Spa is included: La Source, Eau Rouge / Raidillon, Les Combes, Malmedy, Rivage, Pouhon, Fagnes, Stavelot, Paul Frere, Blanchimont, Bus Stop. **Other tracks** work too: with no JSON file the corners are detected from your speed trace and called T1, T2, ... (the straights between them are "Straight after T3").

### Add a track

Copy `acc_telemetry/tracks/spa.json` to `data/tracks/<track>.json` (files there win) and edit it. The file name or an entry in `aliases` must match ACC's track id (see `get_session_info`, e.g. `spa`, `monza`). Corner positions are fractions of the lap: hover a chart in the Lap view, the x axis shows distance, divide by the lap length. The Spa windows came from Ultron's library (F1 timing data) and are approximate; trim them against your own laps.

## Settings (environment)

| Variable | Default | |
|---|---|---|
| `ACC_DATA_DIR` | `./data` (`./data/mock` with `--mock`) | where `laps.sqlite3` and your `tracks/` live |
| `ACC_HOST` / `ACC_PORT` | `127.0.0.1` / `8765` | viewer address. Keep it on loopback |
| `ACC_ALLOWED_HOSTS` | (none) | extra Host names the viewer answers to, e.g. your Tailscale name |
| `ACC_TRACE_HZ` / `ACC_SUMMARY_HZ` | `30` / `10` | sampling rates |
| `ACC_RING_LAPS` | `10` | laps kept in memory for fuel stats |

Event and tyre thresholds are in `acc_telemetry/config.py`.

## Check these on the first real session

Things that depend on how the game reports them, which I could not verify without it:

- **Steering** is shown as ACC's raw `steerAngle` (I believe -1 to 1 across the lock). Only its shape and relative size are used.
- **Wheel slip** units: lockup (`slipRatio < -0.35` while braking), wheelspin (`> 0.35` under power) and slides (rear `slipAngle` above 0.22) use guessed thresholds. If you see constant or no events, adjust `lockup_slip`, `wheelspin_slip`, `slide_angle` in `config.py`.
- **Sector times**: read from `lastSectorTime` as the duration of the sector just finished. If S1+S2 doesn't fit inside the lap time they're ignored and sectors come from the trace and the track's sector markers (which for Spa are approximate). Check that the Laps page's sector times match the in-game ones.
- **Off-track** uses `numberOfTyresOut >= 3`; **curb hit** uses `kerbVibration > 0.45`.
- **Tyre wear** isn't published in ACC's shared memory, so `get_tyre_report` reports temperature, pressure and pace trends instead.
- **Pit-window numbers** come straight from the static block (minutes into the race).

## Smoke-test checklist

Without the game (`--mock`):

1. `python -m unittest` passes.
2. `python -m acc_telemetry.dashboard --mock`, open <http://127.0.0.1:8765>: six laps listed; the fastest is marked "best".
3. Click lap 2, tick "vs best" (or open `#/compare/2/1`): the delta trace climbs through Pouhon, the headline says "Pouhon: lost 0.458 s", the braking table has rows for every corner.
4. Live tab: charts fill in as the mock lap runs; a new lap appears on the Laps page about every 23 seconds.
5. MCP: register the server with `--mock` and ask for `get_live_state`, `compare_laps`, `get_last_lap_summary`. Output is compact (a few KB), no raw traces.

With the game:

1. Start the server with ACC closed: `get_live_state` says "ACC not running". Start ACC and load a session: it becomes live without restarting anything.
2. In the pits or menus the status pill says menus/replay/paused and nothing is recorded.
3. Drive a lap. It appears in Laps within a few seconds, with the lap time matching the game's and S1/S2/S3 adding up to it. The out-lap shows "pit/partial".
4. While driving: `get_live_state` has plausible speed, gear, RPM, pedals, tyre temps (roughly 70 to 100 °C), pressures (roughly 26 to 28 psi), fuel dropping, and the right corner name.
5. Drive two laps with a deliberate mistake in one corner: `compare_laps` names that corner; the braking table shows "earlier"/"later" where you moved your brake point.
6. Lock a wheel or run wide: `get_recent_events` lists it with the corner.

## Tests

```powershell
.venv\Scripts\python -m unittest
```

51 tests: struct sizes and offsets, string decoding, frame flattening, lap detection (line crossed in either order, late lap time, pit laps, restarts, mid-lap joins), resampling, the delta calculation, "which corner lost most time", brake-point flags, corner detection, and the whole mock pipeline through the store, the tools and the HTTP API. No game, network or Windows needed.

## Windows setup

- `winget install Python.Python.3.12` (3.11 or newer), then `pip install -e .` in a venv (installs `mcp`, `fastapi`, `uvicorn`, `websockets`).
- Nothing else to install. No `.env` is required; the optional `ACC_*` variables above go in the MCP client's `env` block.
- To reach the viewer from the Mac: `tailscale serve --bg 8765` and set `ACC_ALLOWED_HOSTS` to the PC's tailnet name.

## Files

```
acc_telemetry/
  acc_shm.py     structs, Frame, read-only reader        server.py     MCP server (stdio)
  sampler.py     lap detection, events, alerts, thread   dashboard.py  FastAPI viewer + WebSockets
  store.py       SQLite                                   tools.py      the tool logic (shared by MCP and /api/tool)
  analysis.py    resample, delta, corner metrics          mock.py       synthetic car for --mock
  tracks.py      corner tables + corner detection         events.py     lockup / wheelspin / slide / off-track / curb
  config.py      settings          runtime.py  wiring     static/       index.html, app.js, charts.js, style.css
  tracks/spa.json
tests/
```

Credits: struct layout cross-checked against [PyAccSharedMemory](https://github.com/rrennoir/PyAccSharedMemory). The Spa outline and corner positions come from Ultron's track library (F1 timing data via FastF1; start-line aid from Lovely Sim Racing track data, CC BY-NC-SA 4.0), for personal use.
