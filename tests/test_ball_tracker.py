import unittest

import numpy as np

from ball_physics import build_trajectory
from ball_tracker import BallTracker
from records import Detection, FrameRecord
from tests.helpers import settings


def ball(x, y=100, confidence=0.2):
    return Detection((x-2, y-2, x+2, y+2), confidence, None, 32)


class BallTrackerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()
        self.tracker = BallTracker(self.cfg, 640, 360)

    def test_low_confidence_fast_ball_needs_no_box_overlap(self):
        self.assertIsNone(self.tracker.select([ball(100, confidence=.11)], 0))
        observed = [self.tracker.select([ball(100+i*25, confidence=.11)], i/30) for i in range(1, 6)]
        self.assertTrue(all(b is not None for b in observed))
        self.assertEqual(len({b.track_id for b in observed}), 1)
        self.assertEqual(observed[-1].center, (225, 100))
        self.assertEqual(observed[-1].confidence, .11)

    def test_short_loss_returns_no_fabricated_detection_and_rejoins(self):
        self.tracker.select([ball(100)], 0)
        first = self.tracker.select([ball(110)], 1/30)
        self.assertIsNone(self.tracker.select([], 2/30))
        self.assertIsNone(self.tracker.select([], 3/30))
        last = self.tracker.select([ball(140)], 4/30)
        self.assertEqual(first.track_id, last.track_id)
        self.assertEqual(last.center, (140, 100))

    def test_long_loss_requires_confirmation_and_new_identity(self):
        self.tracker.select([ball(100)], 0)
        first = self.tracker.select([ball(110)], 1/30)
        self.assertIsNone(self.tracker.select([], .5))
        self.assertIsNone(self.tracker.select([ball(400)], .6))
        last = self.tracker.select([ball(410)], .6+1/30)
        self.assertNotEqual(first.track_id, last.track_id)

    def test_stationary_high_confidence_sign_cannot_block_acquisition(self):
        sign = ball(500, confidence=.99)
        for i in range(10):
            self.assertIsNone(self.tracker.select([sign], i/30))
        self.assertIsNone(self.tracker.select([sign, ball(100)], 10/30))
        selected = self.tracker.select([sign, ball(110)], 11/30)
        self.assertEqual(selected.center, (110, 100))

    def test_motion_wins_over_higher_confidence_distractor(self):
        self.tracker.select([ball(100)], 0)
        self.tracker.select([ball(120)], 1/30)
        selected = self.tracker.select([ball(140), ball(110, confidence=.99)], 2/30)
        self.assertEqual(selected.center, (140, 100))

    def test_abrupt_reversal_keeps_identity(self):
        self.tracker.select([ball(100)], 0)
        before = self.tracker.select([ball(130)], 1/30)
        after = self.tracker.select([ball(100)], 2/30)
        self.assertEqual(before.track_id, after.track_id)
        self.assertEqual(self.tracker.select([ball(70)], 3/30).track_id, before.track_id)

    def test_impossible_jump_and_invalid_boxes_rejected(self):
        self.tracker.select([ball(100)], 0)
        self.tracker.select([ball(110)], 1/30)
        self.assertIsNone(self.tracker.select([ball(600)], 2/30))
        self.assertIsNone(self.tracker.select([ball(float('nan')), ball(-20),
                                              ball(120, confidence=.09),
                                              Detection((120, 100, 119, 102), .9, None, 32)], 3/30))

    def test_stationary_track_is_released(self):
        self.tracker.select([ball(100)], 0)
        self.tracker.select([ball(110)], 1/30)
        observed = [self.tracker.select([ball(110)], i/30) for i in range(2, 25)]
        self.assertTrue(all(b is None for b in observed[-5:]))

    def test_acquisition_requires_distinct_increasing_times(self):
        self.assertIsNone(self.tracker.select([ball(100), ball(110)], 0))
        for time_s in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                self.tracker.select([ball(120)], time_s)

    def test_capture_fps_does_not_change_speed_or_gap_lifetime(self):
        for fps in (30, 120):
            tracker = BallTracker(self.cfg, 640, 360)
            records = []
            for i in range(fps):
                time_s = i/fps
                selected = tracker.select([ball(100+120*time_s)], time_s)
                records.append(FrameRecord(i, time_s, ball=selected))
            self.assertAlmostEqual(tracker.velocity[0], 120)
            first = next(r.ball for r in records if r.ball)
            self.assertTrue(all(r.ball.track_id == first.track_id for r in records if r.ball))
            samples = build_trajectory(records, np.eye(3), 640, 360, self.cfg)
            self.assertTrue(all(s.source == 'observed' for s in samples if s))
            self.assertIsNone(tracker.select([], 1.3))
            self.assertIsNone(tracker.select([ball(300)], 1.4))


if __name__ == '__main__':
    unittest.main()
