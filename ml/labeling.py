"""Ball-label storage, labeling-session logic, and evaluation against labels.

UI-free so it can be unit-tested; label_ball.py is the OpenCV front end.

Label file (one per video, ml/labels/<video stem>.json):
    {"schema": 1, "video": "...", "video_size": [w, h], "detections": "...",
     "frames": {"92": {"time_s": 3.06, "ball": [x1, y1, x2, y2], "origin": "suggestion"},
                "97": {"time_s": 3.23, "ball": null, "origin": "absent"}}}

`ball` is null when no ball is visible. Frames not present were not reviewed (skipped or
ambiguous) and are excluded from evaluation. `origin` records how the label was made:
suggestion (accepted tracker output), candidate (clicked a raw detection), manual
(clicked elsewhere), or absent.
"""
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ball_tracker import BallTracker  # noqa: E402
from config import CONFIG  # noqa: E402
from records import Detection  # noqa: E402
from vantage_classes import CANONICAL  # noqa: E402

# detections.jsonl always uses canonical IDs, whatever model produced it.
BALL = CANONICAL["ball"]
SCHEMA = 1


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def load_detections(path):
    """On-device detections JSONL (app or vantage-analyze), sorted by time."""
    frames = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    frames.sort(key=lambda f: f["timeSeconds"])
    return frames


def ball_candidates(frame):
    """Raw ball candidates as (box, confidence), in detector order."""
    return [(d["box"], d["confidence"]) for d in frame["detections"] if d["classID"] == BALL]


def tracked_balls(frames, config=CONFIG):
    """Desktop BallTracker selection per frame (box or None); identical to the app's."""
    if not frames:
        return []
    tracker = BallTracker(config, frames[0]["width"], frames[0]["height"])
    boxes = []
    for frame in frames:
        selected = tracker.select([Detection(tuple(box), conf, None, BALL)
                                   for box, conf in ball_candidates(frame)], frame["timeSeconds"])
        boxes.append(None if selected is None else list(selected.box))
    return boxes


def best_raw_balls(frames):
    """Highest-confidence raw candidate per frame: the detector alone, no tracking."""
    return [max(ball_candidates(f), key=lambda c: c[1])[0] if ball_candidates(f) else None for f in frames]


def load_labels(path):
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError(f"Unsupported label schema in {path}: {data.get('schema')}")
    return {int(k): v for k, v in data["frames"].items()}


def save_labels(path, labels, *, video, video_size, detections):
    """Atomic write so an interrupted session never corrupts existing labels."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": SCHEMA, "video": str(video), "video_size": list(video_size),
            "detections": None if detections is None else str(detections),
            "frames": {str(k): labels[k] for k in sorted(labels)}}
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as stream:
        json.dump(data, stream, indent=1)
        stream.write("\n")
    os.replace(stream.name, path)


def label_centers(labels):
    """{"frame": [x, y] | null} format used by mobile/model/crop_experiment.py --labels."""
    return {str(k): (None if v["ball"] is None else list(center(v["ball"]))) for k, v in sorted(labels.items())}


@dataclass
class LabelSession:
    """Navigation and editing over sampled frames. Positions are indexes into `order`."""
    order: list[int]
    times: list[float]
    candidates: list[list]  # per video frame: [(box, confidence), ...]
    suggestions: list  # per video frame: box or None
    labels: dict[int, dict] = field(default_factory=dict)
    position: int = 0
    default_box_px: float = 10.0

    @property
    def frame(self):
        return self.order[self.position]

    @property
    def label(self):
        return self.labels.get(self.frame)

    def first_unlabeled(self):
        self.position = next((i for i, f in enumerate(self.order) if f not in self.labels), len(self.order) - 1)

    def move(self, step):
        self.position = min(max(self.position + step, 0), len(self.order) - 1)

    def _set(self, ball, origin):
        self.labels[self.frame] = {"time_s": self.times[self.frame], "ball": ball, "origin": origin}

    def accept(self):
        """Keep the current label, or accept the tracker suggestion, then advance.

        Returns False (no change) when there is neither: the user must click or mark absent.
        """
        if self.label is None:
            suggestion = self.suggestions[self.frame]
            if suggestion is None:
                return False
            self._set([float(v) for v in suggestion], "suggestion")
        self.move(1)
        return True

    def mark_absent(self):
        self._set(None, "absent")
        self.move(1)

    def click(self, x, y, snap_radius):
        """Label at a source-pixel point: snap to the nearest raw candidate within
        snap_radius, else a manual box of the most recent labeled size."""
        nearest = min(self.candidates[self.frame], key=lambda c: math.dist(center(c[0]), (x, y)), default=None)
        if nearest is not None and math.dist(center(nearest[0]), (x, y)) <= snap_radius:
            self._set([float(v) for v in nearest[0]], "candidate")
            return
        half = self._recent_size() / 2
        self._set([x - half, y - half, x + half, y + half], "manual")

    def _recent_size(self):
        for frame in sorted(self.labels, key=lambda f: abs(f - self.frame)):
            ball = self.labels[frame]["ball"]
            if ball is not None:
                return max(ball[2] - ball[0], ball[3] - ball[1])
        return self.default_box_px

    def resize(self, factor):
        if self.label is None or self.label["ball"] is None:
            return
        cx, cy = center(self.label["ball"])
        x1, y1, x2, y2 = self.label["ball"]
        half_w, half_h = max(1.0, (x2 - x1) * factor / 2), max(1.0, (y2 - y1) * factor / 2)
        self.label["ball"] = [cx - half_w, cy - half_h, cx + half_w, cy + half_h]
        self.label["origin"] = "manual"

    def clear(self):
        self.labels.pop(self.frame, None)

    def counts(self):
        visible = sum(v["ball"] is not None for v in self.labels.values())
        return {"labeled": len(self.labels), "ball": visible, "absent": len(self.labels) - visible,
                "suggestions_accepted": sum(v["origin"] == "suggestion" for v in self.labels.values())}


def evaluate(predictions, labels, radius):
    """Score per-frame predicted boxes (or None) against labels.

    A prediction is correct when the label has a ball and the centers are within radius.
    A wrong position on a visible-ball frame counts as both a miss and a false detection,
    as in crop_experiment.evaluate_labels.
    """
    totals = dict(labeled=0, visible=0, correct=0, missed=0, false_detection=0)
    for frame, label in labels.items():
        if frame >= len(predictions):
            continue
        truth, predicted = label["ball"], predictions[frame]
        correct = (truth is not None and predicted is not None
                   and math.dist(center(truth), center(predicted)) <= radius)
        totals["labeled"] += 1
        totals["visible"] += truth is not None
        totals["correct"] += correct
        totals["missed"] += truth is not None and not correct
        totals["false_detection"] += predicted is not None and not correct
    detections = totals["correct"] + totals["false_detection"]
    totals["recall"] = totals["correct"] / totals["visible"] if totals["visible"] else None
    totals["precision"] = totals["correct"] / detections if detections else None
    return totals
