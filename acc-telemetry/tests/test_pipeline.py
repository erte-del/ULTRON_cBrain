"""End to end in mock mode: frames -> sampler -> store -> tools and dashboard, no game and no sockets."""

import json
import time
import unittest

from acc_telemetry import mock
from acc_telemetry.acc_shm import AccNotRunning
from acc_telemetry.config import Settings
from acc_telemetry.dashboard import create_app
from acc_telemetry.runtime import Runtime, build
from acc_telemetry.sampler import Sampler
from acc_telemetry.store import LapRecord, Store
from acc_telemetry.tools import Telemetry
from acc_telemetry.tracks import load_track

from .helpers import asgi_get, tmp_dir


class Seeded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rt = build(mock=True, data_dir=tmp_dir(), seed_laps=5)
        cls.tel, cls.store = cls.rt.telemetry, cls.rt.store

    @classmethod
    def tearDownClass(cls):
        cls.rt.store.close()


class MockLaps(Seeded):
    def test_laps_were_saved_with_sector_times_that_add_up(self):
        laps = self.store.list_laps()
        self.assertEqual(len(laps), 5)
        for l in laps:
            self.assertTrue(l["clean"] and l["valid"])
            self.assertEqual(sum(l["sectors_ms"]), l["lap_time_ms"])
            self.assertTrue(130_000 < l["lap_time_ms"] < 140_000)

    def test_the_saved_trace_ends_at_the_official_lap_time(self):
        lap = self.store.get_lap(1)
        self.assertEqual(len(lap["trace"]["t"]), 500)
        self.assertAlmostEqual(lap["trace"]["t"][-1], lap["lap_time_ms"] / 1000, places=3)
        self.assertEqual(lap["trace"]["t"][0], 0.0)

    def test_same_lap_is_not_stored_twice(self):
        lap = self.store.get_lap(1)
        rec = LapRecord(track=lap["track"], car=lap["car"], lap_time_ms=lap["lap_time_ms"], trace=lap["trace"], lap_number=lap["lap_number"],
                        created_at=lap["created_at"])
        self.assertIsNone(self.store.save_lap(rec))
        self.assertEqual(len(self.store.list_laps()), 5)

    def test_events_are_found_and_kept_with_their_lap(self):
        kinds = {e["type"]: e for e in self.store.get_lap(3)["events"]}
        self.assertEqual(kinds["lockup"]["corner"], "Les Combes")
        self.assertIn("wheelspin", kinds)
        self.assertEqual({e["type"] for e in self.store.get_lap(2)["events"]}, {"slide"})

    def test_track_map_is_stored(self):
        self.assertGreater(len(self.store.get_track_map("spa")), 100)


class Tools(Seeded):
    def test_compare_laps_finds_pouhon(self):
        res = self.tel.compare_laps(2, 1)             # lap 2 carries 7% less speed through Pouhon
        self.assertTrue(res["most_time_lost"].startswith("Pouhon: lost"), res["most_time_lost"])
        self.assertAlmostEqual(res["total_delta_s"], 0.534, delta=0.01)
        top = res["biggest"][0]
        self.assertEqual(top["name"], "Pouhon")
        self.assertLess(top["a_min_kmh"], top["b_min_kmh"] - 5)

    def test_compare_defaults_and_words(self):
        res = self.tel.compare_laps("last", "best")
        self.assertEqual(res["lap_b"]["id"], 4)                     # lap 4 is the quickest of the five
        self.assertEqual(res["lap_a"]["id"], 5)
        self.assertIn("error", self.tel.compare_laps(3, 3))
        self.assertIn("error", self.tel.compare_laps(99, 1))

    def test_last_lap_summary_lists_corners_and_stays_compact(self):
        res = self.tel.get_last_lap_summary()
        self.assertEqual(res["lap_number"], 5)
        self.assertEqual([c["name"] for c in res["corners"]][:3], ["La Source", "Eau Rouge / Raidillon", "Les Combes"])
        self.assertIn("vs_best_s", res)
        for out in (res, self.tel.compare_laps(2, 1), self.tel.list_laps(), self.tel.get_tyre_report()):
            self.assertLess(len(json.dumps(out)), 6000)
            self.assertNotIn('"trace"', json.dumps(out))

    def test_raw_trace_only_when_asked_and_always_thin(self):
        self.assertNotIn("trace", self.tel.get_lap(1))
        thin = self.tel.get_lap(1, include_trace=True, channels=["speed", "brake"], points=5000)["trace"]
        self.assertLessEqual(len(thin["pos"]), 200)
        self.assertEqual(set(thin), {"pos", "speed", "brake"})

    def test_list_laps_filters(self):
        self.assertEqual(self.tel.list_laps(track="spa", limit=2)["count"], 2)
        self.assertEqual(self.tel.list_laps(track="monza")["count"], 0)

    def test_events_tyres_and_fuel_reports(self):
        ev = self.tel.get_recent_events(limit=5)             # nothing live yet, so the last saved lap's events
        self.assertTrue(ev["source"].startswith("saved lap"))
        self.assertEqual((ev["events"][0]["type"], ev["events"][0]["corner"]), ("offtrack", "Blanchimont"))
        fuel = self.tel.get_fuel_report()
        self.assertAlmostEqual(fuel["average_burn_l"], mock.BURN_PER_LAP, places=1)
        tyres = self.tel.get_tyre_report()
        self.assertEqual(tyres["laps_considered"], 5)
        self.assertGreater(tyres["trend_per_lap"]["FL"]["temp_c_per_lap"], 0)

    def test_unknown_track_gets_detected_corners(self):
        lap = self.store.get_lap(1)
        rec = LapRecord(track="monza", car="x", lap_time_ms=lap["lap_time_ms"], trace=lap["trace"], lap_number=1, length_m=5793.0)
        other = LapRecord(track="monza", car="x", lap_time_ms=lap["lap_time_ms"] + 500, trace=self.store.get_lap(2)["trace"], lap_number=2, length_m=5793.0)
        a, b = self.store.save_lap(rec), self.store.save_lap(other)
        res = self.tel.compare_laps(b, a)
        self.assertTrue(all(r["name"].startswith(("T", "Straight")) for r in res["biggest"]), res["biggest"])
        self.assertGreater(len(self.tel.get_lap(a)["corners"]), 3)


