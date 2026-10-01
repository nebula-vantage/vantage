"""Native-resolution overlays and checked MP4 encoding."""
from collections import deque
from bisect import bisect_right
from pathlib import Path
import math

import cv2
import numpy as np


class Overlay:
    def __init__(self, width, height, bounces, rallies, config, ball_coverage=None):
        self.config = config
        self.visual = config["visual"]
        self.width, self.height = width, height
        self.scale = max(self.visual["min_scale"], height / self.visual["reference_height"])
        self.stroke = max(1, round(self.visual["line_width"] * self.scale))
        self.font = self.visual["font_scale"] * self.scale
        self.trail = deque(maxlen=self.visual["trail_length"])
        self.segment = None
        self.bounces = bounces
        self.rallies = rallies
        self.bounce_index = 0
        self.active_bounces = deque()
        self.rally_index = -1
        self.crossing_times = sorted(t for rally in rallies for t in rally.crossing_times_s)
        self.ball_coverage = ball_coverage

    def point(self, point):
        # Clip extreme homography/detector values before passing C integer APIs.
        return (round(min(max(point[0], 0), self.width - 1)),
                round(min(max(point[1], 0), self.height - 1)))

    def text(self, frame, text, point, color):
        cv2.putText(frame, text, self.point(point), cv2.FONT_HERSHEY_SIMPLEX,
                    self.font, color, self.stroke, cv2.LINE_AA)

    def box(self, frame, detection, color, label=None):
        x1, y1, x2, y2 = detection.box
        cv2.rectangle(frame, self.point((x1, y1)), self.point((x2, y2)), color, self.stroke)
        if label:
            self.text(frame, label, (x1, max(self.visual["line_height"] * self.scale, y1 - self.visual["margin"] * self.scale)), color)

    def draw(self, frame, record, sample, speed):
        v = self.visual
        for player in record.players:
            label = f"Player {player.track_id}" if player.track_id is not None else "Player ?"
            self.box(frame, player, v["player_color"], label)
        if record.ball is not None:
            self.box(frame, record.ball, v["ball_color"], f"Ball {record.ball.track_id}")
        if sample is None or sample.segment_id != self.segment:
            self.trail.clear()
        self.segment = sample.segment_id if sample is not None else None
        if sample is not None:
            self.trail.append(sample)
        points = list(self.trail)
        for i, item in enumerate(points):
            color = v["ball_color"] if item.source == "observed" else v["estimated_color"]
            alpha = v["trail_min_alpha"] + (1 - v["trail_min_alpha"]) * (i + 1) / max(1, len(points))
            faded = tuple(round(c * alpha) for c in color)
            center = self.point(item.pixel)
            radius = max(1, round(v["point_radius"] * self.scale))
            cv2.circle(frame, center, radius, faded,
                       -1 if item.source == "observed" else self.stroke, cv2.LINE_AA)
            if i and item.source == "observed" and points[i - 1].source == "observed":
                cv2.line(frame, self.point(points[i - 1].pixel), center, faded, self.stroke, cv2.LINE_AA)
        while self.bounce_index < len(self.bounces) and self.bounces[self.bounce_index].time_s <= record.time_s:
            self.active_bounces.append(self.bounces[self.bounce_index])
            self.bounce_index += 1
        while self.active_bounces and record.time_s - self.active_bounces[0].time_s > self.config["bounce"]["marker_duration_s"]:
            self.active_bounces.popleft()
        for event in self.active_bounces:
            color = v["in_color"] if event.call == "IN" else v["out_color"]
            cv2.circle(frame, self.point(event.pixel), max(1, round(v["bounce_radius"] * self.scale)),
                       color, self.stroke, cv2.LINE_AA)
            self.text(frame, event.call + " (est.)" + (" ?" if "near_boundary" in event.quality_flags else ""),
                      (event.pixel[0], event.pixel[1] - v["margin"] * self.scale), color)
        while (self.rally_index + 1 < len(self.rallies) and
               self.rallies[self.rally_index + 1].crossing_times_s[0] <= record.time_s):
            self.rally_index += 1
        lines = self.stats_lines(record, sample, speed)
        margin = max(1, round(v["margin"] * self.scale))
        line_height = max(1, round(v["line_height"] * self.scale))
        panel_width = min(self.width, max(cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, self.font, self.stroke)[0][0] for s in lines) + 2 * margin)
        panel_height = min(self.height, len(lines) * line_height + 2 * margin)
        roi = frame[:panel_height, :panel_width]
        panel = np.full_like(roi, v["panel_color"])
        cv2.addWeighted(panel, v["panel_alpha"], roi, 1 - v["panel_alpha"], 0, dst=roi)
        for i, line in enumerate(lines):
            self.text(frame, line, (margin, margin + (i + 1) * line_height), v["text_color"])
        return frame

    def stats_lines(self, record, sample, speed):
        rally = self.rallies[self.rally_index] if self.rally_index >= 0 else None
        active = rally is not None and rally.start_s <= record.time_s <= rally.end_s
        shots = bisect_right(rally.crossing_times_s, record.time_s) if active else 0
        lines = [f"Rallies (est.): {self.rally_index + 1} | Shots (est.): {bisect_right(self.crossing_times, record.time_s)}",
                 f"Current rally: {rally.id} | Shots: {shots}" if active else "Current rally: no supported rally",
                 f"Projected speed: {speed:.1f} km/h" if speed is not None else "Projected speed: unavailable",
                 f"Ball: {sample.source if sample else 'not detected'} | Players: {len(record.players)}"]
        if self.ball_coverage is not None:
            status = "limited evidence" if self.ball_coverage < self.config["stats"]["low_coverage_fraction"] else "estimated stats"
            lines.append(f"Video ball coverage: {self.ball_coverage:.0%} | {status}")
        return lines


