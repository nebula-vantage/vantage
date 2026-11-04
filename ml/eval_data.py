"""Public tennis, badminton, and pickleball clips with per-frame ball labels, for evaluation only.

Helpers and the source registry; the sources themselves are in eval_sources.py. Each source
downloads part of a public dataset into ml/external/eval/<source>/download/ and converts it to:
    ml/external/eval/<source>/clips/<clip>.mp4     video whose decoded frame i is label frame i
    ml/external/eval/<source>/labels/<clip>.json   schema-1 labels (see labeling.py)
    ml/external/eval/<source>/source.json          license, provenance, and per-clip counts

Frames a source did not label are left out, like frames skipped in label_ball.py. Converted
frames may carry extra fields the evaluator ignores, such as "visibility" (the source's own
class, e.g. "occluded"), "event" ("hit" or "bounce"), or "interpolated" (true when the source
filled the frame between hand-placed keyframes). Ball labels are points; boxes are a nominal
size around them because evaluation compares centers only.

These clips are never training data: they live outside ml/labels/, which build_dataset.py
reads, and are git-ignored. Most have no stated license or are research-only (see
ml/EVAL_DATA.md), so do not redistribute them or put them in the app bundle.
"""
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from labeling import save_labels

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "ml" / "external" / "eval"
USER_AGENT = "Mozilla/5.0 (vantage-eval-fetch; University of Waterloo capstone)"
# Nominal ball box as a fraction of the longer frame side (about 10 px at 1280).
BALL_BOX_FRACTION = 0.008
RANGE_CHUNK = 8 << 20
# Errors worth retrying: network failures and responses cut short.
TRANSIENT = (OSError, urllib.error.URLError, http.client.HTTPException)
# Small fixed subsets, {suite: {source: frames scored per clip}}. "ci" runs on every pull request
# (.github/workflows/eval.yml): detection is the slow part, so each clip is cut to its first N
# frames. One or two sources per sport, all fixed or corner cameras, from hosts that allow
# automated downloads; tnv2pic and kwyoke add absent frames, so false alarms count too.
SUITES = {"ci": {"arnav-pickleball": 900, "tnv2pic-pickleball": 600, "ballyolo-tennis": 400,
                 "kwyoke-badminton": 120}}


@dataclass(frozen=True)
class Source:
    name: str
    sport: str  # tennis | badminton | pickleball
    view: str  # camera viewpoint, in Vantage terms
    license: str  # as stated by the source; "not stated" when absent
    url: str  # homepage, for attribution
    download_size: str
    fetch: Callable  # fetch(root: Path) -> list of clip records from write_clip


SOURCES = {}


def source(name, *, sport, view, license, url, download_size):
    """Register fetch(root) as an evaluation source."""
    def register(fetch):
        SOURCES[name] = Source(name, sport, view, license, url, download_size, fetch)
        return fetch
    return register


# ---- Downloading ----------------------------------------------------------------------------

def open_url(url, *, headers=None, opener=None, timeout=120):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    if urllib.parse.urlsplit(url).hostname == "api.github.com" and os.environ.get("GITHUB_TOKEN"):
        # CI runners share IPs, so anonymous GitHub API calls can hit the rate limit. Unredirected:
        # the token is never forwarded if the API redirects elsewhere.
        request.add_unredirected_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    return (opener or urllib.request.build_opener()).open(request, timeout=timeout)


def download(url, path, *, size=None, opener=None, attempts=4):
    """Fetch url to path unless it is already there. Writes <path>.part and checks it against
    Content-Length, so a cut-off download is retried rather than kept. `size` pins the file
    for sources whose hard-coded corrections assume one exact upload: a different size means
    the upstream file changed, which is an error."""
    path = Path(path)
    if path.exists() and (size is None or path.stat().st_size == size):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    for attempt in range(attempts):
        try:
            with open_url(url, opener=opener, timeout=300) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream, 1 << 20)
                expected = response.headers.get("Content-Length")
                if expected is not None and stream.tell() != int(expected):
                    raise OSError(f"{url}: received {stream.tell()} of {expected} bytes")
            break
        except TRANSIENT:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))
    if size is not None and partial.stat().st_size != size:
        raise ValueError(f"{url} is {partial.stat().st_size} bytes, expected {size}: the upstream file changed")
    partial.replace(path)
    return path


