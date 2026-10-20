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
from tracking_cache import file_digest, load_cached_tracks, source_signature, tracking_settings


def run_pipeline(input_path, output_dir, recalibrate=False, *, config=None, detector_factory=None,
                 reanalyze=False, stream_output=None):
    """Process a video; detector_factory is an injection point for offline tests."""
    config = CONFIG if config is None else config
    input_path, output_dir = Path(input_path), Path(output_dir)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}.\n"
                                "Place your video there or pass --input /path/to/video.mp4.")
    if input_path.resolve() in {(output_dir / name).resolve()
                               for name in ("annotated.mp4", "tracks.jsonl", "stats.json", "events.jsonl", "landing_heatmap.png")}:
        raise ValueError("Input cannot be a generated output path. Choose a different --output-dir.")
    try:
        import cv2
        from ball_physics import build_trajectory, detect_bounces
        from court import calibrate
        from detector import Detector
        from motion_stream import MotionStream
        from heatmap import render_landing_heatmap
        from stats import aggregate, event_records
        from visualize import encoded_size, render_video
    except ImportError as exc:
        raise RuntimeError("Missing dependency. Run: python -m pip install -r requirements.txt") from exc
    detector_factory = Detector if detector_factory is None else detector_factory
    source = source_signature(input_path)
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
        cached = load_cached_tracks(output_dir, source, config, fps, width, height) if reanalyze else None
        output_dir.mkdir(parents=True, exist_ok=True)
        # Check writable output before asking the user to calibrate.
        with tempfile.TemporaryDirectory(prefix=".processing-", dir=output_dir) as temp:
            staging = Path(temp)
            homography = calibrate(first, output_dir, config, recalibrate)
            motion = MotionStream(homography, width, height, fps, config)

            def emit(message):
                if stream_output is not None:
                    stream_output.write(json.dumps(message, allow_nan=False) + "\n")
                    stream_output.flush()

            emit(motion.metadata())
            records = cached if cached is not None else []
            if cached is None:
                with contextlib.redirect_stdout(sys.stderr):
                    detector = detector_factory(config, width, height, fps, staging)
            else:
                print(f"Reusing {len(records)} validated tracking records; skipping inference.", file=sys.stderr)
            with (staging / "tracks.jsonl").open("w") as stream:
                def write_record(record):
                    stream.write(json.dumps(record.to_dict(), allow_nan=False) + "\n")
                    emit(motion.update(record))

                if cached is not None:
                    for record in records:
                        write_record(record)
                else:
                    frame = first
                    while True:
                        if frame.shape[:2] != (height, width):
                            raise RuntimeError("Input resolution changes between frames; export a fixed-resolution video.")
                        index = len(records)
                        record = detector.process(frame, index, index / fps)
                        records.append(record)
                        write_record(record)
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
            stats["motion"] = motion.summary()
            stats["input"] = str(input_path)
            stats["model"] = config["model"]
            stats["source"] = source
            stats["tracking"] = tracking_settings(config)
            stats["tracks_sha256"] = file_digest(staging / "tracks.jsonl")
            stats["analysis_config"] = {key: config[key] for key in ("court", "trajectory", "bounce", "stats", "motion", "heatmap")}
            stats["landing_heatmap"] = render_landing_heatmap(
                staging / "landing_heatmap.png", bounces, stats["quality"]["ball_detection_coverage"], config)
            stats["video"]["encoded_width"], stats["video"]["encoded_height"] = encoded_size(width, height)
            stats["video"]["audio_preserved"] = False
            if encoded_size(width, height) != (width, height):
                stats["quality"]["warnings"].append("One black edge pixel was added to odd dimensions for MPEG-4 encoding.")
            render_video(input_path, staging / "annotated.mp4", records, samples, bounces,
                         rallies, speeds, width, height, fps, config, progress)
            if source_signature(input_path) != source:
                raise RuntimeError("Input changed during processing; run again.")
            (staging / "stats.json").write_text(json.dumps(stats, indent=2, allow_nan=False) + "\n")
            with (staging / "events.jsonl").open("w") as stream:
                for event in event_records(stats):
                    stream.write(json.dumps(event, allow_nan=False) + "\n")
            # All artifacts are complete and video decode-verified before publication.
            for name in ("tracks.jsonl", "annotated.mp4", "stats.json", "events.jsonl", "landing_heatmap.png"):
                (staging / name).replace(output_dir / name)
            for warning in stats["quality"]["warnings"]:
                print(f"Note: {warning}", file=sys.stderr)
            print(f"Saved {output_dir / 'annotated.mp4'} and {output_dir / 'stats.json'}", file=sys.stderr)
            print(f"Saved {output_dir / 'landing_heatmap.png'}", file=sys.stderr)
            return stats
    finally:
        capture.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline pickleball analysis with estimated stats.")
    parser.add_argument("--input", type=Path, default=Path("input/sample.mp4"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--recalibrate", action="store_true", help="Select court corners again.")
    parser.add_argument("--reanalyze", action="store_true", help="Reuse validated tracks to update statistics and overlays without inference.")
    parser.add_argument("--stream", action="store_true", help="Flush one JSON line per frame with coordinates and motion estimates to stdout.")
    args = parser.parse_args(argv)
    destination = sys.stdout if args.stream else None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            stats = run_pipeline(args.input, args.output_dir, args.recalibrate,
                                 reanalyze=args.reanalyze, stream_output=destination)
    except KeyboardInterrupt:
        print("Processing cancelled; completed outputs from earlier runs are preserved.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.stream:
        print(json.dumps({"type": "summary", "stats": stats}, allow_nan=False), flush=True)
    else:
        print(json.dumps(stats, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
