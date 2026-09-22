import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from court import compute_homography, save_calibration
from main import main, run_pipeline
from records import Detection, FrameRecord
from tests.helpers import settings
from visualize import encoded_size, render_video, verify_video


class FakeDetector:
    def __init__(self, config, width, height, fps, work_dir):
        self.fps = fps

    def process(self, frame, index, time_s):
        y = 170 - abs(index - 30) * 2
        return FrameRecord(index, time_s,
                           players=[Detection((20, 80, 60, 180), 0.9, 7, 0)],
                           ball=Detection((158, y-2, 162, y+2), 0.9, 1, 32))


class EmptyDetector(FakeDetector):
    def process(self, frame, index, time_s):
        return FrameRecord(index, time_s)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'sample.mp4'
        self.output = self.root / 'output'
        self.cfg = settings()
        self.cfg['runtime']['progress_every_s'] = float('inf')
        writer = cv2.VideoWriter(str(self.input), cv2.VideoWriter_fourcc(*'mp4v'), 30, (320, 240))
        self.assertTrue(writer.isOpened())
        for _ in range(60):
            writer.write(np.full((240, 320, 3), 40, dtype=np.uint8))
        writer.release()
        corners = [[20, 220], [300, 220], [280, 20], [40, 20]]
        h = compute_homography(corners, 320, 240, self.cfg)
        save_calibration(self.output, h, corners, 320, 240)

    def test_synthetic_end_to_end(self):
        result = run_pipeline(self.input, self.output, config=self.cfg, detector_factory=FakeDetector)
        self.assertEqual(len(result['in_out_calls']), 1)
        self.assertIsNotNone(result['avg_ball_speed_kmh'])
        self.assertEqual(json.loads((self.output/'stats.json').read_text()), json.loads(json.dumps(result)))
        self.assertEqual(len((self.output/'tracks.jsonl').read_text().splitlines()), 60)
        verify_video(self.output/'annotated.mp4', 60, (320, 240), 30)
        cap = cv2.VideoCapture(str(self.output/'annotated.mp4'))
        ok, frame = cap.read()
        cap.release()
        self.assertTrue(ok)
        self.assertGreater(np.std(frame), 1)

    def test_no_ball_end_to_end(self):
        result = run_pipeline(self.input, self.output, config=self.cfg, detector_factory=EmptyDetector)
        self.assertIsNone(result['avg_ball_speed_kmh'])
        verify_video(self.output/'annotated.mp4', 60, (320, 240), 30)

    def test_failed_run_keeps_previous_outputs(self):
        (self.output/'stats.json').write_text('previous')
        with patch('visualize.render_video', side_effect=RuntimeError('encoder failure')):
            with self.assertRaisesRegex(RuntimeError, 'encoder failure'):
                run_pipeline(self.input, self.output, config=self.cfg, detector_factory=EmptyDetector)
        self.assertEqual((self.output/'stats.json').read_text(), 'previous')
        self.assertFalse(list(self.output.glob('.processing-*')))

    def test_missing_input_error_and_stdout_is_empty(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--input', str(self.root/'missing.mp4')])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), '')
        self.assertIn('Place your video there or pass --input', err.getvalue())

    def test_cli_stdout_is_only_matching_json(self):
        out = io.StringIO()
        with patch('detector.Detector', EmptyDetector), contextlib.redirect_stdout(out):
            code = main(['--input', str(self.input), '--output-dir', str(self.output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), json.loads((self.output/'stats.json').read_text()))

    def test_cannot_overwrite_input(self):
        with self.assertRaisesRegex(ValueError, 'Input cannot'):
            self._overwrite()

    def _overwrite(self):
        path = self.root / 'annotated.mp4'
        path.write_bytes(self.input.read_bytes())
        run_pipeline(path, self.root, config=self.cfg, detector_factory=EmptyDetector)

    def test_odd_dimensions_have_explicit_even_encoding(self):
        self.assertEqual(encoded_size(321, 241), (322, 242))