def download_many(pairs, *, workers=8, opener=None):
    """download() each (url, path) or (url, path, size), several at a time."""
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(lambda pair: download(*pair[:2], size=(pair[2:] or [None])[0], opener=opener),
                              pairs))


def cookie_opener():
    """Opener that keeps cookies, for share links that set an access cookie before the download."""
    from http.cookiejar import CookieJar
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


class RemoteFile(io.RawIOBase):
    """Seekable read-only view of a remote file through HTTP Range requests, so zipfile can pull
    a few members out of a multi-GB archive. Reads ahead in RANGE_CHUNK blocks."""

    def __init__(self, url, opener=None, size=None):
        super().__init__()
        self.url, self.opener, self.position = url, opener, 0
        self.block_start, self.block = 0, b""
        with open_url(url, headers={"Range": "bytes=0-0"}, opener=opener) as response:
            content_range = response.headers.get("Content-Range")
            if response.status != 206 or not content_range:
                raise OSError(f"{url} does not support HTTP range requests")
            self.size = int(content_range.rsplit("/", 1)[1])
        if size is not None and self.size != size:
            raise ValueError(f"{url} is {self.size} bytes, expected {size}: the upstream file changed")

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.size}[whence]
        self.position = base + offset
        return self.position

    def _fetch(self, start, length):
        end = min(start + length, self.size) - 1
        for attempt in range(4):
            try:
                with open_url(self.url, headers={"Range": f"bytes={start}-{end}"}, opener=self.opener,
                              timeout=300) as response:
                    # A 200 (whole file) or an HTML login page must never be read as archive bytes.
                    if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                        raise OSError(f"{self.url}: asked for bytes {start}-{end}, got HTTP {response.status} "
                                      f"{response.headers.get('Content-Range')!r}")
                    data = response.read()
                if len(data) != end - start + 1:
                    raise OSError(f"{self.url}: range {start}-{end} returned {len(data)} bytes")
                return data
            except TRANSIENT:
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))

    def readinto(self, buffer):
        if self.position >= self.size:
            return 0
        offset = self.position - self.block_start
        if not 0 <= offset < len(self.block):
            self.block_start, self.block = self.position, self._fetch(self.position, max(len(buffer), RANGE_CHUNK))
            offset = 0
        count = min(len(buffer), len(self.block) - offset)
        buffer[:count] = self.block[offset:offset + count]
        self.position += count
        return count


def remote_zip(url, opener=None, size=None):
    """zipfile.ZipFile over HTTP; only the central directory and requested members are fetched.
    `size` pins the archive as in download()."""
    return zipfile.ZipFile(io.BufferedReader(RemoteFile(url, opener, size), RANGE_CHUNK))


def extract(archive, names, destination):
    """Extract archive members to destination/<member path>, skipping files already present.
    Refuses absolute or parent-relative member names."""
    destination = Path(destination)
    out = []
    for name in names:
        target = destination / name
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError(f"Unsafe archive member name: {name}")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            with archive.open(name) as source_stream, partial.open("wb") as stream:
                shutil.copyfileobj(source_stream, stream, 1 << 20)
            partial.replace(target)
        out.append(target)
    return out


def read_csv(path):
    """Rows as dicts with stripped header names (some sources pad them with spaces)."""
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(stream)]


# ---- Video ----------------------------------------------------------------------------------

