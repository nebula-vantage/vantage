import unittest

from vantage.rallies import play_segments, segment_rallies
from vantage.records import BounceEvent, Rally
from vantage.stats import crossing_events, speed_series
from helpers import sample, settings


def flight(start, frames, y0, step):
    """Observed ball moving along the court length; 0.2 m/frame at 30 fps is 21.6 km/h."""
    return [sample(start + i, y=y0 + i * step) for i in range(frames)]


def timeline(pieces, total):
    samples = [None] * total
    for piece in pieces:
        for item in piece:
            samples[item.frame_index] = item
    return samples


class RallyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()

    def rallies(self, samples, bounces=()):
        speeds, _ = speed_series(samples, self.cfg)
        return segment_rallies(samples, speeds, crossing_events(samples, self.cfg), list(bounces), self.cfg)

    def test_exchange_with_short_ball_loss_is_one_rally(self):
        # Three shots, with a 1.5 s gap between the second and third.
        samples = timeline([flight(0, 30, 2, .2), flight(30, 30, 8, -.2), flight(105, 30, 2, .2)], 150)
        rallies = self.rallies(samples)
        self.assertEqual(len(rallies), 1)
        self.assertEqual(rallies[0].shots, 3)

    def test_long_downtime_splits_rallies(self):
        samples = timeline([flight(0, 40, 2, .2), flight(160, 40, 8, -.2)], 200)
        self.assertEqual([r.shots for r in self.rallies(samples)], [1, 1])

    def test_quick_toss_across_the_net_is_not_a_rally(self):
        samples = timeline([flight(0, 20, 5, .2)], 60)
        self.assertEqual(len(crossing_events(samples, self.cfg)), 1)
        self.assertEqual(self.rallies(samples), [])

    def test_ball_moving_on_one_side_is_not_a_rally(self):
        # Bouncing the ball before a serve: plenty of motion, never crosses.
        samples = timeline([flight(0, 30, 1, .1), flight(30, 30, 4, -.1)], 60)
        bounce = BounceEvent(30, 1.0, (0, 0), (3, 4), "IN", .8)
        self.assertEqual(self.rallies(samples, [bounce]), [])

    def test_carried_ball_is_not_evidence(self):
        # 0.03 m/frame is 3.2 km/h, below min_ball_speed_kmh: walking with the ball on the far side.
        samples = timeline([flight(0, 40, 2, .2), flight(40, 120, 11, -.03), flight(160, 40, 2, .2)], 200)
        self.assertEqual(len(self.rallies(samples)), 2)

    def test_bounce_extends_rally(self):
        samples = timeline([flight(0, 40, 2, .2)], 200)
        bounce = BounceEvent(110, 110 / 30, (0, 0), (3, 10), "IN", .8)
        rally, = self.rallies(samples, [bounce])
        self.assertAlmostEqual(rally.end_s, 110 / 30)


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
