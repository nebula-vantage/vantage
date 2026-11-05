"""Deterministic evidence for the AI video coach: positions, key moments, and stills.

Everything is derived from one saved run directory and written only inside
``<run_dir>/.coach/``. Player positions are foot points of detections projected onto
the court plane: estimates that can include bystanders, never identified players.
Nothing here calls a model; the same run always yields the same evidence.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
import threading
from bisect import bisect_left
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import numpy as np

from vantage.coaching import validate_stats
from vantage.config import CONFIG

EVIDENCE_VERSION = 1
COACH_DIR = ".coach"
FRAMES_DIR = "frames"
FRAME_NAME = re.compile(r"[a-z0-9-]{1,48}\.jpg")
VIDEO_NAMES = ("source.mp4", "prepared.mp4", "annotated.mp4")  # clean videos first

MAX_STATS_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_TRACK_FRAMES = 100_000
MAX_TRACK_BYTES = 1024**3
MAX_PLAYERS = 200  # detections considered per frame
MAX_MOMENTS = 20
SAMPLE_HZ = 10

COURT_MARGIN_X_M = 1.5  # beyond the sidelines
COURT_MARGIN_Y_M = 4.0  # beyond the baselines
# A player "at the kitchen line" has toes on it, but the box bottom is the rear heel plus
# detector padding: on real near-side footage that reads 0.5-0.8 m behind the line.
KITCHEN_SLACK_M = 0.9
BASELINE_DEPTH_M = 5.2
STAGGER_M = 2.5
SERVE_PHASE_S = 2.0  # one-up-one-back is normal while serving and returning
DEDUPE_S = 1.0
FLAG_SPACING_S = 3.0
SHOT_OFFSETS_S = (-0.3, -0.1, 0.1, 0.3)
CHAT_OFFSETS_S = (-0.6, -0.2, 0.2, 0.6)
MAX_CHAT_FRAMES = 60

# Crop: court bounding box widened on each side, then extended above (far players
# stand behind the far baseline) and below, as fractions of the box size.
CROP_SIDE, CROP_ABOVE, CROP_BELOW = 0.08, 0.30, 0.12
SINGLE_EDGE, TILE_EDGE, TILE_GAP = 1280, 760, 4
JPEG_QUALITY = 82

ZONES = ("kitchen", "transition", "baseline")
NO_VIDEO = "This game has no saved video for the coach to watch. Upload the video to analyze it."
CHAT_FRAME = re.compile(r"t-\d{6}\.jpg")
MOMENT_FRAME = re.compile(r"m\d{2}\.jpg")
_INDEX_PREFIX = re.compile(rb'\s*\{\s*"index"\s*:\s*(\d{1,12})\s*[,}]')


class EvidenceError(ValueError):
    """Actionable, browser-safe message."""


class _Player(NamedTuple):
    x: float  # metres from the left sideline (as seen from the camera)
    depth: float  # metres from the net
    zone: str
    box: tuple
    confidence: float


class _Sample(NamedTuple):
    time_s: float
    near: list
    far: list


class _Court(NamedTuple):
    width: float
    length: float
    net: float
    kitchen: float


def _court():
    width, length = CONFIG["court"]["width_m"], CONFIG["court"]["length_m"]
    return _Court(width, length, length / 2, CONFIG["heatmap"]["kitchen_depth_m"])


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _run_lock(run_dir: Path):
    """Serialize evidence builds per run (analysis worker and chat may both ask)."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(run_dir), threading.RLock())


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _clock(seconds):
    tenths = max(0, round(seconds * 10))
    minutes, rest = divmod(tenths, 600)
    return f"{minutes}:{rest // 10:02d}.{rest % 10}"


def _inside(run_dir: Path, path: Path):
    try:
        return path.is_file() and path.resolve().is_relative_to(run_dir)
    except (OSError, RuntimeError):
        return False


def _video(run_dir: Path):
    for name in VIDEO_NAMES:
        path = run_dir / name
        if _inside(run_dir, path):
            return path.resolve(), name
    return None


def find_video(run_dir: Path) -> tuple[Path, bool] | None:
    """(path, has_overlays) of the cleanest saved video inside the run directory."""
    found = _video(Path(run_dir).resolve())
    return (found[0], found[1] == "annotated.mp4") if found else None


