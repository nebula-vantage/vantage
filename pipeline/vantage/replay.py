"""Estimated 3-D match replay from one fixed camera.

The four-corner court calibration fixes the ground plane. Assuming square pixels and a
centred principal point, the same corners also determine the camera's focal length and
pose, so the match can be redrawn from any viewpoint, including the original one.

Players stand on the court: the bottom of each box projects to the ground, and up to two
court slots per side follow them across ByteTrack identity changes. The ball is airborne,
so its height comes from fitting gravity-only flight arcs to consecutive observations.
Long arcs are placed by gravity alone; short ones lean on a height prior and are marked
approximate. Brief gaps are bridged with ballistic flight, through a bounce candidate when
one falls inside. Every value is an estimate for review, not a measurement.
"""

from __future__ import annotations

import json
import math
from itertools import pairwise, permutations
from pathlib import Path

import numpy as np

from vantage.config import CONFIG
from vantage.court import compute_homography, project

REPLAY_VERSION = 1


class ReplayUnavailable(ValueError):
    """The run lacks the tracking or calibration a replay needs."""


def camera_model(corners, width: int, height: int, config: dict = CONFIG):
    """Pinhole camera consistent with the court calibration, or None if it is degenerate."""
    cfg, court = config["replay"], config["court"]
    to_court = compute_homography(corners, width, height, config)
    to_image = np.linalg.inv(to_court)
    cx, cy = width / 2, height / 2
    g = np.array([[1.0, 0, -cx], [0, 1, -cy], [0, 0, 1]]) @ to_image
    # The rotation's first two columns are orthogonal and equally long (Zhang 2000). With
    # only the focal length unknown, each constraint is linear in w = 1 / f².
    a = np.array(
        [
            g[0, 0] * g[0, 1] + g[1, 0] * g[1, 1],
            g[0, 0] ** 2 + g[1, 0] ** 2 - g[0, 1] ** 2 - g[1, 1] ** 2,
        ]
    )
    b = np.array([g[2, 0] * g[2, 1], g[2, 0] ** 2 - g[2, 1] ** 2])
    w = -(a @ b) / (a @ a) if a @ a > 0 else 0.0
    focal = 1 / math.sqrt(w) if w > 0 else math.nan
    # Only a court that recedes from the camera constrains the lens; seen straight on (or
    # from above) its corners fit any focal length, so a typical phone lens is assumed.
    court_depths = [abs(g[2] @ [x, y, 1]) for x, y in _court_corners(court)]
    receding = max(court_depths) >= cfg["min_perspective_ratio"] * min(court_depths)
    low, high = cfg["focal_range_widths"]
    estimated = receding and low * width <= focal <= high * width
    if not estimated:
        focal = cfg["default_focal_widths"] * width
    k = np.array([[focal, 0, cx], [0, focal, cy], [0, 0, 1]])
    m = np.linalg.solve(k, to_image)
    scale = 2 / (np.linalg.norm(m[:, 0]) + np.linalg.norm(m[:, 1]))
    if (m @ [court["width_m"] / 2, court["length_m"] / 2, 1])[2] < 0:
        scale = -scale  # The court must lie in front of the camera.
    r1, r2, t = scale * m[:, 0], scale * m[:, 1], scale * m[:, 2]
    u, _, vt = np.linalg.svd(np.column_stack([r1, r2, np.cross(r1, r2)]))
    rotation = u @ vt
    center = -rotation.T @ t
    if not np.isfinite(center).all() or center[2] < cfg["min_camera_height_m"]:
        return None
    projection = k @ np.column_stack([rotation, t])
    reprojected = [_image_point(projection, (x, y, 0.0)) for x, y in _court_corners(court)]
    error = max(math.dist(p, q) for p, q in zip(reprojected, corners, strict=True))
    return {
        "projection": projection,
        "to_court": to_court,
        "center": center,
        "rotation": rotation,
        "focal_px": focal,
        "focal_estimated": bool(estimated),
        "corner_error_px": error,
        "width": width,
        "height": height,
    }


def _court_corners(court):
    w, length = court["width_m"], court["length_m"]
    return [(0, 0), (w, 0), (w, length), (0, length)]


def _image_point(projection, point):
    p = projection @ np.array([*point, 1.0])
    return (float(p[0] / p[2]), float(p[1] / p[2]))


def camera_view(camera: dict) -> dict:
    """The original viewpoint in the browser's terms: position, direction, up, and field."""
    rotation = camera["rotation"]
    return {
        "position_m": _rounded(camera["center"], 3),
        "forward": _rounded(rotation.T @ [0, 0, 1], 4),
        "up": _rounded(rotation.T @ [0, -1, 0], 4),
        "vertical_fov_deg": round(
            math.degrees(2 * math.atan(camera["height"] / 2 / camera["focal_px"])), 2
        ),
        "aspect": round(camera["width"] / camera["height"], 4),
        "focal_estimated": camera["focal_estimated"],
        "corner_error_px": round(camera["corner_error_px"], 2),
    }


def _rounded(values, digits):
    return [round(float(v), digits) for v in values]


