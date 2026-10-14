"""Generate ball-tracker parity fixtures for the Swift port (VantageKit tests).

Feeds the raw ball candidates from an on-device detections.jsonl (written by the iPhone
app or `vantage-analyze`) through the desktop BallTracker and build_trajectory, and
records the expected per-frame selection. The Swift tests replay the same candidates and
must reproduce every selection exactly.

    .venv/bin/python mobile/model/make_tracker_fixtures.py \
        mobile/reports/swift-detections/sideview.jsonl \
        mobile/ios/VantageKit/Tests/VantageKitTests/Fixtures/tracker-sideview.json
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ball_physics import build_trajectory  # noqa: E402
from ball_tracker import BallTracker  # noqa: E402
from config import CONFIG  # noqa: E402
from records import Detection, FrameRecord  # noqa: E402

BALL = CONFIG["model"]["classes"]["ball"]


def swift_config():
    """Python settings under the Swift BallTrackerConfig property names."""
    d, b, t = CONFIG["detection"], CONFIG["ball_tracker"], CONFIG["trajectory"]
    return {
        "ballConfidence": d["ball_confidence"],
        "maxMotionDiagonalsPerSecond": d["max_motion_diagonals_s"],
        "motionSlackDiagonals": d["motion_slack_diagonals"],
        "candidateResetSeconds": d["candidate_reset_s"],
        "confirmationWindowSeconds": b["confirmation_window_s"],
        "minConfirmationMotionDiagonals": b["min_confirmation_motion_diagonals"],
        "predictionSlackDiagonals": b["prediction_slack_diagonals"],
        "maxAccelerationDiagonalsPerSecond2": b["max_acceleration_diagonals_s2"],
        "velocitySmoothingSeconds": b["velocity_smoothing_s"],
        "confidenceWeight": b["confidence_weight"],
        "turnWindowSeconds": b["turn_window_s"],
        "stationaryTimeoutSeconds": b["stationary_timeout_s"],
        "stationaryRadiusDiagonals": b["stationary_radius_diagonals"],
        "interpolateGapSeconds": t["interpolate_gap_s"],
    }


def build_fixture(frames, name):
    width, height = frames[0]["width"], frames[0]["height"]
    tracker = BallTracker(CONFIG, width, height)
    records, rows = [], []
    for index, frame in enumerate(frames):
        candidates = [d for d in frame["detections"] if d["classID"] == BALL]
        selected = tracker.select([Detection(tuple(d["box"]), d["confidence"], None, BALL)
                                   for d in candidates], frame["timeSeconds"])
        records.append(FrameRecord(index, frame["timeSeconds"], ball=selected))
        rows.append({"t": frame["timeSeconds"],
                     "candidates": [[*d["box"], d["confidence"]] for d in candidates],
                     "ball": None if selected is None else [*selected.box, selected.confidence, selected.track_id]})
    # Identity homography: only the observed/interpolated decision and track ID are compared.
    samples = build_trajectory(records, np.eye(3), width, height, CONFIG)
    for row, sample in zip(rows, samples):
        row["interpolated_track"] = (sample.track_id if sample is not None and sample.source == "interpolated"
                                     else None)
    return {"name": name, "width": width, "height": height, "config": swift_config(),
            "summary": {"frames": len(rows), "tracked": sum(r["ball"] is not None for r in rows),
                        "interpolated": sum(r["interpolated_track"] is not None for r in rows),
                        "tracks": len({r["ball"][-1] for r in rows if r["ball"]})},
            "frames": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("detections", type=Path, help="detections.jsonl from the app or vantage-analyze")
    parser.add_argument("output", type=Path, help="fixture JSON path")
    args = parser.parse_args()
    frames = [json.loads(line) for line in args.detections.read_text().splitlines() if line.strip()]
    frames.sort(key=lambda f: f["timeSeconds"])
    fixture = build_fixture(frames, args.detections.stem)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture, separators=(",", ":")) + "\n")
    print(json.dumps(fixture["summary"]))


if __name__ == "__main__":
    main()