def _stats_bytes(run_dir: Path):
    path = run_dir / "stats.json"
    if not _inside(run_dir, path):
        raise EvidenceError("This game's measurements are missing. Analyze the video again.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_STATS_BYTES + 1)
    if len(raw) > MAX_STATS_BYTES:
        raise EvidenceError("This game's measurements exceed the 2 MB limit.")
    return raw


def _read_stats(run_dir: Path):
    def reject(value):
        raise ValueError("JSON numbers must be finite.")

    try:
        raw = _stats_bytes(run_dir)
        return raw, validate_stats(json.loads(raw, parse_constant=reject))
    except EvidenceError:
        raise
    except (OSError, ValueError, RecursionError) as exc:
        raise EvidenceError(
            "This game's measurements couldn't be read. Analyze the video again."
        ) from exc


def _coach_dirs(run_dir: Path, *, create: bool):
    coach = run_dir / COACH_DIR
    frames = coach / FRAMES_DIR
    for path in (coach, frames):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise EvidenceError(
                "The coach's cache folder isn't usable. Remove this game's .coach folder and try again."
            )
        if create:
            path.mkdir(exist_ok=True)
    return coach, frames


def _write_atomic(directory: Path, name: str, data: bytes):
    handle, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=directory)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, directory / name)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _calibration(run_dir: Path, width: int, height: int):
    """(homography or None, corners or None); corners alone still allow cropping."""
    from vantage.court import compute_homography, load_calibration

    corners = None
    if _inside(run_dir, run_dir / "calibration.json"):
        try:
            meta = json.loads((run_dir / "calibration.json").read_text())
            if (meta["width"], meta["height"]) == (width, height):
                compute_homography(meta["corners"], width, height, CONFIG)
                corners = [(float(x), float(y)) for x, y in meta["corners"]]
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            corners = None
    homography = None
    if corners is not None and _inside(run_dir, run_dir / "homography.npy"):
        homography = load_calibration(run_dir, width, height, CONFIG)
    return homography, corners


# --- Player positions -------------------------------------------------------------


def _track_lines(path: Path):
    """Complete JSON lines within the frame and byte limits; oversized lines are skipped."""
    total = 0
    with path.open("rb") as stream:
        for _ in range(MAX_TRACK_FRAMES):
            line = stream.readline(MAX_LINE_BYTES + 1)
            total += len(line)
            if not line or total > MAX_TRACK_BYTES:
                return
            if len(line) > MAX_LINE_BYTES:
                while line and not line.endswith(b"\n") and total <= MAX_TRACK_BYTES:
                    line = stream.readline(MAX_LINE_BYTES + 1)
                    total += len(line)
                continue
            yield line


def _zone(depth, court):
    if depth <= court.kitchen + KITCHEN_SLACK_M:
        return "kitchen"
    return "baseline" if depth >= BASELINE_DEPTH_M else "transition"


def _locate(players, homography, court):
    """Per side, the two most confident on-court foot points, ordered left to right."""
    from vantage.court import project

    epsilon = CONFIG["court"]["projection_epsilon"]
    sides = ([], [])
    for item in players[:MAX_PLAYERS]:
        if not isinstance(item, dict):
            continue
        box, confidence = item.get("box"), item.get("confidence", 0.0)
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not all(map(_finite, box))
            or not _finite(confidence)
            or box[2] <= box[0]
            or box[3] <= box[1]
        ):
            continue
        x1, y1, x2, y2 = map(float, box)
        point = project(((x1 + x2) / 2, y2), homography, epsilon)
        if point is None:
            continue
        x, y = point
        if not (
            -COURT_MARGIN_X_M <= x <= court.width + COURT_MARGIN_X_M
            and -COURT_MARGIN_Y_M <= y <= court.length + COURT_MARGIN_Y_M
        ):
            continue
        depth = abs(y - court.net)
        sides[y >= court.net].append(
            _Player(x, depth, _zone(depth, court), (x1, y1, x2, y2), float(confidence))
        )
    return tuple(
        sorted(sorted(side, key=lambda p: -p.confidence)[:2], key=lambda p: p.x) for side in sides
    )


def _read_samples(path, homography, court, duration, *, stride=1, first=0, last=None, check=None):
    """On-court player samples from tracks.jsonl for every ``stride``-th frame in a range."""
    samples = []
    for count, line in enumerate(_track_lines(path)):
        if check is not None and count % 2000 == 0:
            check()
        prefix = _INDEX_PREFIX.match(line)
        if prefix:
            index = int(prefix[1])
            if last is not None and index > last:
                break  # tracks are written in frame order
            if index < first or (index - first) % stride:
                continue
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(record, dict):
            continue
        index, time_s, players = record.get("index"), record.get("time_s"), record.get("players")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < first
            or (last is not None and index > last)
            or (index - first) % stride
            or not _finite(time_s)
            or not 0 <= time_s <= duration + 1
            or not isinstance(players, list)
        ):
            continue
        near, far = _locate(players, homography, court)
        samples.append(_Sample(float(time_s), near, far))
    samples.sort(key=lambda sample: sample.time_s)
    return samples


