"""Label the ball in sampled video frames, pre-filled from the on-device pipeline.

    uv run python ml/label_ball.py --video assets/pickleball/topcorner60fps.mov \
        --detections reports/swift-detections/topcorner60fps.jsonl --stride 5

Detections come from the iPhone app (share/export detections.jsonl) or the Mac CLI
vantage-analyze. Labels autosave to ml/labels/<video stem>.json after every change;
rerun the same command to resume at the first unlabeled sampled frame.

Keys:  Enter/Space  accept suggestion (orange) or keep current label, next frame
       click        set ball here (snaps to a raw candidate, white, if close)
       N            no ball visible, next frame
       S / D / →    skip (leave unlabeled), next frame      A / ←  previous frame
       Backspace    clear this frame's label                  - / =  shrink / grow box
       Q / Esc      save and quit
Label only what you can see: skip frames that are ambiguous rather than guessing.
"""
import argparse
from collections import OrderedDict
from pathlib import Path
import sys

import cv2
import numpy as np

from labeling import (ROOT, LabelSession, ball_candidates, center, load_detections, load_labels,
                      save_labels, tracked_balls)

WINDOW = "Vantage ball labeling"
ORANGE, WHITE, GREEN, RED, BLACK = (0, 165, 255), (255, 255, 255), (80, 220, 80), (70, 70, 255), (0, 0, 0)
LEFT_KEYS, RIGHT_KEYS = {2, 63234, 65361, ord("a")}, {3, 63235, 65363, ord("d"), ord("s")}


class FrameReader:
    """Sequential decoding with a small cache; seeks only when moving backwards."""

    def __init__(self, path, cache=40):
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            raise SystemExit(f"Cannot open video: {path}")
        self.next_index = 0
        self.cache = OrderedDict()
        self.cache_size = cache

    def read(self, index):
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        if index < self.next_index:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            self.next_index = index
        while self.next_index < index:
            if not self.capture.grab():
                raise SystemExit(f"Video ended before frame {index}")
            self.next_index += 1
        ok, image = self.capture.read()
        if not ok:
            raise SystemExit(f"Cannot decode frame {index}")
        self.next_index += 1
        self.cache[index] = image
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return image


