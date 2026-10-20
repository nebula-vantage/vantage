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
        events = [json.loads(line) for line in (self.output/'events.jsonl').read_text().splitlines()]
        self.assertEqual(len(events), result['shot_count'] + result['bounce_candidate_count'])
        self.assertTrue(any(event['type'] == 'bounce_candidate' for event in events))
        self.assertIsNotNone(cv2.imread(str(self.output/'landing_heatmap.png')))
        self.assertEqual(result['landing_heatmap']['included_candidates'], 1)

    def test_reanalyze_reuses_tracks_but_recomputes_stats(self):
        before = run_pipeline(self.input, self.output, config=self.cfg, detector_factory=FakeDetector)
        original_tracks = (self.output/'tracks.jsonl').read_bytes()
        self.cfg['bounce']['min_side_observations'] = 100
        with patch('detector.Detector', side_effect=AssertionError('Inference must be skipped')) as factory:
            after = run_pipeline(self.input, self.output, config=self.cfg, reanalyze=True)
        factory.assert_not_called()
        self.assertEqual(before['bounce_candidate_count'], 1)
        self.assertEqual(after['bounce_candidate_count'], 0)
        self.assertEqual(after['landing_heatmap']['included_candidates'], 0)
        self.assertEqual(original_tracks, (self.output/'tracks.jsonl').read_bytes())
        self.assertEqual(before['tracks_sha256'], after['tracks_sha256'])
        verify_video(self.output/'annotated.mp4', 60, (320, 240), 30)

    def test_reanalyze_rejects_changed_tracking_settings(self):
        run_pipeline(self.input, self.output, config=self.cfg, detector_factory=FakeDetector)
        previous = (self.output/'stats.json').read_bytes()
        self.cfg['detection']['ball_confidence'] = .5
        with self.assertRaisesRegex(ValueError, 'without --reanalyze'):
            run_pipeline(self.input, self.output, config=self.cfg, reanalyze=True)
        self.assertEqual(previous, (self.output/'stats.json').read_bytes())

    def test_reanalyze_rejects_modified_video_and_tracks(self):
        run_pipeline(self.input, self.output, config=self.cfg, detector_factory=FakeDetector)
        tracks = self.output/'tracks.jsonl'
        original = tracks.read_bytes()
        tracks.write_bytes(original[:-20])
        with self.assertRaisesRegex(ValueError, 'cached observations have changed'):
            run_pipeline(self.input, self.output, config=self.cfg, reanalyze=True)
        tracks.write_bytes(original)
        with self.input.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'Video, tracking settings'):
            run_pipeline(self.input, self.output, config=self.cfg, reanalyze=True)

    def test_reanalyze_failure_preserves_completed_artifacts(self):
        run_pipeline(self.input, self.output, config=self.cfg, detector_factory=FakeDetector)
        previous = {name: (self.output/name).read_bytes() for name in
                    ('stats.json', 'tracks.jsonl', 'annotated.mp4', 'events.jsonl', 'landing_heatmap.png')}
        with patch('visualize.render_video', side_effect=RuntimeError('encoder failure')):
            with self.assertRaisesRegex(RuntimeError, 'encoder failure'):
                run_pipeline(self.input, self.output, config=self.cfg, reanalyze=True)
        self.assertEqual(previous, {name: (self.output/name).read_bytes() for name in previous})

    def test_heatmap_failure_preserves_completed_outputs(self):
        run_pipeline(self.input, self.output, config=self.cfg, detector_factory=FakeDetector)
        previous = {name: (self.output/name).read_bytes() for name in
                    ('stats.json', 'tracks.jsonl', 'annotated.mp4', 'events.jsonl', 'landing_heatmap.png')}
        with patch('heatmap.render_landing_heatmap', side_effect=RuntimeError('PNG failure')):
            with self.assertRaisesRegex(RuntimeError, 'PNG failure'):
                run_pipeline(self.input, self.output, config=self.cfg, reanalyze=True)
        self.assertEqual(previous, {name: (self.output/name).read_bytes() for name in previous})

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

    def test_coordinates_are_emitted_before_the_next_frame_is_processed(self):
        out = io.StringIO()

        class CheckingDetector(FakeDetector):
            def process(detector, frame, index, time_s):
                messages = [json.loads(line) for line in out.getvalue().splitlines()]
                if index:
                    self.assertEqual(messages[-1]['frame_index'], index-1)
                else:
                    self.assertEqual(messages[-1]['type'], 'stream_start')
                return super().process(frame, index, time_s)

        result = run_pipeline(self.input, self.output, config=self.cfg,
                              detector_factory=CheckingDetector, stream_output=out)
        messages = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(messages), 61)
        self.assertEqual(messages[-1]['players'][0]['track_id'], 7)
        self.assertIn('motion', result)

    def test_cli_stream_replays_validated_cache_as_json_lines(self):
        run_pipeline(self.input, self.output, config=self.cfg, detector_factory=FakeDetector)
        out, err = io.StringIO(), io.StringIO()
        with patch('detector.Detector', side_effect=AssertionError('No inference')), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--input', str(self.input), '--output-dir', str(self.output), '--reanalyze', '--stream'])
        self.assertEqual(code, 0)
        messages = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([m['type'] for m in messages], ['stream_start'] + ['frame']*60 + ['summary'])
        self.assertEqual(messages[-1]['stats'], json.loads((self.output/'stats.json').read_text()))
        self.assertIn('Reusing 60 validated', err.getvalue())

    def test_cannot_overwrite_input(self):
        with self.assertRaisesRegex(ValueError, 'Input cannot'):
            self._overwrite()

    def _overwrite(self):
        path = self.root / 'annotated.mp4'
        path.write_bytes(self.input.read_bytes())
        run_pipeline(path, self.root, config=self.cfg, detector_factory=EmptyDetector)

    def test_odd_dimensions_have_explicit_even_encoding(self):
        self.assertEqual(encoded_size(321, 241), (322, 242))
