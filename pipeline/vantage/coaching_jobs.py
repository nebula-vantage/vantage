"""Bounded local video uploads and asynchronous analysis for the coaching app.

Uploads and unfinished results are private. A complete, validated run is published
with one directory rename, so the session library never sees partial analysis.
The worker uses the real desktop pipeline; tests replace that boundary explicitly.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import shutil
import threading
import time
from typing import BinaryIO
import uuid

from vantage.coaching import build_report, validate_stats
from vantage.config import CONFIG
from vantage.main import run_pipeline
from vantage.video_input import prepare_video


MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_DURATION_S = 20 * 60
MAX_FRAMES = 72_000
MAX_PIXELS = 4096 * 2160
MAX_ACTIVE_JOBS = 8
MAX_JOBS = 20
ALLOWED_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi"}
TERMINAL = {"completed", "failed", "cancelled"}
LOGGER = logging.getLogger(__name__)


class AnalysisCancelled(RuntimeError):
    """Raised by progress callbacks to stop the pipeline and discard staging."""


class UploadError(ValueError):
    """An actionable input problem that can safely be shown in the browser."""


@dataclass
class _Job:
    public: dict
    directory: Path
    source: Path
    model: Path
    result: Path
    destination: Path
    cancelled: threading.Event = field(default_factory=threading.Event)
    busy: bool = False
    synthetic: bool = False
    last_saved: float = 0


def _model_path():
    configured = os.environ.get("VANTAGE_MODEL_PATH", "").strip()
    return (Path(configured).expanduser() if configured else
            Path(__file__).resolve().parents[2] / "ml" / "models" / "pickleball-v1.pt").resolve()


def _read_video(path: Path):
    """Reject bad metadata before decoding/re-encoding an unbounded recording."""
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise UploadError("This video could not be opened. Try exporting an H.264 MP4.")
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not all(math.isfinite(value) and value > 0 for value in (fps, frames, width, height)):
            raise UploadError("The video has invalid timing or dimensions. Export a constant-frame-rate MP4.")
        frames, width, height = round(frames), round(width), round(height)
        if not 1 <= fps <= 240 or frames < 1:
            raise UploadError("Use a video with a frame rate between 1 and 240 FPS.")
        duration = frames / fps
        if duration > MAX_DURATION_S + 1 / fps:
            raise UploadError("Choose a clip of 20 minutes or less.")
        if frames > MAX_FRAMES:
            raise UploadError("This clip has too many frames. Use a shorter clip (at most 72,000 frames).")
        if width < 16 or height < 16 or width * height > MAX_PIXELS or max(width, height) > 7680:
            raise UploadError("Use a video between 16 pixels and 4K resolution (up to 8.8 megapixels).")
        ok, first = capture.read()
        if not ok or first is None:
            raise UploadError("The video has no decodable frames. Try exporting an H.264 MP4.")
        if first.shape[:2] != (height, width):
            raise UploadError("The video's dimensions are inconsistent. Export a fixed-resolution MP4.")
        return {"width": width, "height": height, "fps": fps,
                "frame_count": frames, "duration_s": duration}, first
    finally:
        capture.release()


def _pipeline_config(model: Path):
    import torch
    config = deepcopy(CONFIG)
    config["model"] = {"path": str(model), "classes": {"player": 0, "ball": 1, "paddle": 2}}
    config["detection"]["ball_confidence"] = .20
    config["detection"]["device"] = ("0" if torch.cuda.is_available() else
                                       "mps" if torch.backends.mps.is_available() else "cpu")
    return config


class AnalysisJobs:
    """One serial daemon worker; bounded uploads and in-memory polling metadata.

    Browser refreshes may resume a job by ID while this server runs. Jobs are not
    resumed across server restarts; completed sessions remain ordinary run folders.
    """

    def __init__(self, runs_dir: Path):
        self.root = Path(runs_dir).resolve()
        self.uploads = self.root / ".uploads"
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()
        self._tasks = queue.Queue()
        self._closed = False
        self._worker = threading.Thread(target=self._work, name="vantage-analysis", daemon=True)
        self._worker.start()

    def config(self):
        available = _model_path().is_file()
        if available:
            available = all(importlib.util.find_spec(name) is not None
                            for name in ("cv2", "ultralytics", "imageio_ffmpeg", "torch"))
        result = {"analysis_available": available, "max_upload_bytes": MAX_UPLOAD_BYTES,
                  "max_duration_s": MAX_DURATION_S, "max_frames": MAX_FRAMES}
        if not available:
            result["analysis_error"] = ("Video analysis needs the trained pickleball model and Python dependencies. "
                                        "Run uv sync and provide ml/models/pickleball-v1.pt or VANTAGE_MODEL_PATH.")
        return result

    def create_upload(self, filename: str, stream: BinaryIO, length: int):
        if not isinstance(filename, str) or not filename or len(filename) > 255 or any(ord(c) < 32 for c in filename):
            raise UploadError("Choose a video with a valid filename (up to 255 characters).")
        name = filename.replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise UploadError("Choose an MP4, MOV, M4V, WebM, or AVI video.")
        if isinstance(length, bool) or not isinstance(length, int) or not 0 < length <= MAX_UPLOAD_BYTES:
            raise UploadError("Choose a nonempty video up to 512 MB.")
        configuration = self.config()
        if not configuration["analysis_available"]:
            raise UploadError(configuration["analysis_error"])
        with self._lock:
            if self._closed:
                raise UploadError("The analysis service has stopped. Restart the workspace.")
            active = sum(job.public["status"] not in TERMINAL for job in self._jobs.values())
            if active >= MAX_ACTIVE_JOBS:
                raise UploadError("Too many videos are waiting. Finish or cancel an existing analysis first.")
            if len(self._jobs) >= MAX_JOBS:
                raise UploadError("This workspace has reached its upload limit. Restart it to analyze more videos.")
            self.root.mkdir(parents=True, exist_ok=True)
            if self.uploads.is_symlink():
                raise UploadError("The private upload folder is unavailable. Choose another runs directory.")
            self.uploads.mkdir(mode=0o700, exist_ok=True)
            identity = uuid.uuid4().hex
            directory = self.uploads / identity
            directory.mkdir(mode=0o700)
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", Path(name).stem).strip("-")[:48] or "session"
            destination = self.root / f"{slug}-{identity[:8]}"
            public = {"id": identity, "name": Path(name).stem, "status": "preparing", "stage": "Uploading video",
                      "progress": None, "frames_done": 0, "total_frames": 0, "error": None}
            job = _Job(public, directory, directory / f"upload{suffix}", _model_path(),
                       directory / "result", destination, busy=True)
            self._jobs[identity] = job
        try:
            remaining = length
            with job.source.open("xb") as target:
                while remaining:
                    self._check_cancel(job)
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk or not isinstance(chunk, bytes) or len(chunk) > remaining:
                        raise UploadError("The upload was interrupted. Choose the video and try again.")
                    target.write(chunk)
                    remaining -= len(chunk)
            self._check_cancel(job)
            with self._lock:
                job.busy = False
                job.public["stage"] = "Preparing video"
                self._persist(job)
            self._tasks.put((identity, "prepare"))
            return self.get(identity)
        except Exception as exc:
            with self._lock:
                job.busy = False
                job.public.update(status="cancelled" if job.cancelled.is_set() else "failed",
                                  stage="Cancelled" if job.cancelled.is_set() else "Upload failed",
                                  error=None if job.cancelled.is_set() else "The upload was interrupted. Please try again.")
            self._cleanup(job)
            if isinstance(exc, (UploadError, AnalysisCancelled)):
                raise UploadError(str(exc)) from exc
            raise UploadError("The upload could not be saved. Check free disk space and try again.") from exc

    def get(self, identity: str):
        with self._lock:
            job = self._jobs.get(identity)
            return deepcopy(job.public) if job else None

    def preview(self, identity: str):
        with self._lock:
            job = self._jobs.get(identity)
            if not job or job.public["status"] in TERMINAL:
                return None
            path = job.directory / "preview.png"
            return path if path.is_file() else None

    def start(self, identity: str, corners, synthetic=False):
        from vantage.court import compute_homography, save_calibration
        if not isinstance(synthetic, bool):
            raise UploadError("Synthetic footage must be true or false.")
        with self._lock:
            job = self._jobs.get(identity)
            if not job:
                raise UploadError("This upload is no longer available. Upload the video again.")
            if job.public["status"] != "awaiting_calibration":
                raise UploadError("Wait for the court preview before starting analysis.")
            if (not isinstance(corners, list) or len(corners) != 4 or
                    any(not isinstance(point, list) or len(point) != 2 or
                        any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                            not -10_000_000 < v < 10_000_000 or
                            not math.isfinite(v) for v in point) for point in corners)):
                raise UploadError("Select four court corners in order: near-left, near-right, far-right, far-left.")
            video = job.public["video"]
            try:
                homography = compute_homography(corners, video["width"], video["height"], CONFIG)
            except (ValueError, OverflowError) as exc:
                raise UploadError("Select four visible court corners forming a non-crossing court inside the frame.") from exc
            save_calibration(job.result, homography, corners, video["width"], video["height"])
            job.synthetic = synthetic
            job.public.update(status="queued", stage="Waiting for analysis", progress=0.0)
            self._persist(job)
            self._tasks.put((identity, "analyze"))
            return deepcopy(job.public)

    def cancel(self, identity: str):
        with self._lock:
            job = self._jobs.get(identity)
            if not job:
                raise UploadError("This upload is no longer available.")
            if job.public["status"] not in TERMINAL:
                job.cancelled.set()
                job.public.update(status="cancelled", stage="Cancelled", progress=None, error=None)
                if not job.busy:
                    self._cleanup(job)
            return deepcopy(job.public)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            identities = list(self._jobs)
        for identity in identities:
            self.cancel(identity)
        self._tasks.put(None)

    def _check_cancel(self, job):
        if job.cancelled.is_set() or self._closed:
            raise AnalysisCancelled("Analysis cancelled.")

    def _persist(self, job):
        """Write only status metadata; private source paths never enter the API."""
        if job.directory.is_dir():
            staged = job.directory / "job.tmp.json"
            staged.write_text(json.dumps(job.public, allow_nan=False) + "\n")
            staged.replace(job.directory / "job.json")
            job.last_saved = time.monotonic()

    def _cleanup(self, job):
        shutil.rmtree(job.directory, ignore_errors=True)

    def _work(self):
        while True:
            task = self._tasks.get()
            if task is None:
                return
            identity, operation = task
            with self._lock:
                job = self._jobs.get(identity)
                if not job or job.cancelled.is_set() or self._closed:
                    continue
                job.busy = True
            try:
                self._check_cancel(job)
                if operation == "prepare":
                    self._prepare(job)
                else:
                    self._analyze(job)
            except AnalysisCancelled:
                with self._lock:
                    job.public.update(status="cancelled", stage="Cancelled", progress=None, error=None)
                self._cleanup(job)
            except Exception as exc:
                if not isinstance(exc, UploadError) and not job.cancelled.is_set():
                    # Keep diagnostic details on the local server, never in the
                    # browser response, before failed staging is removed.
                    LOGGER.exception("Analysis job %s failed during %s", identity, operation)
                with self._lock:
                    if job.cancelled.is_set():
                        job.public.update(status="cancelled", stage="Cancelled", progress=None, error=None)
                    else:
                        message = str(exc) if isinstance(exc, UploadError) else (
                            "Video preparation failed. Try a complete H.264 MP4 and check free disk space."
                            if operation == "prepare" else
                            "Analysis could not finish. Check the trained model, free disk space, and video, then try again.")
                        job.public.update(status="failed", stage="Preparation failed" if operation == "prepare" else "Analysis failed",
                                          progress=None, error=message)
                self._cleanup(job)
            finally:
                with self._lock:
                    job.busy = False
                    if job.cancelled.is_set():
                        self._cleanup(job)

    def _prepare(self, job):
        import cv2
        _read_video(job.source)
        self._check_cancel(job)
        prepared = prepare_video(job.source, job.directory / "prepared")
        self._check_cancel(job)
        metadata, first = _read_video(prepared)
        if not cv2.imwrite(str(job.directory / "preview.png"), first, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
            raise UploadError("The video preview could not be created. Try another MP4.")
        job.result.mkdir(exist_ok=True)
        scale = min(1.0, 640 / max(first.shape[:2]))
        thumbnail = cv2.resize(first, (max(1, round(first.shape[1] * scale)),
                                       max(1, round(first.shape[0] * scale))))
        # A thumbnail is optional; preparation and analysis still work if encoding it fails.
        try:
            cv2.imwrite(str(job.result / "thumbnail.png"), thumbnail, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        except cv2.error:
            pass
        shutil.copy2(prepared, job.result / "source.mp4")
        with self._lock:
            self._check_cancel(job)
            job.public.update(status="awaiting_calibration", stage="Select court corners", progress=None,
                              video=metadata, total_frames=metadata["frame_count"],
                              preview_url=f"/api/analysis/{job.public['id']}/preview")
            self._persist(job)

    def _analyze(self, job):
        if not job.model.is_file():
            raise UploadError("The trained model is no longer available. Restore it and upload the video again.")
        with self._lock:
            self._check_cancel(job)
            job.public.update(status="analyzing", stage="Loading detector", progress=0.0)
            self._persist(job)

        def progress(stage, count, total):
            self._check_cancel(job)
            with self._lock:
                self._check_cancel(job)
                phase = "rendering" if stage.lower().startswith(("render", "final")) else "analyzing"
                measured_progress = stage.lower().startswith(("detect", "render"))
                fraction = min(1.0, max(0.0, count / total)) if total and measured_progress else None
                job.public.update(status=phase, stage=stage, frames_done=count,
                                  total_frames=total or job.public["total_frames"], progress=fraction)
                if time.monotonic() - job.last_saved >= 1:
                    self._persist(job)

        stats = run_pipeline(job.result / "source.mp4", job.result,
                             config=_pipeline_config(job.model), progress_callback=progress)
        self._check_cancel(job)
        for name in ("annotated.mp4", "stats.json", "tracks.jsonl", "events.jsonl", "landing_heatmap.png"):
            if not (job.result / name).is_file():
                raise RuntimeError("Incomplete output artifacts.")
        stats["input"] = str(job.destination / "source.mp4")
        stats["original_input"] = stats["input"]
        if isinstance(stats.get("source"), dict):
            stats["source"]["path"] = stats["input"]
        stats["session_name"] = job.public["name"][:120]
        if job.synthetic:
            stats["synthetic"] = True
            stats["quality"]["warnings"].append(
                "The detector processed synthetic illustrative footage, not a recorded match. These are actual detector results on that animation.")
        validate_stats(stats)
        report = build_report(stats)
        (job.result / "stats.json").write_text(json.dumps(stats, indent=2, allow_nan=False) + "\n")
        (job.result / "coaching-report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        with self._lock:
            self._check_cancel(job)
            job.result.rename(job.destination)
            relative = str(job.destination.relative_to(self.root))
            session_id = hashlib.sha256(relative.encode()).hexdigest()[:20]
            job.public.update(status="completed", stage="Ready to review", progress=1.0,
                              frames_done=job.public["total_frames"], session_id=session_id)
            job.public.pop("preview_url", None)
        self._cleanup(job)
