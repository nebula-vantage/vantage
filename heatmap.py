"""A top-down density image of estimated bounce events, not ball occupancy."""
import math

import cv2
import numpy as np


def landing_density(bounces, config):
    """Count each event frame once; never clamp out-of-range events to court edges."""
    cfg, court = config["heatmap"], config["court"]
    margin, scale, sigma = cfg["margin_m"], cfg["pixels_per_m"], cfg["sigma_m"]
    if not all(math.isfinite(v) for v in (margin, scale, sigma)) or margin < 0 or scale <= 0 or sigma <= 0:
        raise ValueError("Heatmap margin must be nonnegative; scale and sigma must be positive and finite.")
    width = round((court["width_m"] + 2 * margin) * scale) + 1
    height = round((court["length_m"] + 2 * margin) * scale) + 1
    counts = np.zeros((height, width), dtype=np.float32)
    included, seen = [], set()
    excluded = duplicates = 0
    for bounce in bounces:
        x, y = bounce.court
        if (not math.isfinite(x) or not math.isfinite(y)
                or not -margin <= x <= court["width_m"] + margin
                or not -margin <= y <= court["length_m"] + margin):
            excluded += 1
            continue
        if bounce.frame_index in seen:
            duplicates += 1
            continue
        seen.add(bounce.frame_index)
        # Far baseline at the top; near-left court corner remains the origin.
        px = round((x + margin) * scale)
        py = round((court["length_m"] + margin - y) * scale)
        counts[py, px] += 1
        included.append(bounce)
    density = cv2.GaussianBlur(counts, (0, 0), sigma * scale, borderType=cv2.BORDER_CONSTANT)
    metadata = {"file": "landing_heatmap.png", "measurement_type": "estimated_bounce_locations",
                "input_candidates": len(bounces), "included_candidates": len(included),
                "excluded_candidates": excluded, "duplicate_frames_removed": duplicates,
                "sigma_m": sigma, "margin_m": margin, "normalization": "relative_to_image_peak",
                "coordinate_origin": "near_left", "far_baseline_at_top": True,
                "note": "Unverified bounce candidates, not confirmed landings or complete shot placement."}
    return density, included, metadata


