from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from vantage.coaching_video import PlaybackCache


class PlaybackCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "annotated.mp4"
        self.cache = PlaybackCache(self.root / "cache")
        self.make_video()

    def make_video(self, frames=18, fps=30):
        writer = cv2.VideoWriter(str(self.source), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
        self.assertTrue(writer.isOpened())
        try:
            for i in range(frames):
                image = np.full((120, 160, 3), 40, dtype=np.uint8)
                cv2.rectangle(image, (i, 20), (i + 30, 60), (0, 150, 255), -1)
                writer.write(image)
        finally:
            writer.release()

    def fingerprint(self):
        return hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source.stat().st_mtime_ns

    def assert_h264_video(self, path, frames=18, fps=30):
        capture = cv2.VideoCapture(str(path))
        try:
            self.assertTrue(capture.isOpened())
            codec = int(capture.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode()
            self.assertIn(codec, ("avc1", "h264"))
            self.assertAlmostEqual(capture.get(cv2.CAP_PROP_FPS), fps, places=3)
            self.assertEqual(capture.get(cv2.CAP_PROP_FRAME_WIDTH), 160)
            self.assertEqual(capture.get(cv2.CAP_PROP_FRAME_HEIGHT), 120)
            count = 0
            while capture.read()[0]:
                count += 1
            self.assertEqual(count, frames)
        finally:
            capture.release()
        raw = path.read_bytes()
        # A fast-start MP4 publishes its seek/index atom before video payload.
        self.assertLess(raw.index(b"moov"), raw.index(b"mdat"))

    def test_converts_mp4v_to_h264_preserving_timing_and_source(self):
        before = self.fingerprint()
        output = self.cache.get(self.source)
        self.assertNotEqual(output, self.source)
        self.assert_h264_video(output)
        self.assertEqual(before, self.fingerprint())
        self.assertEqual(list(self.cache.cache_dir.iterdir()), [output])

    def test_reuses_cached_revision_and_converts_when_source_changes(self):
        old_output = self.cache.get(self.source)
        with patch("vantage.coaching_video.subprocess.run", side_effect=AssertionError("Unexpected re-encode")):
            self.assertEqual(self.cache.get(self.source), old_output)
        self.make_video(frames=24, fps=24)
        new_output = self.cache.get(self.source)
        self.assertNotEqual(new_output, old_output)
        self.assert_h264_video(new_output, frames=24, fps=24)
        self.assert_h264_video(old_output)

    def test_parallel_requests_share_one_conversion(self):
        original_run = subprocess.run
        with patch("vantage.coaching_video.subprocess.run", wraps=original_run) as encoder:
            with ThreadPoolExecutor(max_workers=4) as workers:
                outputs = list(workers.map(self.cache.get, [self.source] * 4))
        self.assertEqual(len(set(outputs)), 1)
        self.assertEqual(encoder.call_count, 1)
        self.assert_h264_video(outputs[0])

    def test_conversion_error_and_timeout_leave_no_output_and_preserve_source(self):
        before = self.fingerprint()
        for problem in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired("ffmpeg", 300),
                        OSError("not installed")):
            with self.subTest(problem=type(problem).__name__):
                def fail(command, **kwargs):
                    Path(command[-1]).write_bytes(b"unfinished")
                    if isinstance(problem, Exception):
                        raise problem
                    return problem
                with patch("vantage.coaching_video.subprocess.run", side_effect=fail):
                    with self.assertRaises(RuntimeError):
                        self.cache.get(self.source)
                self.assertEqual(list(self.cache.cache_dir.iterdir()), [])
                self.assertEqual(before, self.fingerprint())

    def test_source_change_during_conversion_is_not_published(self):
        original_run = subprocess.run
        before = self.source.stat()
        def change_source(command, **kwargs):
            result = original_run(command, **kwargs)
            os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
            return result
        with patch("vantage.coaching_video.subprocess.run", side_effect=change_source):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                self.cache.get(self.source)
        self.assertEqual(list(self.cache.cache_dir.iterdir()), [])

    def test_missing_and_invalid_input_do_not_produce_playback(self):
        with self.assertRaises(FileNotFoundError):
            self.cache.get(self.root / "missing.mp4")
        self.source.write_bytes(b"not a video")
        with self.assertRaises(RuntimeError):
            self.cache.get(self.source)
        self.assertEqual(list(self.cache.cache_dir.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b"not a video")


if __name__ == "__main__":
    unittest.main()
