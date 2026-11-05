"""A tiny synthetic saved run for AI-coach tests: video, calibration, tracks, and stats.

Timeline (fractions of the duration): rally 0.125–0.875 with net crossings at 0.25,
0.5 and 0.75; a bounce candidate at 0.375. The near-right player waits in the
transition zone (4.2 m from the net) and reaches the kitchen at 0.625. Both far
players stay at the kitchen. A spectator stands beside the far court, off the court.
"""

import json
from pathlib import Path

import cv2
import numpy as np
from vantage.coaching import validate_stats
from vantage.config import CONFIG
from vantage.court import compute_homography, project, save_calibration

WIDTH, HEIGHT = 320, 180
# Near-left, near-right, far-right, far-left pixel corners.
CORNERS = [[60, 165], [260, 165], [205, 70], [115, 70]]
NET_Y = CONFIG["court"]["length_m"] / 2
ARRIVAL_FRACTION = 0.625
SPECTATOR = (-2.6, 11.0)


def homography():
    return compute_homography(CORNERS, WIDTH, HEIGHT, CONFIG)


def people(time_s, duration_s):
    """(name, court x, court y, confidence) for everyone visible at a time."""
    near_depth = 4.2 if time_s < ARRIVAL_FRACTION * duration_s else 1.8
    return [
        ("near-left", 1.5, NET_Y - 1.5, 0.90),
        ("near-right", 4.5, NET_Y - near_depth, 0.85),
        ("far-left", 1.5, NET_Y + 1.2, 0.80),
        ("far-right", 4.5, NET_Y + 1.6, 0.75),
        ("spectator", *SPECTATOR, 0.95),
    ]


def person_box(x_m, y_m, inverse):
    """A standing-person box whose bottom centre is the court point (x_m, y_m)."""
    foot = project((x_m, y_m), inverse)
    scale = abs(project((x_m + 1, y_m), inverse)[0] - foot[0])  # pixels per metre here
    height, width = 1.75 * scale, 0.55 * scale
    return [foot[0] - width / 2, foot[1] - height, foot[0] + width / 2, foot[1]]


def make_stats(duration_s, fps, rallies):
    frames = round(duration_s * fps)

    def at(fraction):
        index = round(fraction * frames)
        return index, index / fps

    crossings = [at(fraction) for fraction in (0.25, 0.5, 0.75)] if rallies else []
    bounce_index, bounce_time = at(0.375)
    rally_list = (
        [
            {
                "id": 1,
                "start_s": at(0.125)[1],
                "end_s": at(0.875)[1],
                "crossing_times_s": [t for _, t in crossings],
                "shots": len(crossings),
                "duration_s": at(0.875)[1] - at(0.125)[1],
                "ball_observation_coverage": 0.6,
                "quality_flags": ["heuristic_rally"],
            }
        ]
        if rallies
        else []
    )
    stats = {
        "schema_version": 2,
        "session_name": "Fixture game",
        "video": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": float(fps),
            "frame_count": frames,
            "duration_s": frames / fps,
        },
        "rally_count": len(rally_list),
        "shot_count": len(crossings),
        "crossing_events": [{"frame_index": i, "time_s": t} for i, t in crossings],
        "shots_per_rally": [r["shots"] for r in rally_list],
        "longest_rally": len(crossings),
        "avg_ball_speed_kmh": 31.5,
        "in_out_calls": [
            {
                "frame_index": bounce_index,
                "time_s": bounce_time,
                "pixel": [160.0, 90.0],
                "court": [3.0, 10.0],
                "call": "IN",
                "fit_improvement": 0.9,
                "quality_flags": ["heuristic_bounce"],
            }
        ],
        "bounce_candidate_count": 1,
        "rallies": rally_list,
        "tracking_summary": {
            "player_detection_coverage": 1.0,
            "frames_with_players": frames,
            "max_simultaneous_player_detections": 5,
            "player_track_count": 5,
            "player_tracks": [],
            "ball_track_count": 1,
            "longest_contiguous_ball_observation_s": 1.0,
        },
        "quality": {
            "status": "heuristic",
            "ball_detection_coverage": 0.6,
            "observed_frames": round(frames * 0.6),
            "warnings": ["Bounce calls and net-crossing shot counts are heuristic estimates."],
        },
        "input": "/private/never/used.mp4",
    }
    validate_stats(stats)
    return stats


def make_run(directory: Path, *, rallies=True, with_video=True, duration_s=4.0, fps=10) -> Path:
    """Write a complete saved run into ``directory`` and return it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    h = homography()
    inverse = np.linalg.inv(h)
    save_calibration(directory, h, CORNERS, WIDTH, HEIGHT)
    stats = make_stats(duration_s, fps, rallies)
    (directory / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    frames = stats["video"]["frame_count"]
    records = []
    for index in range(frames):
        time_s = index / fps
        players = [
            {
                "box": person_box(x, y, inverse),
                "confidence": confidence,
                "track_id": number + 1,
                "class_id": 0,
            }
            for number, (_, x, y, confidence) in enumerate(people(time_s, duration_s))
        ]
        records.append(
            {"index": index, "time_s": time_s, "players": players, "ball": None, "paddles": []}
        )
    with (directory / "tracks.jsonl").open("w") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")
    if with_video:
        write_video(directory / "source.mp4", records, fps, inverse)
    return directory


def write_video(path, records, fps, inverse):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open an MP4 writer for the coach fixture.")
    court = np.int32(CORNERS)
    net = [tuple(round(v) for v in project((x, NET_Y), inverse)) for x in (-0.3, 6.4)]
    try:
        for record in records:
            image = np.full((HEIGHT, WIDTH, 3), (60, 120, 50), np.uint8)
            cv2.fillPoly(image, [court], (130, 80, 40))
            cv2.polylines(image, [court], True, (255, 255, 255), 1)
            cv2.line(image, net[0], net[1], (230, 230, 230), 2)
            for number, player in enumerate(record["players"]):
                x1, y1, x2, y2 = (round(v) for v in player["box"])
                color = (
                    (200, 200, 200)
                    if number == 4
                    else (40, 200, 240)
                    if number < 2
                    else (240, 120, 200)
                )
                cv2.rectangle(image, (x1, y1), (x2, y2), color, -1)
            writer.write(image)
    finally:
        writer.release()
