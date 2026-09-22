"""Pretrained YOLO + persistent ByteTrack; no training or custom tracker."""
import contextlib
import math
from pathlib import Path
import sys

from records import Detection, FrameRecord


class BallSelector:
    def __init__(self, config: dict, width: int, height: int):
        self.config = config["detection"]
        self.diagonal = math.hypot(width, height)
        self.last: tuple[float, Detection] | None = None

    def select(self, candidates: list[Detection], time_s: float) -> Detection | None:
        candidates = [b for b in candidates if b.confidence >= self.config["ball_confidence"]]
        if self.last is not None:
            last_time, last_ball = self.last
            dt = time_s - last_time
            if dt <= self.config["candidate_reset_s"]:
                limit = self.diagonal * (self.config["motion_slack_diagonals"]
                                        + self.config["max_motion_diagonals_s"] * dt)
                candidates = [b for b in candidates
                              if math.dist(b.center, last_ball.center) <= limit]
        selected = max(candidates, key=lambda b: b.confidence, default=None)
        if selected is not None:
            self.last = (time_s, selected)
        return selected


class Detector:
    def __init__(self, config: dict, width: int, height: int, fps: float, work_dir: Path):
        self.config = config
        self.selector = BallSelector(config, width, height)
        self.tracker_path = work_dir / "bytetrack.yaml"
        tracker = dict(config["tracker"])
        # Ultralytics initializes ByteTrack with a nominal 30 FPS; its buffer is
        # expressed in frames, so convert using the actual input frame rate here.
        tracker["track_buffer"] = max(1, round(tracker.pop("track_buffer_s") * fps))
        self.tracker_path.write_text("\n".join(
            f"{key}: {str(value).lower() if isinstance(value, bool) else value}"
            for key, value in tracker.items()) + "\n")
        try:
            with contextlib.redirect_stdout(sys.stderr):
                from ultralytics import YOLO
                from ultralytics.utils import LOGGER
                for handler in LOGGER.handlers:
                    if hasattr(handler, "setStream"):
                        handler.setStream(sys.stderr)
                self.model = YOLO(config["model"]["path"])
        except Exception as exc:
            raise RuntimeError(
                f"Could not load model {config['model']['path']!r}. Install requirements.txt; "
                "the first run needs internet to download weights. "
                "For offline use, pre-download weights and set CONFIG['model']['path']. "
                f"Details: {exc}") from exc
        expected = set(config["model"]["classes"].values())
        if not expected.issubset(set(self.model.names)):
            raise RuntimeError("Model class IDs do not match CONFIG['model']['classes'].")

    def process(self, frame, index: int, time_s: float) -> FrameRecord:
        cfg = self.config["detection"]
        classes = self.config["model"]["classes"]
        with contextlib.redirect_stdout(sys.stderr):
            result = self.model.track(
                frame, persist=True, tracker=str(self.tracker_path),
                classes=list(classes.values()), conf=cfg["confidence"], iou=cfg["iou"],
                imgsz=cfg["image_size"], device=cfg["device"],
                max_det=cfg["max_detections"], verbose=False, save=False)[0]
        record = FrameRecord(index, time_s)
        balls = []
        boxes = result.boxes
        if boxes is None:
            return record
        ids = boxes.id.cpu().tolist() if boxes.id is not None else [None] * len(boxes)
        for box, score, class_id, track_id in zip(
                boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(),
                boxes.cls.cpu().tolist(), ids):
            if not all(math.isfinite(v) for v in [*box, score]):
                continue
            detection = Detection(tuple(box), float(score),
                                  int(track_id) if track_id is not None else None, int(class_id))
            if class_id == classes["player"] and score >= cfg["player_confidence"]:
                record.players.append(detection)
            elif class_id == classes["ball"]:
                balls.append(detection)
            elif class_id == classes["paddle"] and score >= cfg["paddle_confidence"]:
                record.paddles.append(detection)
        record.ball = self.selector.select(balls, time_s)
        return record