def _height_at(projection, ground, top_y):
    """Height of the point above `ground` that the camera sees at image row `top_y`."""
    row = projection[1] - top_y * projection[2]
    if abs(row[2]) < 1e-12:
        return None
    return float(-(row[0] * ground[0] + row[1] * ground[1] + row[3]) / row[2])


# --- Players ---------------------------------------------------------------------------


def _outside_distance(x, y, court):
    """Distance outside the court; behind a baseline counts half (players serve from there)."""
    side = max(0.0, -x, x - court["width_m"])
    end = max(0.0, -y, y - court["length_m"])
    return side + 0.5 * end


def _player_slots(rows, camera, fps, config):
    """Follow up to `players_per_side` people on each half of the court, frame by frame."""
    cfg, court = config["replay"], config["court"]
    width, length, net = court["width_m"], court["length_m"], court["length_m"] / 2
    per_side = cfg["players_per_side"]
    count = len(rows)
    positions = np.full((2 * per_side, count, 2), np.nan)
    noise = np.full((2 * per_side, count, 2), np.nan)  # Per-axis variance of each position.
    heights = [[] for _ in range(2 * per_side)]
    owners = [dict() for _ in range(count)]  # frame -> {slot: player detection index}
    last = [None] * (2 * per_side)  # (frame, x, y, track_id)
    for frame, row in enumerate(rows):
        candidates = {0: [], 1: []}
        for index, player in enumerate(row["players"]):
            x1, y1, x2, y2 = player["box"]
            ground = project(((x1 + x2) / 2, y2), camera["to_court"])
            if ground is None:
                continue
            x, y = ground
            if not (
                -cfg["player_side_margin_m"] <= x <= width + cfg["player_side_margin_m"]
                and -cfg["player_end_margin_m"] <= y <= length + cfg["player_end_margin_m"]
            ):
                continue
            variance = _ground_variance(camera["to_court"], ((x1 + x2) / 2, y2), (y2 - y1), cfg)
            candidates[0 if y < net else 1].append(
                (index, x, y, player.get("track_id"), player.get("confidence", 0.0), y1, variance)
            )
        for side, found in candidates.items():
            slots = list(range(side * per_side, (side + 1) * per_side))
            followed = {last[s][3] for s in slots if last[s] is not None}

            def rank(c, followed=followed):
                bonus = cfg["player_continuity_bonus_m"] if c[3] in followed else 0.0
                return (_outside_distance(c[1], c[2], court) - bonus, -c[4])

            picks = sorted(found, key=rank)[:per_side]
            best, best_cost = {}, math.inf
            for order in permutations(slots, len(picks)):
                cost, assignment = 0.0, {}
                for slot, pick in zip(order, picks, strict=True):
                    previous = last[slot]
                    if previous is None:
                        cost += 1.0
                    elif pick[3] is not None and pick[3] == previous[3]:
                        cost += 0.0
                    else:
                        elapsed = (frame - previous[0]) / fps
                        jump = math.dist(previous[1:3], pick[1:3])
                        limit = cfg["player_max_speed_m_s"] * elapsed + cfg["player_jump_slack_m"]
                        if jump > limit and elapsed < cfg["player_reacquire_s"]:
                            continue  # Too fast to be the same person: leave this slot empty.
                        cost += 0.5 + jump / max(limit, 1e-6)
                    assignment[slot] = pick
                cost += 2.0 * (len(picks) - len(assignment))
                if cost < best_cost:
                    best, best_cost = assignment, cost
            for slot, (index, x, y, track_id, _, top, variance) in best.items():
                positions[slot, frame] = (x, y)
                noise[slot, frame] = variance
                last[slot] = (frame, x, y, track_id)
                owners[frame][slot] = index
                height = _height_at(camera["projection"], (x, y), top)
                if height is not None:
                    heights[slot].append(height)
    return positions, noise, heights, owners


def _ground_variance(to_court, pixel, box_height, cfg):
    """Court-plane variance of a foot position: pixel jitter scaled by the local perspective."""
    p = to_court @ [pixel[0], pixel[1], 1.0]
    x, y = p[0] / p[2], p[1] / p[2]
    jacobian = (
        np.array(
            [
                [to_court[0, 0] - x * to_court[2, 0], to_court[0, 1] - x * to_court[2, 1]],
                [to_court[1, 0] - y * to_court[2, 0], to_court[1, 1] - y * to_court[2, 1]],
            ]
        )
        / p[2]
    )
    sigma = cfg["player_foot_jitter_heights"] * max(box_height, 1.0)
    return (jacobian**2).sum(axis=1) * sigma * sigma