def _nearest(samples, times, time_s, tolerance):
    if not samples:
        return None
    i = bisect_left(times, time_s)
    best = min(
        (j for j in (i - 1, i) if 0 <= j < len(samples)), key=lambda j: abs(times[j] - time_s)
    )
    return samples[best] if abs(times[best] - time_s) <= tolerance else None


def _share(count, total, digits=3):
    return round(count / total, digits) if total else None


def _mean(values, digits=2):
    return round(sum(values) / len(values), digits) if values else None


def _gap(pair):
    return abs(pair[0].depth - pair[1].depth)


def _zone_share(players):
    return (
        {zone: _share(sum(p.zone == zone for p in players), len(players)) for zone in ZONES}
        if players
        else None
    )


def _side_summary(samples, side):
    groups = [getattr(sample, side) for sample in samples]
    players = [p for group in groups for p in group]
    pairs = [group for group in groups if len(group) == 2]
    return {
        "samples": sum(bool(group) for group in groups),
        "avg_players": _mean([len(group) for group in groups]) or 0.0,
        "zone_share": _zone_share(players),
        "both_at_kitchen_share": _share(
            sum(all(p.zone == "kitchen" for p in pair) for pair in pairs), len(pairs)
        ),
        "staggered_share": _share(sum(_gap(pair) >= STAGGER_M for pair in pairs), len(pairs)),
        "avg_partner_spacing_m": _mean([abs(pair[0].x - pair[1].x) for pair in pairs]),
        "avg_depth_m": _mean([p.depth for p in players]),
    }


def _rally_side(samples, side, start_s):
    groups = [(sample.time_s, getattr(sample, side)) for sample in samples]
    players = [p for _, group in groups for p in group]
    counts = Counter(len(group) for _, group in groups if group)
    arrival = None
    if counts:
        # Expect the usual number of players on this side (two in doubles) so a missed
        # detection does not count as the whole team arriving.
        expected = max(counts, key=lambda n: (counts[n], n))
        arrival = next(
            (
                round(max(0.0, t - start_s), 2)
                for t, group in groups
                if len(group) >= expected and all(p.zone == "kitchen" for p in group)
            ),
            None,
        )
    return {
        "avg_depth_m": _mean([p.depth for p in players]),
        "kitchen_arrival_s": arrival,
        "zone_share": _zone_share(players),
    }


def _positioning(samples, rallies, reason):
    if reason:
        return {"available": False, "reason": reason, "sides": None, "rallies": []}
    per_rally = []
    for rally in rallies:
        inside = [s for s in samples if rally["start_s"] <= s.time_s <= rally["end_s"]]
        per_rally.append(
            {
                "rally_id": rally["id"],
                "start_s": round(rally["start_s"], 2),
                "end_s": round(rally["end_s"], 2),
                **{side: _rally_side(inside, side, rally["start_s"]) for side in ("near", "far")},
            }
        )
    return {
        "available": True,
        "reason": None,
        "sides": {side: _side_summary(samples, side) for side in ("near", "far")},
        "rallies": per_rally,
    }


def _positions(sample):
    if sample is None:
        return {"near": [], "far": []}
    return {
        side: [
            {"x_m": round(p.x, 2), "depth_m": round(p.depth, 2), "zone": p.zone}
            for p in getattr(sample, side)
        ]
        for side in ("near", "far")
    }


def _describe(side, players, court):
    name = side.title()
    if not players:
        return f"{name}: no player detected"
    if len(players) == 1:
        p = players[0]
        lateral = (
            "on the left side"
            if p.x < court.width / 3
            else "on the right side"
            if p.x > court.width * 2 / 3
            else "in the middle"
        )
        return f"{name}: 1 player {lateral}, {p.depth:.1f} m from the net ({p.zone})"
    left, right = players
    notes = []
    if left.zone == right.zone == "kitchen":
        notes.append("both at the kitchen line")
    elif _gap(players) >= STAGGER_M:
        notes.append(f"staggered {_gap(players):.1f} m")
    notes.append(f"{abs(right.x - left.x):.1f} m apart side to side")
    return (
        f"{name}: 2 players — left {left.depth:.1f} m from the net ({left.zone}), "
        f"right {right.depth:.1f} m ({right.zone}); {', '.join(notes)}"
    )


