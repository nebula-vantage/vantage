import unittest

import numpy as np

from records import FrameRecord, Rally
from tests.helpers import settings
from visualize import Overlay


class OverlayTests(unittest.TestCase):
    def test_total_shots_persist_but_current_rally_ends(self):
        rallies = [Rally(1, 0, 2, [.5, 1.5]), Rally(2, 4, 6, [4.5])]
        overlay = Overlay(640, 360, [], rallies, settings(), .21)
        for time_s, expected_total, expected_current in (
                (0, 0, 'no supported rally'), (1, 1, '1 | Shots: 1'),
                (3, 2, 'no supported rally'), (5, 3, '2 | Shots: 1'),
                (7, 3, 'no supported rally')):
            frame = FrameRecord(round(time_s*30), time_s)
            overlay.draw(np.zeros((360, 640, 3), dtype=np.uint8), frame, None, None)
            lines = overlay.stats_lines(frame, None, None)
            self.assertIn(f'Shots (est.): {expected_total}', lines[0])
            self.assertIn(expected_current, lines[1])
            self.assertIn('21%', lines[-1])
            self.assertIn('limited evidence', lines[-1])