def _smooth_axis(z, r, dt, cfg):
    """Constant-velocity Rauch-Tung-Striebel smoother for one axis; NaN marks no measurement.

    Measurement variances differ by orders of magnitude (a far player's depth on a low camera
    moves metres per pixel), so each position is weighted by its own perspective noise.
    """
    q = cfg["player_accel_m_s2"] ** 2
    gate = cfg["player_gate_sigmas"] ** 2
    reset = max(1, round(cfg["player_gate_reset_s"] / dt))
    n = len(z)
    first = next(i for i in range(n) if not math.isnan(z[i]))
    p, v, a, b, c = z[first], 0.0, r[first], 0.0, 4.0
    filtered, predicted, rejected = [None] * n, [None] * n, 0
    for i in range(first, n):
        if i > first:
            p, v = p + v * dt, v
            a, b, c = (
                a + 2 * dt * b + dt * dt * c + q * dt**3 / 3,
                b + dt * c + q * dt * dt / 2,
                c + q * dt,
            )
        predicted[i] = (p, v, a, b, c)
        if not math.isnan(z[i]):
            s, innovation = a + r[i], z[i] - p
            if innovation * innovation <= gate * s or rejected >= reset:
                k0, k1 = a / s, b / s
                p, v = p + k0 * innovation, v + k1 * innovation
                a, b, c = (1 - k0) * a, (1 - k0) * b, c - k1 * b
                rejected = 0
            else:
                rejected += 1
        filtered[i] = (p, v, a, b, c)
    out = np.full(n, np.nan)
    sp, sv = filtered[n - 1][:2]
    out[n - 1] = sp
    for i in range(n - 2, first - 1, -1):
        fp, fv, fa, fb, fc = filtered[i]
        pp, pv, pa, pb, pc = predicted[i + 1]
        # Gain C = P_i Fᵀ P⁻¹_{i+1|i} for the 2x2 state covariance.
        ma, mb, mc, md = fa + dt * fb, fb, fb + dt * fc, fc  # P_i Fᵀ
        det = pa * pc - pb * pb
        if det <= 0:
            out[i] = fp
            sp, sv = fp, fv
            continue
        ia, ib, ic = pc / det, -pb / det, pa / det
        g00, g01 = ma * ia + mb * ib, ma * ib + mb * ic
        g10, g11 = mc * ia + md * ib, mc * ib + md * ic
        dp, dv = sp - pp, sv - pv
        sp, sv = fp + g00 * dp + g01 * dv, fv + g10 * dp + g11 * dv
        out[i] = sp
    return out


def _runs(valid):
    """(start, stop) index pairs of consecutive True values."""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], valid.astype(int), [0]])))
    return list(zip(edges[::2], edges[1::2], strict=True))


def _clean_track(track, noise, fps, cfg):
    """Drop flickers, then smooth one slot's (frames, 2) positions across short gaps."""
    track = track.copy()
    valid = ~np.isnan(track[:, 0])
    for start, stop in _runs(valid):
        if (stop - start) / fps < cfg["player_min_fragment_s"]:
            track[start:stop] = np.nan
    runs = _runs(~np.isnan(track[:, 0]))
    out = np.full_like(track, np.nan)
    # Join runs separated by short gaps into stretches the smoother may bridge.
    stretches = []
    for start, stop in runs:
        if stretches and (start - stretches[-1][1]) / fps <= cfg["player_gap_fill_s"]:
            stretches[-1][1] = stop
        else:
            stretches.append([start, stop])
    for start, stop in stretches:
        for axis in range(2):
            out[start:stop, axis] = _smooth_axis(
                track[start:stop, axis], noise[start:stop, axis], 1 / fps, cfg
            )
    return out


def _players(rows, camera, fps, config):
    cfg, court = config["replay"], config["court"]
    positions, noise, heights, owners = _player_slots(rows, camera, fps, config)
    count = len(rows)
    rate = min(cfg["sample_rate_hz"], fps)
    sample_frames = np.minimum(
        np.round(np.arange(0, count / fps, 1 / rate) * fps).astype(int), count - 1
    )
    low, high = cfg["player_height_range_m"]
    players, kept = [], {}
    per_side = cfg["players_per_side"]
    for slot in range(len(positions)):
        track = _clean_track(positions[slot], noise[slot], fps, cfg)
        valid = ~np.isnan(track[:, 0])
        coverage = float(valid.mean()) if count else 0.0
        if coverage < cfg["player_min_coverage"]:
            continue
        steps = np.linalg.norm(np.diff(track, axis=0), axis=1)
        limit = cfg["player_max_speed_m_s"] / fps
        distance = float(np.nansum(np.where(steps <= limit, steps, 0.0)))
        samples = [
            None if np.isnan(track[f, 0]) else [round(track[f, 0], 2), round(track[f, 1], 2)]
            for f in sample_frames
        ]
        side = "near" if slot < per_side else "far"
        height = float(np.median(heights[slot])) if heights[slot] else 1.7
        kept[slot] = len(players)
        players.append(
            {
                "id": f"{side}-{slot % per_side + 1}",
                "side": side,
                "median_x_m": float(np.nanmedian(track[:, 0])),
                "height_m": round(min(high, max(low, height)), 2),
                "coverage": round(coverage, 3),
                "distance_m": round(distance, 1),
                "samples": samples,
            }
        )
    # Name slots as the camera sees them; x = 0 is the near-left corner.
    for side in ("near", "far"):
        group = sorted((p for p in players if p["side"] == side), key=lambda p: p["median_x_m"])
        names = ["left", "right"] if len(group) == 2 else [None] * len(group)
        for player, name in zip(group, names, strict=True):
            player["label"] = f"{side.title()} {name}" if name else f"{side.title()} player"
    for player in players:
        player.pop("median_x_m")
    return players, {"rate_hz": rate, "kept": kept, "owners": owners, "court": court}