def _caption(identity, time_s, title, frame_times, sample, court):
    if len(frame_times) > 1:
        layout = (
            f"2×2 sequence {_clock(frame_times[0])}–{_clock(frame_times[-1])} "
            "(read left→right, top→bottom)"
        )
    else:
        layout = "single frame"
    parts = [f"Moment {identity}", _clock(time_s), title, layout]
    if sample is None:
        parts.append("Player positions unavailable")
    else:
        parts.extend(_describe(side, getattr(sample, side), court) for side in ("near", "far"))
    return " · ".join(parts)


# --- Moment selection ---------------------------------------------------------------


def _flag(sample):
    """(title, reason) when a side is staggered or exposed while the other is at the kitchen."""
    for side, other in (("near", "far"), ("far", "near")):
        mine, theirs = getattr(sample, side), getattr(sample, other)
        name = side.title()
        if len(mine) == 2 and _gap(mine) >= STAGGER_M:
            return (
                f"{name} side staggered",
                f"{name} partners are {_gap(mine):.1f} m apart in depth",
            )
        exposed = [p.depth for p in mine if p.zone == "transition"]
        if exposed and theirs and all(p.zone == "kitchen" for p in theirs):
            return (
                f"{name} player in the transition zone",
                f"{name} player {max(exposed):.1f} m from the net while the {other} side is at the kitchen",
            )
    return None


def _even(count, wanted):
    if wanted >= count:
        return list(range(count))
    return [int((i + 0.5) * count / wanted) for i in range(wanted)]


def _select_moments(stats, samples, positioned, last_s, max_moments):
    rallies = stats.get("rallies", [])
    crossings = [event["time_s"] for event in stats.get("crossing_events", [])]
    chosen = []

    def rally_at(t):
        return next((r["id"] for r in rallies if r["start_s"] <= t <= r["end_s"]), None)

    def moment(t, kind, title, reason, rally_id=None, layout="single"):
        t = round(min(max(t, 0.0), last_s), 2)
        return {
            "time_s": t,
            "kind": kind,
            "title": title,
            "reason": reason,
            "rally_id": rally_id if rally_id is not None else rally_at(t),
            "layout": layout,
        }

    def offer(candidate):
        if len(chosen) >= max_moments or any(
            abs(candidate["time_s"] - c["time_s"]) < DEDUPE_S for c in chosen
        ):
            return False
        chosen.append(candidate)
        return True

    def bucket(candidates, limit):
        taken = 0
        for candidate in candidates:
            if taken >= limit:
                break
            taken += offer(candidate)

    ranked = sorted(rallies, key=lambda r: (-r["shots"], r["start_s"]))
    bucket(
        [
            moment(
                min(r["start_s"] + 0.5, r["end_s"]),
                "rally_start",
                f"Start of rally {r['id']}",
                f"Rally {r['id']} starts ({r['shots']} estimated net crossings)",
                r["id"],
            )
            for r in ranked
        ],
        3,
    )

    # Shots: share four slots across rallies, spread through each rally; the rest are fallbacks.
    shot_times = {
        r["id"]: r.get("crossing_times_s")
        or [t for t in crossings if r["start_s"] <= t <= r["end_s"]]
        for r in ranked
    }
    quota, remaining = dict.fromkeys(shot_times, 0), 4
    while remaining and any(quota[i] < len(times) for i, times in shot_times.items()):
        for identity, times in shot_times.items():
            if remaining and quota[identity] < len(times):
                quota[identity] += 1
                remaining -= 1
    preferred, fallback = [], []
    for identity, times in shot_times.items():
        picked = set(_even(len(times), quota[identity]))
        for i, t in enumerate(times):
            (preferred if i in picked else fallback).append(
                moment(
                    t,
                    "shot",
                    f"Shot {i + 1} of rally {identity}",
                    "Net crossing detected",
                    identity,
                    "sequence",
                )
            )
    bucket(preferred + fallback, 4)

    # Positioning: persistent flags (≥3 samples), longest first, one moment per run.
    if positioned:
        in_play = [
            s
            for s in samples
            if not rallies
            or any(r["start_s"] + SERVE_PHASE_S <= s.time_s <= r["end_s"] for r in rallies)
        ]
        runs, current = [], None
        for sample in in_play:
            flag = _flag(sample)
            if (
                flag
                and current
                and flag[0] == current["flag"][0]
                and sample.time_s - current["samples"][-1].time_s <= 0.35
            ):
                current["samples"].append(sample)
                continue
            current = {"flag": flag, "samples": [sample]} if flag else None
            if current:
                runs.append(current)
        runs = sorted(
            (run for run in runs if len(run["samples"]) >= 3),
            key=lambda run: (-len(run["samples"]), run["samples"][0].time_s),
        )
        picked = 0
        for run in runs:
            if picked >= 3:
                break
            middle = (run["samples"][0].time_s + run["samples"][-1].time_s) / 2
            for sample in sorted(run["samples"], key=lambda s: abs(s.time_s - middle)):
                title, reason = _flag(sample)
                candidate = moment(sample.time_s, "positioning", title, reason)
                if any(
                    c["kind"] == "positioning"
                    and abs(c["time_s"] - candidate["time_s"]) < FLAG_SPACING_S
                    for c in chosen
                ):
                    break
                if offer(candidate):
                    picked += 1
                    break

    bounces = sorted(
        stats.get("in_out_calls", []),
        key=lambda b: ("near_boundary" not in b["quality_flags"], b["call"] != "OUT", b["time_s"]),
    )
    bucket(
        [
            moment(
                b["time_s"],
                "bounce",
                f"Bounce candidate, projected {b['call']}",
                "Heuristic landing estimate"
                + (" near a line" if "near_boundary" in b["quality_flags"] else "")
                + "; confirm it in the video",
            )
            for b in bounces
        ],
        2,
    )
    bucket(
        [
            moment(
                r["end_s"],
                "rally_end",
                f"End of rally {r['id']}",
                "Ball tracking stopped; the rally likely ended around here",
                r["id"],
            )
            for r in ranked
        ],
        2,
    )

    # Overview: evenly spaced, snapped to times with at least two players on court.
    eligible = [s.time_s for s in samples if len(s.near) + len(s.far) >= 2] if positioned else []
    slots = max_moments - len(chosen)
    reason = (
        "Evenly spaced snapshot of player positions"
        if eligible
        else "Evenly spaced snapshot of play"
    )
    for count in (slots, slots * 2, slots * 4):
        for i in range(count):
            target = (i + 0.5) * last_s / count if last_s > 0 else 0.0
            if eligible:
                j = bisect_left(eligible, target)
                target = min(
                    (eligible[k] for k in (j - 1, j) if 0 <= k < len(eligible)),
                    key=lambda t: abs(t - target),
                )
            offer(moment(target, "overview", "Court overview", reason))
    return sorted(chosen, key=lambda c: c["time_s"])


