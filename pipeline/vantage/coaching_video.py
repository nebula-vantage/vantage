"""Disposable browser-playback copies of completed annotated videos.

The desktop pipeline's OpenCV MPEG-4 Part 2 output is not supported by major web
browsers. A cached H.264 copy preserves its timeline and overlays while leaving
the analyzed run untouched. The server owns the cache directory's lifetime.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading

from vantage.tracking_cache import source_signature


CONVERSION_TIMEOUT_S = 300


class PlaybackCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir).resolve()
        self._lock = threading.Lock()

    def get(self, source: Path) -> Path:
        """Return a complete H.264 rendition, converting once per source revision.

        One conversion at a time prevents parallel video range/metadata requests
        from starting duplicate encoders. Failed or timed-out conversions leave
        no published or temporary output. Earlier successful revisions remain
        usable until the server removes its disposable cache.
        """
        from imageio_ffmpeg import get_ffmpeg_exe

        with self._lock:
            source = Path(source).resolve(strict=True)
            if not source.is_file():
                raise ValueError("The session video is unavailable.")
            signature = source_signature(source)
            digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
            destination = self.cache_dir / f"h264-v1-{digest}.mp4"
            if destination.is_file() and destination.stat().st_size > 0:
                return destination
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".playback-", dir=self.cache_dir) as temporary:
                staged = Path(temporary) / "playback.mp4"
                command = [
                    get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source), "-map", "0:v:0", "-an", "-map_metadata", "-1",
                    "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
                    "-movflags", "+faststart", str(staged),
                ]
                try:
                    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            timeout=CONVERSION_TIMEOUT_S, check=False)
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError("Preparing browser playback took too long. Try a shorter video.") from exc
                except OSError as exc:
                    raise RuntimeError("Could not start the browser video converter. Check the Python installation.") from exc
                if result.returncode or not staged.is_file() or staged.stat().st_size == 0:
                    raise RuntimeError("Could not prepare browser playback. Check that the session video is complete.")
                if source_signature(source) != signature:
                    raise RuntimeError("The session video changed while preparing playback. Reload the session.")
                staged.replace(destination)
            return destination