def render_landing_heatmap(path, bounces, coverage, config):
    density, included, metadata = landing_density(bounces, config)
    cfg, court = config["heatmap"], config["court"]
    margin, scale = cfg["margin_m"], cfg["pixels_per_m"]
    board_h, board_w = density.shape
    left, top = 70, 205
    sidebar = left + board_w + 60
    footer = max(top + board_h, top + 900) + 66
    image = np.full((footer + 110, board_w + 520, 3), (24, 20, 17), np.uint8)
    white, muted, accent = (237, 238, 236), (161, 168, 166), (193, 221, 111)

    def text(label, x, y, size=.55, color=white, thickness=1):
        cv2.putText(image, label, (round(x), round(y)), cv2.FONT_HERSHEY_SIMPLEX,
                    size, color, thickness, cv2.LINE_AA)

    def point(x, y):
        return (left + round((x+margin)*scale), top + round((court["length_m"]+margin-y)*scale))

    def line(a, b, color=white, thickness=2):
        cv2.line(image, point(*a), point(*b), color, thickness, cv2.LINE_AA)

    text("VANTAGE  /  MATCH REVIEW", left, 48, .48, accent)
    text("Estimated bounce locations", left, 101, 1.12, white, 2)
    text("One dot per candidate landing. Colour shows local concentration.", left, 143, .57, muted)
    cv2.line(image, (left, 172), (image.shape[1]-70, 172), (65, 64, 58), 1)

    board = np.full((board_h, board_w, 3), (39, 37, 30), np.uint8)
    x0, y0 = round(margin*scale), round(margin*scale)
    x1, y1 = round((margin+court["width_m"])*scale), round((margin+court["length_m"])*scale)
    cv2.rectangle(board, (x0, y0), (x1, y1), (66, 67, 43), -1)
    peak = float(density.max())
    normalized = density / peak if peak > 0 else density
    colours = cv2.applyColorMap(np.uint8(np.clip(normalized, 0, 1)*255), cv2.COLORMAP_INFERNO)
    alpha = np.minimum(normalized * 2, .90)[..., None]
    image[top:top+board_h, left:left+board_w] = np.uint8(board*(1-alpha) + colours*alpha)
    cv2.rectangle(image, (left, top), (left+board_w-1, top+board_h-1), (78, 78, 64), 1)
    w, length = court["width_m"], court["length_m"]
    net = length/2
    kitchen = cfg["kitchen_depth_m"]
    for a, b in (((0, 0), (w, 0)), ((w, 0), (w, length)), ((w, length), (0, length)), ((0, length), (0, 0)),
                 ((0, net-kitchen), (w, net-kitchen)), ((0, net+kitchen), (w, net+kitchen)),
                 ((w/2, 0), (w/2, net-kitchen)), ((w/2, net+kitchen), (w/2, length))):
        line(a, b)
    line((0, net), (w, net), accent, 3)
    for bounce in included:
        centre = point(*bounce.court)
        cv2.circle(image, centre, 5, (28, 25, 20), -1, cv2.LINE_AA)
        cv2.circle(image, centre, 3, white, -1, cv2.LINE_AA)
    text("FAR BASELINE", left + x0, top + y0 - 22, .43, muted)
    text("NEAR BASELINE  /  ORIGIN AT LEFT", left + x0, top + y1 + 33, .43, muted)
    text("NET", left + x1 + 12, point(0, net)[1] + 5, .42, accent)

    eps = court["boundary_epsilon_m"]
    inside = sum(-eps <= b.court[0] <= w+eps and -eps <= b.court[1] <= length+eps for b in included)
    metadata.update({"inside_candidates": inside, "outside_candidates": len(included)-inside,
                     "ball_observation_coverage": coverage})
    text("CANDIDATES SHOWN", sidebar, top+28, .46, muted)
    text(str(len(included)), sidebar, top+100, 2.0, white, 3)
    text(f"{inside} inside  /  {len(included)-inside} outside", sidebar, top+141, .57)
    text("Not verified line calls", sidebar, top+169, .46, muted)
    text("BALL OBSERVATION COVERAGE", sidebar, top+239, .44, muted)
    text(f"{coverage:.1%}", sidebar, top+293, 1.23, accent, 2)
    text("of video frames", sidebar, top+323, .48, muted)
    text("RELATIVE DENSITY", sidebar, top+402, .46, muted)
    gradient = np.tile(np.linspace(255, 0, 240, dtype=np.uint8)[:, None], (1, 25))
    legend = cv2.applyColorMap(gradient, cv2.COLORMAP_INFERNO)
    legend_alpha = np.minimum(gradient.astype(float)/255*2, .90)[..., None]
    legend = np.uint8(np.array([66, 67, 43])*(1-legend_alpha) + legend*legend_alpha)
    image[top+430:top+670, sidebar:sidebar+25] = legend
    for label, offset in (("High", 446), ("Low", 660)):
        text(label, sidebar+44, top+offset, .52, muted)
    text("Scaled to this image's peak", sidebar, top+711, .46, muted)
    text(f"Smoothing: {cfg['sigma_m']:.2f} m sigma", sidebar, top+748, .46, muted)
    text(f"Outside margin: {margin:g} m", sidebar, top+778, .46, muted)
    text(f"Excluded: {metadata['excluded_candidates']}", sidebar, top+827, .46, muted)
    text(f"Duplicates removed: {metadata['duplicate_frames_removed']}", sidebar, top+857, .46, muted)
    if not included:
        text("NO BOUNCE CANDIDATES", left+30, top+board_h//2-35, .68, white, 2)
        text("No landing density is inferred.", left+30, top+board_h//2, .53, white)
    limited = coverage < config["stats"]["low_coverage_fraction"]
    text("LIMITED EVIDENCE" if limited else "HEURISTIC ESTIMATES", left, footer, .52, accent, 1)
    text("Missed detections and false bounce candidates can distort this map.", left, footer+32, .52, muted)
    text("This shows estimated landing locations, not complete shot placement or player occupancy.", left, footer+61, .48, muted)
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Could not write landing heatmap: {path}")
    decoded = cv2.imread(str(path))
    if decoded is None or decoded.shape != image.shape:
        raise RuntimeError("Landing heatmap PNG could not be verified after encoding.")
    return metadata
