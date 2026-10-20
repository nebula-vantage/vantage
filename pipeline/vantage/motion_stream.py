"""Causal, measured-coordinate telemetry and explicitly provisional motion stats."""
from collections import deque
import math

from court import project


class MotionStream:
    def __init__(self, homography, width, height, fps, config):
        self.homography = homography
        self.width, self.height, self.fps = width, height, fps
        self.config = config
        self.cfg = config["motion"]
        self.diagonal = math.hypot(width, height)
        self.players = {}
        self.ball_history = deque(maxlen=3)
        self.hits = []
        self.last_hit_s = -math.inf

    def metadata(self):
        return {"type": "stream_start", "stream_schema_version": 1, "fps": self.fps,
                "image_size_px": [self.width, self.height],
                "court_size_m": [self.config["court"]["width_m"], self.config["court"]["length_m"]],
                "coordinates": {"pixel_origin": "top_left", "pixel_axes": "x_right_y_down",
                                "court_origin": "near_left", "court_axes": "x_across_y_toward_far_baseline"},
                "notes": ["Frames contain observations only; missing balls are null.",
                          "Distances are partial estimates per track ID, not identified players' total metres run.",
                          "Ball court projection and speed are 2-D estimates, not true 3-D flight.",
                          "Paddle-contact candidates are unverified hits, not confirmed shot counts."]}

    def _court(self, point):
        position = project(point, self.homography, self.config["court"]["projection_epsilon"])
        margin = self.cfg["projection_margin_m"]
        if position is None or not (-margin <= position[0] <= self.config["court"]["width_m"] + margin
                                    and -margin <= position[1] <= self.config["court"]["length_m"] + margin):
            return None
        return position

    def _adjacent(self, a, b):
        return (b.index == a.index + 1
                and 0 < b.time_s - a.time_s <= self.cfg["max_pair_gap_s"])

    def _player(self, detection, record):
        x1, y1, x2, y2 = detection.box
        foot = ((x1 + x2) / 2, y2)
        clipped = y2 >= self.height - 1 or y1 <= 0
        court = None if clipped else self._court(foot)
        identity = detection.track_id
        state = self.players.setdefault(identity, {"distance": 0.0, "valid_duration": 0.0,
                                                   "last": None}) if identity is not None else None
        speed = None
        status = "no_track_id" if state is None else "unavailable_projection" if court is None else "new_segment"
        if state is not None:
            previous = state["last"]
            filtered = anchor = court
            if court is not None and previous is not None and self._adjacent(previous[0], record):
                last_record, last_court, last_filtered, last_anchor = previous
                dt = record.time_s - last_record.time_s
                if math.dist(last_court, court) / dt <= self.cfg["player_max_speed_m_s"]:
                    alpha = 1 - math.exp(-dt / self.cfg["player_smoothing_s"])
                    filtered = tuple(a + alpha * (b-a) for a, b in zip(last_filtered, court))
                    step = math.dist(last_anchor, filtered)
                    speed = math.dist(last_filtered, filtered) / dt
                    anchor = last_anchor
                    if step >= self.cfg["player_min_step_m"]:
                        state["distance"] += step
                        anchor = filtered
                    state["valid_duration"] += dt
                    status = "observed_pair"
                else:
                    status = "rejected_jump"
            # A gap, clipped foot point, or impossible jump starts a new segment;
            # previously accumulated distance remains partial evidence for this ID.
            state["last"] = (record, court, filtered, anchor) if court is not None else None
        return {"track_id": identity, "confidence": detection.confidence,
                "box_px": detection.box, "footpoint_px": foot, "court_m": court,
                "observed_distance_m": state["distance"] if state is not None else None,
                "projected_speed_m_s": speed, "motion_status": status}

    def _hit_candidate(self):
        if len(self.ball_history) != 3:
            return None
        a, b, c = [entry[0] for entry in self.ball_history]
        if b.time_s - self.last_hit_s < self.cfg["hit_cooldown_s"] or not b.paddles:
            return None
        velocities = [tuple((q-p)/(right.time_s-left.time_s) for p, q in
                            zip(left.ball.center, right.ball.center)) for left, right in ((a, b), (b, c))]
        norms = [math.hypot(*v) for v in velocities]
        if min(norms) < self.diagonal * self.cfg["hit_min_speed_diagonals_s"]:
            return None
        cosine = sum(x*y for x, y in zip(*velocities)) / (norms[0] * norms[1])
        angle = math.degrees(math.acos(min(1.0, max(-1.0, cosine))))
        if angle < self.cfg["hit_min_turn_degrees"]:
            return None
        x, y = b.ball.center
        for paddle in b.paddles:
            x1, y1, x2, y2 = paddle.box
            distance = math.hypot(max(x1-x, 0, x-x2), max(y1-y, 0, y-y2))
            if distance <= self.diagonal * self.cfg["hit_paddle_margin_diagonals"]:
                self.last_hit_s = b.time_s
                return {"type": "paddle_hit_candidate", "frame_index": b.index, "time_s": b.time_s,
                        "emitted_at_s": c.time_s, "ball_track_id": b.ball.track_id,
                        "pixel": b.ball.center, "paddle_box_px": paddle.box,
                        "turn_degrees": angle, "quality_flags": ["heuristic_contact", "unverified_hit"]}
        return None

    def update(self, record):
        players = [self._player(player, record) for player in record.players]
        ball = None
        hits = []
        if record.ball is None:
            self.ball_history.clear()
        else:
            detection = record.ball
            court = self._court(detection.center)
            speed_px = speed_kmh = None
            if self.ball_history:
                previous, last_court = self.ball_history[-1]
                if (not self._adjacent(previous, record)
                        or previous.ball.track_id is None or previous.ball.track_id != detection.track_id):
                    self.ball_history.clear()
                else:
                    dt = record.time_s - previous.time_s
                    speed_px = math.dist(previous.ball.center, detection.center) / dt
                    if court is not None and last_court is not None:
                        candidate = math.dist(last_court, court) / dt * 3.6
                        if candidate <= self.config["trajectory"]["max_projected_speed_kmh"]:
                            speed_kmh = candidate
            self.ball_history.append((record, court))
            candidate = self._hit_candidate()
            if candidate is not None:
                hits.append(candidate)
                self.hits.append(candidate)
            ball = {"track_id": detection.track_id, "confidence": detection.confidence,
                    "box_px": detection.box, "center_px": detection.center,
                    "court_projection_m": court, "image_speed_px_s": speed_px,
                    "instant_projected_speed_kmh": speed_kmh, "source": "observed"}
        return {"type": "frame", "frame_index": record.index, "time_s": record.time_s,
                "players": players, "ball": ball, "hit_candidates": hits,
                "hit_candidate_count": len(self.hits)}

    def summary(self):
        return {"measurement_type": "partial_per_track_footpoint_distance",
                "player_tracks": [{"track_id": identity, "observed_distance_m": state["distance"],
                                   "valid_movement_duration_s": state["valid_duration"]}
                                  for identity, state in sorted(self.players.items())],
                "hit_candidate_count": len(self.hits), "hit_candidates": self.hits,
                "confirmed_hit_count": None}
