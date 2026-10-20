import unittest

from stats import aggregate, crossing_events, event_records, speed_series, tracking_summary
from records import BounceEvent, Detection, FrameRecord
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
        self.assertEqual(result['quality']['status'], 'insufficient_evidence')

    def test_event_counts_rally_evidence_and_chronological_ledger(self):
        samples = [sample(i, y=5+i/10) for i in range(40)]
        records = [record(i) for i in range(40)]
        bounce = BounceEvent(5, 5/30, (100, 100), (2, 3), 'IN', .8, ['heuristic_bounce'])
        result, _, _ = aggregate(records, samples, [bounce], 30, 640, 360, self.cfg)
        self.assertEqual(result['shot_count'], sum(result['shots_per_rally']))
        self.assertEqual(result['rallies'][0]['ball_observation_coverage'], 1)
        self.assertAlmostEqual(result['rallies'][0]['duration_s'], 39/30)
        events = event_records(result)
        self.assertEqual([e['type'] for e in events], ['bounce_candidate', 'net_crossing'])
        self.assertEqual(events[1]['rally_id'], 1)
        self.assertEqual([e['event_id'] for e in events], [1, 2])

    def test_player_track_visibility_and_ball_contiguity(self):
        records = [record(i, track_id=1 if i < 3 else 2) for i in range(5)]
        player = Detection((20, 20, 40, 80), .9, 7, 0)
        for i in (0, 1, 4):
            records[i].players = [player]
        records[2].ball = None
        result = tracking_summary(records, 30)
        self.assertEqual(result['player_detection_coverage'], 3/5)
        self.assertEqual(result['player_track_count'], 1)
        self.assertAlmostEqual(result['player_tracks'][0]['observed_duration_s'], 3/30)
        self.assertEqual(result['ball_track_count'], 2)
        self.assertAlmostEqual(result['longest_contiguous_ball_observation_s'], 2/30)
