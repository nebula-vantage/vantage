"""Validated reuse of completed tracking runs while iterating on statistics."""
import hashlib
import json
import math

from records import Detection, FrameRecord


def source_signature(path):
    info = path.stat()
    return {"path": str(path.resolve()), "size_bytes": info.st_size, "mtime_ns": info.st_mtime_ns}


def tracking_settings(config):
    return {key: config[key] for key in ("model", "detection", "tracker", "ball_tracker")}


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_cached_tracks(output_dir, source, config, fps, width, height):
    try:
        metadata = json.loads((output_dir / "stats.json").read_text())
        path = output_dir / "tracks.jsonl"
        video = metadata["video"]
        if (metadata.get("source") != source
                or metadata.get("tracking") != tracking_settings(config)
                or metadata.get("tracks_sha256") != file_digest(path)
                or (video["width"], video["height"]) != (width, height)
                or not math.isclose(video["fps"], fps, rel_tol=1e-9)):
            raise ValueError("Video, tracking settings, or cached observations have changed.")

        def detection(data):
            return None if data is None else Detection(tuple(data["box"]), data["confidence"],
                                                       data["track_id"], data["class_id"])

        records = []
        with path.open() as stream:
            for index, line in enumerate(stream):
                row = json.loads(line)
                if row["index"] != index or not math.isclose(row["time_s"], index / fps, abs_tol=1e-9):
                    raise ValueError("Cached observations have inconsistent timestamps or frame indices.")
                records.append(FrameRecord(index, row["time_s"],
                                           [detection(d) for d in row["players"]], detection(row["ball"]),
                                           [detection(d) for d in row["paddles"]]))
        if not records or len(records) != video["frame_count"]:
            raise ValueError("Cached observation count does not match the completed run.")
        return records
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Cannot reanalyze this tracking cache: {exc} Run again without --reanalyze.") from exc
