"""One YOLO inference pass, player ByteTrack, and independent ball motion tracking."""
import contextlib
import math
from pathlib import Path
import sys
from types import SimpleNamespace

from ball_tracker import BallTracker
from records import Detection, FrameRecord


class Detector:
    def __init__(self, config: dict, width: int, height: int, fps: float, work_dir: Path):
        self.config = config
        self.ball_tracker = BallTracker(config, width, height)
        self.raw_balls: list[Detection] = []
        tracker = dict(config["tracker"])
        # BYTETracker's buffer is measured in frames. Older releases default
        # to a nominal 30 FPS (unit scaling); newer releases use frames directly.
        tracker["track_buffer"] = max(1, round(tracker.pop("track_buffer_s") * fps))
        try:
            with contextlib.redirect_stdout(sys.stderr):
                from ultralytics import YOLO
                from ultralytics.trackers.byte_tracker import BYTETracker
                from ultralytics.utils import LOGGER
                for handler in LOGGER.handlers:
                    if hasattr(handler, "setStream"):
                        handler.setStream(sys.stderr)
                self.model = YOLO(config["model"]["path"])
                self.player_tracker = BYTETracker(SimpleNamespace(**tracker))
        except Exception as exc:
            raise RuntimeError(
                f"Could not load model {config['model']['path']!r} or player tracker. Install requirements.txt; "
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
            result = self.model.predict(
                frame, classes=list(classes.values()), conf=cfg["confidence"], iou=cfg["iou"],
                imgsz=cfg["image_size"], device=cfg["device"],
                max_det=cfg["max_detections"], verbose=False, save=False)[0]
        record = FrameRecord(index, time_s)
        self.raw_balls = []
        boxes = result.boxes
        if boxes is not None:
            boxes = boxes.cpu()
            player_indices = []
            for i, (box, score, class_id) in enumerate(zip(
                    boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist())):
                if (not all(math.isfinite(v) for v in [*box, score, class_id])
                        or box[2] <= box[0] or box[3] <= box[1]):
                    continue
                detection = Detection(tuple(box), float(score), None, int(class_id))
                if class_id == classes["player"]:
                    player_indices.append(i)
                elif class_id == classes["ball"]:
                    self.raw_balls.append(detection)
                elif class_id == classes["paddle"] and score >= cfg["paddle_confidence"]:
                    # Paddles are raw observations for contact suppression, not identities.
                    record.paddles.append(detection)
            # Update even on empty player frames so missing-track lifetimes advance.
            tracked = self.player_tracker.update(boxes[player_indices].numpy(), frame)
            for row in tracked:
                x1, y1, x2, y2, track_id, score, class_id, _ = row
                if score >= cfg["player_confidence"]:
                    record.players.append(Detection((float(x1), float(y1), float(x2), float(y2)),
                                                    float(score), int(track_id), int(class_id)))
        else:
            # Standard detection Results use empty Boxes rather than None, but
            # still age the player tracker if an adapter returns no boxes.
            import numpy as np
            from ultralytics.engine.results import Boxes
            self.player_tracker.update(Boxes(np.empty((0, 6)), frame.shape[:2]), frame)
        record.ball = self.ball_tracker.select(self.raw_balls, time_s)
        return record