# --- Frames -------------------------------------------------------------------------


class _Video:
    def __init__(self, path: Path, fps: float, frame_count: int):
        import cv2

        self.cv2 = cv2
        self.fps = fps
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            self.capture.release()
            raise EvidenceError(
                "The saved video couldn't be opened. Upload the video again to analyze it."
            )
        reported = self.capture.get(cv2.CAP_PROP_FRAME_COUNT)
        self.last = frame_count - 1
        if math.isfinite(reported) and reported >= 1:
            self.last = min(self.last, round(reported) - 1)

    def frame_time(self, time_s):
        return min(max(round(time_s * self.fps), 0), max(self.last, 0)) / self.fps

    def read(self, time_s):
        """(image, actual time) of the frame at a time; containers may overstate their length."""
        index = round(self.frame_time(time_s) * self.fps)
        for candidate in range(index, max(-1, index - 4), -1):
            self.capture.set(self.cv2.CAP_PROP_POS_FRAMES, candidate)
            ok, image = self.capture.read()
            if ok and image is not None and image.ndim == 3:
                return image, candidate / self.fps
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.capture.release()


def _court_crop(corners, width, height):
    if corners is None:
        return (0.0, 0.0, float(width), float(height))
    xs, ys = [x for x, _ in corners], [y for _, y in corners]
    box_w, box_h = max(xs) - min(xs), max(ys) - min(ys)
    return (
        min(xs) - CROP_SIDE * box_w,
        min(ys) - CROP_ABOVE * box_h,
        max(xs) + CROP_SIDE * box_w,
        max(ys) + CROP_BELOW * box_h,
    )


def _crop_box(base, players, width, height):
    """The court crop grown to keep every counted player whole, clamped to the frame."""
    x1, y1, x2, y2 = base
    for p in players:
        bx1, by1, bx2, by2 = p.box
        pad = 0.12 * (by2 - by1)
        x1, y1 = min(x1, bx1 - pad), min(y1, by1 - pad)
        x2, y2 = max(x2, bx2 + pad), max(y2, by2 + pad / 2)
    x1, y1 = max(0, math.floor(x1)), max(0, math.floor(y1))
    x2, y2 = min(width, math.ceil(x2)), min(height, math.ceil(y2))
    return (x1, y1, x2, y2) if x2 - x1 >= 16 and y2 - y1 >= 16 else (0, 0, width, height)


