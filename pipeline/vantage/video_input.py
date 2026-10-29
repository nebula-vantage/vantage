"""Convert phone recordings to a constant-frame-rate MP4 before analysis.

iPhone MOV files often have edit lists or variable frame timing, so the container's
frame count overstates the decodable frames and index / fps drifts from playback
time. Re-encoding the visible timeline at a constant rate fixes both.
"""
import json
from pathlib import Path
import subprocess
import tempfile

from vantage.tracking_cache import source_signature

PREPARED_NAME = "prepared.mp4"


def needs_preparation(path):
    return Path(path).suffix.lower() != ".mp4"


def prepare_video(source, output_dir):
    """Return a CFR H.264 copy of source in output_dir, reusing it while source is unchanged."""
    from imageio_ffmpeg import get_ffmpeg_exe
    import cv2
    from vantage.visualize import verify_video

    source, output_dir = Path(source), Path(output_dir)
    destination = output_dir / PREPARED_NAME
    marker = output_dir / "prepared.json"
    signature = source_signature(source)
    try:
        if destination.is_file() and json.loads(marker.read_text()) == signature:
            return destination
    except (OSError, ValueError):
        pass
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=output_dir) as temp:
        staged = Path(temp) / PREPARED_NAME
        # Explicit mapping skips the extra metadata/depth tracks phones add.
        command = [get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-c:a", "aac",
                   "-movflags", "+faststart", str(staged)]
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if result.returncode:
            raise RuntimeError(f"Could not convert {source} to MP4: {result.stderr[-1500:].strip()}")
        capture = cv2.VideoCapture(str(staged))
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            frames = round(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            size = (round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        finally:
            capture.release()
        verify_video(staged, frames, size, fps)
        staged.replace(destination)
    marker.write_text(json.dumps(signature) + "\n")
    return destination