def render(session, image, scale, mouse=None, message=""):
    """Display image: scaled frame, overlays, magnifier, and status bar."""
    frame = session.frame
    view = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    def overlays(img, origin, zoom, gap):
        """Draw markers on an already-scaled image. Rings sit `gap` px outside the box so
        they never cover the ball's pixels."""
        to_px = lambda p: (int(round((p[0] - origin[0]) * zoom)), int(round((p[1] - origin[1]) * zoom)))

        def ring(box, color, extra, thickness):
            radius = int(max(box[2] - box[0], box[3] - box[1]) * zoom / 2) + gap + extra
            cv2.circle(img, to_px(center(box)), radius, color, thickness, cv2.LINE_AA)

        for box, conf in session.candidates[frame]:
            ring(box, WHITE, 0, 1)
        if session.suggestions[frame] is not None and session.label is None:
            ring(session.suggestions[frame], ORANGE, 4, 2)
        if session.label is not None and session.label["ball"] is not None:
            x1, y1, x2, y2 = session.label["ball"]
            cv2.rectangle(img, to_px((x1, y1)), to_px((x2, y2)), GREEN, 1)
            ring(session.label["ball"], GREEN, 8, 2)

    overlays(view, (0, 0), scale, 4)
    if session.label is not None and session.label["ball"] is None:
        cv2.putText(view, "NO BALL", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, RED, 3, cv2.LINE_AA)

    # Magnifier: 6x zoom around the cursor (or the label/suggestion), top-right corner.
    focus = None
    if mouse is not None:
        focus = (mouse[0] / scale, mouse[1] / scale)
    elif session.label is not None and session.label["ball"] is not None:
        focus = center(session.label["ball"])
    elif session.suggestions[frame] is not None:
        focus = center(session.suggestions[frame])
    if focus is not None:
        zoom, half = 6, 30
        h, w = image.shape[:2]
        cx = int(min(max(focus[0], half), w - half))
        cy = int(min(max(focus[1], half), h - half))
        patch = cv2.resize(image[cy - half:cy + half, cx - half:cx + half], None,
                           fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
        overlays(patch, (cx - half, cy - half), zoom, 10)
        if mouse is not None:  # aiming aid only; never drawn over a suggested ball
            cv2.drawMarker(patch, (int((focus[0] - cx + half) * zoom), int((focus[1] - cy + half) * zoom)),
                           RED, cv2.MARKER_CROSS, 24, 1)
        ph, pw = patch.shape[:2]
        x0 = view.shape[1] - pw - 10
        if x0 > 0 and ph + 10 < view.shape[0]:
            view[10:10 + ph, x0:x0 + pw] = patch
            cv2.rectangle(view, (x0, 10), (x0 + pw, 10 + ph), WHITE, 1)

    counts = session.counts()
    status = (f"frame {frame}  sample {session.position + 1}/{len(session.order)}  "
              f"labeled {counts['labeled']} (ball {counts['ball']}, none {counts['absent']})   "
              "Enter accept | click set | N none | S skip | A back | Bksp clear | -/= size | Q quit")
    bar = np.full((52, view.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, status, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, WHITE, 1, cv2.LINE_AA)
    legend = "orange = suggestion (tracker)   white = raw detections   green = your label"
    cv2.putText(bar, message or legend, (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                RED if message else (180, 180, 180), 1, cv2.LINE_AA)
    return np.vstack([view, bar])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--detections", type=Path, required=True, help="detections.jsonl from the app or vantage-analyze")
    parser.add_argument("--labels", type=Path, help="default: ml/labels/<video stem>.json")
    parser.add_argument("--stride", type=int, default=5, help="label every Nth frame (default 5)")
    parser.add_argument("--offset", type=int, default=0, help="first sampled frame")
    parser.add_argument("--max-width", type=int, default=1400)
    parser.add_argument("--max-height", type=int, default=820)
    parser.add_argument("--preview", type=int, metavar="FRAME", help="render one frame to --preview-out and exit")
    parser.add_argument("--preview-out", type=Path, default=Path("label-preview.png"))
    args = parser.parse_args()

    frames = load_detections(args.detections)
    labels_path = args.labels or ROOT / "ml" / "labels" / f"{args.video.stem}.json"
    reader = FrameReader(args.video)
    first = reader.read(0)
    height, width = first.shape[:2]
    if (width, height) != (frames[0]["width"], frames[0]["height"]):
        raise SystemExit(f"Video is {width}x{height} but detections are {frames[0]['width']}x{frames[0]['height']}: "
                         "use detections made from this video.")
    session = LabelSession(order=list(range(args.offset, len(frames), args.stride)),
                           times=[f["timeSeconds"] for f in frames],
                           candidates=[ball_candidates(f) for f in frames],
                           suggestions=tracked_balls(frames), labels=load_labels(labels_path))
    session.first_unlabeled()
    scale = min(1.0, args.max_width / width, (args.max_height - 52) / height)
    relative_video = args.video.resolve().relative_to(ROOT) if args.video.resolve().is_relative_to(ROOT) else args.video

    def save():
        save_labels(labels_path, session.labels, video=relative_video, video_size=(width, height),
                    detections=args.detections)

    if args.preview is not None:
        session.position = min(range(len(session.order)), key=lambda i: abs(session.order[i] - args.preview))
        cv2.imwrite(str(args.preview_out), render(session, reader.read(session.frame), scale))
        print(f"Wrote {args.preview_out}")
        return

    state = {"mouse": None, "message": "", "dirty": True}

    def on_mouse(event, x, y, flags, param):
        if y >= int(height * scale):
            state["mouse"] = None
            return
        state["mouse"] = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            session.click(x / scale, y / scale, snap_radius=12 / scale)
            save()
            state["message"] = ""
        state["dirty"] = True

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, on_mouse)
    print(f"Labeling {len(session.order)} frames (every {args.stride}th); saving to {labels_path}", file=sys.stderr)
    try:
        while True:
            if state["dirty"]:
                cv2.imshow(WINDOW, render(session, reader.read(session.frame), scale, state["mouse"], state["message"]))
                state["dirty"] = False
            key = cv2.waitKeyEx(30)
            if key == -1:
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
                continue
            state["dirty"], state["message"] = True, ""
            char = key & 0xFF if key < 256 else None
            if char in (ord("q"), 27):
                break
            if char in (13, 10, 32):
                if not session.accept():
                    state["message"] = "No suggestion here: click the ball, press N for no ball, or S to skip."
            elif char in (ord("n"),):
                session.mark_absent()
            elif char in (8, 127):
                session.clear()
            elif char == ord("-"):
                session.resize(1 / 1.25)
            elif char in (ord("="), ord("+")):
                session.resize(1.25)
            elif key in LEFT_KEYS or char in LEFT_KEYS:
                session.move(-1)
            elif key in RIGHT_KEYS or char in RIGHT_KEYS:
                session.move(1)
            else:
                continue
            save()
    finally:
        save()
        cv2.destroyAllWindows()
        counts = session.counts()
        print(f"Saved {labels_path}: {counts['labeled']} labeled ({counts['ball']} ball, {counts['absent']} none)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
