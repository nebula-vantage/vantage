"""Estimated net-crossing shots, inactivity-based rallies, and projected speeds."""
from dataclasses import asdict
import math

import numpy as np

from records import Rally


def _valid_pair(a, b, config):
    return (a is not None and b is not None and a.source == b.source == "observed"
            and a.court is not None and b.court is not None
            and a.segment_id == b.segment_id and b.time_s > a.time_s
            and math.dist(a.court, b.court) / (b.time_s - a.time_s) * 3.6
            <= config["trajectory"]["max_projected_speed_kmh"])


def speed_series(samples, config):
    """Use adjacent observed frames only; return filtered speed and valid duration."""
    speeds = [None] * len(samples)
    durations = [0.0] * len(samples)
    for i in range(1, len(samples)):
        a, b = samples[i - 1:i + 1]
        if _valid_pair(a, b, config):
            dt = b.time_s - a.time_s
            speeds[i] = math.dist(a.court, b.court) / dt * 3.6
            durations[i] = dt
    filtered = list(speeds)
    half_window = config["stats"]["speed_smooth_window_s"] / 2
    for i, speed in enumerate(speeds):
        if speed is None:
            continue
        neighbours = [speed]
        for direction in (-1, 1):
            j = i + direction
            while 0 <= j < len(samples) and speeds[j] is not None:
                if abs(samples[j].time_s - samples[i].time_s) > half_window:
                    break
                neighbours.append(speeds[j])
                j += direction
        filtered[i] = float(np.median(neighbours))
    return filtered, durations


def crossing_events(samples, config):
    cfg = config["stats"]
    net = config["court"]["length_m"] / 2
    # Any missing/interpolated/coasted point clears confirmation state. Crossings
    # therefore always have uninterrupted observed support through the net.
    events = []
    stable_side = None
    pending_side = None
    pending_since = None
    previous = None
    last_crossing = -math.inf
    for sample in samples:
        if (sample is None or sample.source != "observed" or sample.court is None):
            stable_side = pending_side = pending_since = previous = None
            continue
        if previous is not None and not _valid_pair(previous, sample, config):
            stable_side = pending_side = pending_since = None
        offset = sample.court[1] - net
        side = 1 if offset > cfg["net_deadband_m"] else -1 if offset < -cfg["net_deadband_m"] else 0
        if side == 0:
            pending_side = pending_since = None
        else:
            if side != pending_side:
                pending_side, pending_since = side, sample.time_s
            if sample.time_s - pending_since >= cfg["crossing_support_s"]:
                if (stable_side is not None and stable_side != side and
                        sample.time_s - last_crossing >= cfg["crossing_cooldown_s"]):
                    events.append({"frame_index": sample.frame_index, "time_s": sample.time_s})
                    last_crossing = sample.time_s
                stable_side = side
        previous = sample
    return events


def segment_rallies(records, samples, crossings, speeds, config):
    cfg = config["stats"]
    # Missing evidence and stationary evidence are separate termination reasons.
    # Brief loss should not split every rally, but cannot itself count a shot.
    groups: dict[int, dict] = {}
    group_id = 0
    last_observed = None
    inactive_since = None
    frame_groups = []
    gap_active = False
    for i, record in enumerate(records):
        sample = samples[i]
        observed = sample is not None and sample.source == "observed"
        missing_break = last_observed is not None and record.time_s - last_observed >= cfg["rally_gap_s"]
        if observed:
            last_observed = record.time_s
        if observed and speeds[i] is not None and speeds[i] <= cfg["inactive_speed_kmh"]:
            if inactive_since is None:
                inactive_since = record.time_s
        else:
            inactive_since = None
        inactive_break = inactive_since is not None and record.time_s - inactive_since >= cfg["rally_gap_s"]
        if missing_break or inactive_break:
            if not gap_active:
                group_id += 1
                gap_active = True
        elif observed:
            gap_active = False
        frame_groups.append(group_id)
        if observed:
            group = groups.setdefault(group_id, {"start": record.time_s, "end": record.time_s, "crossings": []})
            group["end"] = record.time_s
    for event in crossings:
        group = groups.get(frame_groups[event["frame_index"]])
        if group is not None:
            group["crossings"].append(event["time_s"])
    rallies = []
    for group in groups.values():
        if group["crossings"]:
            rallies.append(Rally(len(rallies) + 1, group["start"], group["end"], group["crossings"]))
    return rallies


