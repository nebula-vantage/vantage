"""Four-point court calibration and safe projective mapping."""
import json
from pathlib import Path
import sys

import cv2
import numpy as np


def project(point, homography, epsilon=None):
    if epsilon is None:
        from config import CONFIG
        epsilon = CONFIG["court"]["projection_epsilon"]
    p = homography @ np.array([*point, 1.0], dtype=float)
    if not np.isfinite(p).all() or abs(p[2]) <= epsilon:
        return None
    return (float(p[0] / p[2]), float(p[1] / p[2]))


def compute_homography(corners, width: int, height: int, config: dict):
    points = np.asarray(corners, dtype=np.float32)
    cfg = config["court"]
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("Select exactly four finite court corners.")
    if np.any(points < 0) or np.any(points[:, 0] >= width) or np.any(points[:, 1] >= height):
        raise ValueError("Court corners must be inside the video frame.")
    if not cv2.isContourConvex(points) or abs(cv2.contourArea(points)) < width * height * cfg["min_area_fraction"]:
        raise ValueError("Corners must form a non-crossing court with a visible area. Press R and retry.")
    destination = np.float32([[0, 0], [cfg["width_m"], 0],
                              [cfg["width_m"], cfg["length_m"]], [0, cfg["length_m"]]])
    h = cv2.getPerspectiveTransform(points, destination)
    if not np.isfinite(h).all() or np.linalg.matrix_rank(h) != 3:
        raise ValueError("Calibration is singular; select the court corners again.")
    return h


def save_calibration(output_dir: Path, h, corners, width: int, height: int):
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_tmp = output_dir / "homography.tmp.npy"
    metadata_tmp = output_dir / "calibration.tmp.json"
    np.save(matrix_tmp, h)
    metadata_tmp.write_text(json.dumps({"width": width, "height": height, "corners": corners}, indent=2))
    matrix_tmp.replace(output_dir / "homography.npy")
    metadata_tmp.replace(output_dir / "calibration.json")


def load_calibration(output_dir: Path, width: int, height: int, config: dict):
    try:
        h = np.load(output_dir / "homography.npy", allow_pickle=False)
        meta = json.loads((output_dir / "calibration.json").read_text())
        if (meta["width"], meta["height"]) != (width, height):
            return None
        expected = compute_homography(meta["corners"], width, height, config)
        if h.shape != (3, 3) or not np.isfinite(h).all() or not np.allclose(h, expected):
            return None
        return h
    except (OSError, ValueError, KeyError, TypeError):
        return None


def calibrate(frame, output_dir: Path, config: dict, recalibrate: bool = False):
    height, width = frame.shape[:2]
    if not recalibrate:
        cached = load_calibration(output_dir, width, height, config)
        if cached is not None:
            print("Reusing calibration. Use --recalibrate if the camera has moved.", file=sys.stderr)
            return cached
    # Qt can abort the process rather than raise when no Linux display exists.
    import os
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("Court calibration needs a desktop display. Run locally with opencv-python "
                           "or supply calibration files from the same camera setup and resolution.")
    cfg, visual = config["court"], config["visual"]
    scale = min(1.0, cfg["preview_width"] / width, cfg["preview_height"] / height)
    preview = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
    sx, sy = preview.shape[1] / width, preview.shape[0] / height
    corners = []
    names = ["near-left", "near-right", "far-right", "far-left"]
    window = "Court calibration: click corners; R reset; Enter confirm; Esc cancel"

    def click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(corners) < 4:
            corners.append([x / sx, y / sy])

    print("Click outer court corners: near-left, near-right, far-right, far-left. "
          "Enter confirms; R resets; Esc cancels.", file=sys.stderr)
    try:
        cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(window, click)
        while True:
            canvas = preview.copy()
            for i, (x, y) in enumerate(corners):
                p = (round(x * sx), round(y * sy))
                cv2.circle(canvas, p, visual["point_radius"], visual["ball_color"], -1)
                cv2.putText(canvas, names[i], p, cv2.FONT_HERSHEY_SIMPLEX,
                            visual["font_scale"], visual["ball_color"], visual["line_width"])
            if len(corners) == 4:
                cv2.polylines(canvas, [np.int32([[x * sx, y * sy] for x, y in corners])],
                              True, visual["ball_color"], visual["line_width"])
            prompt = f"Click {names[len(corners)]}" if len(corners) < 4 else "Enter: confirm | R: reset"
            cv2.putText(canvas, prompt, (visual["margin"], visual["line_height"]),
                        cv2.FONT_HERSHEY_SIMPLEX, visual["font_scale"],
                        visual["ball_color"], visual["line_width"])
            cv2.imshow(window, canvas)
            key = cv2.waitKey(cfg["gui_poll_ms"]) & 0xFF
            if key == 27 or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                raise RuntimeError("Calibration cancelled. Run again to select court corners.")
            if key in (ord("r"), ord("R")):
                corners.clear()
            if key in (10, 13) and len(corners) == 4:
                try:
                    h = compute_homography(corners, width, height, config)
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    continue
                save_calibration(output_dir, h, corners, width, height)
                return h
    except cv2.error as exc:
        raise RuntimeError("Could not open calibration window. Use a desktop session and "
                           "opencv-python (not opencv-python-headless).") from exc
    finally:
        try:
            cv2.destroyWindow(window)
        except cv2.error:
            pass
