import unittest

from stats import aggregate, crossing_events, speed_series
from tests.helpers import record, sample, settings


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()

    def test_known_speed_and_no_gap_speed(self):
        samples = [sample(i, x=i / 30) for i in range(30)]
        speeds, durations = speed_series(samples, self.cfg)
        self.assertTrue(all(abs(s - 3.6) < 1e-8 for s in speeds[1:]))
        samples[10] = None
        speeds, _ = speed_series(samples, self.cfg)
        self.assertIsNone(speeds[10])
        self.assertIsNone(speeds[11])
        records = [record(i) for i in range(30)]
        result, _, _ = aggregate(records, samples, [], 30, 640, 360, self.cfg)
        self.assertAlmostEqual(result['avg_ball_speed_kmh'], 3.6)

    def test_crossing_debounce_and_missing_evidence(self):
        samples = [sample(i, y=5 + i / 10) for i in range(40)]
        self.assertEqual(len(crossing_events(samples, self.cfg)), 1)
        for i in range(15, 23):
            samples[i] = None
        self.assertEqual(crossing_events(samples, self.cfg), [])
        samples = [sample(i, y=6.705 + (0.1 if i % 2 else -0.1)) for i in range(40)]
        self.assertEqual(crossing_events(samples, self.cfg), [])

    def test_group_exchanges_then_split_after_loss(self):
        ys = [5 + i / 10 for i in range(40)] + [9 - i / 10 for i in range(40)]
        samples = [sample(i, y=y) for i, y in enumerate(ys)]
        samples += [None] * 90
        samples += [sample(i + 170, y=5 + i / 10) for i in range(40)]
        records = [record(i) for i in range(len(samples))]
        result, rallies, _ = aggregate(records, samples, [], 30, 640, 360, self.cfg)
        self.assertEqual(result['rally_count'], 2)
        self.assertEqual(result['shots_per_rally'], [2, 1])
        self.assertEqual(result['longest_rally'], 2)

    def test_inactivity_splits_rallies(self):
        ys = [5 + i / 10 for i in range(40)] + [8.9] * 90 + [8.9 - i / 10 for i in range(40)]
        samples = [sample(i, y=y) for i, y in enumerate(ys)]
        records = [record(i) for i in range(len(samples))]
        result, _, _ = aggregate(records, samples, [], 30, 640, 360, self.cfg)
        self.assertEqual(result['shots_per_rally'], [1, 1])

    def test_no_ball_is_valid_and_explicit(self):
        result, _, _ = aggregate([record(i) for i in range(30)], [None] * 30,
                                 [], 30, 640, 360, self.cfg)
        self.assertEqual(result['rally_count'], 0)
        self.assertIsNone(result['avg_ball_speed_kmh'])
        self.assertEqual(result['in_out_calls'], [])
        self.assertEqual(result['quality']['ball_detection_coverage'], 0)
        self.assertTrue(any('Low ball' in w for w in result['quality']['warnings']))