# --- Ball ------------------------------------------------------------------------------


def _gravity(cfg):
    return np.array([0.0, 0.0, -cfg["gravity_m_s2"]])


def _flight_position(p0, v0, tau, gravity):
    tau = np.asarray(tau, dtype=float)
    return p0 + np.multiply.outer(tau, v0) + 0.5 * np.multiply.outer(tau * tau, gravity)


def _fit_flight(times, u, v, camera, cfg, diag, *, prior_sigma, anchors=(), strong=False):
    """Least-squares gravity-only arc through pixel observations.

    Each observation constrains the 3-D position to the camera ray through its pixel; with
    X(τ) = p0 + v0·τ + ½gτ² the constraints are linear in (p0, v0). Rows are rescaled by the
    current depth estimate so residuals are pixels, with Huber weights against outliers.
    """
    p, gravity = camera["projection"], _gravity(cfg)
    tau = times - times[0]
    au = u[:, None] * p[2, :3] - p[0, :3]
    av = v[:, None] * p[2, :3] - p[1, :3]
    a = np.vstack([au, av])
    taus = np.concatenate([tau, tau])
    rows = np.hstack([a, taus[:, None] * a])
    rhs = -np.concatenate([u * p[2, 3] - p[0, 3], v * p[2, 3] - p[1, 3]])
    rhs -= 0.5 * taus * taus * (a @ gravity)

    prior_rows, prior_rhs = [], []
    prior_times = tau if strong else [tau[-1] / 2]
    for t in prior_times:
        # z(τ) = p0z + v0z·τ + ½g_zτ² should be near the typical rally height.
        prior_rows.append(np.array([0, 0, 1, 0, 0, t]) / prior_sigma)
        prior_rhs.append((cfg["ball_height_prior_m"] - 0.5 * gravity[2] * t * t) / prior_sigma)
    for t, point in anchors:
        for axis in range(3):
            row = np.zeros(6)
            row[axis], row[axis + 3] = 1, t
            prior_rows.append(row / cfg["bounce_anchor_sigma_m"])
            prior_rhs.append(
                (point[axis] - 0.5 * gravity[axis] * t * t) / cfg["bounce_anchor_sigma_m"]
            )
    prior_rows, prior_rhs = np.array(prior_rows), np.array(prior_rhs)

    sigma = cfg["ball_pixel_sigma_diagonals"] * diag
    tolerance = cfg["ball_point_tolerance_diagonals"] * diag
    weights = np.full(len(times), 1 / (camera["typical_depth"] * sigma))
    residuals = None
    for _ in range(4):
        w = np.concatenate([weights, weights])
        system = np.vstack([rows * w[:, None], prior_rows])
        target = np.concatenate([rhs * w, prior_rhs])
        theta, *_ = np.linalg.lstsq(system, target, rcond=None)
        p0, v0 = theta[:3], theta[3:]
        homogeneous = _flight_position(p0, v0, tau, gravity) @ p[:, :3].T + p[:, 3]
        depth = homogeneous[:, 2]
        if not np.isfinite(theta).all() or (depth <= 1e-6).any():
            return None
        residuals = np.hypot(homogeneous[:, 0] / depth - u, homogeneous[:, 1] / depth - v)
        robust = np.minimum(1.0, tolerance / np.maximum(residuals, 1e-9))
        weights = robust / (depth * sigma)
    return p0, v0, residuals


def _plausible(p0, v0, span, cfg, court, *, estimated=False):
    gravity, margin = _gravity(cfg), cfg["ball_court_margin_m"]
    top_speed = cfg["ball_estimated_max_speed_m_s" if estimated else "ball_max_speed_m_s"]
    ticks = np.linspace(0, max(span, 0.0), 9)
    points = _flight_position(p0, v0, ticks, gravity)
    speeds = np.linalg.norm(v0 + np.multiply.outer(ticks, gravity), axis=1)
    return bool(
        np.isfinite(points).all()
        and points[:, 2].min() >= -cfg["ball_ground_tolerance_m"]
        and points[:, 2].max() <= cfg["ball_max_height_m"]
        and speeds.max() <= top_speed
        and points[:, 0].min() >= -margin
        and points[:, 0].max() <= court["width_m"] + margin
        and points[:, 1].min() >= -margin
        and points[:, 1].max() <= court["length_m"] + margin
    )


def _anchors(times, bounces, observed, cfg):
    """Bounce candidates this arc's free flight reaches: at its ends, or across a short gap.

    A ball flying straight at the camera barely changes its image curvature with depth, so
    a nearby landing spot is often what fixes how far away the arc was.
    """
    near = cfg["ball_break_run_s"] + 1e-9
    reach = cfg["bounce_anchor_reach_s"]
    t0, t1 = times[0], times[-1]
    anchors = []
    for bounce in bounces:
        tb = bounce["time_s"]
        if t0 + near < tb < t1 - near or not t0 - reach <= tb <= t1 + reach:
            continue  # A bounce mid-arc would break free flight; a distant one isn't this arc's.
        low, high = sorted((tb, t0 if tb < t0 else t1))
        unseen = np.searchsorted(observed, high - near) - np.searchsorted(
            observed, low + near, side="right"
        )
        if unseen <= 0:  # Nothing observed in between that could be another hit.
            anchors.append((tb - t0, [*bounce["court_m"], 0.0]))
    return anchors


