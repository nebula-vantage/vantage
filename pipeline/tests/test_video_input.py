"""Preparation publishes only complete videos from an unchanged source revision."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from vantage.tracking_cache import source_signature
from vantage.video_input import PREPARATION_TIMEOUT_S, prepare_video


class VideoPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "phone.mp4"
        self.output = self.root / "output"
        writer = cv2.VideoWriter(str(self.source), cv2.VideoWriter_fourcc(*"mp4v"), 30, (64, 48))
        self.assertTrue(writer.isOpened())
        try:
            for value in range(6):
                writer.write(np.full((48, 64, 3), value * 30, dtype=np.uint8))
        finally:
            writer.release()

    def change_source_revision(self):
        info = self.source.stat()
        os.utime(self.source, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))

    def test_conversion_reuses_only_unchanged_source_and_output(self):
        original = self.source.read_bytes()
        prepared = prepare_video(self.source, self.output)
        with patch("vantage.video_input.subprocess.run", side_effect=AssertionError("cache miss")):
            self.assertEqual(prepare_video(self.source, self.output), prepared)
        prepared.write_bytes(b"truncated")
        prepare_video(self.source, self.output)
        capture = cv2.VideoCapture(str(prepared))
        try:
            self.assertTrue(capture.isOpened())
            count = 0
            while capture.read()[0]:
                count += 1
            self.assertEqual(count, 6)
        finally:
            capture.release()
        self.assertEqual(self.source.read_bytes(), original)

    def test_legacy_or_invalid_metadata_is_regenerated(self):
        prepared = prepare_video(self.source, self.output)
        marker = self.output / "prepared.json"
        for metadata in (json.dumps(source_signature(self.source)), "broken json", "null"):
            with self.subTest(metadata=metadata):
                marker.write_text(metadata)
                original_run = subprocess.run
                with patch("vantage.video_input.subprocess.run", wraps=original_run) as encoder:
                    prepare_video(self.source, self.output)
                self.assertEqual(encoder.call_count, 1)
                self.assertEqual(
                    json.loads(marker.read_text()),
                    {
                        "source": source_signature(self.source),
                        "prepared": source_signature(prepared),
                    },
                )

    def test_failed_conversion_preserves_previous_output_and_cleans_staging(self):
        prepared = prepare_video(self.source, self.output)
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        self.change_source_revision()
        for failure in (
            subprocess.TimeoutExpired("ffmpeg", PREPARATION_TIMEOUT_S),
            OSError("missing executable"),
            subprocess.CompletedProcess([], 1, stderr="encoding failed"),
        ):
            with self.subTest(failure=type(failure).__name__):

                def fail(command, failure=failure, **kwargs):
                    self.assertEqual(kwargs["timeout"], PREPARATION_TIMEOUT_S)
                    Path(command[-1]).write_bytes(b"incomplete")
                    if isinstance(failure, Exception):
                        raise failure
                    return failure

                with patch("vantage.video_input.subprocess.run", side_effect=fail):
                    with self.assertRaises(RuntimeError):
                        prepare_video(self.source, self.output)
                self.assertEqual(
                    before, {path.name: path.read_bytes() for path in self.output.iterdir()}
                )
        self.assertTrue(prepared.is_file())

    def test_source_changed_during_conversion_is_not_published(self):
        prepare_video(self.source, self.output)
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        self.change_source_revision()
        original_run = subprocess.run

        def convert_then_change(command, **kwargs):
            result = original_run(command, **kwargs)
            self.change_source_revision()
            return result

        with patch("vantage.video_input.subprocess.run", side_effect=convert_then_change):
            with self.assertRaisesRegex(RuntimeError, "changed during preparation"):
                prepare_video(self.source, self.output)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_cannot_overwrite_source(self):
        source = self.root / "prepared.mp4"
        source.write_bytes(self.source.read_bytes())
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "separate from the source"):
            prepare_video(source, self.root)
        self.assertEqual(source.read_bytes(), before)

    def test_failed_marker_publication_cannot_leave_a_stale_cache_hit(self):
        prepare_video(self.source, self.output)
        self.change_source_revision()
        original_replace = Path.replace

        def fail_marker(path, target):
            if path.name == "prepared.json":
                raise OSError("metadata publication failed")
            return original_replace(path, target)

        with patch.object(Path, "replace", fail_marker):
            with self.assertRaisesRegex(OSError, "metadata publication failed"):
                prepare_video(self.source, self.output)
        self.assertFalse((self.output / "prepared.json").exists())
        self.assertEqual([path.name for path in self.output.iterdir()], ["prepared.mp4"])
        original_run = subprocess.run
        with patch("vantage.video_input.subprocess.run", wraps=original_run) as encoder:
            prepare_video(self.source, self.output)
        self.assertEqual(encoder.call_count, 1)
