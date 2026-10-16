"""ACC shared memory: the three blocks the game publishes, and a read-only reader (Windows).

ACC exposes Local\\acpmf_physics, Local\\acpmf_graphics and Local\\acpmf_static. The layouts below
follow the ACC shared memory documentation (v1.8.x) and were cross-checked field by field against
PyAccSharedMemory's reader. All structs are packed to 4 bytes, like the game's C++ header.

Strings are UTF-16 `wchar_t` arrays. They are declared as uint16 arrays and decoded by hand, so the
structs have the same size and offsets on every OS (ctypes' c_wchar is 4 bytes outside Windows) and
the parsing can be unit-tested anywhere.

Read-only: the reader opens the game's mappings with FILE_MAP_READ and never creates one.
"""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# --- constants -------------------------------------------------------------------------------

STATUS_OFF, STATUS_REPLAY, STATUS_LIVE, STATUS_PAUSE = 0, 1, 2, 3
STATUS_NAMES = {0: "off", 1: "replay", 2: "live", 3: "pause"}
SESSION_NAMES = {-1: "unknown", 0: "practice", 1: "qualify", 2: "race", 3: "hotlap",
                 4: "time attack", 5: "drift", 6: "drag", 7: "hotstint", 8: "hotlap superpole"}
FLAG_NAMES = {0: "none", 1: "blue", 2: "yellow", 3: "black", 4: "white", 5: "checkered", 6: "penalty",
              7: "green", 8: "orange"}
GRIP_NAMES = {0: "green", 1: "fast", 2: "optimum", 3: "greasy", 4: "damp", 5: "wet", 6: "flooded"}
RAIN_NAMES = {0: "none", 1: "drizzle", 2: "light", 3: "medium", 4: "heavy", 5: "thunderstorm"}

PHYSICS_NAME = "Local\\acpmf_physics"
GRAPHICS_NAME = "Local\\acpmf_graphics"
STATIC_NAME = "Local\\acpmf_static"

F, I, W = ctypes.c_float, ctypes.c_int32, ctypes.c_uint16  # W: one UTF-16 code unit of a wchar_t

# --- structs ---------------------------------------------------------------------------------


class Physics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", I), ("gas", F), ("brake", F), ("fuel", F), ("gear", I), ("rpms", I),
        ("steerAngle", F), ("speedKmh", F), ("velocity", F * 3), ("accG", F * 3),
        ("wheelSlip", F * 4), ("wheelLoad", F * 4), ("wheelsPressure", F * 4),
        ("wheelAngularSpeed", F * 4), ("tyreWear", F * 4), ("tyreDirtyLevel", F * 4),
        ("tyreCoreTemperature", F * 4), ("camberRAD", F * 4), ("suspensionTravel", F * 4),
        ("drs", F), ("tc", F), ("heading", F), ("pitch", F), ("roll", F), ("cgHeight", F),
        ("carDamage", F * 5), ("numberOfTyresOut", I), ("pitLimiterOn", I), ("abs", F),
        ("kersCharge", F), ("kersInput", F), ("autoShifterOn", I), ("rideHeight", F * 2),
        ("turboBoost", F), ("ballast", F), ("airDensity", F), ("airTemp", F), ("roadTemp", F),
        ("localAngularVel", F * 3), ("finalFF", F), ("performanceMeter", F),
        ("engineBrake", I), ("ersRecoveryLevel", I), ("ersPowerLevel", I), ("ersHeatCharging", I),
        ("ersIsCharging", I), ("kersCurrentKJ", F), ("drsAvailable", I), ("drsEnabled", I),
        ("brakeTemp", F * 4), ("clutch", F), ("tyreTempI", F * 4), ("tyreTempM", F * 4),
        ("tyreTempO", F * 4), ("isAIControlled", I), ("tyreContactPoint", (F * 3) * 4),
        ("tyreContactNormal", (F * 3) * 4), ("tyreContactHeading", (F * 3) * 4),
        ("brakeBias", F), ("localVelocity", F * 3), ("P2PActivations", I), ("P2PStatus", I),
        ("currentMaxRpm", F), ("mz", F * 4), ("fx", F * 4), ("fy", F * 4), ("slipRatio", F * 4),
        ("slipAngle", F * 4), ("tcinAction", I), ("absInAction", I), ("suspensionDamage", F * 4),
        ("tyreTemp", F * 4), ("waterTemp", F), ("brakePressure", F * 4),
        ("frontBrakeCompound", I), ("rearBrakeCompound", I), ("padLife", F * 4), ("discLife", F * 4),
        ("ignitionOn", I), ("starterEngineOn", I), ("isEngineRunning", I),
        ("kerbVibration", F), ("slipVibrations", F), ("gVibrations", F), ("absVibrations", F),
    ]