def _arc(times, u, v, camera, cfg, court, diag, bounces, observed):
    """Fit one arc; fall back to a strong height prior; None if neither is plausible."""
    span = float(times[-1] - times[0])
    anchors = _anchors(times, bounces, observed, cfg)
    long_enough = (
        len(times) >= cfg["ball_fit_min_observations"] and span >= cfg["ball_fit_min_span_s"]
    )
    for prior_sigma, strong in (
        (cfg["ball_height_prior_sigma_m"], False),
        (cfg["ball_fallback_sigma_m"], True),
    ):
        for use in (anchors, ()) if anchors else ((),):
            fit = _fit_flight(
                times, u, v, camera, cfg, diag, prior_sigma=prior_sigma, anchors=use, strong=strong
            )
            if fit is None:
                continue
            p0, v0, residuals = fit
            rms = float(np.sqrt(np.mean(residuals**2)))
            trusted = long_enough and not strong and rms <= cfg["ball_fitted_rms_diagonals"] * diag
            quality = "fitted" if trusted else "approximate"
            if rms <= cfg["ball_point_tolerance_diagonals"] * diag and _plausible(
                p0, v0, span, cfg, court, estimated=not trusted
            ):
                return {
                    "t0": float(times[0]),
                    "t1": float(times[-1]),
                    "p0": p0,
                    "v0": v0,
                    "quality": quality,
                    "observations": len(times),
                    "rms_px": rms,
                }
    return None


def _flight_arcs(times, u, v, camera, fps, cfg, court, diag, bounces):
    """Split observations into gravity-only arcs where several points in a row stop fitting."""
    tolerance = cfg["ball_point_tolerance_diagonals"] * diag
    minimum = cfg["ball_min_observations"]
    break_run = max(2, math.ceil(cfg["ball_break_run_s"] * fps))
    step = max(1, round(fps / 30))  # Grow high-frame-rate arcs a few frames at a time.
    arcs = []
    gaps = np.flatnonzero(np.diff(times) > cfg["ball_max_gap_s"]) + 1
    for start, stop in zip([0, *gaps], [*gaps, len(times)], strict=True):
        i = start
        while stop - i >= minimum:
            end, accepted = i + minimum, None
            while True:
                fit = _fit_flight(
                    times[i:end],
                    u[i:end],
                    v[i:end],
                    camera,
                    cfg,
                    diag,
                    prior_sigma=cfg["ball_height_prior_sigma_m"],
                )
                if fit is None:
                    break
                if end - i > minimum and (fit[2][-break_run:] > tolerance).all():
                    break
                accepted = (end, fit[2])
                if end == stop:
                    break
                end = min(stop, end + step)
            if accepted is None:
                i += 1
                continue
            end, residuals = accepted
            good = np.flatnonzero(residuals <= tolerance)
            last = i + int(good[-1]) if len(good) else end - 1
            last = max(last, i + minimum - 1)
            arc = _arc(
                times[i : last + 1],
                u[i : last + 1],
                v[i : last + 1],
                camera,
                cfg,
                court,
                diag,
                bounces,
                times,
            )
            if arc is not None:
                arcs.append(arc)
            # Arcs share their boundary observation: it is the contact point.
            i = last if last > i else i + 1
            if stop - i < minimum:
                break
    return arcs


def _ballistic(t0, t1, start, end, quality, gravity):
    span = t1 - t0
    velocity = (np.asarray(end) - np.asarray(start) - 0.5 * gravity * span * span) / span
    return {"t0": t0, "t1": t1, "p0": np.asarray(start, float), "v0": velocity, "quality": quality}


def _bridges(arcs, bounces, cfg, court):
    """Ballistic flight across short gaps, landing on a bounce candidate inside the gap."""
    gravity, pieces = _gravity(cfg), []
    for a, b in pairwise(arcs):
        gap = b["t0"] - a["t1"]
        if gap <= 1e-6 or gap > cfg["bridge_max_gap_s"]:
            continue
        start = _flight_position(a["p0"], a["v0"], a["t1"] - a["t0"], gravity)
        waypoints = [(a["t1"], start)]
        inside = [x for x in bounces if a["t1"] < x["time_s"] < b["t0"]]
        if inside:
            waypoints.append((inside[0]["time_s"], np.array([*inside[0]["court_m"], 0.0])))
        waypoints.append((b["t0"], b["p0"]))
        candidate = [
            _ballistic(ta, tb, pa, pb, "bridged", gravity)
            for (ta, pa), (tb, pb) in pairwise(waypoints)
        ]
        if all(
            _plausible(p["p0"], p["v0"], p["t1"] - p["t0"], cfg, court, estimated=True)
            for p in candidate
        ):
            pieces.extend(candidate)
    return pieces


