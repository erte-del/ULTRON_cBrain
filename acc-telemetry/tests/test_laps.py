import unittest

from acc_telemetry.acc_shm import STATUS_LIVE
from acc_telemetry.sampler import LapBuilder, normalize_sectors

from .helpers import drive, frame, lap_time


def run(frames):
    b, laps = LapBuilder(), []
    for f in frames:
        laps.extend(b.feed(f))
    return laps


class LapDetection(unittest.TestCase):
    def check(self, laps, n=3):
        self.assertEqual([l.lap_number for l in laps], list(range(1, n + 1)))
        self.assertEqual([l.lap_time_ms for l in laps], [lap_time(i) for i in range(n)])
        self.assertTrue(all(l.clean for l in laps))

    def test_counter_and_position_move_together(self):
        self.check(run(drive(3)))

    def test_position_wraps_before_the_counter(self):
        self.check(run(drive(3, lag=3)))

    def test_counter_moves_before_the_position_wraps(self):
        self.check(run(drive(3, lead=3)))

    def test_lap_time_published_late_is_waited_for(self):
        self.check(run(drive(3, lag=10)))

    def test_a_late_counter_does_not_count_the_lap_twice(self):
        self.check(run(drive(4, lag=14)), n=4)

    def test_joining_mid_lap_does_not_make_a_clean_lap(self):
        laps = run(drive(2, start_pos=0.6))
        self.assertFalse(laps[0].clean)             # the partial first lap
        self.assertTrue(laps[1].clean)

    def test_a_lap_with_a_pit_stop_is_not_clean(self):
        laps = run(drive(3, in_pit_lap=1))
        self.assertEqual([l.clean for l in laps], [True, False, True])

    def test_paused_and_replay_frames_are_ignored(self):
        frames = drive(2)
        mid = len(frames) // 4
        noise = [frame(status=s, pos=0.2, t=frames[mid].t) for s in (0, 1, 3) for _ in range(5)]
        laps = run(frames[:mid] + noise + frames[mid:])
        self.assertEqual(len(laps), 2)
        self.assertTrue(all(l.clean for l in laps))

    def test_restarting_the_session_starts_over(self):
        first = drive(2)
        restart = drive(2, first_lap=0, t0=first[-1].t + 5)
        laps = run(first + restart)
        self.assertEqual([l.lap_number for l in laps], [1, 2, 1, 2])

    def test_lap_number_follows_the_game_counter(self):
        laps = run(drive(2, first_lap=7, last_ms0=99_000))
        self.assertEqual([l.lap_number for l in laps], [8, 9])
        self.assertEqual([l.lap_time_ms for l in laps], [lap_time(7), lap_time(8)])


class Sectors(unittest.TestCase):
    def test_durations_become_three_sectors(self):
        self.assertEqual(normalize_sectors([42_000, 56_000], 135_000), [42_000, 56_000, 37_000])

    def test_marks_that_dont_add_up_are_rejected(self):
        self.assertEqual(normalize_sectors([90_000, 80_000], 135_000), [])   # would leave a negative last sector
        self.assertEqual(normalize_sectors([42_000], 135_000), [])           # a mark is missing
        self.assertEqual(normalize_sectors([0, 56_000], 135_000), [])


if __name__ == "__main__":
    unittest.main()