class Graphics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", I), ("status", I), ("session", I),
        ("currentTime", W * 15), ("lastTime", W * 15), ("bestTime", W * 15), ("split", W * 15),
        ("completedLaps", I), ("position", I), ("iCurrentTime", I), ("iLastTime", I),
        ("iBestTime", I), ("sessionTimeLeft", F), ("distanceTraveled", F), ("isInPit", I),
        ("currentSectorIndex", I), ("lastSectorTime", I), ("numberOfLaps", I),
        ("tyreCompound", W * 33), ("replayTimeMultiplier", F), ("normalizedCarPosition", F),
        ("activeCars", I), ("carCoordinates", (F * 3) * 60), ("carID", I * 60), ("playerCarID", I),
        ("penaltyTime", F), ("flag", I), ("penalty", I), ("idealLineOn", I), ("isInPitLane", I),
        ("surfaceGrip", F), ("mandatoryPitDone", I), ("windSpeed", F), ("windDirection", F),
        ("isSetupMenuVisible", I), ("mainDisplayIndex", I), ("secondaryDisplayIndex", I),
        ("TC", I), ("TCCut", I), ("EngineMap", I), ("ABS", I), ("fuelXLap", F), ("rainLights", I),
        ("flashingLights", I), ("lightsStage", I), ("exhaustTemperature", F), ("wiperLV", I),
        ("driverStintTotalTimeLeft", I), ("driverStintTimeLeft", I), ("rainTyres", I),
        ("sessionIndex", I), ("usedFuel", F), ("deltaLapTime", W * 15), ("iDeltaLapTime", I),
        ("estimatedLapTime", W * 15), ("iEstimatedLapTime", I), ("isDeltaPositive", I),
        ("iSplit", I), ("isValidLap", I), ("fuelEstimatedLaps", F), ("trackStatus", W * 33),
        ("missingMandatoryPits", I), ("clock", F), ("directionLightsLeft", I),
        ("directionLightsRight", I), ("globalYellow", I), ("globalYellow1", I),
        ("globalYellow2", I), ("globalYellow3", I), ("globalWhite", I), ("globalGreen", I),
        ("globalChequered", I), ("globalRed", I), ("mfdTyreSet", I), ("mfdFuelToAdd", F),
        ("mfdTyrePressureLF", F), ("mfdTyrePressureRF", F), ("mfdTyrePressureLR", F),
        ("mfdTyrePressureRR", F), ("trackGripStatus", I), ("rainIntensity", I),
        ("rainIntensityIn10min", I), ("rainIntensityIn30min", I), ("currentTyreSet", I),
        ("strategyTyreSet", I), ("gapAhead", I), ("gapBehind", I),
    ]


class Static(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", W * 15), ("acVersion", W * 15), ("numberOfSessions", I), ("numCars", I),
        ("carModel", W * 33), ("track", W * 33), ("playerName", W * 33), ("playerSurname", W * 33),
        ("playerNick", W * 33), ("sectorCount", I), ("maxTorque", F), ("maxPower", F),
        ("maxRpm", I), ("maxFuel", F), ("suspensionMaxTravel", F * 4), ("tyreRadius", F * 4),
        ("maxTurboBoost", F), ("deprecated1", F), ("deprecated2", F), ("penaltiesEnabled", I),
        ("aidFuelRate", F), ("aidTireRate", F), ("aidMechanicalDamage", F),
        ("aidAllowTyreBlankets", F), ("aidStability", F), ("aidAutoClutch", I), ("aidAutoBlip", I),
        ("hasDRS", I), ("hasERS", I), ("hasKERS", I), ("kersMaxJ", F),
        ("engineBrakeSettingsCount", I), ("ersPowerControllerCount", I), ("trackSPlineLength", F),
        ("trackConfiguration", W * 33), ("ersMaxJ", F), ("isTimedRace", I), ("hasExtraLap", I),
        ("carSkin", W * 33), ("reversedGridPositions", I), ("pitWindowStart", I),
        ("pitWindowEnd", I), ("isOnline", I), ("dryTyresName", W * 33), ("wetTyresName", W * 33),
    ]


# byte sizes of the blocks as laid out above (asserted in tests against the reference reader)
PHYSICS_SIZE, GRAPHICS_SIZE, STATIC_SIZE = ctypes.sizeof(Physics), ctypes.sizeof(Graphics), ctypes.sizeof(Static)


