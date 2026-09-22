"""CLI for a single, offline pickleball video analysis run."""
import argparse
import contextlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time

from config import CONFIG


def run_pipeline(input_path, output_dir, recalibrate=False, *, config=None, detector_factory=None):
    """Process a video; detector_factory is an injection point for offline tests."""
    config = CONFIG if config is None else config
    input_path, output_dir = Path(input_path), Path(output_dir)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}.\n"
                                "Place your video there or pass --input /path/to/video.mp4.")
    if input_path.resolve() in {(output_dir / name).resolve()
                               for name in ("annotated.mp4", "tracks.jsonl", "stats.json")}:
        raise ValueError("Input cannot be a generated output path. Choose a different --output-dir.")
    try:
        import cv2
        from ball_physics import build_trajectory, detect_bounces
        from court import calibrate
        from detector import Detector
        from stats import aggregate
        from visualize import encoded_size, render_video
    except ImportError as exc:
        raise RuntimeError("Missing dependency. Run: python -m pip install -r requirements.txt") from exc
    detector_factory = Detector if detector_factory is None else detector_factory
    capture = cv2.VideoCapture(str(input_path))
    last_progress = 0.0

    def progress(stage, count, total):
        nonlocal last_progress
        now = time.monotonic()
        if now - last_progress >= config["runtime"]["progress_every_s"]:
            print(f"{stage}: {count}/{total or '?'} frames", file=sys.stderr)
            last_progress = now

    try:
        if not capture.isOpened():
            raise RuntimeError(f"Cannot decode video: {input_path}. Try exporting an H.264 MP4.")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise RuntimeError("Video reports an invalid frame rate. Re-export with a fixed, positive FPS.")
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        total = max(0, round(frame_count)) if math.isfinite(frame_count) else 0
        ok, first = capture.read()
        if not ok:
            raise RuntimeError("Video contains no decodable frames.")
        height, width = first.shape[:2]
        output_dir.mkdir(parents=True, exist_ok=True)
        # Check writable output before asking the user to calibrate.
        with tempfile.TemporaryDirectory(prefix=".processing-", dir=output_dir) as temp:
            staging = Path(temp)
            homography = calibrate(first, output_dir, config, recalibrate)
            with contextlib.redirect_stdout(sys.stderr):
                detector = detector_factory(config, width, height, fps, staging)
            records = []
            frame = first
            with (staging / "tracks.jsonl").open("w") as stream:
                while True:
                    if frame.shape[:2] != (height, width):
                        raise RuntimeError("Input resolution changes between frames; export a fixed-resolution video.")
                    index = len(records)
                    record = detector.process(frame, index, index / fps)
                    records.append(record)
                    stream.write(json.dumps(record.to_dict(), allow_nan=False) + "\n")
                    progress("Detecting", len(records), total)
                    ok, frame = capture.read()
                    if not ok:
                        break
            capture.release()
            if total and len(records) + config["runtime"]["frame_count_tolerance"] < total:
                raise RuntimeError(f"Video stopped decoding at {len(records)} of {total} advertised frames. "
                                   "The input may be truncated; re-export it and retry.")
            print(f"Analyzing {len(records)} frames...", file=sys.stderr)
            samples = build_trajectory(records, homography, width, height, config)
            bounces = detect_bounces(records, samples, homography, width, height, config)
            stats, rallies, speeds = aggregate(records, samples, bounces, fps, width, height, config)
            stats["input"] = str(input_path)
            stats["model"] = config["model"]
            stats["video"]["encoded_width"], stats["video"]["encoded_height"] = encoded_size(width, height)
            stats["video"]["audio_preserved"] = False
            if encoded_size(width, height) != (width, height):
                stats["quality"]["warnings"].append("One black edge pixel was added to odd dimensions for MPEG-4 encoding.")
            render_video(input_path, staging / "annotated.mp4", records, samples, bounces,
                         rallies, speeds, width, height, fps, config, progress)
            (staging / "stats.json").write_text(json.dumps(stats, indent=2, allow_nan=False) + "\n")
            # All artifacts are complete and video decode-verified before publication.
            for name in ("tracks.jsonl", "annotated.mp4", "stats.json"):
                (staging / name).replace(output_dir / name)
            for warning in stats["quality"]["warnings"]:
                print(f"Note: {warning}", file=sys.stderr)
            print(f"Saved {output_dir / 'annotated.mp4'} and {output_dir / 'stats.json'}", file=sys.stderr)
            return stats
    finally:
        capture.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline pickleball analysis with estimated stats.")
    parser.add_argument("--input", type=Path, default=Path("input/sample.mp4"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--recalibrate", action="store_true", help="Select court corners again.")
    args = parser.parse_args(argv)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            stats = run_pipeline(args.input, args.output_dir, args.recalibrate)
    except KeyboardInterrupt:
        print("Processing cancelled; completed outputs from earlier runs are preserved.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(stats, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