def _ball(rows, camera, fps, config, bounces):
    cfg, court = config["replay"], config["court"]
    observed = [
        (
            row["time_s"],
            (row["ball"]["box"][0] + row["ball"]["box"][2]) / 2,
            (row["ball"]["box"][1] + row["ball"]["box"][3]) / 2,
        )
        for row in rows
        if row.get("ball")
    ]
    if not observed:
        return [], 0
    times, u, v = (np.array(column, dtype=float) for column in zip(*observed, strict=True))
    diag = math.hypot(camera["width"], camera["height"])
    arcs = _flight_arcs(times, u, v, camera, fps, cfg, court, diag, bounces)
    pieces = sorted(arcs + _bridges(arcs, bounces, cfg, court), key=lambda p: p["t0"])
    used = sum(a["observations"] for a in arcs)
    return pieces, min(used, len(observed)) / len(observed)


def _piece_json(piece):
    data = {
        "t0": round(piece["t0"], 4),
        "t1": round(piece["t1"], 4),
        "p0": _rounded(piece["p0"], 3),
        "v0": _rounded(piece["v0"], 3),
        "quality": piece["quality"],
    }
    if "rms_px" in piece:
        data["observations"] = piece["observations"]
        data["rms_px"] = round(piece["rms_px"], 2)
    return data


# --- Events ----------------------------------------------------------------------------


def _read_jsonl(path: Path):
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _bounces(stats, events):
    source = (
        [e for e in events if e.get("type") == "bounce_candidate"]
        if events is not None
        else stats.get("in_out_calls") or []
    )
    bounces = []
    for event in source:
        court = event.get("court")
        if court is None or not all(math.isfinite(c) for c in court):
            continue
        bounces.append(
            {
                "type": "bounce",
                "time_s": float(event["time_s"]),
                "court_m": [round(float(court[0]), 3), round(float(court[1]), 3)],
                "call": event.get("call"),
                "near_line": "near_boundary" in (event.get("quality_flags") or []),
            }
        )
    return sorted(bounces, key=lambda e: e["time_s"])


def _box_distance(point, box):
    x1, y1, x2, y2 = box
    return math.hypot(max(x1 - point[0], 0, point[0] - x2), max(y1 - point[1], 0, point[1] - y2))


def _hits(events, rows, players, slots):
    hits = []
    for event in events or []:
        if event.get("type") != "paddle_hit_candidate":
            continue
        frame = event.get("frame_index")
        player = None
        if isinstance(frame, int) and 0 <= frame < len(rows) and event.get("paddle_box_px"):
            x1, y1, x2, y2 = event["paddle_box_px"]
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            owners = slots["owners"][frame]
            nearest = min(
                (
                    (_box_distance(center, rows[frame]["players"][index]["box"]), slot)
                    for slot, index in owners.items()
                    if slot in slots["kept"]
                ),
                default=None,
            )
            if nearest is not None:
                player = players[slots["kept"][nearest[1]]]["id"]
        hits.append({"type": "hit", "time_s": float(event["time_s"]), "player": player})
    return hits


def _court_json(config):
    court, cfg = config["court"], config["replay"]
    return {
        "width_m": court["width_m"],
        "length_m": court["length_m"],
        "net_y_m": court["length_m"] / 2,
        "kitchen_depth_m": config["heatmap"]["kitchen_depth_m"],
        "net_post_height_m": cfg["net_post_height_m"],
        "net_center_height_m": cfg["net_center_height_m"],
    }


def _shared(stats, config):
    video = stats["video"]
    return {
        "version": REPLAY_VERSION,
        "measurement_type": "estimated_3d_reconstruction",
        "court": _court_json(config),
        "gravity_m_s2": config["replay"]["gravity_m_s2"],
        "video": {
            "fps": video["fps"],
            "duration_s": video["duration_s"],
            "width": video["width"],
            "height": video["height"],
        },
        "rallies": [
            {
                "id": r["id"],
                "start_s": float(r["start_s"]),
                "end_s": float(r["end_s"]),
                "shots": len(r.get("crossing_times_s") or []),
            }
            for r in stats.get("rallies") or []
        ],
    }


