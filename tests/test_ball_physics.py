import unittest

import numpy as np

from ball_physics import build_trajectory, detect_bounces, in_out
from detector import BallSelector
from records import Detection, FrameRecord
from tests.helpers import record, settings


class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()
        self.h = np.array([[0.01, 0, 0], [0, 0.02, 0], [0, 0, 1]])

    def test_short_gap_interpolates_long_gap_does_not(self):
        records = [FrameRecord(i, i / 30) for i in range(30)]
        for i in (0, 1, 4, 25):
            records[i] = record(i, x=100 + i)
        samples = build_trajectory(records, self.h, 640, 360, self.cfg)
        self.assertEqual(samples[2].source, 'interpolated')
        self.assertAlmostEqual(samples[2].pixel[0], 102)
        self.assertEqual(samples[5].source, 'coasted')
        self.assertIsNone(samples[15])
        self.assertNotEqual(samples[4].segment_id, samples[25].segment_id)

    def test_track_switch_and_jump_split(self):
        records = [record(0), record(1, track_id=2), record(2, x=600, track_id=2)]
        samples = build_trajectory(records, self.h, 640, 360, self.cfg)
        self.assertEqual(len({s.segment_id for s in samples}), 3)

    def test_ball_choice_confidence_motion_gate_and_reacquire(self):
        selector = BallSelector(self.cfg, 640, 360)
        a = Detection((98, 98, 102, 102), 0.7, 1, 32)
        b = Detection((500, 300, 510, 310), 0.9, 2, 32)
        self.assertIs(selector.select([a, b], 0), b)
        self.assertIsNone(selector.select([a], 1/30))
        self.assertIs(selector.select([a], 1), a)

    def test_boundary_calls(self):
        for p in ((0, 0), (6.1, 13.41), (3, 4)):
            self.assertEqual(in_out(p, self.cfg)[0], 'IN')
        self.assertEqual(in_out((-0.01, 4), self.cfg), ('OUT', ['near_boundary']))
        self.assertEqual(in_out((-1, 4), self.cfg), ('OUT', []))

    def test_single_supported_kink_and_paddle_suppression(self):
        records = [record(i, y=200 - abs(i - 15) * 3) for i in range(31)]
        samples = build_trajectory(records, self.h, 640, 360, self.cfg)
        events = detect_bounces(records, samples, self.h, 640, 360, self.cfg)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].frame_index, 15)
        self.assertEqual(events[0].call, 'IN')
        for r in records:
            r.paddles = [Detection((90, 140, 110, 220), 0.8, 3, 38)]
        self.assertEqual(detect_bounces(records, samples, self.h, 640, 360, self.cfg), [])

    def test_straight_line_is_not_bounce_and_gap_cannot_create_one(self):
        records = [record(i, y=100 + i) for i in range(31)]
        samples = build_trajectory(records, self.h, 640, 360, self.cfg)
        self.assertEqual(detect_bounces(records, samples, self.h, 640, 360, self.cfg), [])
        records = [record(i, y=200 - abs(i - 15) * 3) for i in range(31)]
        for i in range(10, 21):
            records[i].ball = None
        samples = build_trajectory(records, self.h, 640, 360, self.cfg)
        self.assertEqual(detect_bounces(records, samples, self.h, 640, 360, self.cfg), [])
