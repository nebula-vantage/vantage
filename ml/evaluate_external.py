"""Score a detector and the ball tracker on the external evaluation clips.

    uv run python ml/fetch_eval_data.py --all          # once: download and convert the clips
    uv run python ml/evaluate_external.py --weights ml/models/pickleball-v1.pt
    uv run python ml/evaluate_external.py --weights yolo26n.pt --sport tennis --per-clip

Runs the model over each fetched clip once at a low raw threshold (detections are cached in
reports/external-eval/<weights>-<hash>-<imgsz>px-conf<confidence>/<source>/<clip>.jsonl), then
applies the model's ball operating point (from its model card, e.g. ml/models/pickleball-v1.json,
or --ball-confidence) and reports recall and precision exactly as evaluate_ball.py does, pooled
per source and per sport. To score the app instead, run vantage-analyze on
ml/external/eval/<source>/clips/<clip>.mp4, save the output under the same layout, and pass
--detections-dir.
"""
import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from eval_data import fetched_sources
from evaluate_ball import predictors
from labeling import BALL, ROOT, evaluate, load_detections, load_labels

COUNTS = ("labeled", "visible", "correct", "missed", "false_detection")


def add(totals, result):
    for key in COUNTS:
        totals[key] = totals.get(key, 0) + result[key]


def rates(totals):
    predictions = totals["correct"] + totals["false_detection"]
    totals["recall"] = totals["correct"] / totals["visible"] if totals["visible"] else None
    totals["precision"] = totals["correct"] / predictions if predictions else None
    return totals


def card_ball_confidence(weights):
    """Ball operating point from the model card next to the weights (ml/models/<name>.json)."""
    card = Path(weights).with_suffix(".json")
    if card.is_file():
        return json.loads(card.read_text()).get("operating_point", {}).get("ball_confidence")
    return None