def _label(image, text):
    import cv2

    scale = min(1.1, max(0.45, image.shape[0] / 600))
    thickness = 2 if scale >= 0.7 else 1
    (text_w, text_h), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    pad = max(4, round(text_h * 0.45))
    cv2.rectangle(image, (0, 0), (text_w + 2 * pad, text_h + baseline + 2 * pad), (24, 24, 24), -1)
    cv2.putText(
        image,
        text,
        (pad, pad + text_h),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def _compose(video, times, base_crop, nearby, width, height):
    """JPEG bytes and actual frame times: one still, or a labelled 2×2 grid of four."""
    import cv2

    frames = [video.read(t) for t in times]
    if any(frame is None for frame in frames):
        return None
    players = [
        p
        for _, actual in frames
        for sample in [nearby(actual)]
        if sample
        for p in sample.near + sample.far
    ]
    x1, y1, x2, y2 = _crop_box(base_crop, players, width, height)
    edge = SINGLE_EDGE if len(frames) == 1 else TILE_EDGE
    tiles = []
    for image, actual in frames:
        sx, sy = image.shape[1] / width, image.shape[0] / height  # tolerate padded encodes
        tile = image[round(y1 * sy) : round(y2 * sy), round(x1 * sx) : round(x2 * sx)]
        scale = min(1.0, edge / max(tile.shape[:2]))
        size = (max(1, round(tile.shape[1] * scale)), max(1, round(tile.shape[0] * scale)))
        if tiles and size != tiles[0].shape[1::-1]:
            size = tiles[0].shape[1::-1]
        tile = (
            cv2.resize(tile, size, interpolation=cv2.INTER_AREA)
            if size != tile.shape[1::-1]
            else tile.copy()
        )
        _label(tile, _clock(actual))
        tiles.append(tile)
    if len(tiles) == 1:
        canvas = tiles[0]
    else:
        tile_h, tile_w = tiles[0].shape[:2]
        canvas = np.full((2 * tile_h + TILE_GAP, 2 * tile_w + TILE_GAP, 3), 24, np.uint8)
        for i, tile in enumerate(tiles):
            row, column = divmod(i, 2)
            top, left = row * (tile_h + TILE_GAP), column * (tile_w + TILE_GAP)
            canvas[top : top + tile_h, left : left + tile_w] = tile
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        return None
    return encoded.tobytes(), [round(actual, 2) for _, actual in frames]


# --- Public API -----------------------------------------------------------------------


def _evidence_file(run_dir: Path):
    return run_dir / COACH_DIR / "evidence.json"


def _built_from(run_dir: Path):
    """(stats_sha256, video source) of the saved evidence, or None when unreadable."""
    path = _evidence_file(run_dir)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_EVIDENCE_BYTES + 1)
        evidence = json.loads(raw) if len(raw) <= MAX_EVIDENCE_BYTES else None
        return (evidence["stats_sha256"], evidence["video"]["source"])
    except (OSError, ValueError, RecursionError, KeyError, TypeError):
        return None


def load_evidence(run_dir: Path) -> dict | None:
    """Saved evidence when it still matches stats.json, the video, and its frames."""
    try:
        run_dir = Path(run_dir).resolve()
        _, frames = _coach_dirs(run_dir, create=False)
        path = _evidence_file(run_dir)
        if path.is_symlink() or not path.is_file():
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_EVIDENCE_BYTES + 1)
        if len(raw) > MAX_EVIDENCE_BYTES:
            return None
        evidence = json.loads(raw)
        found = _video(run_dir)
        if (
            not isinstance(evidence, dict)
            or evidence.get("version") != EVIDENCE_VERSION
            or evidence.get("stats_sha256") != hashlib.sha256(_stats_bytes(run_dir)).hexdigest()
            or not found
            or not isinstance(evidence.get("video"), dict)
            or evidence["video"].get("source") != found[1]
            or not isinstance(evidence.get("moments"), list)
            or not evidence["moments"]
        ):
            return None
        for moment in evidence["moments"]:
            name = moment.get("frame") if isinstance(moment, dict) else None
            if (
                not isinstance(name, str)
                or not FRAME_NAME.fullmatch(name)
                or not _inside(run_dir, frames / name)
            ):
                return None
        return evidence
    except (OSError, ValueError, RecursionError):
        return None


