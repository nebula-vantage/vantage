"""Single-ball association using measured centers and capture-time motion.

Predictions choose among observations; they are never returned as detections.
"""
from dataclasses import replace
import math

from records import Detection


class BallTracker:
    def __init__(self, config: dict, width: int, height: int):
        self.config = config["ball_tracker"]
        self.detection = config["detection"]
        self.width, self.height = width, height
        self.diagonal = math.hypot(width, height)
        self.last: tuple[float, Detection] | None = None
        self.velocity = (0.0, 0.0)
        self.pending: list[tuple[float, Detection]] = []
        self.anchor: tuple[float, tuple[float, float]] | None = None
        self.last_update: float | None = None
        self.next_id = 1

    def _limit(self, dt: float) -> float:
        return self.diagonal * (self.detection["motion_slack_diagonals"]
                                + self.detection["max_motion_diagonals_s"] * dt)

    def _velocity(self, a: Detection, b: Detection, dt: float) -> tuple[float, float]:
        velocity = tuple((y - x) / dt for x, y in zip(a.center, b.center))
        speed = math.hypot(*velocity)
        limit = self.diagonal * self.detection["max_motion_diagonals_s"]
        scale = min(1.0, limit / speed) if speed else 1.0
        return tuple(v * scale for v in velocity)

    def _valid(self, candidate: Detection) -> bool:
        x1, y1, x2, y2 = candidate.box
        x, y = candidate.center
        return (all(math.isfinite(v) for v in (*candidate.box, candidate.confidence))
                and self.detection["ball_confidence"] <= candidate.confidence <= 1
                and x2 > x1 and y2 > y1
                and 0 <= x < self.width and 0 <= y < self.height)

    def select(self, candidates: list[Detection], time_s: float) -> Detection | None:
        if not math.isfinite(time_s) or (self.last_update is not None and time_s <= self.last_update):
            raise ValueError("Ball tracker timestamps must be finite and strictly increasing.")
        self.last_update = time_s
        candidates = [c for c in candidates if self._valid(c)]
        window = self.config["confirmation_window_s"]
        self.pending = [(t, c) for t, c in self.pending if time_s - t <= window]
        if self.last and time_s - self.last[0] > self.detection["candidate_reset_s"]:
            self.last = None
            self.anchor = None

        if self.last:
            last_time, last = self.last
            dt = time_s - last_time
            possible = [c for c in candidates if math.dist(c.center, last.center) <= self._limit(dt)]
            prediction = tuple(p + v * dt for p, v in zip(last.center, self.velocity))
            radius = self.diagonal * (self.config["prediction_slack_diagonals"]
                                     + 0.5 * self.config["max_acceleration_diagonals_s2"] * dt * dt)
            near_prediction = [c for c in possible if math.dist(c.center, prediction) <= radius]
            # A paddle impact or bounce can abruptly invalidate the velocity.
            # Only allow this fallback over short gaps, within the speed gate.
            turning = not near_prediction and dt <= self.config["turn_window_s"]
            pool = near_prediction or (possible if turning else [])
            if pool:
                target = last.center if turning else prediction
                scale = self._limit(dt) if turning else radius
                selected = min(pool, key=lambda c: math.dist(c.center, target) / scale
                               - self.config["confidence_weight"] * c.confidence)
                anchor_time, anchor_center = self.anchor
                if math.dist(selected.center, anchor_center) > self.diagonal * self.config["stationary_radius_diagonals"]:
                    self.anchor = (time_s, selected.center)
                elif time_s - anchor_time >= self.config["stationary_timeout_s"]:
                    # Stop following stationary clutter; require fresh moving evidence.
                    self.last = None
                    self.anchor = None
                    self.pending = [(time_s, c) for c in candidates]
                    return None
                measured = self._velocity(last, selected, dt)
                weight = 1.0 if turning else 1 - math.exp(-dt / self.config["velocity_smoothing_s"])
                self.velocity = tuple((1 - weight) * old + weight * new
                                      for old, new in zip(self.velocity, measured))
                selected = replace(selected, track_id=last.track_id)
                self.last = (time_s, selected)
                self.pending.clear()
                return selected
            # Hold state over a short loss without inventing an observation.
            self.pending.extend((time_s, c) for c in candidates)
            return None

        # Keep alternative seeds so a high-confidence stationary sign cannot
        # prevent a lower-confidence moving ball from being acquired.
        pairs = [(t, seed, current) for t, seed in self.pending for current in candidates
                 if self.diagonal * self.config["min_confirmation_motion_diagonals"]
                 <= math.dist(seed.center, current.center) <= self._limit(time_s - t)]
        if pairs:
            t, seed, current = max(pairs, key=lambda pair:
                                  (pair[1].confidence + pair[2].confidence) / 2
                                  - self.config["confidence_weight"] * (time_s - pair[0]) / window)
            self.velocity = self._velocity(seed, current, time_s - t)
            selected = replace(current, track_id=self.next_id)
            self.next_id += 1
            self.last = (time_s, selected)
            self.anchor = (time_s, selected.center)
            self.pending.clear()
            return selected
        self.pending.extend((time_s, c) for c in candidates)
        return None
