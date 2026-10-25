"""Score ball detection/tracking against hand labels.

    uv run python ml/evaluate_ball.py --labels ml/labels/topcorner60fps.json \
        --detections reports/swift-detections/topcorner60fps.jsonl

Compares, on the labeled frames only:
  raw best       highest-confidence raw candidate (the detector alone)
  tracked        the app/desktop BallTracker (current settings)
  tracked, no static filter   same tracker with static-clutter suppression disabled
Recall = correct / frames with a visible ball. Precision = correct / frames with a
prediction. A prediction is correct within --radius-diagonals of the labeled center.
Pass several --labels/--detections pairs (same order) to pool clips.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path

from labeling import (CONFIG, best_raw_balls, evaluate, label_centers, load_detections, load_labels,
                      tracked_balls)


def predictors():
    no_static = deepcopy(CONFIG)
    no_static["ball_tracker"]["static_min_observed_s"] = math.inf
    return {"raw best": best_raw_balls,
            "tracked": tracked_balls,
            "tracked, no static filter": lambda frames: tracked_balls(frames, no_static)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", type=Path, action="append", required=True)
    parser.add_argument("--detections", type=Path, action="append", required=True)
    parser.add_argument("--radius-diagonals", type=float, default=0.01,
                        help="correct-match distance as a fraction of the frame diagonal (default 0.01)")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    parser.add_argument("--export-centers", type=Path,
                        help="also write {frame: [x, y] | null} for crop_experiment.py --labels (single clip)")
    args = parser.parse_args()
    if len(args.labels) != len(args.detections):
        parser.error("pass one --detections per --labels")

    pooled = {}
    for labels_path, detections_path in zip(args.labels, args.detections):
        labels = load_labels(labels_path)
        frames = load_detections(detections_path)
        radius = args.radius_diagonals * math.hypot(frames[0]["width"], frames[0]["height"])
        for name, predict in predictors().items():
            result = evaluate(predict(frames), labels, radius)
            totals = pooled.setdefault(name, dict.fromkeys(("labeled", "visible", "correct", "missed",
                                                            "false_detection"), 0))
            for key in totals:
                totals[key] += result[key]
        if args.export_centers:
            args.export_centers.write_text(json.dumps(label_centers(labels), indent=1) + "\n")

    for totals in pooled.values():
        predictions = totals["correct"] + totals["false_detection"]
        totals["recall"] = totals["correct"] / totals["visible"] if totals["visible"] else None
        totals["precision"] = totals["correct"] / predictions if predictions else None
    if args.json:
        print(json.dumps(pooled, indent=2))
        return
    pct = lambda v: "   -  " if v is None else f"{v:6.1%}"
    any_totals = next(iter(pooled.values()))
    print(f"{any_totals['labeled']} labeled frames, {any_totals['visible']} with a visible ball "
          f"(match radius {args.radius_diagonals:.1%} of diagonal)\n")
    print(f"{'predictor':28s} {'recall':>7s} {'precision':>9s} {'correct':>8s} {'missed':>7s} {'false':>6s}")
    for name, t in pooled.items():
        print(f"{name:28s} {pct(t['recall']):>7s} {pct(t['precision']):>9s} {t['correct']:8d} "
              f"{t['missed']:7d} {t['false_detection']:6d}")


if __name__ == "__main__":
    main()
