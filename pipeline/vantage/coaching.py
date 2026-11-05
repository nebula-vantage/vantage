"""Portable, evidence-led coaching for completed analysis runs.

This module deliberately has no server, UI, model SDK, or video dependencies. Reports
describe a session, never an identified player's skill. Counts and clips retain the
analysis engine's uncertainty; practice suggestions are exercises, not diagnoses.
"""
import hashlib
import json
import math


MAX_STATS_BYTES = 2_000_000
MAX_EVENTS = 10_000
FOCUSES = ("consistency", "placement", "review")


def _number(value, name, *, minimum=0, maximum=None, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value < minimum
            or (maximum is not None and value > maximum)
            or not math.isfinite(value)
            or (integer and int(value) != value)):
        raise ValueError(f"{name} must be a finite {'integer' if integer else 'number'}"
                         f" between {minimum} and {maximum if maximum is not None else 'the supported limit'}.")
    return int(value) if integer else float(value)


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object.")
    return value


def _array(value, name, maximum=MAX_EVENTS):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{name} must be a list with at most {maximum} entries.")
    return value


def _text(value, name, maximum=500):
    if (not isinstance(value, str) or len(value) > maximum
            or any(ord(char) < 32 and char not in "\n\t" for char in value)):
        raise ValueError(f"{name} must be text of at most {maximum} characters without control characters.")
    return value


def _flags(value, name):
    return [_text(item, name, 100) for item in _array(value, name, 30)]


