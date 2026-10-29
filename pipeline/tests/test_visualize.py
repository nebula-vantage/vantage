import unittest

import numpy as np

from vantage.records import FrameRecord, Rally
from helpers import settings
from vantage.visualize import Overlay


class OverlayTests(unittest.TestCase):
    def test_total_shots_persist_but_current_rally_ends(self):
        rallies = [Rally(1, 0, 2, [.5, 1.5]), Rally(2, 4, 6, [4.5])]
        overlay = Overlay(640, 360, [], rallies, settings(), .21)
        for time_s, expected_total, expected_current in (
                (0, 0, '1 | Shots: 0'), (1, 1, '1 | Shots: 1'),
                (3, 2, 'no supported rally'), (5, 3, '2 | Shots: 1'),
                (7, 3, 'no supported rally')):
            frame = FrameRecord(round(time_s*30), time_s)
            overlay.draw(np.zeros((360, 640, 3), dtype=np.uint8), frame, None, None)
            lines = overlay.stats_lines(frame, None, None)
            self.assertIn(f'Shots (est.): {expected_total}', lines[0])
            self.assertIn(expected_current, lines[1])
            self.assertIn('21%', lines[-1])
            self.assertIn('limited evidence', lines[-1])

    def test_play_line_follows_segments(self):
        overlay = Overlay(640, 360, [], [], settings(), segments=[{'start_s': 1, 'end_s': 3, 'rally_ids': [1]}])
        for time_s, expected in ((0, 'dead ball'), (2, 'RALLY'), (4, 'dead ball')):
            lines = overlay.stats_lines(FrameRecord(round(time_s*30), time_s), None, None)
            self.assertIn(expected, lines[2])