def drop_weak_balls(frames, threshold):
    """Apply a ball operating point to detections made at a lower raw threshold, as the app's
    Detector does with the threshold in the model's metadata."""
    for frame in frames:
        frame["detections"] = [d for d in frame["detections"]
                               if d["classID"] != BALL or d["confidence"] >= threshold]
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", type=Path, default=ROOT / "ml" / "models" / "pickleball-v1.pt")
    parser.add_argument("--detections-dir", type=Path,
                        help="score detections made elsewhere (<dir>/<source>/<clip>.jsonl) instead of running --weights")
    parser.add_argument("--source", action="append", help="only these sources (repeatable)")
    parser.add_argument("--sport", choices=("tennis", "badminton", "pickleball"))
    parser.add_argument("--keyframes-only", action="store_true",
                        help="ignore labels a source interpolated between hand-placed keyframes")
    parser.add_argument("--radius-diagonals", type=float, default=0.01)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--confidence", type=float, default=0.10,
                        help="raw detection threshold for all classes (default 0.10, as predict_video.py)")
    parser.add_argument("--ball-confidence", type=float,
                        help="ball operating point applied when scoring (default: the model card's, else none)")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--per-clip", action="store_true", help="also print every clip")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()

    fetched = fetched_sources()
    missing = sorted(set(args.source or ()) - set(fetched))
    if missing:
        raise SystemExit(f"Not fetched (or misspelled): {', '.join(missing)}; see ml/fetch_eval_data.py --list")
    sources = {name: spec for name, spec in fetched.items()
               if (not args.source or name in args.source) and (not args.sport or spec["sport"] == args.sport)}
    if not sources:
        raise SystemExit("No matching fetched sources; run ml/fetch_eval_data.py first (see --list).")

    model = None
    if args.detections_dir:
        detections_dir, ball_confidence = args.detections_dir, args.ball_confidence
        described = f"detections {args.detections_dir}"
    else:
        weights = args.weights
        if weights.is_dir():
            raise SystemExit(f"{weights}: pass a .pt checkpoint; score Core ML packages with vantage-analyze "
                             "and --detections-dir")
        if not weights.exists():  # e.g. yolo26n.pt, which Ultralytics downloads on first use
            model = load(weights)
            weights = Path(model.ckpt_path)
        digest = hashlib.sha256(weights.read_bytes()).hexdigest()[:8]
        detections_dir = (ROOT / "reports" / "external-eval"
                          / f"{weights.stem}-{digest}-{args.imgsz}px-conf{args.confidence:g}")
        ball_confidence = args.ball_confidence if args.ball_confidence is not None else card_ball_confidence(weights)
        if ball_confidence is not None and ball_confidence < args.confidence:
            origin = "--ball-confidence" if args.ball_confidence is not None else f"{weights.stem}.json model card"
            raise SystemExit(f"ball threshold {ball_confidence} ({origin}) is below --confidence {args.confidence}")
        described = f"model {weights.name} ({digest}), {args.imgsz} px, detection threshold {args.confidence:g}"
    described += f", ball threshold {ball_confidence:g}" if ball_confidence is not None else ""

    groups = {}  # (level, name) -> {predictor: totals}
    skipped = []
    for name, spec in sources.items():
        for clip in spec["clips"]:
            detections_path = detections_dir / name / f"{clip['clip']}.jsonl"
            if not detections_path.exists():
                if args.detections_dir:
                    raise SystemExit(f"Missing {detections_path}")
                model = model or load(args.weights)
                detect(model, ROOT / clip["video"], detections_path, clip["frames"], args)
            frames = load_detections(detections_path)
            if len(frames) != clip["frames"]:
                if not args.detections_dir:
                    raise SystemExit(f"{detections_path} has {len(frames)} frames but the clip decodes "
                                     f"{clip['frames']}; delete it to detect again")
                skipped.append(f"{name}/{clip['clip']} ({len(frames)} of {clip['frames']} frames)")
                continue
            if ball_confidence is not None:
                drop_weak_balls(frames, ball_confidence)
            labels = load_labels(ROOT / clip["labels"])
            if args.keyframes_only:
                labels = {k: v for k, v in labels.items() if not v.get("interpolated")}
            radius = args.radius_diagonals * math.hypot(frames[0]["width"], frames[0]["height"])
            for predictor, predict in predictors().items():
                result = evaluate(predict(frames), labels, radius)
                for key in (("clip", f"{name}/{clip['clip']}"), ("source", name), ("sport", spec["sport"]),
                            ("all", "all")):
                    add(groups.setdefault(key, {}).setdefault(predictor, {}), result)
    for by_predictor in groups.values():
        for totals in by_predictor.values():
            rates(totals)
    if skipped:
        print(f"Skipped {len(skipped)} clips whose detections do not cover every frame (indices would not "
              f"line up): {', '.join(skipped)}", file=sys.stderr)
    if not groups:
        raise SystemExit("No clip could be scored.")

    if args.json:
        print(json.dumps({"setup": described, "skipped": skipped,
                          "results": {f"{level}:{name}": v for (level, name), v in groups.items()}}, indent=1))
        return
    pct = lambda v: "   -  " if v is None else f"{v:6.1%}"
    levels = ("clip", "source", "sport", "all") if args.per_clip else ("source", "sport", "all")
    width = max(len(name) for level, name in groups if level in levels)
    print(f"{described}; match radius {args.radius_diagonals:.1%} of diagonal"
          f"{'; keyframes only' if args.keyframes_only else ''}\n")
    print(f"{'':{width}s} {'labeled':>7s} {'visible':>7s}   {'raw best':^18s}   {'tracked':^18s}")
    print(f"{'':{width}s} {'':7s} {'':7s}   {'recall':>8s} {'precision':>9s}   {'recall':>8s} {'precision':>9s}")
    for level in levels:
        print(f"-- {level}")
        for (row_level, name), by_predictor in groups.items():
            if row_level != level:
                continue
            raw, tracked = by_predictor["raw best"], by_predictor["tracked"]
            print(f"{name:{width}s} {raw['labeled']:7d} {raw['visible']:7d}   {pct(raw['recall']):>8s} "
                  f"{pct(raw['precision']):>9s}   {pct(tracked['recall']):>8s} {pct(tracked['precision']):>9s}")


def load(weights):
    # Ultralytics logs to stdout (first-run settings notice, weight downloads); keep stdout for results.
    with contextlib.redirect_stdout(sys.stderr):
        from predict_video import load_model
        return load_model(weights)


def detect(model, video, output, expected_frames, args):
    """Run the model over a clip into output, keeping it only if every frame was decoded."""
    from predict_video import predict_video
    print(f"detecting {output.parent.name}/{output.stem}", file=sys.stderr)
    partial = output.with_name(f".{output.stem}.{os.getpid()}.part")
    with contextlib.redirect_stdout(sys.stderr):
        count = predict_video(model, video, partial, imgsz=args.imgsz, confidence=args.confidence, device=args.device)
    if count != expected_frames:
        partial.unlink()
        raise SystemExit(f"{video} decoded {count} frames, expected {expected_frames}")
    partial.replace(output)


if __name__ == "__main__":
    main()