def tracking_summary(records, fps):
    """Observation coverage and per-track visibility, not player identities."""
    players = {}
    ball_ids = set()
    player_frames = 0
    longest_run = run = 0
    previous_ball_id = None
    for record in records:
        player_frames += bool(record.players)
        seen = set()
        for player in record.players:
            if player.track_id is None or player.track_id in seen:
                continue
            seen.add(player.track_id)
            entry = players.setdefault(player.track_id, {
                "track_id": player.track_id, "first_seen_s": record.time_s,
                "last_seen_s": record.time_s, "observed_frames": 0})
            entry["last_seen_s"] = record.time_s
            entry["observed_frames"] += 1
        ball = record.ball
        if ball is None:
            run = 0
            previous_ball_id = None
        else:
            if ball.track_id is not None:
                ball_ids.add(ball.track_id)
            run = run + 1 if run and ball.track_id == previous_ball_id else 1
            previous_ball_id = ball.track_id
            longest_run = max(longest_run, run)
    for entry in players.values():
        entry["observed_duration_s"] = entry["observed_frames"] / fps
    return {"player_detection_coverage": player_frames / len(records) if records else 0.0,
            "frames_with_players": player_frames,
            "max_simultaneous_player_detections": max((len(r.players) for r in records), default=0),
            "player_track_count": len(players),
            "player_tracks": sorted(players.values(), key=lambda p: p["track_id"]),
            "ball_track_count": len(ball_ids),
            "longest_contiguous_ball_observation_s": longest_run / fps}


def event_records(stats):
    """Timestamped evidence for review; inferred events are explicitly labeled."""
    events = []
    for crossing in stats["crossing_events"]:
        rally_id = next((r["id"] for r in stats["rallies"]
                         if crossing["time_s"] in r["crossing_times_s"]), None)
        events.append({**crossing, "type": "net_crossing", "rally_id": rally_id,
                       "quality_flags": ["heuristic_net_crossing"]})
    events.extend({**bounce, "type": "bounce_candidate"} for bounce in stats["in_out_calls"])
    events.extend(stats.get("motion", {}).get("hit_candidates", []))
    events.sort(key=lambda event: (event["time_s"], event["type"]))
    return [{"event_id": i + 1, **event} for i, event in enumerate(events)]


def aggregate(records, samples, bounces, fps, width, height, config):
    speeds, durations = speed_series(samples, config)
    crossings = crossing_events(samples, config)
    rallies = segment_rallies(records, samples, crossings, speeds, config)
    observed = sum(s is not None and s.source == "observed" for s in samples)
    interpolated = sum(s is not None and s.source == "interpolated" for s in samples)
    coasted = sum(s is not None and s.source == "coasted" for s in samples)
    duration = sum(durations)
    average = sum(s * dt for s, dt in zip(speeds, durations) if s is not None) / duration if duration else None
    coverage = observed / len(records) if records else 0.0
    status = "insufficient_evidence" if not observed else (
        "limited_evidence" if coverage < config["stats"]["low_coverage_fraction"] else "heuristic")
    rally_details = []
    for rally in rallies:
        supported = [s for r, s in zip(records, samples) if rally.start_s <= r.time_s <= rally.end_s]
        rally_coverage = sum(s is not None and s.source == "observed" for s in supported) / len(supported)
        rally_details.append({**asdict(rally), "shots": rally.shots,
                              "duration_s": rally.end_s - rally.start_s,
                              "ball_observation_coverage": rally_coverage,
                              "quality_flags": ["heuristic_rally"] + (
                                  ["low_ball_coverage"] if rally_coverage < config["stats"]["low_coverage_fraction"] else [])})
    warnings = [
        "Speed is a court-plane projection, not true airborne ball speed.",
        "Bounce calls and net-crossing shot counts are heuristic estimates.",
        "Rallies are grouped by ball inactivity/loss, not official scoring rules.",
        "Ball track IDs change after prolonged loss; COCO may miss pickleballs and paddles.",
    ]
    if coverage < config["stats"]["low_coverage_fraction"]:
        warnings.append("Low ball detection coverage: zero counts do not establish that no play occurred.")
    if not bounces:
        warnings.append("No supported bounce candidates; IN/OUT calls are unavailable.")
    if average is None:
        warnings.append("Insufficient consecutive ball observations to estimate speed.")
    stats = {
        "schema_version": config["runtime"]["schema_version"],
        "video": {"width": width, "height": height, "fps": fps,
                  "frame_count": len(records), "duration_s": len(records) / fps},
        "rally_count": len(rallies),
        "shot_count": len(crossings),
        "crossing_events": crossings,
        "shots_per_rally": [r.shots for r in rallies],
        "longest_rally": max((r.shots for r in rallies), default=0),
        "avg_ball_speed_kmh": average,
        "in_out_calls": [asdict(b) for b in bounces],
        "bounce_candidate_count": len(bounces),
        "rallies": rally_details,
        "tracking_summary": tracking_summary(records, fps),
        "quality": {"status": status, "ball_detection_coverage": coverage,
                    "observed_frames": observed, "interpolated_frames": interpolated,
                    "coasted_frames": coasted,
                    "interpolation_fraction": interpolated / len(records) if records else 0.0,
                    "valid_speed_duration_s": duration,
                    "valid_speed_coverage": duration / (len(records) / fps) if records else 0.0,
                    "measurement_type": "heuristic_court_projection",
                    "warnings": warnings},
    }
    return stats, rallies, speeds
