"""Synthetic runs seen through a known camera, for checking the 3-D replay against truth."""

import json

import numpy as np

WIDTH, HEIGHT, FOCAL = 1920, 1080, 1400.0
CAMERA = np.array([3.05, -10.0, 4.0])
GRAVITY = np.array([0.0, 0.0, -9.81])


def projection(center=CAMERA, target=(3.05, 6.7, 0.0), focal=FOCAL):
    forward = np.asarray(target, float) - center
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0, 0, 1])
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.array([right, down, forward])
    k = np.array([[focal, 0, WIDTH / 2], [0, focal, HEIGHT / 2], [0, 0, 1]])
    return k @ np.column_stack([rotation, -rotation @ center])


def pixel(p, point):
    h = p @ np.array([*point, 1.0])
    return [float(h[0] / h[2]), float(h[1] / h[2])]


def corners(p):
    return [pixel(p, c) for c in ((0, 0, 0), (6.1, 0, 0), (6.1, 13.41, 0), (0, 13.41, 0))]


def flight(p0, v0, t):
    return np.asarray(p0, float) + np.asarray(v0, float) * t + 0.5 * GRAVITY * t * t


def player_box(p, x, y, height=1.75, half_width=22):
    foot = pixel(p, (x, y, 0))
    head = pixel(p, (x, y, height))
    return [foot[0] - half_width, head[1], foot[0] + half_width, foot[1]]


def write_run(directory, *, fps, frames, players=None, ball=None, events=(), p=None):
    """`players(t)` returns [(track_id, x, y)]; `ball(t)` returns a 3-D point or None."""
    p = projection() if p is None else p
    directory.mkdir(parents=True, exist_ok=True)
    stats = {
        "schema_version": 2,
        "video": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": fps,
            "frame_count": frames,
            "duration_s": frames / fps,
        },
        "rallies": [{"id": 1, "start_s": 0.0, "end_s": frames / fps, "crossing_times_s": [0.5]}],
        "crossing_events": [{"frame_index": int(0.5 * fps), "time_s": 0.5}],
    }
    (directory / "stats.json").write_text(json.dumps(stats))
    (directory / "calibration.json").write_text(
        json.dumps({"width": WIDTH, "height": HEIGHT, "corners": corners(p)})
    )
    rows = []
    for index in range(frames):
        t = index / fps
        row = {"index": index, "time_s": t, "players": [], "ball": None, "paddles": []}
        for track_id, x, y in players(t) if players else ():
            box = player_box(p, x, y)
            row["players"].append(
                {"box": box, "confidence": 0.9, "track_id": track_id, "class_id": 0}
            )
        point = ball(t) if ball else None
        if point is not None:
            u, v = pixel(p, point)
            row["ball"] = {
                "box": [u - 5, v - 5, u + 5, v + 5],
                "confidence": 0.8,
                "track_id": 1,
                "class_id": 32,
            }
        rows.append(json.dumps(row))
    (directory / "tracks.jsonl").write_text("\n".join(rows) + "\n")
    (directory / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    return p


def doubles(t):
    """Four players drifting slowly in their usual spots, plus one spectator off court."""
    sway = 0.3 * np.sin(t)
    return [
        (1, 1.5 + sway, 3.8),
        (2, 4.6 - sway, 4.0),
        (3, 4.5, 9.6 + sway),
        (4, 1.6, 9.4 - sway),
        (99, -4.5, 6.0),
    ]