class NotRunning(unittest.TestCase):
    class Gone:
        def read(self):
            raise AccNotRunning("ACC not running (its shared memory isn't there yet)")

    def test_tools_say_so_instead_of_inventing_numbers(self):
        cfg = Settings()
        cfg.data_dir = tmp_dir()
        store = Store(cfg.db_path)
        s = Sampler(self.Gone(), store, cfg)
        s.start()
        time.sleep(0.3)
        s.stop()
        tel = Telemetry(s, store, cfg)
        live = tel.get_live_state()
        self.assertFalse(live["running"])
        self.assertIn("ACC not running", live["message"])
        self.assertIn("not running", tel.get_session_info()["message"])
        self.assertFalse(tel.get_fuel_report()["live"])
        self.assertEqual(tel.list_laps()["count"], 0)
        self.assertIn("error", tel.get_last_lap_summary())
        store.close()


class Dashboard(Seeded):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = create_app(cls.rt)

    def get(self, path):
        return asgi_get(self.app, path)

    def test_laps_lap_and_compare_endpoints(self):
        status, body = self.get("/api/laps")
        self.assertEqual((status, len(body["laps"])), (200, 5))
        status, lap = self.get("/api/lap/3")
        self.assertEqual(status, 200)
        self.assertEqual(len(lap["trace"]["speed"]), 500)
        self.assertEqual(lap["corners_metrics"][0]["name"], "La Source")
        status, cmp = self.get("/api/compare?a=2&b=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(cmp["delta"]), 500)
        self.assertEqual(cmp["summary"]["biggest"][0]["name"], "Pouhon")
        self.assertEqual(cmp["braking"][0]["corner"], "La Source")
        self.assertEqual(self.get("/api/lap/999")[0], 404)
        self.assertEqual(self.get("/api/compare?a=1&b=999")[0], 404)

    def test_mcp_tools_are_reachable_as_json(self):
        status, body = self.get("/api/tool/compare_laps?lap_a=2&lap_b=1")
        self.assertEqual(status, 200)
        self.assertTrue(body["most_time_lost"].startswith("Pouhon"))
        self.assertEqual(self.get("/api/tool/get_session_info")[0], 200)
        self.assertEqual(self.get("/api/tool/not_a_tool")[0], 404)

    def test_index_and_static_files(self):
        self.assertEqual(self.get("/")[0], 200)
        self.assertEqual(self.get("/static/app.js")[0], 200)

    def test_other_host_names_are_refused(self):
        self.assertEqual(asgi_get(self.app, "/api/laps", host="evil.example.com")[0], 400)
        self.assertEqual(asgi_get(self.app, "/api/laps", host="localhost:8765")[0], 200)

    def test_extra_hosts_can_be_allowed_for_tailscale(self):
        import os
        os.environ["ACC_ALLOWED_HOSTS"] = "pc.tail1234.ts.net"
        try:
            app = create_app(self.rt)
        finally:
            del os.environ["ACC_ALLOWED_HOSTS"]
        self.assertEqual(asgi_get(app, "/api/laps", host="pc.tail1234.ts.net")[0], 200)

    def test_status_says_mock(self):
        status, body = self.get("/api/status")
        self.assertEqual(body["mode"], "mock")


class MockSourceLive(unittest.TestCase):
    def test_live_frames_flow_through_the_sampler_and_get_a_corner_name(self):
        cfg = Settings()
        cfg.data_dir = tmp_dir()
        store = Store(cfg.db_path)
        s = Sampler(mock.MockSource(load_track("spa"), speedup=1), store, cfg)
        for _ in range(60 * 30):                       # a minute of driving
            s.process_frame(s.source.read())
        tel = Telemetry(s, store, cfg)
        live = tel.get_live_state()
        self.assertTrue(live["live"])
        self.assertGreater(live["speed_kmh"], 50)
        self.assertEqual(live["lap"], 1)
        self.assertIn("corner", live)
        self.assertEqual(set(live["tyre_temp_c"]), {"FL", "FR", "RL", "RR"})
        store.close()


if __name__ == "__main__":
    unittest.main()