def build_replay(directory: Path, config: dict = CONFIG) -> dict:
    """Assemble the replay for one completed run directory."""
    try:
        stats = json.loads((directory / "stats.json").read_text())
        calibration = json.loads((directory / "calibration.json").read_text())
        rows = _read_jsonl(directory / "tracks.jsonl")
        events_path = directory / "events.jsonl"
        events = _read_jsonl(events_path) if events_path.is_file() else None
        video = stats["video"]
        width, height, fps = int(video["width"]), int(video["height"]), float(video["fps"])
        corners = calibration["corners"]
        if (calibration["width"], calibration["height"]) != (width, height):
            raise ReplayUnavailable("The court calibration doesn't match this video.")
        if not rows or fps <= 0 or any("players" not in row or "time_s" not in row for row in rows):
            raise ReplayUnavailable("This game's tracking data is incomplete.")
    except FileNotFoundError as exc:
        raise ReplayUnavailable(
            "This game has no saved tracking data. Analyze its video again to build a replay."
        ) from exc
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ReplayUnavailable("This game's analysis files couldn't be read.") from exc
    try:
        camera = camera_model(corners, width, height, config)
    except (ValueError, TypeError) as exc:
        raise ReplayUnavailable(
            "This game's court calibration is invalid. Recalibrate it."
        ) from exc
    if camera is None:
        raise ReplayUnavailable(
            "The court calibration doesn't place the camera above the court. Recalibrate it."
        )
    court = config["court"]
    middle = camera["projection"] @ [court["width_m"] / 2, court["length_m"] / 2, 0, 1]
    camera["typical_depth"] = float(middle[2])

    try:
        bounces = _bounces(stats, events)
        players, slots = _players(rows, camera, fps, config)
        pieces, ball_used = _ball(rows, camera, fps, config, bounces)
        hits = _hits(events, rows, players, slots)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        # numpy's LinAlgError is a ValueError too.
        raise ReplayUnavailable("This game's tracking data couldn't be reconstructed.") from exc
    duration = float(video["duration_s"])
    covered = {
        quality: sum(p["t1"] - p["t0"] for p in pieces if p["quality"] == quality)
        for quality in ("fitted", "approximate", "bridged")
    }
    crossings = [
        {"type": "net_crossing", "time_s": float(c["time_s"])}
        for c in stats.get("crossing_events") or []
    ]
    warnings = [
        "Ball height is estimated by fitting gravity-only flight to one camera's view; "
        "it is not measured.",
        "Players are court positions, not identities: partners who cross over can swap.",
    ]
    if covered["approximate"] or covered["bridged"]:
        warnings.append(
            "Short ball tracks assume a typical 1 m rally height, and brief gaps are bridged "
            "with estimated flight. Both are drawn fainter, with shorter dashes."
        )
    if not camera["focal_estimated"]:
        warnings.append(
            "The court's perspective didn't fix the lens, so a typical phone lens was assumed."
        )
    if not pieces:
        warnings.append("No ball flight could be reconstructed from this video's ball tracking.")
    return {
        **_shared(stats, config),
        "synthetic": bool(stats.get("synthetic", False)),
        "camera": camera_view(camera),
        "players": players,
        "player_rate_hz": slots["rate_hz"],
        "ball": [_piece_json(p) for p in pieces],
        "events": sorted(bounces + crossings + hits, key=lambda e: e["time_s"]),
        "quality": {
            "ball_observations_used": round(ball_used, 3),
            "ball_fitted_s": round(covered["fitted"], 2),
            "ball_approximate_s": round(covered["approximate"], 2),
            "ball_bridged_s": round(covered["bridged"], 2),
            "ball_time_fraction": round(sum(covered.values()) / duration, 3) if duration else 0,
            "player_count": len(players),
            "warnings": warnings,
        },
    }


# --- Sample game -----------------------------------------------------------------------


def _smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _keyframed(keys, times):
    """Ease between (time, x, y) keyframes; hold the first and last positions."""
    keys = sorted(keys)
    out, k = [], 0
    for t in times:
        while k + 1 < len(keys) and keys[k + 1][0] <= t:
            k += 1
        if k + 1 >= len(keys) or t <= keys[0][0]:
            ref = keys[0] if t <= keys[0][0] else keys[-1]
            out.append([ref[1], ref[2]])
            continue
        (t0, x0, y0), (t1, x1, y1) = keys[k], keys[k + 1]
        s = _smooth((t - t0) / (t1 - t0)) if t1 > t0 else 1.0
        out.append([x0 + (x1 - x0) * s, y0 + (y1 - y0) * s])
    return out


