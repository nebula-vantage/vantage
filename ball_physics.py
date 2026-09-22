"""Conservative 2-D trajectory heuristics, not a reconstruction of 3-D flight."""
import math

import numpy as np

from court import project
from records import BounceEvent, FrameRecord, TrajectorySample


def _continuous(a: FrameRecord, b: FrameRecord, diagonal: float, config: dict) -> bool:
    dt = b.time_s - a.time_s
    if dt <= 0 or dt > config["trajectory"]["interpolate_gap_s"]:
        return False
    if a.ball.track_id != b.ball.track_id:
        return False
    cfg = config["detection"]
    limit = diagonal * (cfg["motion_slack_diagonals"] + cfg["max_motion_diagonals_s"] * dt)
    return math.dist(a.ball.center, b.ball.center) <= limit


def build_trajectory(records: list[FrameRecord], homography, width: int, height: int,
                     config: dict) -> list[TrajectorySample | None]:
    samples: list[TrajectorySample | None] = [None] * len(records)
    observed = [r for r in records if r.ball is not None]
    diagonal = math.hypot(width, height)
    segment = 0
    previous = None
    epsilon = config["court"]["projection_epsilon"]
    for record in observed:
        if previous is not None and _continuous(previous, record, diagonal, config):
            for i in range(previous.index + 1, record.index):
                alpha = ((records[i].time_s - previous.time_s) /
                         (record.time_s - previous.time_s))
                pixel = tuple(float(a + alpha * (b - a)) for a, b in
                              zip(previous.ball.center, record.ball.center))
                samples[i] = TrajectorySample(i, records[i].time_s, pixel,
                                               project(pixel, homography, epsilon),
                                               "interpolated", segment, record.ball.track_id)
        elif previous is not None:
            segment += 1
        pixel = record.ball.center
        samples[record.index] = TrajectorySample(record.index, record.time_s, pixel,
                                                 project(pixel, homography, epsilon),
                                                 "observed", segment, record.ball.track_id)
        previous = record

    # Fit local polynomials independently within each uninterrupted segment.
    segments: dict[int, list[TrajectorySample]] = {}
    for sample in samples:
        if sample is not None:
            segments.setdefault(sample.segment_id, []).append(sample)
    cfg = config["trajectory"]
    for group in segments.values():
        times = np.array([s.time_s for s in group])
        pixels = np.array([s.pixel for s in group])
        for sample in group:
            lo, hi = np.searchsorted(times, [sample.time_s - cfg["smooth_window_s"] / 2,
                                            sample.time_s + cfg["smooth_window_s"] / 2],
                                     side="left")
            if hi - lo > cfg["smooth_degree"]:
                coefficients = np.polynomial.polynomial.polyfit(
                    times[lo:hi] - sample.time_s, pixels[lo:hi], cfg["smooth_degree"])
                sample.pixel = tuple(float(v) for v in coefficients[0])
                sample.court = project(sample.pixel, homography, epsilon)
        # Extrapolation is display-only and may not bridge a discontinuity.
        if len(group) < 2:
            continue
        a, b = group[-2:]
        dt = b.time_s - a.time_s
        if dt <= 0:
            continue
        velocity = (np.array(b.pixel) - a.pixel) / dt
        for i in range(b.frame_index + 1, len(records)):
            elapsed = records[i].time_s - b.time_s
            if elapsed > cfg["coast_s"] or samples[i] is not None:
                break
            p = np.array(b.pixel) + velocity * elapsed
            if not (0 <= p[0] < width and 0 <= p[1] < height):
                break
            samples[i] = TrajectorySample(i, records[i].time_s,
                                           tuple(float(v) for v in p), None,
                                           "coasted", b.segment_id, b.track_id)
    return samples


def in_out(point, config: dict) -> tuple[str, list[str]]:
    x, y = point
    cfg = config["court"]
    w, length = cfg["width_m"], cfg["length_m"]
    eps = cfg["boundary_epsilon_m"]
    inside = -eps <= x <= w + eps and -eps <= y <= length + eps
    # Distance to the finite boundary, not its infinite extension.
    nearest_x, nearest_y = min(max(x, 0), w), min(max(y, 0), length)
    distance = (min(x, w - x, y, length - y) if inside else
                math.hypot(x - nearest_x, y - nearest_y))
    flags = ["near_boundary"] if distance <= cfg["line_tolerance_m"] else []
    return ("IN" if inside else "OUT", flags)


def detect_bounces(records: list[FrameRecord], samples: list[TrajectorySample | None],
                   homography, width: int, height: int, config: dict) -> list[BounceEvent]:
    cfg = config["bounce"]
    groups: dict[int, list[TrajectorySample]] = {}
    for sample in samples:
        if sample is not None and sample.source == "observed":
            groups.setdefault(sample.segment_id, []).append(sample)
    candidates = []
    for group in groups.values():
        times = np.array([s.time_s for s in group])
        # Use raw observations for fitting; smoothing must not erase the kink.
        y = np.array([records[s.frame_index].ball.center[1] / height for s in group])
        for sample in group:
            t = sample.time_s
            lo = np.searchsorted(times, t - cfg["fit_half_window_s"], side="left")
            hi = np.searchsorted(times, t + cfg["fit_half_window_s"], side="right")
            offsets = times[lo:hi] - t
            if min(np.count_nonzero(offsets <= 0), np.count_nonzero(offsets >= 0)) < cfg["min_side_observations"]:
                continue
            values = y[lo:hi]
            # A continuous hinge fit: common contact height, distinct velocities.
            hinge = np.column_stack([np.ones(len(offsets)), np.minimum(offsets, 0),
                                     np.maximum(offsets, 0)])
            fit = np.linalg.lstsq(hinge, values, rcond=None)[0]
            if not (fit[1] >= cfg["min_vertical_velocity_heights_s"] and
                    fit[2] <= -cfg["min_vertical_velocity_heights_s"]):
                continue
            line = np.column_stack([np.ones(len(offsets)), offsets])
            line_fit = np.linalg.lstsq(line, values, rcond=None)[0]
            single_error = float(np.mean((line @ line_fit - values) ** 2))
            if math.sqrt(single_error) < cfg["min_single_rmse_height"]:
                continue
            split_error = float(np.mean((hinge @ fit - values) ** 2))
            improvement = 1 - split_error / single_error
            if improvement < cfg["min_fit_improvement"]:
                continue
            frame = records[sample.frame_index]
            contact = frame.ball.center
            radius = cfg["paddle_radius_diagonals"] * math.hypot(width, height)
            if any(math.dist(contact, paddle.center) <= radius for paddle in frame.paddles):
                continue
            court_point = project(contact, homography, config["court"]["projection_epsilon"])
            if court_point is None:
                continue
            call, flags = in_out(court_point, config)
            candidates.append(BounceEvent(sample.frame_index, t, contact, court_point,
                                           call, improvement, ["heuristic_bounce", *flags]))
    # Keep the strongest candidate within each cooldown neighbourhood.
    accepted = []
    for candidate in sorted(candidates, key=lambda e: e.fit_improvement, reverse=True):
        if all(abs(candidate.time_s - other.time_s) >= cfg["cooldown_s"] for other in accepted):
            accepted.append(candidate)
    return sorted(accepted, key=lambda e: e.time_s)