def build_evidence(run_dir: Path, *, max_moments: int = 12, progress=None, cancelled=None) -> dict:
    """Measure positions, pick key moments, and save their stills plus evidence.json."""
    if (
        isinstance(max_moments, bool)
        or not isinstance(max_moments, int)
        or not 1 <= max_moments <= MAX_MOMENTS
    ):
        raise ValueError(f"max_moments must be an integer from 1 to {MAX_MOMENTS}.")

    def step(stage=None):
        if cancelled is not None and cancelled():
            raise EvidenceError("Cancelled.")
        if stage and progress is not None:
            progress(stage)

    run_dir = Path(run_dir).resolve()
    with _run_lock(run_dir):
        step("Reading player tracks")
        raw, stats = _read_stats(run_dir)
        found = _video(run_dir)
        if found is None:
            raise EvidenceError(NO_VIDEO)
        video_path, source = found
        info = stats["video"]
        fps, duration, width, height = (
            info["fps"],
            info["duration_s"],
            info["width"],
            info["height"],
        )
        if info["frame_count"] < 1:
            raise EvidenceError("This game's video has no frames to review.")
        coach, frames_dir = _coach_dirs(run_dir, create=True)
        previous = _built_from(run_dir)
        # Readers must never pair old evidence with frames this build is replacing.
        _evidence_file(run_dir).unlink(missing_ok=True)
        if previous != (hashlib.sha256(raw).hexdigest(), source):
            # Cached chat stills may show a different video or analysis; rebuild them on demand.
            for path in frames_dir.iterdir():
                if CHAT_FRAME.fullmatch(path.name):
                    path.unlink(missing_ok=True)
        court = _court()
        homography, corners = _calibration(run_dir, width, height)
        tracks = run_dir / "tracks.jsonl"
        samples, reason = [], None
        if homography is None:
            reason = "Court calibration is missing or doesn't match the video, so player positions weren't measured."
        elif not _inside(run_dir, tracks):
            reason = (
                "Player tracks weren't saved with this game, so player positions weren't measured."
            )
        else:
            samples = _read_samples(
                tracks,
                homography,
                court,
                duration,
                stride=max(1, round(fps / SAMPLE_HZ)),
                check=step,
            )
            if not any(s.near or s.far for s in samples):
                reason = "No players were detected on the court."
        times = [s.time_s for s in samples]
        rallies = stats.get("rallies", [])

        step("Picking key moments")
        with _Video(video_path, fps, info["frame_count"]) as video:
            candidates = _select_moments(
                stats, samples, reason is None, video.last / fps, max_moments
            )
            base_crop = _court_crop(corners, width, height)
            rendered = []
            for number, candidate in enumerate(candidates, 1):
                step(f"Extracting frames ({number} of {len(candidates)})")
                offsets = SHOT_OFFSETS_S if candidate["layout"] == "sequence" else (0.0,)
                result = _compose(
                    video,
                    [candidate["time_s"] + offset for offset in offsets],
                    base_crop,
                    lambda t: _nearest(samples, times, t, 0.3),
                    width,
                    height,
                )
                if result is not None:
                    rendered.append((candidate, *result))
        if not rendered:
            raise EvidenceError(
                "Frames couldn't be read from this game's video. Upload the video again to analyze it."
            )
        moments = []
        for number, (candidate, data, frame_times) in enumerate(rendered, 1):
            step()
            identity = f"m{number:02d}"
            sample = _nearest(samples, times, candidate["time_s"], 0.5)
            moments.append(
                {
                    "id": identity,
                    "time_s": candidate["time_s"],
                    "start_s": min(frame_times),
                    "end_s": max(frame_times),
                    "kind": candidate["kind"],
                    "title": candidate["title"],
                    "reason": candidate["reason"],
                    "rally_id": candidate["rally_id"],
                    "frame": f"{identity}.jpg",
                    "layout": candidate["layout"],
                    "frame_times_s": frame_times,
                    "positions": _positions(sample),
                    "caption": _caption(
                        identity,
                        candidate["time_s"],
                        candidate["title"],
                        frame_times,
                        sample,
                        court,
                    ),
                }
            )
            _write_atomic(frames_dir, f"{identity}.jpg", data)

        quality = stats["quality"]
        on_court = [len(s.near) + len(s.far) for s in samples]
        warnings = []
        if source == "annotated.mp4":
            warnings.append(
                "Video has analysis overlays drawn on it (boxes, labels, ball trail); they are not part of play."
            )
        warnings.append(
            reason
            or "Positions are estimated from player detections and may include bystanders near the court."
        )
        if not rallies:
            warnings.append("No rallies were detected; moments are evenly spaced over the video.")
        if quality["status"] != "heuristic":
            warnings.append(
                "Ball tracking coverage is limited, so rallies, shots, and bounces may be missing."
            )
        evidence = {
            "version": EVIDENCE_VERSION,
            "stats_sha256": hashlib.sha256(raw).hexdigest(),
            "video": {
                "duration_s": round(duration, 3),
                "fps": round(fps, 3),
                "width": width,
                "height": height,
                "source": source,
                "has_overlays": source == "annotated.mp4",
            },
            "court": {
                "width_m": court.width,
                "length_m": court.length,
                "net_y_m": round(court.net, 3),
                "kitchen_depth_m": court.kitchen,
            },
            "tracking": {
                "quality_status": quality["status"],
                "ball_coverage": round(quality["ball_detection_coverage"], 3),
                "rally_count": stats["rally_count"],
                "shot_count": stats["shot_count"],
                "on_court_player_coverage": None
                if reason
                else _share(sum(n > 0 for n in on_court), len(on_court)),
                "avg_on_court_players": None if reason else _mean(on_court),
            },
            "positioning": _positioning(samples, rallies, reason),
            "moments": moments,
            "warnings": warnings,
        }
        step()
        _write_atomic(
            coach, "evidence.json", (json.dumps(evidence, allow_nan=False) + "\n").encode()
        )
        current = {moment["frame"] for moment in moments}
        for path in frames_dir.iterdir():
            if MOMENT_FRAME.fullmatch(path.name) and path.name not in current:
                path.unlink(missing_ok=True)
        return evidence


