"""Rallies from paddle-hit sounds, and padded play segments for cutting downtime.

A rally is a run of hits close together in time, on a court where the ball is
being tracked. Feeding balls back or bouncing before a serve can also pop, so
expect some downtime just before rallies. Pure functions with no frames or
OpenCV, so the logic can be ported to VantageKit the same way the ball tracker was.
"""
from bisect import bisect_left, bisect_right

from vantage.records import Rally


def play_evidence_times(samples, speeds, crossings, bounces, config):
    """Fallback without audio: crossings, bounces, or a moving ball on the court plane."""
    floor = config["rallies"]["min_ball_speed_kmh"]
    moving = [sample.time_s for sample, speed in zip(samples, speeds)
              if sample is not None and speed is not None and speed >= floor]
    return sorted(moving + [c["time_s"] for c in crossings] + [b.time_s for b in bounces])


def _groups(times, max_gap_s):
    groups = []
    for time_s in times:
        if groups and time_s - groups[-1][-1] <= max_gap_s:
            groups[-1].append(time_s)
        else:
            groups.append([time_s])
    return groups


def segment_rallies(records, samples, speeds, crossings, bounces, onsets, config):
    """Group hit onsets separated by at most max_gap_s; keep groups that look like a point.

    onsets is None when the video has no audio; ball and crossing evidence is used instead.
    """
    cfg = config["rallies"]
    evidence = onsets if onsets is not None else play_evidence_times(samples, speeds, crossings, bounces, config)
    record_times = [record.time_s for record in records]
    rallies = []
    for times in _groups(evidence, cfg["max_gap_s"]):
        start, end = times[0], times[-1]
        crossing_times = [c["time_s"] for c in crossings if start <= c["time_s"] <= end]
        if end - start < cfg["min_duration_s"]:
            continue
        if onsets is None:
            if len(crossing_times) < cfg["min_crossings"]:
                continue
            times = []
        else:
            span = records[bisect_left(record_times, start):bisect_right(record_times, end)]
            ball_fraction = sum(r.ball is not None for r in span) / len(span) if span else 0.0
            if len(times) < cfg["min_hits"] or ball_fraction < cfg["min_ball_fraction"]:
                continue
        rallies.append(Rally(len(rallies) + 1, start, end, crossing_times, list(times)))
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