def encoded_size(width, height):
    # MPEG-4 requires even dimensions; pad a single black edge pixel if needed.
    return (width + width % 2, height + height % 2)


def render_video(input_path: Path, output_path: Path, records, samples, bounces,
                 rallies, speeds, width, height, fps, config, progress=None):
    capture = cv2.VideoCapture(str(input_path))
    size = encoded_size(width, height)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*config["visual"]["codec"]), fps, size)
    try:
        if not capture.isOpened():
            raise RuntimeError("Could not reopen input for annotation.")
        if not writer.isOpened():
            raise RuntimeError("Could not initialize MP4 writer. Check output permissions and OpenCV codec support.")
        coverage = sum(r.ball is not None for r in records) / len(records) if records else 0.0
        overlay = Overlay(width, height, bounces, rallies, config, coverage)
        for i, record in enumerate(records):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Input stopped decoding at frame {i} during rendering.")
            if frame.shape[:2] != (height, width):
                raise RuntimeError("Video dimensions changed during decoding; export a fixed-resolution video.")
            annotated = overlay.draw(frame, record, samples[i], speeds[i])
            if size != (width, height):
                annotated = cv2.copyMakeBorder(annotated, 0, size[1] - height, 0, size[0] - width,
                                              cv2.BORDER_CONSTANT, value=(0, 0, 0))
            writer.write(annotated)
            if progress:
                progress("Rendering", i + 1, len(records))
        if capture.read()[0]:
            raise RuntimeError("Input changed between detection and rendering; run again.")
    finally:
        writer.release()
        capture.release()
    verify_video(output_path, len(records), size, fps, config["runtime"]["fps_relative_tolerance"])


def verify_video(path, expected_frames, size, fps, fps_tolerance=None):
    if fps_tolerance is None:
        from config import CONFIG
        fps_tolerance = CONFIG["runtime"]["fps_relative_tolerance"]
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise RuntimeError("Encoded MP4 could not be reopened.")
        actual_size = (round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if actual_size != size or not math.isclose(capture.get(cv2.CAP_PROP_FPS), fps, rel_tol=fps_tolerance):
            raise RuntimeError("Encoded MP4 dimensions or frame rate do not match the input.")
        count = 0
        while capture.read()[0]:
            count += 1
        if count != expected_frames:
            raise RuntimeError(f"Encoded MP4 has {count} frames; expected {expected_frames}.")
    finally:
        capture.release()