def ensure_evidence(run_dir, **kw) -> dict:
    """Saved evidence when still valid, otherwise a fresh build."""
    run_dir = Path(run_dir).resolve()
    with _run_lock(run_dir):
        return load_evidence(run_dir) or build_evidence(run_dir, **kw)


def extract_moment_frames(run_dir: Path, evidence: dict, at_s: float) -> dict:
    """A 2×2 sequence around any time for chat, cached as t-NNNNNN.jpg (tenths of a second)."""
    run_dir = Path(run_dir).resolve()
    try:
        info = evidence["video"]
        fps, duration = float(info["fps"]), float(info["duration_s"])
        width, height = int(info["width"]), int(info["height"])
        if not (
            fps > 0 and math.isfinite(fps) and math.isfinite(duration) and width > 0 and height > 0
        ):
            raise ValueError
    except (TypeError, KeyError, ValueError) as exc:
        raise EvidenceError(
            "The coach's evidence for this game is incomplete. Analyze the game again."
        ) from exc
    if not _finite(at_s) or not 0 <= at_s <= duration:
        raise EvidenceError("Choose a moment within the video.")
    found = _video(run_dir)
    if found is None:
        raise EvidenceError(NO_VIDEO)
    tenths = round(at_s * 10)
    identity, time_s = f"t-{tenths:06d}", tenths / 10
    name = f"{identity}.jpg"
    _, frames_dir = _coach_dirs(run_dir, create=True)
    court = _court()
    last_index = max(0, round(duration * fps) - 1)
    frame_times = [
        round(min(max(round((time_s + offset) * fps), 0), last_index) / fps, 2)
        for offset in CHAT_OFFSETS_S
    ]
    homography, corners = _calibration(run_dir, width, height)
    samples = []
    if homography is not None and _inside(run_dir, run_dir / "tracks.jsonl"):
        samples = _read_samples(
            run_dir / "tracks.jsonl",
            homography,
            court,
            duration,
            first=max(0, math.floor((frame_times[0] - 0.5) * fps)),
            last=math.ceil((frame_times[-1] + 0.5) * fps),
        )
    times = [s.time_s for s in samples]
    target = frames_dir / name
    if _inside(run_dir, target):
        os.utime(target)  # most recently used survives pruning
    else:
        with _Video(found[0], fps, last_index + 1) as video:
            result = _compose(
                video,
                frame_times,
                _court_crop(corners, width, height),
                lambda t: _nearest(samples, times, t, 0.3),
                width,
                height,
            )
        if result is None:
            raise EvidenceError("This moment couldn't be read from the video. Try another time.")
        data, frame_times = result
        _write_atomic(frames_dir, name, data)
    _prune_chat_frames(frames_dir, keep=name)
    sample = _nearest(samples, times, time_s, 0.5)
    return {
        "id": identity,
        "frame": name,
        "time_s": time_s,
        "start_s": min(frame_times),
        "end_s": max(frame_times),
        "layout": "sequence",
        "frame_times_s": frame_times,
        "positions": _positions(sample),
        "caption": _caption(identity, time_s, "Requested moment", frame_times, sample, court),
    }


def _prune_chat_frames(frames_dir: Path, keep: str):
    entries = []
    for path in frames_dir.iterdir():
        if CHAT_FRAME.fullmatch(path.name) and path.name != keep:
            with contextlib.suppress(OSError):
                entries.append((path.stat().st_mtime_ns, path.name, path))
    entries.sort(reverse=True)
    for _, _, path in entries[MAX_CHAT_FRAMES - 1 :]:
        path.unlink(missing_ok=True)
