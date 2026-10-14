"""Run a YOLO checkpoint over a video and write detections.jsonl in the app's format.

    .venv/bin/python ml/predict_video.py --weights ml/runs/pickleball-v1/weights/best.pt \
        --video assets/pickleball/topcorner60fps.mov --output /tmp/topcorner-v1.jsonl

Class IDs are mapped to Vantage canonical IDs by class name, so evaluate_ball.py, the
labeling tool, and the app's player all work with any model. Uses PyTorch (desktop-style
rectangular letterboxing); confirm a final model on-device via Core ML export and
vantage-analyze, whose square letterboxing yields somewhat different candidates.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2

from vantage_classes import canonical_map


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--confidence", type=float, default=0.10, help="same raw threshold as the app")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args()

    from ultralytics import YOLO
    model = YOLO(str(args.weights))
    mapping = canonical_map(model.names)
    if 32 not in mapping.values():
        raise SystemExit(f"Model has no ball class: {model.names}")
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.output.open("w") as stream:
        while True:
            ok, image = capture.read()
            if not ok or (args.max_frames and count >= args.max_frames):
                break
            start = time.perf_counter()
            result = model.predict(image, imgsz=args.imgsz, conf=args.confidence, device=args.device,
                                   max_det=100, verbose=False)[0]
            elapsed = (time.perf_counter() - start) * 1000
            detections = [{"classID": mapping[int(c)], "confidence": float(s), "box": [float(v) for v in b]}
                          for b, c, s in zip(result.boxes.xyxy.tolist(), result.boxes.cls.tolist(),
                                             result.boxes.conf.tolist()) if int(c) in mapping]
            h, w = image.shape[:2]
            stream.write(json.dumps({"timeSeconds": count / fps, "width": w, "height": h,
                                     "inferenceMilliseconds": elapsed, "detections": detections}) + "\n")
            count += 1
            if count % 200 == 0:
                print(f"{count} frames", file=sys.stderr)
    print(f"Wrote {count} frames to {args.output}")


if __name__ == "__main__":
    main()
