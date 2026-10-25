"""Compare desktop preprocessing, square PyTorch, and square Core ML detections.

Agreement is model parity, not accuracy against labelled ground truth.
"""
import argparse
import json
import math
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".cache/ultralytics"))


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def agreement(reference, candidate, threshold=0.5):
    # Greedy one-to-one matches, separately within each class.
    pairs = sorted(((iou(a["box"], b["box"]), i, j)
                    for i, a in enumerate(reference) for j, b in enumerate(candidate)
                    if a["class_id"] == b["class_id"]), reverse=True)
    used_a, used_b, matches = set(), set(), []
    for overlap, i, j in pairs:
        if overlap >= threshold and i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
            matches.append({"iou": overlap, "confidence_delta": abs(reference[i]["confidence"]-candidate[j]["confidence"])})
    return {"reference_count": len(reference), "candidate_count": len(candidate),
            "matched": len(matches), "matches": matches}


def main():
    import cv2
    Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--package", type=Path, default=ROOT / "artifacts/yolo26n-1280/VantageDetector.mlpackage")
    parser.add_argument("--weights", type=Path, default=ROOT / "yolo26n.pt")
    parser.add_argument("--size", type=int, default=1280)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1 or not all(p.exists() for p in (args.video, args.package, args.weights)):
        parser.error("Provide existing video/model paths and a positive sample count.")
    args.output.mkdir(parents=True, exist_ok=False)
    capture = cv2.VideoCapture(str(args.video))
    count, fps = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), capture.get(cv2.CAP_PROP_FPS)
    if count <= 0 or not math.isfinite(fps) or fps <= 0:
        raise RuntimeError("Video has invalid frame metadata")
    import numpy as np
    indices = sorted(set(np.linspace(0, count-1, args.samples, dtype=int).tolist()))
    models = {"desktop": YOLO(str(args.weights)), "square": YOLO(str(args.weights)),
              "coreml": YOLO(str(args.package), task="detect")}
    records = []
    for index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Cannot decode sample {index}")
        if index == indices[0]:
            cv2.imwrite(str(args.output / "source.png"), frame)
        record = {"frame_index": index, "time_s": index/fps, "detections": {}, "elapsed_ms": {}}
        for name, model in models.items():
            start = time.perf_counter()
            result = model.predict(frame, imgsz=args.size, conf=0.10, iou=0.70,
                                   classes=[0,32,38], max_det=100, device="cpu",
                                   rect=name == "desktop", verbose=False)[0]
            record["elapsed_ms"][name] = (time.perf_counter()-start)*1000
            record["detections"][name] = [
                {"box": box, "confidence": score, "class_id": int(cls)}
                for box, score, cls in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist(), result.boxes.cls.tolist())]
            if index == indices[0]:
                cv2.imwrite(str(args.output / f"{name}-preview.jpg"), result.plot())
        records.append(record)
        print(f"Compared frame {index} ({len(records)}/{len(indices)})", flush=True)
    capture.release()
    report = {"video": str(args.video.resolve()), "size": args.size, "sample_count": len(records),
              "note": "Detection agreement only, not ground-truth accuracy or iPhone performance. Timings exclude first sample warmup.",
              "comparisons": {}, "median_elapsed_ms": {}}
    for reference in ("desktop", "square"):
        result = {}
        for label, cls in (("player",0), ("ball",32), ("paddle",38)):
            comparisons = [agreement([d for d in r["detections"][reference] if d["class_id"] == cls],
                                     [d for d in r["detections"]["coreml"] if d["class_id"] == cls]) for r in records]
            totals = {key: sum(c[key] for c in comparisons) for key in ("reference_count", "candidate_count", "matched")}
            totals["reference_match_fraction"] = totals["matched"] / totals["reference_count"] if totals["reference_count"] else None
            matches = [m for c in comparisons for m in c["matches"]]
            totals["mean_iou"] = float(np.mean([m["iou"] for m in matches])) if matches else None
            totals["mean_confidence_delta"] = float(np.mean([m["confidence_delta"] for m in matches])) if matches else None
            result[label] = totals
        report["comparisons"][f"{reference}_vs_coreml"] = result
    for name in models:
        report["median_elapsed_ms"][name] = float(np.median([r["elapsed_ms"][name] for r in records[1:]])) if len(records)>1 else None
    (args.output / "frames.jsonl").write_text("".join(json.dumps(r)+"\n" for r in records))
    (args.output / "report.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
