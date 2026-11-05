"""Real upload/prepare/calibration boundaries with a replaceable inference worker."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from vantage.coaching import build_report
from vantage.coaching_jobs import AnalysisJobs, MAX_UPLOAD_BYTES, UploadError, _read_video
from vantage.config import CONFIG
from vantage.court import load_calibration


def fake_pipeline(source, output, *, config, progress_callback):
    """A deterministic test boundary, never selected by production code."""
    capture = cv2.VideoCapture(str(source))
    try:
        width = round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = round(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    assert load_calibration(output, width, height, config) is not None
    progress_callback("Detecting", frames // 2, frames)
    progress_callback("Analyzing", frames, frames)
    progress_callback("Rendering", frames, frames)
    stats = {
        "schema_version": 2,
        "video": {"width": width, "height": height, "fps": fps,
                  "frame_count": frames, "duration_s": frames / fps},
        "quality": {"status": "insufficient_evidence", "ball_detection_coverage": 0,
                    "observed_frames": 0, "warnings": []},
        "rallies": [], "crossing_events": [], "in_out_calls": [],
        "rally_count": 0, "shot_count": 0, "longest_rally": 0,
        "bounce_candidate_count": 0, "avg_ball_speed_kmh": None,
        "source": {"path": str(source), "size_bytes": source.stat().st_size,
                   "mtime_ns": source.stat().st_mtime_ns},
    }
    (output / "stats.json").write_text(json.dumps(stats))
    (output / "tracks.jsonl").write_text("".join(json.dumps({"index": i, "time_s": i / fps}) + "\n" for i in range(frames)))
    (output / "events.jsonl").write_text("")
    shutil.copy2(source, output / "annotated.mp4")
    cv2.imwrite(str(output / "landing_heatmap.png"), np.zeros((30, 30, 3), np.uint8))
    return stats


class AnalysisJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "clip.mp4"
        writer = cv2.VideoWriter(str(self.source), cv2.VideoWriter_fourcc(*"mp4v"), 6, (180, 120))
        self.assertTrue(writer.isOpened())
        for i in range(12):
            frame = np.full((120, 180, 3), 50, np.uint8)
            cv2.circle(frame, (20 + i * 5, 60), 4, (255, 255, 255), -1)
            writer.write(frame)
        writer.release()
        self.data = self.source.read_bytes()
        self.model = self.root / "test-model.pt"
        self.model.write_bytes(b"test-only-placeholder")
        self.env = patch.dict(os.environ, {"VANTAGE_MODEL_PATH": str(self.model)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config_patch = patch("vantage.coaching_jobs._pipeline_config", return_value=deepcopy(CONFIG))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.pipeline_patch = patch("vantage.coaching_jobs.run_pipeline", side_effect=fake_pipeline)
        self.pipeline = self.pipeline_patch.start()
        self.addCleanup(self.pipeline_patch.stop)
        self.jobs = AnalysisJobs(self.root / "runs")
        self.addCleanup(self.close_jobs)

    def close_jobs(self):
        self.jobs.close()
        self.jobs._worker.join(timeout=5)

    def upload(self, name="Weekend match.mp4"):
        return self.jobs.create_upload(name, io.BytesIO(self.data), len(self.data))

    def wait_for(self, identity, statuses):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = self.jobs.get(identity)
            if result["status"] in statuses:
                return result
            time.sleep(.02)
        self.fail(f"Job did not reach {statuses}: {self.jobs.get(identity)}")

    def calibrated(self, name="Weekend match.mp4"):
        upload = self.upload(name)
        self.wait_for(upload["id"], {"awaiting_calibration"})
        return self.jobs.start(upload["id"], [[10, 110], [170, 110], [170, 10], [10, 10]])

    def test_upload_prepare_calibrate_analyze_and_publish_real_importable_session(self):
        job = self.upload("../Weekend match.mp4")
        self.assertEqual(job["name"], "Weekend match")
        self.assertEqual(job["status"], "preparing")
        ready = self.wait_for(job["id"], {"awaiting_calibration"})
        self.assertEqual(ready["video"]["frame_count"], 12)
        self.assertAlmostEqual(ready["video"]["duration_s"], 2)
        self.assertTrue(self.jobs.preview(job["id"]).is_file())
        self.assertNotIn(str(self.root), json.dumps(ready))
        self.assertEqual(list((self.root / "runs").glob("*/stats.json")), [])
        self.jobs.start(job["id"], [[10, 110], [170, 110], [170, 10], [10, 10]], synthetic=True)
        done = self.wait_for(job["id"], {"completed", "failed"})
        self.assertEqual(done["status"], "completed", done)
        self.pipeline.assert_called_once()
        runs = [path for path in (self.root / "runs").iterdir() if not path.name.startswith(".")]
        self.assertEqual(len(runs), 1)
        result = runs[0]
        self.assertEqual(done["session_id"], hashlib.sha256(result.name.encode()).hexdigest()[:20])
        self.assertIsNone(self.jobs.preview(job["id"]))
        self.assertFalse((self.root / "runs" / ".uploads" / job["id"]).exists())
        stats = json.loads((result / "stats.json").read_text())
        self.assertTrue(stats["synthetic"])
        self.assertEqual(stats["shot_count"], 0)  # Never replace detections with sample numbers.
        self.assertIn("synthetic illustrative footage", stats["quality"]["warnings"][0])
        self.assertTrue(Path(stats["input"]).is_file())
        self.assertEqual(stats["source"]["path"], stats["input"])
        self.assertEqual(json.loads((result / "coaching-report.json").read_text()), build_report(stats))
        self.assertEqual(self.jobs.cancel(job["id"])["status"], "completed")

    def test_rejects_invalid_extensions_sizes_missing_model_and_truncated_upload(self):
        for name, length in (("movie.exe", 5), ("movie.mp4", 0), ("movie.mp4", MAX_UPLOAD_BYTES + 1),
                             ("movie.mp4", True), ("bad\x00name.mp4", 5)):
            with self.subTest(name=name, length=length), self.assertRaises(UploadError):
                self.jobs.create_upload(name, io.BytesIO(b"abc"), length)
        with self.assertRaisesRegex(UploadError, "interrupted"):
            self.jobs.create_upload("clip.mp4", io.BytesIO(self.data[:20]), len(self.data))
        self.assertEqual(list(self.jobs.uploads.iterdir()), [])
        self.model.unlink()
        self.assertFalse(self.jobs.config()["analysis_available"])
        with self.assertRaisesRegex(UploadError, "trained pickleball model"):
            self.upload()

    def test_invalid_video_and_oversized_duration_fail_before_pipeline(self):
        bad = self.jobs.create_upload("bad.mp4", io.BytesIO(b"invalid video"), 13)
        done = self.wait_for(bad["id"], {"failed"})
        self.assertIn("could not be opened", done["error"])
        with patch("vantage.coaching_jobs._read_video", side_effect=UploadError("Choose a clip of 20 minutes or less.")):
            job = self.upload()
            done = self.wait_for(job["id"], {"failed"})
        self.assertIn("20 minutes", done["error"])
        self.pipeline.assert_not_called()

    def test_frame_duration_and_resolution_budgets_are_checked_before_decode(self):
        cases = [
            {"fps": 30, "frames": 36_060, "width": 1920, "height": 1080},
            {"fps": 120, "frames": 72_120, "width": 1920, "height": 1080},
            {"fps": 30, "frames": 30, "width": 7680, "height": 4320},
            {"fps": 0, "frames": 30, "width": 1920, "height": 1080},
        ]
        for values in cases:
            metadata = {cv2.CAP_PROP_FPS: values["fps"], cv2.CAP_PROP_FRAME_COUNT: values["frames"],
                        cv2.CAP_PROP_FRAME_WIDTH: values["width"], cv2.CAP_PROP_FRAME_HEIGHT: values["height"]}
            with self.subTest(values=values), patch("cv2.VideoCapture") as constructor:
                capture = constructor.return_value
                capture.isOpened.return_value = True
                capture.get.side_effect = metadata.__getitem__
                with self.assertRaises(UploadError):
                    _read_video(self.source)
                capture.read.assert_not_called()
                capture.release.assert_called_once()

    def test_calibration_rejects_bad_coordinates_and_preserves_retry(self):
        job = self.upload()
        self.wait_for(job["id"], {"awaiting_calibration"})
        for corners in (None, [], [[0, 0]] * 4, [[1, 1], [170, 110], [170, 10], [1, 110]],
                        [[-1, 1], [170, 110], [170, 10], [10, 10]],
                        [[float("nan"), 1], [170, 110], [170, 10], [10, 10]],
                        [[10**500, 1], [170, 110], [170, 10], [10, 10]]):
            with self.subTest(corners=corners), self.assertRaises(ValueError):
                self.jobs.start(job["id"], corners)
            self.assertEqual(self.jobs.get(job["id"])["status"], "awaiting_calibration")
        with self.assertRaises(ValueError):
            self.jobs.start(job["id"], [[10, 110], [170, 110], [170, 10], [10, 10]], synthetic="true")
        self.jobs.start(job["id"], [[10, 110], [170, 110], [170, 10], [10, 10]])
        with self.assertRaises(ValueError):
            self.jobs.start(job["id"], [[10, 110], [170, 110], [170, 10], [10, 10]])
        self.wait_for(job["id"], {"completed"})

    def test_cancel_during_analysis_uses_callback_and_never_publishes(self):
        started, proceed = threading.Event(), threading.Event()
        def wait_pipeline(source, output, *, config, progress_callback):
            progress_callback("Detecting", 1, 12)
            started.set()
            proceed.wait(timeout=4)
            progress_callback("Detecting", 2, 12)
            self.fail("Cancelled inference must not continue")
        self.pipeline.side_effect = wait_pipeline
        job = self.calibrated()
        self.assertTrue(started.wait(timeout=4))
        during = self.jobs.get(job["id"])
        self.assertEqual(during["status"], "analyzing")
        self.assertEqual(during["frames_done"], 1)
        self.assertAlmostEqual(during["progress"], 1 / 12)
        self.assertEqual(self.jobs.cancel(job["id"])["status"], "cancelled")
        proceed.set()
        deadline = time.monotonic() + 4
        while (self.jobs.uploads / job["id"]).exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse((self.jobs.uploads / job["id"]).exists())
        self.assertEqual(list((self.root / "runs").glob("*/stats.json")), [])

    def test_preparation_cancel_discards_work_and_close_cancels_pending_jobs(self):
        entered, proceed = threading.Event(), threading.Event()
        from vantage.coaching_jobs import prepare_video
        def waiting_prepare(source, destination):
            entered.set()
            proceed.wait(timeout=4)
            return prepare_video(source, destination)
        with patch("vantage.coaching_jobs.prepare_video", side_effect=waiting_prepare):
            job = self.upload()
            self.assertTrue(entered.wait(timeout=4))
            self.assertEqual(self.jobs.cancel(job["id"])["status"], "cancelled")
            proceed.set()
            self.jobs.close()
            self.jobs._worker.join(timeout=5)
        self.assertFalse((self.jobs.uploads / job["id"]).exists())
        with self.assertRaisesRegex(ValueError, "stopped"):
            self.upload()

    def test_cancel_after_preview_publication_still_cleans_busy_worker(self):
        ready, proceed = threading.Event(), threading.Event()
        original = self.jobs._prepare
        def hold_after_ready(job):
            original(job)
            ready.set()
            proceed.wait(timeout=4)
        with patch.object(self.jobs, "_prepare", side_effect=hold_after_ready):
            job = self.upload()
            self.assertTrue(ready.wait(timeout=4))
            self.assertEqual(self.jobs.get(job["id"])["status"], "awaiting_calibration")
            self.jobs.cancel(job["id"])
            proceed.set()
            self.jobs.close()
            self.jobs._worker.join(timeout=5)
        self.assertFalse((self.jobs.uploads / job["id"]).exists())

    def test_aggregation_and_finalization_report_indeterminate_progress(self):
        job = self.upload()
        self.wait_for(job["id"], {"awaiting_calibration"})
        stages = []
        def reported_pipeline(source, output, *, config, progress_callback):
            progress_callback("Analyzing", 0, 12)
            stages.append(self.jobs.get(job["id"]))
            result = fake_pipeline(source, output, config=config, progress_callback=progress_callback)
            progress_callback("Finalizing", 0, 12)
            stages.append(self.jobs.get(job["id"]))
            return result
        self.pipeline.side_effect = reported_pipeline
        self.jobs.start(job["id"], [[10, 110], [170, 110], [170, 10], [10, 10]])
        self.wait_for(job["id"], {"completed"})
        self.assertEqual([stage["status"] for stage in stages], ["analyzing", "rendering"])
        self.assertEqual([stage["progress"] for stage in stages], [None, None])

    def test_pipeline_failure_preserves_existing_run_and_suppresses_private_error(self):
        previous = self.jobs.root / "previous"
        previous.mkdir(parents=True)
        (previous / "stats.json").write_text("previous result")
        self.pipeline.side_effect = RuntimeError("secret/path/to/model")
        job = self.calibrated()
        done = self.wait_for(job["id"], {"failed"})
        self.assertNotIn("secret", done["error"])
        self.assertEqual((previous / "stats.json").read_text(), "previous result")
        self.assertEqual(list(self.jobs.root.glob("*/stats.json")), [previous / "stats.json"])

    def test_active_job_limit_unknown_ids_and_readonly_snapshots(self):
        with patch("vantage.coaching_jobs.MAX_ACTIVE_JOBS", 1):
            job = self.upload()
            ready = self.wait_for(job["id"], {"awaiting_calibration"})
            ready["video"]["width"] = 1
            self.assertEqual(self.jobs.get(job["id"])["video"]["width"], 180)
            with self.assertRaisesRegex(ValueError, "Too many"):
                self.upload()
        self.assertIsNone(self.jobs.get("unknown"))
        self.assertIsNone(self.jobs.preview("unknown"))
        with self.assertRaises(ValueError):
            self.jobs.cancel("unknown")
        with self.assertRaises(ValueError):
            self.jobs.start("unknown", [])


if __name__ == "__main__":
    unittest.main()
