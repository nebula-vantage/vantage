import unittest

from vantage.rallies import play_segments, segment_rallies
from vantage.records import Rally
from vantage.stats import crossing_events, speed_series
from helpers import record, sample, settings


def flight(start, frames, y0, step):
    """Observed ball moving along the court length; 0.2 m/frame at 30 fps is 21.6 km/h."""
    return [sample(start + i, y=y0 + i * step) for i in range(frames)]


def timeline(pieces, total):
    samples = [None] * total
    for piece in pieces:
        for item in piece:
            samples[item.frame_index] = item
    return samples


class AudioRallyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()
        self.records = [record(i) for i in range(30 * 60)]  # One minute with a tracked ball.

    def rallies(self, onsets, records=None):
        records = self.records if records is None else records
        return segment_rallies(records, [None] * len(records), [None] * len(records), [], [], onsets, self.cfg)

    def test_regular_hits_form_one_rally(self):
        rally, = self.rallies([2.0, 3.1, 4.0, 5.2, 8.9, 10.0])  # Includes a 3.7 s quiet dink stretch.
        self.assertEqual((rally.start_s, rally.end_s), (2.0, 10.0))
        self.assertEqual(len(rally.hit_times_s), 6)

    def test_feeding_balls_back_is_not_a_rally(self):
        self.assertEqual(self.rallies([10.0, 11.5, 20.0, 30.0]), [])

    def test_long_quiet_gap_splits_rallies(self):
        rallies = self.rallies([1.0, 2.0, 3.0, 8.0, 9.0, 10.0])
        self.assertEqual([(r.start_s, r.end_s) for r in rallies], [(1.0, 3.0), (8.0, 10.0)])

    def test_hits_without_a_tracked_ball_are_another_court(self):
        for r in self.records[30 * 5:30 * 15]:
            r.ball = None
        self.assertEqual(self.rallies([6.0, 7.0, 8.0, 9.0]), [])

    def test_crossings_are_attached_for_shot_counts(self):
        records = [record(i) for i in range(300)]
        samples = timeline([flight(30, 40, 2, .2)], 300)
        speeds, _ = speed_series(samples, self.cfg)
        rally, = segment_rallies(records, samples, speeds, crossing_events(samples, self.cfg), [],
                                 [1.0, 2.0, 3.0], self.cfg)
        self.assertEqual(rally.shots, 1)


class FallbackRallyTests(unittest.TestCase):
    """Without audio: crossings, bounces, and court-plane ball motion."""

    def setUp(self):
        self.cfg = settings()

    def rallies(self, samples):
        speeds, _ = speed_series(samples, self.cfg)
        records = [record(i) for i in range(len(samples))]
        return segment_rallies(records, samples, speeds, crossing_events(samples, self.cfg), [], None, self.cfg)

    def test_exchange_is_one_rally_and_long_loss_splits(self):
        samples = timeline([flight(0, 30, 2, .2), flight(30, 30, 8, -.2), flight(210, 40, 2, .2)], 250)
        self.assertEqual([r.shots for r in self.rallies(samples)], [2, 1])

    def test_quick_toss_across_the_net_is_not_a_rally(self):
        samples = timeline([flight(0, 20, 5, .2)], 60)
        self.assertEqual(len(crossing_events(samples, self.cfg)), 1)
        self.assertEqual(self.rallies(samples), [])

    def test_ball_moving_on_one_side_is_not_a_rally(self):
        samples = timeline([flight(0, 30, 1, .1), flight(30, 30, 4, -.1)], 60)
        self.assertEqual(self.rallies(samples), [])


class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()

    def test_padding_clamps_to_video(self):
        segments = play_segments([Rally(1, .5, 5, [2]), Rally(2, 20, 29.5, [21])], 30, self.cfg)
        self.assertEqual(segments, [{"start_s": 0.0, "end_s": 6, "rally_ids": [1]},
                                    {"start_s": 19, "end_s": 30, "rally_ids": [2]}])

    def test_padding_merges_close_rallies(self):
        segments = play_segments([Rally(1, 2, 5, [3]), Rally(2, 6.5, 9, [7])], 30, self.cfg)
        self.assertEqual(segments, [{"start_s": 1, "end_s": 10, "rally_ids": [1, 2]}])

    def test_no_rallies_keeps_nothing(self):
        self.assertEqual(play_segments([], 30, self.cfg), [])


if __name__ == "__main__":
    unittest.main()