def video_info(path):
    """(fps, decoded frame count, (width, height)). Counts frames by decoding, as predict_video.py
    and the labeling tool read them, because container frame counts can be wrong."""
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open {path}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        size = (round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        frames = 0
        while capture.grab():
            frames += 1
    finally:
        capture.release()
    return fps, frames, size


def video_size(path):
    """(width, height) from the container, without decoding."""
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        return round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        capture.release()


def encode_frames(images, fps, output):
    """Encode an ordered list of image files as constant-frame-rate H.264, so decoded frame i is
    images[i]. Near-lossless (CRF 12) to keep tiny balls intact."""
    from imageio_ffmpeg import get_ffmpeg_exe
    output = Path(output)
    if output.exists():
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = Path(images[0]).suffix
    with tempfile.TemporaryDirectory(prefix=".encode-", dir=output.parent) as temp:
        for i, image in enumerate(images):
            os.symlink(Path(image).resolve(), Path(temp) / f"{i:06d}{suffix}")
        staged = Path(temp) / output.name
        command = [get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-framerate", f"{fps:g}", "-i", str(Path(temp) / f"%06d{suffix}"),
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "12", "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-movflags", "+faststart",
                   str(staged)]
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if result.returncode:
            raise RuntimeError(f"ffmpeg failed for {output}: {result.stderr[-1500:].strip()}")
        staged.replace(output)
    return output


def link_video(video, output):
    """Hard-link (or copy) a source video into clips/ unchanged, so frame indices stay as labeled.
    Replaces an existing clip that no longer matches the download (e.g. after a re-download)."""
    output = Path(output)
    if output.exists() and (os.path.samefile(video, output) or output.stat().st_size == Path(video).stat().st_size):
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(f".{output.name}.{os.getpid()}.part")
    try:
        os.link(video, staged)
    except OSError:
        shutil.copy2(video, staged)
    staged.replace(output)
    return output


# ---- Labels ---------------------------------------------------------------------------------

def ball_box(x, y, size):
    half = BALL_BOX_FRACTION * max(size) / 2
    return [round(x - half, 1), round(y - half, 1), round(x + half, 1), round(y + half, 1)]


def write_clip(root, name, video, points, *, notes=""):
    """Write labels/<name>.json for clips/<name>.mp4 and return the clip record.

    points: {frame index: (x, y) or None, or a dict with "ball" ((x, y) or None) plus optional
    extra fields such as "visibility" and "event" (None values are dropped)}. Frames past the end
    of the video are an error: they would mean the labels and video do not line up.
    """
    fps, frame_count, size = video_info(video)
    if not points:
        raise ValueError(f"{name}: no labeled frames")
    if max(points) >= frame_count:
        raise ValueError(f"{name}: labels reach frame {max(points)} but the video decodes {frame_count} frames")
    labels = {}
    for frame, value in sorted(points.items()):
        value = value if isinstance(value, dict) else {"ball": value}
        point = value["ball"]
        label = {"time_s": round(frame / fps, 6),
                 "ball": None if point is None else ball_box(point[0], point[1], size),
                 "origin": "external" if point is not None else "absent"}
        label.update({k: v for k, v in value.items() if k != "ball" and v is not None})
        labels[frame] = label
    path = Path(root) / "labels" / f"{name}.json"
    # absolute(), not resolve(): ml/external may be a symlink to a copy shared between checkouts.
    video = Path(video).absolute().relative_to(ROOT)
    save_labels(path, labels, video=video, video_size=size, detections=None)
    visible = sum(v["ball"] is not None for v in labels.values())
    return {"clip": name, "video": str(video), "labels": str(path.absolute().relative_to(ROOT)),
            "fps": round(fps, 3), "size": list(size),
            "frames": frame_count, "labeled": len(labels), "visible": visible,
            "events": sum("event" in v for v in labels.values()), **({"notes": notes} if notes else {})}


def fetch_source(name):
    """Download and convert one source; write its source.json. Returns the clip records."""
    spec = SOURCES[name]
    root = EVAL / name
    clips = spec.fetch(root)
    record = {"source": name, "sport": spec.sport, "view": spec.view, "license": spec.license,
              "url": spec.url, "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "clips": clips}
    (root / "source.json").write_text(json.dumps(record, indent=1) + "\n")
    return clips


def fetched_sources():
    """source.json records of every converted source, by name."""
    return {p.parent.name: json.loads(p.read_text()) for p in sorted(EVAL.glob("*/source.json"))}