def wstr(arr) -> str:
    """Decode a UTF-16 code-unit array up to its first NUL."""
    units = []
    for u in arr:
        if u == 0:
            break
        units.append(u)
    return b"".join(u.to_bytes(2, "little") for u in units).decode("utf-16-le", errors="replace")


def set_wstr(arr, text: str) -> None:
    """Write text into a UTF-16 array (used by the mock and the tests)."""
    raw = text.encode("utf-16-le")[: (len(arr) - 1) * 2]
    for i in range(len(arr)):
        arr[i] = int.from_bytes(raw[i * 2:i * 2 + 2], "little") if i * 2 < len(raw) else 0


# --- the flat sample every other module works with --------------------------------------------


@dataclass
class Frame:
    """One reading of all three blocks, reduced to what the telemetry needs.

    Wheel order everywhere: FL, FR, RL, RR. gear: -1 reverse, 0 neutral, 1.. forward.
    Mock frames use the same type, so nothing downstream knows the difference.
    """
    t: float = 0.0                       # monotonic seconds at read time
    # physics
    speed_kmh: float = 0.0
    gas: float = 0.0
    brake: float = 0.0
    steer: float = 0.0                   # ACC's steerAngle, passed through
    gear: int = 0
    rpm: int = 0
    fuel: float = 0.0                    # litres in the tank
    g_lat: float = 0.0
    g_lon: float = 0.0
    slip_ratio: tuple = (0.0,) * 4
    slip_angle: tuple = (0.0,) * 4
    wheel_slip: tuple = (0.0,) * 4
    tyre_pressure: tuple = (0.0,) * 4    # psi
    tyre_temp: tuple = (0.0,) * 4        # core, °C
    brake_temp: tuple = (0.0,) * 4
    brake_pressure: tuple = (0.0,) * 4
    susp_travel: tuple = (0.0,) * 4
    tc: float = 0.0                      # TC / ABS intervention
    abs: float = 0.0
    tyres_out: int = 0
    pit_limiter: bool = False
    air_temp: float = 0.0
    road_temp: float = 0.0
    water_temp: float = 0.0
    kerb_vib: float = 0.0
    brake_bias: float = 0.0
    # graphics
    status: int = STATUS_OFF
    session: int = -1
    session_index: int = 0
    completed_laps: int = 0
    position: int = 0
    current_ms: int = 0
    last_ms: int = 0
    best_ms: int = 0
    delta_ms: int = 0                    # the game's own delta to its best lap
    in_pit: bool = False
    in_pit_lane: bool = False
    sector_index: int = 0
    last_sector_ms: int = 0
    number_of_laps: int = 0
    tyre_compound: str = ""
    pos: float = 0.0                     # normalizedCarPosition, 0..1 around the lap
    x: float = 0.0
    z: float = 0.0
    valid_lap: bool = True
    fuel_per_lap: float = 0.0            # the game's own estimate
    fuel_est_laps: float = 0.0
    session_time_left: float = 0.0
    flag: int = 0
    used_fuel: float = 0.0
    tc_level: int = 0
    abs_level: int = 0
    engine_map: int = 0
    rain_intensity: int = 0
    track_grip: int = 0
    wind_speed: float = 0.0
    # static
    car: str = ""
    track: str = ""
    player: str = ""
    max_rpm: int = 0
    max_fuel: float = 0.0
    sector_count: int = 3
    pit_window_start: int = 0            # minutes into the race, 0 = none
    pit_window_end: int = 0
    track_length_m: float = 0.0


