import math
import unittest

from acc_telemetry import analysis
from acc_telemetry.tracks import Corner, Track, auto_corners, load_track

from .helpers import synth_trace

LENGTH = 7000.0


def dip(centre, width, depth):
    return lambda p: depth * math.exp(-0.5 * ((p - centre) / width) ** 2)


def lap(min_x=180.0, min_y=120.0, brake_x_start=0.30, brake_y_start=0.60):
    """A lap with two corners, X at 0.35 and Y at 0.65; each with a brake zone before its apex."""
    def speed(p):
        v = 280.0
        v -= (280 - min_x) * math.exp(-0.5 * ((p - 0.35) / 0.015) ** 2)
        v -= (280 - min_y) * math.exp(-0.5 * ((p - 0.65) / 0.012) ** 2)
        return v

    def brake(p):
        return 0.9 if (brake_x_start <= p < 0.345) or (brake_y_start <= p < 0.645) else 0.0

    def throttle(p):
        return 0.0 if (brake(p) > 0 or 0.345 <= p < 0.36 or 0.645 <= p < 0.66) else 1.0
    return synth_trace(speed, brake, throttle, steer_fn=lambda p: 0.5 if 0.32 < p < 0.38 or 0.62 < p < 0.68 else 0.0)


TRACK = Track(key="t", name="Test", length_m=LENGTH, sectors=[0.4, 0.8, 1.0],
              corners=[Corner("X", 0.28, 0.35, 0.42, "R", 180), Corner("Y", 0.58, 0.65, 0.72, "L", 120)])


class Resample(unittest.TestCase):
    def test_grid_is_pinned_to_the_line_at_both_ends(self):
        samples = [(i / 100, i * 1.0, 100 + i, 0.5, 0.0, 0.0, 3, 6000, 0, 0, 0, 0, 0, 0, 0) for i in range(1, 99)]
        tr = analysis.resample(samples, 100.0, 500)
        self.assertEqual(len(tr["t"]), 500)
        self.assertEqual((tr["t"][0], tr["t"][-1]), (0.0, 100.0))
        self.assertAlmostEqual(tr["speed"][250], 100 + 50.1, delta=0.2)
        self.assertTrue(all(b >= a for a, b in zip(tr["t"], tr["t"][1:])))
        self.assertTrue(set(tr["gear"]) == {3.0})

    def test_samples_that_go_backwards_are_dropped(self):
        samples = [(0.1, 1, 100, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0), (0.05, 2, 999, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0),
                   (0.5, 50, 120, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0), (0.9, 90, 130, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0)]
        tr = analysis.resample(samples, 100.0, 50)
        self.assertLess(max(tr["speed"]), 200)

    def test_too_few_samples_is_an_error(self):
        with self.assertRaises(ValueError):
            analysis.resample([(0.5, 1, 100, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0)], 100.0)


class Delta(unittest.TestCase):
    def test_delta_is_zero_for_the_same_lap_and_lap_time_difference_at_the_end(self):
        a, b = lap(), lap(min_y=100)
        self.assertTrue(all(d == 0 for d in analysis.delta_curve(a, a)))
        d = analysis.delta_curve(b, a)                 # B slower in corner Y
        self.assertAlmostEqual(d[-1], b["t"][-1] - a["t"][-1], places=9)
        self.assertGreater(d[-1], 0.1)

    def test_pieces_add_up_to_the_lap_delta(self):
        a, b = lap(min_y=95), lap()
        delta = analysis.delta_curve(a, b)
        rows = analysis.segment_deltas(delta, TRACK)
        self.assertAlmostEqual(sum(r["delta_s"] for r in rows), delta[-1], places=6)

    def test_compare_names_the_corner_where_most_time_was_lost(self):
        slow_y = lap(min_y=95)        # carries 25 km/h less through Y
        fast = lap()
        res = analysis.compare(slow_y, fast, TRACK, LENGTH)
        self.assertTrue(res["most_time_lost"].startswith("Y: lost"), res["most_time_lost"])
        self.assertEqual(res["biggest"][0]["name"], "Y")
        self.assertGreater(res["biggest"][0]["delta_s"], 0.1)
        self.assertIsNone(res["most_time_gained"])
        # the other way round: the same corner is where time was gained
        back = analysis.compare(fast, slow_y, TRACK, LENGTH)
        self.assertTrue(back["most_time_gained"].startswith("Y: gained"))
        self.assertLess(back["total_delta_s"], 0)

    def test_sector_deltas_use_the_track_markers(self):
        res = analysis.compare(lap(min_y=95), lap(), TRACK, LENGTH)
        s = {x["sector"]: x["delta_s"] for x in res["sectors"]}
        self.assertAlmostEqual(s[1], 0.0, places=3)          # Y sits in sector 2 (0.4 to 0.8)
        self.assertGreater(s[2], 0.1)


