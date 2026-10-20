from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from ultralytics.engine.results import Results

from detector import Detector
from tests.helpers import settings


class DetectorTests(unittest.TestCase):
    def test_one_inference_routes_raw_balls_and_paddles_around_player_tracker(self):
        cfg = settings()
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        names = {0: 'person', 32: 'sports ball', 38: 'tennis racket'}
        def result(x):
            boxes = np.array([[20, 40, 80, 200, .9, 0],
                              [x-2, 98, x+2, 102, .11, 32],
                              [90, 95, 95, 105, .8, 38]], dtype=np.float32)
            return Results(frame, path='test', names=names, boxes=boxes)
        empty = Results(frame, path='test', names=names, boxes=np.empty((0, 6), dtype=np.float32))
        with tempfile.TemporaryDirectory() as tmp, patch('ultralytics.YOLO') as factory:
            model = factory.return_value
            model.names = names
            model.predict.side_effect = [[result(100)], [result(125)], [empty], [result(175)]]
            detector = Detector(cfg, 640, 360, 30, Path(tmp))
            with patch.object(detector.player_tracker, 'update', wraps=detector.player_tracker.update) as update:
                records = [detector.process(frame, i, i/30) for i in range(4)]
                self.assertEqual(update.call_count, 4)
                for call in update.call_args_list:
                    self.assertTrue(all(c == 0 for c in call.args[0].cls))
            self.assertEqual(model.predict.call_count, 4)
            model.track.assert_not_called()
            self.assertIsNone(records[0].ball)  # Two observations confirm acquisition.
            self.assertIsNotNone(records[1].ball)  # A weak, non-overlapping ball is retained.
            self.assertIsNone(records[2].ball)  # No fabricated measurement over a gap.
            self.assertEqual(records[1].ball.track_id, records[3].ball.track_id)
            self.assertEqual(records[0].players[0].track_id, records[1].players[0].track_id)
            self.assertEqual(len(records[1].paddles), 1)
            self.assertIsNone(records[1].paddles[0].track_id)
            self.assertEqual(detector.player_tracker.frame_id, 4)


if __name__ == '__main__':
    unittest.main()