def validate_stats(stats):
    """Return a bounded measurement-only copy of schema-1/2 statistics.

    Unknown fields (including local paths and detector provenance) are discarded.
    Unknown fields still must be valid finite JSON, so they cannot hide oversized or
    non-JSON input. Missing optional data stays missing rather than becoming evidence.
    """
    _object(stats, "Statistics")
    try:
        encoded = json.dumps(stats, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("Statistics must contain finite JSON values.") from exc
    if len(encoded.encode("utf-8")) > MAX_STATS_BYTES:
        raise ValueError("Statistics exceed the 2 MB coaching limit.")
    version = _number(stats.get("schema_version", 1), "schema_version", integer=True, minimum=1, maximum=2)
    raw_video = _object(stats.get("video"), "video")
    video = {
        "duration_s": _number(raw_video.get("duration_s"), "video.duration_s", maximum=86_400),
        "frame_count": _number(raw_video.get("frame_count"), "video.frame_count", integer=True, maximum=30_000_000),
        "fps": _number(raw_video.get("fps"), "video.fps", minimum=0.001, maximum=1000),
        "width": _number(raw_video.get("width"), "video.width", minimum=1, maximum=32768, integer=True),
        "height": _number(raw_video.get("height"), "video.height", minimum=1, maximum=32768, integer=True),
    }
    duration = video["duration_s"]
    if abs(duration - video["frame_count"] / video["fps"]) > 1 / video["fps"] + 1e-6:
        raise ValueError("video.duration_s must agree with frame_count and fps within one frame.")
    raw_quality = _object(stats.get("quality"), "quality")
    coverage = _number(raw_quality.get("ball_detection_coverage"), "quality.ball_detection_coverage", maximum=1)
    if (video["frame_count"] == 0 or duration == 0) and coverage > 0:
        raise ValueError("An empty video cannot have ball observation coverage.")
    status = raw_quality.get("status", "heuristic" if coverage >= .3 else "limited_evidence")
    if status not in ("heuristic", "limited_evidence", "insufficient_evidence"):
        raise ValueError("quality.status is not a supported evidence status.")
    # Never upgrade a restrictive engine status, including old exports with sparse observations.
    if coverage == 0:
        status = "insufficient_evidence"
    elif coverage < .3 and status == "heuristic":
        status = "limited_evidence"
    quality = {
        "status": status, "ball_detection_coverage": coverage,
        "warnings": [_text(item, "quality.warnings") for item in _array(raw_quality.get("warnings", []), "quality.warnings", 50)],
    }
    for key in ("observed_frames", "interpolated_frames", "coasted_frames"):
        if key in raw_quality:
            quality[key] = _number(raw_quality[key], f"quality.{key}", maximum=video["frame_count"], integer=True)
    if quality.get("observed_frames") == 0:
        quality["status"] = "insufficient_evidence"
    for key in ("interpolation_fraction", "valid_speed_coverage"):
        if key in raw_quality:
            quality[key] = _number(raw_quality[key], f"quality.{key}", maximum=1)
    if "valid_speed_duration_s" in raw_quality:
        quality["valid_speed_duration_s"] = _number(raw_quality["valid_speed_duration_s"], "quality.valid_speed_duration_s", maximum=duration + 1 / video["fps"])

    def timestamp(value, name):
        return _number(value, name, maximum=duration)

    def frame(value, name):
        return _number(value, name, integer=True, maximum=max(0, video["frame_count"] - 1))

    rallies = []
    rally_ids = set()
    for raw in _array(stats.get("rallies", []), "rallies"):
        raw = _object(raw, "rally")
        identity = _number(raw.get("id"), "rally.id", integer=True, minimum=1, maximum=1_000_000)
        if identity in rally_ids:
            raise ValueError("Rally IDs must be unique.")
        rally_ids.add(identity)
        start, end = timestamp(raw.get("start_s"), "rally.start_s"), timestamp(raw.get("end_s"), "rally.end_s")
        if end < start:
            raise ValueError("A rally must end at or after its start.")
        crossing_times = [timestamp(t, "rally.crossing_times_s") for t in _array(raw.get("crossing_times_s", []), "rally.crossing_times_s")]
        if crossing_times != sorted(crossing_times) or any(t < start or t > end for t in crossing_times):
            raise ValueError("Rally crossings must be ordered and fall within the rally.")
        shots = _number(raw.get("shots", len(crossing_times)), "rally.shots", integer=True, maximum=MAX_EVENTS)
        if "crossing_times_s" in raw and shots != len(crossing_times):
            raise ValueError("Rally shots must match the supplied net-crossing evidence.")
        rallies.append({"id": identity, "start_s": start, "end_s": end,
                        "duration_s": end - start, "shots": shots,
                        "crossing_times_s": crossing_times,
                        "ball_observation_coverage": _number(raw.get("ball_observation_coverage", 0), "rally.ball_observation_coverage", maximum=1),
                        "quality_flags": _flags(raw.get("quality_flags", ["heuristic_rally"]), "rally.quality_flags")})
        if "crossing_times_s" not in raw:
            rallies[-1].pop("crossing_times_s")
    rallies.sort(key=lambda item: (item["start_s"], item["id"]))
    crossings = []
    for raw in _array(stats.get("crossing_events", []), "crossing_events"):
        raw = _object(raw, "crossing")
        crossings.append({"frame_index": frame(raw.get("frame_index"), "crossing.frame_index"),
                          "time_s": timestamp(raw.get("time_s"), "crossing.time_s")})
    bounces = []
    seen_frames = set()
    for raw in _array(stats.get("in_out_calls", []), "in_out_calls"):
        raw = _object(raw, "bounce")
        index = frame(raw.get("frame_index"), "bounce.frame_index")
        if index in seen_frames:
            raise ValueError("Bounce evidence must have unique frame indices.")
        seen_frames.add(index)
        court = _array(raw.get("court"), "bounce.court", 2)
        if len(court) != 2:
            raise ValueError("bounce.court must contain exactly two coordinates.")
        call = raw.get("call")
        if call not in ("IN", "OUT"):
            raise ValueError("Bounce calls must be IN or OUT.")
        bounces.append({"frame_index": index, "time_s": timestamp(raw.get("time_s"), "bounce.time_s"),
                        "court": [_number(x, "bounce.court", minimum=-1000, maximum=1000) for x in court],
                        "call": call, "quality_flags": _flags(raw.get("quality_flags", ["heuristic_bounce"]), "bounce.quality_flags")})
    bounces.sort(key=lambda item: item["time_s"])
    speed = stats.get("avg_ball_speed_kmh")
    if speed is not None:
        speed = _number(speed, "avg_ball_speed_kmh", maximum=1000)
        if quality.get("valid_speed_duration_s") == 0 or quality.get("valid_speed_coverage") == 0:
            speed = None
    counts = {key: _number(stats.get(key, default), key, integer=True, maximum=MAX_EVENTS)
              for key, default in (("rally_count", len(rallies)), ("shot_count", sum(r["shots"] for r in rallies)),
                                   ("longest_rally", max((r["shots"] for r in rallies), default=0)),
                                   ("bounce_candidate_count", len(bounces)))}
    for field, actual, present in (("rally_count", len(rallies), "rallies" in stats),
                                   ("bounce_candidate_count", len(bounces), "in_out_calls" in stats)):
        if present and counts[field] != actual:
            raise ValueError(f"{field} does not match the supplied evidence.")
    if "rallies" in stats and counts["shot_count"] != sum(r["shots"] for r in rallies):
        raise ValueError("shot_count does not match the supplied rallies.")
    if "crossing_events" in stats and counts["shot_count"] != len(crossings):
        raise ValueError("shot_count does not match the supplied crossing events.")
    if "rallies" in stats and counts["longest_rally"] != max((r["shots"] for r in rallies), default=0):
        raise ValueError("longest_rally does not match the supplied rallies.")
    canonical = {"schema_version": version, "video": video, "quality": quality,
                 **counts, "rallies": rallies, "crossing_events": crossings,
                 "shots_per_rally": [r["shots"] for r in rallies],
                 "avg_ball_speed_kmh": speed, "in_out_calls": bounces}
    # Preserve absence of older optional evidence lists so normalization is idempotent.
    for key in ("rallies", "crossing_events", "in_out_calls"):
        if key not in stats:
            canonical.pop(key)
    if "synthetic" in stats:
        if not isinstance(stats["synthetic"], bool):
            raise ValueError("synthetic must be a boolean.")
        canonical["synthetic"] = stats["synthetic"]
    if "session_name" in stats:
        canonical["session_name"] = _text(stats["session_name"], "session_name", 120)
    return canonical


def _clock(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def build_report(stats, focus="consistency"):
    """Build a stable JSON report with traceable observations and optional exercises."""
    if focus not in FOCUSES:
        raise ValueError("Choose consistency, placement, or review as the coaching focus.")
    stats = validate_stats(stats)
    session_id = hashlib.sha256(json.dumps(stats, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    q = stats["quality"]
    coverage, status = q["ball_detection_coverage"], q["status"]
    available = status != "insufficient_evidence"
    limited = status != "heuristic"
    labels = {"insufficient_evidence": "Not enough ball evidence", "limited_evidence": "Limited ball evidence", "heuristic": "Estimated observations"}
    warnings = ["Net crossings and rally boundaries are estimates, not official shots or scoring.",
                "Bounce candidates need video review; an OUT candidate is not a confirmed error.",
                "This session has no player attribution, shot-type labels, or technique analysis.",
                "Observation coverage measures visibility, not detection accuracy."]
    if limited:
        warnings.insert(0, "Missing detections can hide play or split rallies; zero counts do not prove nothing happened.")
    warnings = list(dict.fromkeys(warnings + q["warnings"]))
    metrics = [
        {"label": "Estimated rallies", "value": stats["rally_count"] if available else None, "unit": "", "detail": "Grouped by ball loss or inactivity; not official points."},
        {"label": "Net crossings", "value": stats["shot_count"] if available else None, "unit": "", "detail": "Supported projected crossings; not paddle impacts."},
        {"label": "Ball observed", "value": round(coverage * 100, 1), "unit": "%", "detail": "Share of video frames with an observed ball."},
        {"label": "Projected speed", "value": round(stats["avg_ball_speed_kmh"], 1) if available and stats["avg_ball_speed_kmh"] is not None else None, "unit": "km/h", "detail": "Court-plane projection; not true airborne ball speed."},
    ]
    moments, insights = [], []
    coverage_insight = {
        "id": "coverage", "title": "Start with clearer ball evidence" if not available else "Read the session through its coverage",
        "body": (f"The ball was observed in {coverage:.0%} of frames. " +
                 ("There is not enough evidence to assess play. Review the recording and tracking before drawing conclusions."
                  if not available else "This is a partial sample of play. Missing detections can shorten exchanges or hide landings; coverage is not an accuracy score.")),
        "evidence": [{"label": "Observed video frames", "value": f"{coverage:.1%}"}, {"label": "Evidence status", "value": labels[status]}],
    }
    insights.append(coverage_insight)
    rallies = [r for r in stats.get("rallies", []) if r["shots"] > 0]
    supported = [r for r in rallies if r["ball_observation_coverage"] >= .3 and "low_ball_coverage" not in r["quality_flags"]]
    if available and rallies:
        best = max(supported or rallies, key=lambda r: (r["shots"], r["ball_observation_coverage"]))
        moment_id = f"rally-{best['id']}"
        moments.append({"id": moment_id, "title": f"Rally {best['id']} · {best['shots']} estimated crossings",
                        "reason": "Use the longest supported exchange as a review reference." if supported else "Coverage is sparse; inspect this candidate exchange before interpreting it.",
                        "start_s": best["start_s"], "end_s": best["end_s"], "rally_id": best["id"],
                        "coverage": best["ball_observation_coverage"], "kind": "rally"})
        insights.append({"id": "rally-reference", "title": "Find a repeatable exchange to study" if supported else "Check how missing detections affect an exchange",
                         "body": f"Rally {best['id']} contains {best['shots']} estimated net crossings over {best['duration_s']:.1f} seconds, with {best['ball_observation_coverage']:.0%} ball coverage. Watch the sequence and choose one repeatable pattern to practice. These measurements do not identify who played a shot or why the rally ended.",
                         "evidence": [{"label": "Review window", "value": f"{_clock(best['start_s'])}–{_clock(best['end_s'])}"}, {"label": "Rally ball coverage", "value": f"{best['ball_observation_coverage']:.1%}"}],
                         "moment_id": moment_id})
        other = [r for r in supported if r["id"] != best["id"]]
        if other:
            short = min(other, key=lambda r: (r["shots"], r["start_s"]))
            moments.append({"id": f"rally-{short['id']}", "title": f"Compare rally {short['id']}",
                            "reason": "Compare with the reference exchange; a shorter detected sequence is not proof of a mistake.",
                            "start_s": short["start_s"], "end_s": short["end_s"], "rally_id": short["id"],
                            "coverage": short["ball_observation_coverage"], "kind": "rally"})
    bounces = stats.get("in_out_calls", []) if available else []
    if bounces:
        uncertain = [b for b in bounces if "near_boundary" in b["quality_flags"]]
        outside = [b for b in bounces if b["call"] == "OUT"]
        candidate = (uncertain or outside or bounces)[0]
        identity = f"bounce-{candidate['frame_index']}"
        moments.append({"id": identity, "title": "Check a near-line landing" if uncertain else "Review a candidate landing",
                        "reason": "Confirm the contact and location in the video. This is an unverified bounce candidate.",
                        "start_s": max(0, candidate["time_s"] - 2), "end_s": min(stats["video"]["duration_s"], candidate["time_s"] + 2),
                        "kind": "bounce"})
        insights.append({"id": "landing-review", "title": "Review placement before changing your target",
                         "body": f"The tracker found {len(bounces)} bounce candidates: {len(bounces) - len(outside)} projected inside and {len(outside)} outside the court. {len(uncertain)} are marked near a boundary. Check these locations in the video; they are not verified line calls, an error rate, or a complete map of either player's shots.",
                         "evidence": [{"label": "Bounce candidates", "value": len(bounces)}, {"label": "Near a boundary", "value": len(uncertain)}], "moment_id": identity})
    if focus == "placement":
        insights.sort(key=lambda item: (item["id"] != "landing-review", item["id"] != "coverage"))
        moments.sort(key=lambda item: item["kind"] != "bounce")
    elif focus == "consistency" and not limited:
        insights.sort(key=lambda item: item["id"] != "rally-reference")
    drills = _practice_plan(focus, available, limited)
    duration = _clock(stats["video"]["duration_s"])
    if not available:
        headline = "Build a clearer picture of your session"
        summary = f"This {duration} recording does not contain enough ball evidence for play-specific coaching. Start with a short review and a cleaner recording."
    elif focus == "placement":
        headline = "Turn reviewed landings into a practice target"
        summary = f"Review {len(bounces)} candidate landings from this {duration} session, then choose a controlled placement exercise. All suggestions are for practice; player-specific accuracy is not measured."
    elif focus == "review":
        headline = "Find one useful pattern in the replay"
        summary = f"Use the timestamped evidence from this {duration} session to review an exchange, check the tracking, and choose one thing to repeat in practice."
    else:
        headline = "Build your next session around a repeatable rally"
        summary = f"This {duration} session contains {stats['rally_count']} estimated rallies and {stats['shot_count']} supported net crossings. Review a reference exchange, then practice keeping a controlled rally going."
    if stats.get("synthetic"):
        summary = "Synthetic demo data — this is not an analysis of a real match. " + summary
    return {"schema_version": 1, "session_id": session_id, "focus": focus,
            "headline": headline, "summary": summary,
            "quality": {"status": status, "coverage": coverage, "label": labels[status], "warnings": warnings},
            "metrics": metrics, "insights": insights[:3], "moments": moments[:3], "drills": drills,
            "suggested_questions": ["What should I practice next?", "Which moment should I review?", "How reliable are these observations?"]}


def _practice_plan(focus, available, limited):
    recording = {"id": "clear-recording", "title": "Capture a clearer reference", "minutes": 5,
                 "why": "Better observed evidence makes the next review more useful.",
                 "steps": ["Keep the camera fixed with all four court corners visible.", "Record a short exchange in good light and review whether the ball is visible.", "Run analysis again and check coverage before comparing results."],
                 "target": "One short clip with visible ball movement and stable court calibration."}
    review = {"id": "replay-one-pattern", "title": "Watch, name, repeat", "minutes": 5,
              "why": "A video check helps separate actual play from tracking gaps.",
              "steps": ["Watch a highlighted exchange once at normal speed, then replay it slowly.", "Check whether detected crossings and candidate landings match the video.", "Write down one pattern you can see and choose a practice cue from it."],
              "target": "One video-verified observation and one cue for the next session."}
    consistency = {"id": "cooperative-rally", "title": "Build a controlled rally", "minutes": 10,
                   "why": "A neutral consistency exercise gives you a repeatable practice goal; it is not a diagnosis of this session.",
                   "steps": ["With a partner, choose a comfortable pace and a large target area.", "Count successful exchanges together, resetting the count when the rally stops.", "Complete three rounds and record your best controlled sequence."],
                   "target": "Aim for 10 consecutive controlled exchanges; adjust the target to your current level."}
    placement = {"id": "large-target-placement", "title": "Choose a generous landing target", "minutes": 10,
                 "why": "Manual target tracking gives you a placement measure that the current video estimates cannot provide.",
                 "steps": ["Agree on a large target area comfortably inside the court lines.", "Take 10 controlled feeds and have a partner count confirmed target landings.", "Repeat for a second set at the same pace, keeping the target unchanged."],
                 "target": "Record confirmed target landings out of 10 for each set; use your own first set as the reference."}
    if not available:
        return [recording, review]
    if focus == "placement":
        return [placement, review, recording] if limited else [placement, review]
    if focus == "review":
        return [review, recording] if limited else [review, consistency]
    return [consistency, review, recording] if limited else [consistency, review]


def local_answer(report, message, history=None):
    """Answer supported intents from the report using fixed templates, without a model.

    ``history`` is accepted for transport compatibility; no free-form generation or
    inferred conversational memory occurs in local mode.
    """
    message = _text(message, "Question", 2000).strip()
    if not message:
        raise ValueError("Enter a question about this session.")
    query = message.casefold()
    insights = {item["id"]: item for item in report["insights"]}
    evidence = []
    if any(word in query for word in ("who won", "winner", "win rate", "score", "my backhand", "my forehand", "my serve", "technique", "which player", "my errors", "my mistakes", "who am i", "identify", "injury", "injured", "pain", "diagnos")) and not any(word in query for word in ("coverage", "accuracy score")):
        answer = "This analysis does not identify players, attribute shots, classify technique, or establish winners and errors. Use the replay to verify what happened; the practice plan offers general exercises rather than a personal performance assessment."
        if any(word in query for word in ("injur", "pain", "diagnos")):
            answer = "The tracking data cannot assess pain or diagnose an injury. Avoid using these practice suggestions to make a medical decision."
        evidence = ["coverage"]
    elif any(word in query for word in ("reliab", "coverage", "accur", "trust", "confiden", "missing", "quality", "detect")):
        answer = insights["coverage"]["body"] + " " + report["quality"]["warnings"][0]
        evidence = ["coverage"]
    elif any(word in query for word in ("speed", "fast", "km/h", "mph")):
        metric = next(item for item in report["metrics"] if item["label"] == "Projected speed")
        answer = (f"The average projected speed is {metric['value']} km/h. " if metric["value"] is not None else "A supported average speed is unavailable for this session. ") + "This is movement projected onto the court plane, not true airborne ball speed. It does not show a player's power or serve speed."
        evidence = ["coverage"]
    elif any(word in query for word in ("drill", "practi", "train", "plan", "improv", "next", "work on")):
        parts = []
        for drill in report["drills"]:
            parts.append(f"{drill['title']} ({drill['minutes']} min): {' '.join(drill['steps'])} Target: {drill['target']}")
        answer = "\n\n".join(parts)
        evidence = [item["id"] for item in report["insights"]]
    elif any(word in query for word in ("moment", "watch", "replay", "review", "rally", "rallies", "clip")):
        if report["moments"]:
            answer = "\n\n".join(f"{_clock(item['start_s'])}–{_clock(item['end_s'])}: {item['title']}. {item['reason']}" for item in report["moments"])
            evidence = [item["id"] for item in report["moments"]]
        else:
            answer = "There are no supported moments to highlight. Review the recording and improve ball visibility before treating zero detections as evidence about play."
            evidence = ["coverage"]
    elif any(word in query for word in ("land", "bounce", "placement", "out of bounds", "line call")):
        if "landing-review" in insights:
            answer = insights["landing-review"]["body"]
            evidence = ["landing-review"]
        else:
            answer = "There are no supported bounce candidates to discuss. That does not establish that no balls landed. Review the video before drawing conclusions about placement."
            evidence = ["coverage"]
    else:
        answer = report["summary"] + "\n\nThis local evidence assistant uses fixed responses. I can explain the practice plan, review moments, ball coverage, projected speed, and candidate landings."
        evidence = [item["id"] for item in report["insights"]]
    valid_ids = set(insights) | {item["id"] for item in report["moments"]}
    return {"answer": answer, "source": "local", "evidence_ids": [identity for identity in evidence if identity in valid_ids]}
