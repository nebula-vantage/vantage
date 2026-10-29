"""Rallies from ball-in-play evidence, and padded play segments for cutting downtime.

Pure functions over trajectory-derived events, with no frames or OpenCV, so the
logic can be ported to VantageKit the same way the ball tracker was.
"""
from vantage.records import Rally


def play_evidence_times(samples, speeds, crossings, bounces, config):
    """Times with evidence the ball is in play: crossings, bounces, or a moving ball."""
    floor = config["rallies"]["min_ball_speed_kmh"]
    moving = [sample.time_s for sample, speed in zip(samples, speeds)
              if sample is not None and speed is not None and speed >= floor]
    return sorted(moving + [c["time_s"] for c in crossings] + [b.time_s for b in bounces])


def segment_rallies(samples, speeds, crossings, bounces, config):
    """Group evidence separated by short gaps; keep groups that look like a point.

    A lone toss or a ball retrieved across the net is short or never crosses, so
    it is dropped. A rally can still be split when the ball is lost for longer
    than max_gap_s, or merged with the next one when the gap between them is short.
    """
    cfg = config["rallies"]
    groups = []
    for time_s in play_evidence_times(samples, speeds, crossings, bounces, config):
        if groups and time_s - groups[-1][1] <= cfg["max_gap_s"]:
            groups[-1][1] = time_s
        else:
            groups.append([time_s, time_s])
    rallies = []
    for start, end in groups:
        crossing_times = [c["time_s"] for c in crossings if start <= c["time_s"] <= end]
        if len(crossing_times) >= cfg["min_crossings"] and end - start >= cfg["min_duration_s"]:
            rallies.append(Rally(len(rallies) + 1, start, end, crossing_times))
    return rallies


def play_segments(rallies, duration_s, config):
    """Padded, merged intervals to keep when cutting; everything else is downtime."""
    cfg = config["rallies"]
    segments = []
    for rally in rallies:
        start = max(0.0, rally.start_s - cfg["lead_in_s"])
        end = min(duration_s, rally.end_s + cfg["lead_out_s"])
        if segments and start <= segments[-1]["end_s"]:
            segments[-1]["end_s"] = max(segments[-1]["end_s"], end)
            segments[-1]["rally_ids"].append(rally.id)
        else:
            segments.append({"start_s": start, "end_s": end, "rally_ids": [rally.id]})
    return segments