def demo_replay(stats: dict, config: dict = CONFIG) -> dict:
    """A deterministic, clearly synthetic replay that follows the sample game's rallies."""
    court, cfg = config["court"], config["replay"]
    width, length = court["width_m"], court["length_m"]
    net, kitchen = length / 2, config["heatmap"]["kitchen_depth_m"]
    gravity = _gravity(cfg)
    duration = float(stats["video"]["duration_s"])
    rate = cfg["sample_rate_hz"]
    # Slots 0-1 are the near team (y < net), 2-3 the far team.
    ready = [
        (1.6, net - kitchen - 0.4),
        (4.5, net - kitchen - 0.4),
        (4.5, net + kitchen + 0.4),
        (1.6, net + kitchen + 0.4),
    ]
    base = [(1.6, -0.3), (4.5, 0.4), (4.5, length + 0.3), (1.6, length - 0.4)]
    keys = [[(0.0, *base[s])] for s in range(4)]
    calls = [
        (float(c["time_s"]), c["court"]) for c in stats.get("in_out_calls") or [] if c.get("court")
    ]
    pieces, events = [], []
    for rally in stats.get("rallies") or []:
        crossings = [float(c) for c in rally.get("crossing_times_s") or []]
        start, end = float(rally["start_s"]), float(rally["end_s"])
        if not crossings:
            continue
        for s in range(4):
            keys[s].append((max(0.0, start - 2.0), *base[s]))
            keys[s].append((start, *base[s]))
        far_first = rally["id"] % 2 == 0
        for k, crossing in enumerate(crossings):
            far = far_first == (k % 2 == 0)  # The hitter's side alternates every shot.
            hitter = (2 if far else 0) + (rally["id"] + k) % 2
            hit_time = max(start + 0.2, crossing - 0.5)
            hx, hy = _keyframed(keys[hitter], [hit_time])[0]
            if k == 0:
                hx, hy = base[hitter]
            keys[hitter].append((hit_time, hx, hy))
            keys[hitter].append((min(hit_time + 1.0, end), *ready[hitter]))
            contact = np.array([hx + 0.35, hy + (-0.4 if far else 0.4), 0.85])
            bounce_time = crossing + 0.45
            landing = next((c for t, c in calls if crossing <= t <= crossing + 1.5), None)
            if landing is None:
                depth = 1.2 + 0.8 * ((rally["id"] * 7 + k * 3) % 5) / 4 if k > 1 else 5.0
                lateral = 1.0 + 4.0 * ((rally["id"] * 5 + k * 11) % 7) / 6
                landing = (lateral, net - depth if far else net + depth)
            landing = np.array([float(landing[0]), float(landing[1]), 0.0])
            if (landing[1] > net) == far:
                # A recorded call on the hitter's own half: mirror it onto the receivers'.
                landing[1] = 2 * net - landing[1]
            pieces.append(_ballistic(hit_time, bounce_time, contact, landing, "synthetic", gravity))
            events.append({"type": "net_crossing", "time_s": crossing})
            inside = 0 <= landing[0] <= width and 0 <= landing[1] <= length
            events.append(
                {
                    "type": "bounce",
                    "time_s": bounce_time,
                    "court_m": _rounded(landing[:2], 3),
                    "call": "IN" if inside else "OUT",
                    "near_line": False,
                }
            )
            events.append({"type": "hit", "time_s": hit_time, "player": None, "_slot": hitter})
            if k + 1 < len(crossings):
                receiver_side = 0 if far else 2
                # Slots 0-1 stand left-right; slots 2-3 right-left (see `ready`).
                right = landing[0] > width / 2
                receiver = receiver_side + int(right if receiver_side == 0 else not right)
                next_hit = max(bounce_time + 0.3, crossings[k + 1] - 0.5)
                toward_baseline = -0.9 if receiver_side == 0 else 0.9
                rx = float(np.clip(landing[0], 0.3, width - 0.3))
                ry = float(landing[1] + toward_baseline)
                ry = min(ry, net - 0.5) if receiver_side == 0 else max(ry, net + 0.5)
                keys[receiver].append((next_hit, rx - 0.35, ry))
                after = np.array([rx, ry + (0.4 if receiver_side == 0 else -0.4), 0.0])
                after[2] = 0.85
                pieces.append(
                    _ballistic(bounce_time, next_hit, landing, after, "synthetic", gravity)
                )
            else:
                # The last ball skips away past the receivers.
                drift = np.array([0.0, -3.0 if far else 3.0, 0.0])
                tail_end = min(end, bounce_time + 0.6)
                if tail_end > bounce_time:
                    roll = landing + drift * (tail_end - bounce_time) + [0, 0, 0.05]
                    pieces.append(
                        _ballistic(bounce_time, tail_end, landing, roll, "synthetic", gravity)
                    )
        for s in range(4):
            keys[s].append((end + 1.5, *ready[s]))
    times = np.arange(0, duration, 1 / rate)
    labels = ["Near left", "Near right", "Far right", "Far left"]
    ids = ["near-1", "near-2", "far-1", "far-2"]
    players = []
    for s in range(4):
        path = _keyframed(keys[s], times)
        # A little idle sway so standing players don't look frozen.
        samples = [
            [round(x + 0.06 * math.sin(1.3 * t + s), 2), round(y + 0.05 * math.cos(1.7 * t + s), 2)]
            for (x, y), t in zip(path, times, strict=True)
        ]
        steps = np.linalg.norm(np.diff(np.array(samples), axis=0), axis=1)
        players.append(
            {
                "id": ids[s],
                "side": "near" if s < 2 else "far",
                "label": labels[s],
                "height_m": [1.72, 1.66, 1.78, 1.69][s],
                "coverage": 1.0,
                "distance_m": round(float(steps.sum()), 1),
                "samples": samples,
            }
        )
    for event in events:
        if "_slot" in event:
            event["player"] = ids[event.pop("_slot")]
    return {
        **_shared(stats, config),
        "synthetic": True,
        "camera": {
            "position_m": [width / 2, -9.5, 4.8],
            "forward": _rounded(np.array([0, 18.0, -4.8]) / np.linalg.norm([0, 18.0, -4.8]), 4),
            "up": _rounded(np.array([0, 4.8, 18.0]) / np.linalg.norm([0, 4.8, 18.0]), 4),
            "vertical_fov_deg": 38.0,
            "aspect": round(16 / 9, 4),
            "focal_estimated": False,
            "corner_error_px": 0.0,
        },
        "players": players,
        "player_rate_hz": rate,
        "ball": [_piece_json(p) for p in pieces],
        "events": sorted(events, key=lambda e: e["time_s"]),
        "quality": {
            "ball_observations_used": 0.0,
            "ball_fitted_s": 0.0,
            "ball_approximate_s": 0.0,
            "ball_bridged_s": 0.0,
            "ball_time_fraction": round(sum(p["t1"] - p["t0"] for p in pieces) / duration, 3),
            "player_count": 4,
            "warnings": [
                "Synthetic sample: generated play that follows the sample game's rallies."
            ],
        },
    }
