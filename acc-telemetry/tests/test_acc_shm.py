import struct
import sys
import unittest

from acc_telemetry import acc_shm as shm


class StructTests(unittest.TestCase):
    def test_sizes_match_the_reference_reader(self):
        # PyAccSharedMemory's sequential reader consumes exactly this many bytes per block
        self.assertEqual(shm.PHYSICS_SIZE, 800)
        self.assertEqual(shm.GRAPHICS_SIZE, 1588)
        self.assertEqual(shm.STATIC_SIZE, 820)

    def test_offsets_of_key_fields(self):
        P, G, S = shm.Physics, shm.Graphics, shm.Static
        self.assertEqual((P.gas.offset, P.brake.offset, P.speedKmh.offset), (4, 8, 28))
        self.assertEqual(G.completedLaps.offset, 132)           # after 3 ints and four 15-char strings
        self.assertEqual(S.numberOfSessions.offset, 60)
        # float fields land where a hand-written struct format puts them
        raw = bytearray(shm.PHYSICS_SIZE)
        struct.pack_into("<f", raw, 28, 187.5)
        struct.pack_into("<i", raw, 16, 4)
        p = P.from_buffer_copy(bytes(raw))
        self.assertAlmostEqual(p.speedKmh, 187.5)
        self.assertEqual(p.gear, 4)

    def test_wide_strings_round_trip_and_stop_at_nul(self):
        s = shm.Static()
        shm.set_wstr(s.track, "spa")
        shm.set_wstr(s.carModel, "amr_v12_vantage_gt3")
        copy = shm.Static.from_buffer_copy(bytes(s))
        self.assertEqual(shm.wstr(copy.track), "spa")
        self.assertEqual(shm.wstr(copy.carModel), "amr_v12_vantage_gt3")
        shm.set_wstr(s.track, "x" * 100)                          # too long: truncated, never overruns
        self.assertEqual(len(shm.wstr(s.track)), 32)

    def test_frame_from_blocks(self):
        p, g, s = shm.Physics(), shm.Graphics(), shm.Static()
        p.speedKmh, p.gas, p.brake, p.gear, p.rpms, p.fuel = 211.0, 0.8, 0.0, 5, 7100, 41.5   # raw gear 5 = 4th gear
        p.accG[0], p.accG[2] = 1.2, -0.4
        for i in range(4):
            p.wheelsPressure[i], p.tyreCoreTemperature[i], p.slipRatio[i] = 27.5 + i * 0.1, 80 + i, 0.01 * i
        g.status, g.session, g.completedLaps, g.iCurrentTime, g.normalizedCarPosition = 2, 0, 3, 45123, 0.42
        g.activeCars, g.playerCarID = 3, 7
        for i, cid in enumerate((5, 7, 9)):
            g.carID[i] = cid
            g.carCoordinates[i][0], g.carCoordinates[i][2] = 100.0 * (i + 1), -50.0 * (i + 1)
        shm.set_wstr(g.tyreCompound, "dry_compound")
        shm.set_wstr(s.track, "spa")
        shm.set_wstr(s.carModel, "ferrari_296_gt3")
        s.maxRpm, s.maxFuel, s.sectorCount = 8000, 104.0, 3
        f = shm.frame_from_blocks(p, g, s, t=1.0)
        self.assertEqual((f.gear, f.rpm, round(f.speed_kmh)), (4, 7100, 211))
        self.assertAlmostEqual(f.g_lat, 1.2, places=5)
        self.assertAlmostEqual(f.g_lon, -0.4, places=5)
        self.assertEqual((f.track, f.car, f.tyre_compound), ("spa", "ferrari_296_gt3", "dry_compound"))
        self.assertEqual((f.status, f.completed_laps, f.current_ms), (2, 3, 45123))
        self.assertEqual((f.x, f.z), (200.0, -100.0))             # slot of carID 7, the player
        self.assertAlmostEqual(f.tyre_pressure[2], 27.7, places=4)

    @unittest.skipIf(sys.platform == "win32", "checks the non-Windows message")
    def test_reader_off_windows_says_so(self):
        with self.assertRaises(shm.AccNotRunning) as cm:
            shm.ShmReader()
        self.assertIn("Windows", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
