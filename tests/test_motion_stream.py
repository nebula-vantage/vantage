import unittest

import numpy as np

from motion_stream import MotionStream
from records import Detection, FrameRecord
from tests.helpers import settings


def player(x, y=200, identity=7):
    return Detection((x-10, y-40, x+10, y), .9, identity, 0)


def ball(x, y=100, identity=1):
    return Detection((x-2, y-2, x+2, y+2), .7, identity, 32)


class MotionStreamTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()
        self.h = np.diag([.01, .01, 1])
        self.motion = MotionStream(self.h, 640, 360, 30, self.cfg)

    def test_player_uses_feet_not_box_center(self):
        row = self.motion.update(FrameRecord(0, 0, players=[player(100)]))
        self.assertEqual(row['players'][0]['footpoint_px'], (100, 200))
        self.assertEqual(row['players'][0]['court_m'], (1, 2))
        self.assertIsNone(row['players'][0]['projected_speed_m_s'])
        self.assertIsNone(row['ball'])

    def test_distance_has_known_units_at_30_and_120_fps(self):
        self.cfg['motion']['player_smoothing_s'] = 1e-6
        self.cfg['motion']['player_min_step_m'] = 0
        for fps in (30, 120):
            motion = MotionStream(self.h, 640, 360, fps, self.cfg)
            for i in range(fps+1):
                row = motion.update(FrameRecord(i, i/fps, players=[player(100+200*i/fps)]))
            self.assertAlmostEqual(row['players'][0]['observed_distance_m'], 2, places=5)
            self.assertAlmostEqual(row['players'][0]['projected_speed_m_s'], 2, places=5)
            self.assertAlmostEqual(motion.summary()['player_tracks'][0]['valid_movement_duration_s'], 1)

    def test_gaps_identity_changes_and_jumps_do_not_add_distance(self):
        self.cfg['motion']['player_smoothing_s'] = 1e-6
        self.cfg['motion']['player_min_step_m'] = 0
        motion = MotionStream(self.h, 640, 360, 30, self.cfg)
        motion.update(FrameRecord(0, 0, players=[player(100)]))
        row = motion.update(FrameRecord(1, 1/30, players=[player(110)]))
        self.assertAlmostEqual(row['players'][0]['observed_distance_m'], .1)
        row = motion.update(FrameRecord(2, 2/30, players=[player(600)]))
        self.assertEqual(row['players'][0]['motion_status'], 'rejected_jump')
        self.assertAlmostEqual(row['players'][0]['observed_distance_m'], .1)
        row = motion.update(FrameRecord(10, 10/30, players=[player(300)]))
        self.assertAlmostEqual(row['players'][0]['observed_distance_m'], .1)
        self.assertIsNone(row['players'][0]['projected_speed_m_s'])
        row = motion.update(FrameRecord(11, 11/30, players=[player(310, identity=8)]))
        self.assertEqual(row['players'][0]['observed_distance_m'], 0)

    def test_stationary_jitter_does_not_accumulate_metres(self):
        for i in range(100):
            row = self.motion.update(FrameRecord(i, i/30, players=[player(100+i%2)]))
        self.assertEqual(row['players'][0]['observed_distance_m'], 0)

    def test_clipped_footpoint_and_unstable_projection_are_unavailable(self):
        row = self.motion.update(FrameRecord(0, 0, players=[player(100, y=360)]))
        self.assertIsNone(row['players'][0]['court_m'])
        motion = MotionStream(np.zeros((3, 3)), 640, 360, 30, self.cfg)
        row = motion.update(FrameRecord(0, 0, players=[player(100)], ball=ball(100)))
        self.assertIsNone(row['ball']['court_projection_m'])
        self.assertEqual(row['ball']['center_px'], (100, 100))

    def test_ball_speed_needs_adjacent_observed_identity(self):
        self.motion.update(FrameRecord(0, 0, ball=ball(100)))
        row = self.motion.update(FrameRecord(1, 1/30, ball=ball(110)))
        self.assertAlmostEqual(row['ball']['image_speed_px_s'], 300)
        self.assertAlmostEqual(row['ball']['instant_projected_speed_kmh'], 10.8)
        self.motion.update(FrameRecord(2, 2/30))
        row = self.motion.update(FrameRecord(3, 3/30, ball=ball(120)))
        self.assertIsNone(row['ball']['instant_projected_speed_kmh'])
        row = self.motion.update(FrameRecord(4, 4/30, ball=ball(130, identity=2)))
        self.assertIsNone(row['ball']['image_speed_px_s'])

    def test_hit_requires_observed_turn_near_paddle_and_is_not_confirmed(self):
        paddle = Detection((116, 96, 124, 104), .8, None, 38)
        for i, x in enumerate((100, 120, 100)):
            row = self.motion.update(FrameRecord(i, i/30, ball=ball(x), paddles=[paddle] if i == 1 else []))
        self.assertEqual(row['hit_candidate_count'], 1)
        event = row['hit_candidates'][0]
        self.assertEqual(event['frame_index'], 1)
        self.assertEqual(event['emitted_at_s'], 2/30)
        self.assertIn('unverified_hit', event['quality_flags'])
        self.assertIsNone(self.motion.summary()['confirmed_hit_count'])
        for i, x in enumerate((120, 100), 3):
            row = self.motion.update(FrameRecord(i, i/30, ball=ball(x), paddles=[paddle]))
        self.assertEqual(row['hit_candidate_count'], 1)  # Debounced.

    def test_turn_without_paddle_and_straight_pass_are_not_hits(self):
        for positions, paddles in (((100, 120, 100), []),
                                    ((100, 120, 140), [Detection((115, 90, 125, 110), .8, None, 38)])):
            motion = MotionStream(self.h, 640, 360, 30, self.cfg)
            for i, x in enumerate(positions):
                row = motion.update(FrameRecord(i, i/30, ball=ball(x), paddles=paddles))
            self.assertEqual(row['hit_candidate_count'], 0)