class CornerMetrics(unittest.TestCase):
    def test_numbers_for_one_corner(self):
        tr = lap(brake_x_start=0.30)
        m = analysis.corner_metrics(tr, TRACK.corners[0], LENGTH)
        self.assertAlmostEqual(m["min_kmh"], 180, delta=3)
        self.assertAlmostEqual(m["brake_start_pos"], 0.30, delta=0.004)
        self.assertAlmostEqual(m["brake_dist_m"], (0.35 - 0.30) * LENGTH, delta=30)
        self.assertEqual(m["brake_peak"], 0.9)
        self.assertGreater(m["trail_s"], 0.0)                 # braking continues once steering is in
        self.assertAlmostEqual(m["throttle_pickup_pos"], 0.36, delta=0.006)

    def test_brake_point_difference_is_flagged_earlier_or_later(self):
        early, late = lap(brake_x_start=0.29), lap(brake_x_start=0.31)
        rows = {r["corner"]: r for r in analysis.braking_table(early, late, TRACK, LENGTH)}
        self.assertEqual(rows["X"]["brake"], "earlier")
        self.assertGreater(rows["X"]["brake_diff_m"], 0)      # A starts braking earlier than B
        self.assertEqual(rows["Y"]["brake"], "same")
        flipped = {r["corner"]: r for r in analysis.braking_table(late, early, TRACK, LENGTH)}
        self.assertEqual(flipped["X"]["brake"], "later")

    def test_a_corner_without_braking_has_no_brake_point(self):
        tr = synth_trace(lambda p: 200 - 40 * math.exp(-0.5 * ((p - 0.5) / 0.02) ** 2))
        m = analysis.corner_metrics(tr, Corner("Kink", 0.45, 0.5, 0.55), LENGTH)
        self.assertIsNone(m["brake_start_pos"])
        self.assertIsNone(m["brake_dist_m"])


class Corners(unittest.TestCase):
    def test_auto_corners_finds_the_two_dips(self):
        tr = lap()
        found = auto_corners(tr["speed"])
        self.assertEqual(len(found), 2)
        self.assertAlmostEqual(found[0].apex, 0.35, delta=0.01)
        self.assertAlmostEqual(found[1].apex, 0.65, delta=0.01)
        self.assertEqual([c.name for c in found], ["T1", "T2"])
        self.assertLess(found[0].end, found[1].start + 1e-9)

    def test_small_wobbles_are_not_corners(self):
        self.assertEqual(auto_corners([250 + 3 * math.sin(i / 7) for i in range(500)]), [])

    def test_segments_cover_the_whole_lap_without_gaps(self):
        segs = TRACK.segments()
        self.assertEqual(segs[0].start, 0.0)
        self.assertEqual(segs[-1].end, 1.0)
        for a, b in zip(segs, segs[1:]):
            self.assertAlmostEqual(a.end, b.start)

    def test_spa_table_names_the_corners_and_wraps_the_start_straight(self):
        spa = load_track("Spa-Francorchamps")
        names = [c.name for c in spa.corners]
        for n in ("La Source", "Eau Rouge / Raidillon", "Les Combes", "Pouhon", "Stavelot", "Bus Stop"):
            self.assertIn(n, names)
        self.assertEqual(spa.name_at(0.5615), "Pouhon")
        self.assertEqual(spa.name_at(0.999), "Start/finish straight")
        self.assertEqual(spa.name_at(0.01), "Start/finish straight")
        self.assertIsNotNone(load_track("spa"))
        self.assertIsNone(load_track("no such track"))


if __name__ == "__main__":
    unittest.main()