def frame_from_blocks(phys: Physics, gfx: Graphics, stat: Static, t: Optional[float] = None) -> Frame:
    """Flatten the three parsed blocks into a Frame."""
    p, g, s = phys, gfx, stat
    me = 0
    for i in range(max(0, min(g.activeCars, 60))):  # the player's slot in the car list
        if g.carID[i] == g.playerCarID:
            me = i
            break
    four = lambda a: tuple(float(v) for v in a)  # noqa: E731
    return Frame(
        t=time.monotonic() if t is None else t,
        speed_kmh=p.speedKmh, gas=p.gas, brake=p.brake, steer=p.steerAngle,
        gear=int(p.gear) - 1, rpm=int(p.rpms), fuel=p.fuel, g_lat=p.accG[0], g_lon=p.accG[2],
        slip_ratio=four(p.slipRatio), slip_angle=four(p.slipAngle), wheel_slip=four(p.wheelSlip),
        tyre_pressure=four(p.wheelsPressure), tyre_temp=four(p.tyreCoreTemperature),
        brake_temp=four(p.brakeTemp), brake_pressure=four(p.brakePressure),
        susp_travel=four(p.suspensionTravel), tc=p.tc, abs=p.abs, tyres_out=int(p.numberOfTyresOut),
        pit_limiter=bool(p.pitLimiterOn), air_temp=p.airTemp, road_temp=p.roadTemp,
        water_temp=p.waterTemp, kerb_vib=p.kerbVibration, brake_bias=p.brakeBias,
        status=int(g.status), session=int(g.session), session_index=int(g.sessionIndex),
        completed_laps=int(g.completedLaps), position=int(g.position), current_ms=int(g.iCurrentTime),
        last_ms=int(g.iLastTime), best_ms=int(g.iBestTime), delta_ms=int(g.iDeltaLapTime),
        in_pit=bool(g.isInPit), in_pit_lane=bool(g.isInPitLane), sector_index=int(g.currentSectorIndex),
        last_sector_ms=int(g.lastSectorTime), number_of_laps=int(g.numberOfLaps),
        tyre_compound=wstr(g.tyreCompound), pos=float(g.normalizedCarPosition),
        x=g.carCoordinates[me][0], z=g.carCoordinates[me][2], valid_lap=bool(g.isValidLap),
        fuel_per_lap=g.fuelXLap, fuel_est_laps=g.fuelEstimatedLaps, session_time_left=g.sessionTimeLeft,
        flag=int(g.flag), used_fuel=g.usedFuel, tc_level=int(g.TC), abs_level=int(g.ABS),
        engine_map=int(g.EngineMap), rain_intensity=int(g.rainIntensity),
        track_grip=int(g.trackGripStatus), wind_speed=g.windSpeed,
        car=wstr(s.carModel), track=wstr(s.track), player=wstr(s.playerName),
        max_rpm=int(s.maxRpm), max_fuel=s.maxFuel, sector_count=int(s.sectorCount) or 3,
        pit_window_start=int(s.pitWindowStart), pit_window_end=int(s.pitWindowEnd),
        track_length_m=float(s.trackSPlineLength),
    )


# --- the reader ---------------------------------------------------------------------------------


class AccNotRunning(Exception):
    """The game's shared memory isn't there (game closed, or not on Windows)."""


class _Mapping:
    """A read-only view of one named file mapping the game created (Windows)."""

    FILE_MAP_READ = 0x0004

    def __init__(self, name: str, size: int):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        k32.OpenFileMappingW.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._k32, self.size = k32, size
        self._handle = k32.OpenFileMappingW(self.FILE_MAP_READ, False, name)
        if not self._handle:
            raise AccNotRunning("ACC not running (its shared memory isn't there yet)")
        # 0 = map the whole section (it is page-rounded, so reading `size` bytes from it is safe)
        self._view = k32.MapViewOfFile(self._handle, self.FILE_MAP_READ, 0, 0, 0)
        if not self._view:
            k32.CloseHandle(self._handle)
            raise AccNotRunning("ACC shared memory could not be mapped")

    def read(self) -> bytes:
        return ctypes.string_at(self._view, self.size)

    def close(self) -> None:
        self._k32.UnmapViewOfFile(self._view)
        self._k32.CloseHandle(self._handle)


class ShmReader:
    """Reads Frames from the running game. `read()` raises AccNotRunning when it isn't there."""

    def __init__(self):
        if sys.platform != "win32":
            raise AccNotRunning("Reading ACC live needs Windows (use --mock elsewhere)")
        self._maps: Optional[tuple[_Mapping, _Mapping, _Mapping]] = None

    def _open(self) -> None:
        a = _Mapping(PHYSICS_NAME, PHYSICS_SIZE)
        try:
            b = _Mapping(GRAPHICS_NAME, GRAPHICS_SIZE)
            c = _Mapping(STATIC_NAME, STATIC_SIZE)
        except AccNotRunning:
            a.close()
            raise
        self._maps = (a, b, c)

    def read(self) -> Frame:
        if self._maps is None:
            self._open()
        assert self._maps
        for _ in range(3):  # a torn read (packetId changed while copying) is just retried
            raw_p, raw_g, raw_s = (m.read() for m in self._maps)
            phys, gfx = Physics.from_buffer_copy(raw_p), Graphics.from_buffer_copy(raw_g)
            if Physics.from_buffer_copy(self._maps[0].read()).packetId == phys.packetId:
                break
        return frame_from_blocks(phys, gfx, Static.from_buffer_copy(raw_s))

    def close(self) -> None:
        if self._maps:
            for m in self._maps:
                m.close()
            self._maps = None
