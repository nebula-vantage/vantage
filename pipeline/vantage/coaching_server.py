"""Local desktop coaching workspace. No detector, cloud account or web build required."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit
import webbrowser

from vantage.coaching import build_report, validate_stats
from vantage.coaching_ai import answer_question, configuration
from vantage.coaching_jobs import AnalysisJobs
from vantage.coaching_video import PlaybackCache


WEB_ROOT = Path(__file__).with_name("web")
MAX_BODY = 2 * 1024 * 1024
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/fonts.css": ("fonts.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/fonts/bricolage-grotesque-variable.woff2": ("fonts/bricolage-grotesque-variable.woff2", "font/woff2"),
    "/fonts/ibm-plex-sans-variable.woff2": ("fonts/ibm-plex-sans-variable.woff2", "font/woff2"),
    "/fonts/ibm-plex-mono-regular.woff2": ("fonts/ibm-plex-mono-regular.woff2", "font/woff2"),
    "/fonts/ibm-plex-mono-medium.woff2": ("fonts/ibm-plex-mono-medium.woff2", "font/woff2"),
}


def decode_json(raw: bytes):
    def reject_constant(value):
        raise ValueError("JSON numbers must be finite.")
    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Choose a valid stats.json exported by Vantage.") from exc


def read_stats(path: Path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError("Statistics file exceeds the 2 MB limit.")
    return validate_stats(decode_json(raw))


class SessionLibrary:
    """Read only completed runs in the selected directory and its direct children."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def _inside(self, path: Path) -> bool:
        return path.resolve().is_relative_to(self.root)

    def directories(self):
        if not self.root.is_dir():
            return {}
        candidates = [self.root]
        candidates.extend(sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")))
        return {
            hashlib.sha256(str(p.relative_to(self.root)).encode()).hexdigest()[:20]: p
            for p in candidates
            if self._inside(p) and (p / "stats.json").is_file() and self._inside(p / "stats.json")
        }

    def list_sessions(self):
        sessions, errors = [], []
        for session_id, directory in self.directories().items():
            try:
                stats = read_stats(directory / "stats.json")
                sessions.append({"id": session_id, "name": stats.get("session_name") or directory.name})
            except (OSError, ValueError):
                errors.append(f"Could not load {directory.name}: check its stats.json export.")
        return {"sessions": sessions, "errors": errors}

    def media(self, session_id: str, name: str):
        if name not in ("annotated.mp4", "prepared.mp4", "landing_heatmap.png"):
            return None
        directory = self.directories().get(session_id)
        if directory is None:
            return None
        path = directory / name
        return path if path.is_file() and self._inside(path) else None

    def session(self, session_id: str):
        directory = self.directories().get(session_id)
        if directory is None:
            return None
        video = next((name for name in ("annotated.mp4", "prepared.mp4") if self.media(session_id, name)), None)
        if video == "annotated.mp4":
            video = "playback.mp4"
        heatmap = self.media(session_id, "landing_heatmap.png")
        stats = read_stats(directory / "stats.json")
        return {"id": session_id, "name": stats.get("session_name") or directory.name, "is_demo": stats.get("synthetic", False),
                "stats": stats, "video_url": f"/media/{session_id}/{video}" if video else None,
                "heatmap_url": f"/media/{session_id}/landing_heatmap.png" if heatmap else None}


class CoachingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, runs_dir: Path):
        self.library = SessionLibrary(runs_dir)
        super().__init__(address, CoachingHandler)
        self.playback_dir = tempfile.TemporaryDirectory(prefix="vantage-coach-")
        self.playback = PlaybackCache(Path(self.playback_dir.name))
        self.jobs = AnalysisJobs(self.library.root)

    def server_close(self):
        if hasattr(self, "jobs"):
            self.jobs.close()
        super().server_close()
        if hasattr(self, "playback_dir"):
            self.playback_dir.cleanup()


class CoachingHandler(BaseHTTPRequestHandler):
    server_version = "VantageCoach/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(40)

    def log_message(self, fmt, *args):
        # Do not log session paths, questions or provider responses.
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        super().end_headers()

    def _local_request(self):
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed_hosts:
            self._json({"error": "Open this workspace using its localhost address."}, 403)
            return False
        origin = self.headers.get("Origin")
        if ((origin and origin not in {f"http://{host}" for host in allowed_hosts}) or
                self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self._json({"error": "Cross-origin requests are not allowed."}, 403)
            return False
        return True

    def _json(self, body, status=200):
        data = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _file(self, path, content_type, ranges=False):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        requested = self.headers.get("Range") if ranges else None
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            try:
                if match is None or not any(match.groups()):
                    raise ValueError
                a, b = match.groups()
                if a:
                    start = int(a)
                    end = min(int(b), size - 1) if b else size - 1
                else:
                    length = int(b)
                    if length <= 0:
                        raise ValueError
                    start = max(0, size - length)
                if not 0 <= start <= end < size:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        if ranges:
            self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = stream.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        try:
            if path in STATIC_FILES:
                filename, content_type = STATIC_FILES[path]
                return self._file(WEB_ROOT / filename, content_type)
            if path == "/api/config":
                return self._json({**configuration(), **self.server.jobs.config()})
            if path.startswith("/api/analysis/"):
                parts = path.split("/")
                if len(parts) == 4:
                    job = self.server.jobs.get(parts[3])
                    if job:
                        return self._json(job)
                elif len(parts) == 5 and parts[4] == "preview":
                    preview = self.server.jobs.preview(parts[3])
                    if preview:
                        return self._file(preview, "image/png")
                return self._json({"error": "This analysis is unavailable. Upload the video again."}, 404)
            if path == "/api/sessions":
                return self._json(self.server.library.list_sessions())
            if path == "/api/demo":
                stats = read_stats(WEB_ROOT / "demo-stats.json")
                return self._json({"id": "demo", "name": "Demo session", "is_demo": True,
                                   "stats": stats, "video_url": None, "heatmap_url": None})
            if path.startswith("/api/sessions/"):
                session = self.server.library.session(path.removeprefix("/api/sessions/"))
                if session:
                    return self._json(session)
            if path.startswith("/media/"):
                parts = path.split("/")
                if len(parts) == 4:
                    if parts[3] == "playback.mp4":
                        original = self.server.library.media(parts[2], "annotated.mp4")
                        media = self.server.playback.get(original) if original else None
                    else:
                        media = self.server.library.media(parts[2], parts[3])
                    if media:
                        return self._file(media, "image/png" if media.suffix == ".png" else "video/mp4", ranges=True)
            self._json({"error": "This session or file is unavailable."}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError):
            self._json({"error": "Unable to load this session. Check its stats.json export."}, 400)
        except RuntimeError:
            self._json({"error": "Unable to prepare the video. Attach a matching H.264 MP4 to continue."}, 503)

    def do_POST(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/analysis":
            return self._upload_video()
        parts = path.split("/")
        job_action = (len(parts) == 5 and parts[1:3] == ["api", "analysis"]
                      and parts[4] in ("start", "cancel"))
        if path not in ("/api/session", "/api/report", "/api/chat") and not job_action:
            return self._json({"error": "Unknown endpoint."}, 404)
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json({"error": "Send application/json."}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                return self._json({"error": "Request must be between 1 byte and 2 MB."}, 413)
            body = decode_json(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Request must be a JSON object.")
            if job_action:
                if self.server.jobs.get(parts[3]) is None:
                    return self._json({"error": "This analysis is unavailable. Upload the video again."}, 404)
                if parts[4] == "cancel":
                    return self._json(self.server.jobs.cancel(parts[3]))
                return self._json(self.server.jobs.start(parts[3], body.get("corners"), body.get("synthetic", False)), 202)
            stats = validate_stats(body.get("stats"))
            focus = body.get("focus", "consistency")
            if focus not in ("consistency", "placement", "review"):
                raise ValueError("Choose consistency, placement or review as your focus.")
            if path == "/api/session":
                name = body.get("name", "Imported session")
                if not isinstance(name, str) or not name.strip() or len(name) > 200:
                    raise ValueError("Session name must be between 1 and 200 characters.")
                session_id = build_report(stats, focus)["session_id"]
                return self._json({"id": session_id, "name": name.strip(), "is_demo": stats.get("synthetic", False),
                                   "stats": stats, "video_url": None, "heatmap_url": None})
            report = build_report(stats, focus)
            if path == "/api/report":
                return self._json(report)
            use_ai = body.get("use_ai", False)
            if not isinstance(use_ai, bool):
                raise ValueError("use_ai must be true or false.")
            return self._json(answer_question(report, body.get("message"), body.get("history", []), use_ai))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, RecursionError) as exc:
            self._json({"error": str(exc) if isinstance(exc, ValueError) else "JSON nesting is too deep."}, 400)
        except Exception:
            # Keep imported data, local paths and provider credentials out of errors.
            self._json({"error": "Coaching is temporarily unavailable. Please try again."}, 500)

    def _upload_video(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/octet-stream":
            return self._json({"error": "Send the video as application/octet-stream."}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            config = self.server.jobs.config()
            if not 0 < length <= config["max_upload_bytes"]:
                return self._json({"error": "Choose a video between 1 byte and 512 MB."}, 413)
            if not config["analysis_available"]:
                return self._json({"error": config.get("analysis_error", "Video analysis is not configured.")}, 503)
            query = parse_qs(urlsplit(self.path).query, max_num_fields=3)
            name = query.get("name", [""])[0]
            job = self.server.jobs.create_upload(name, self.rfile, length)
            return self._json(job, 202)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except (OSError, TimeoutError):
            self._json({"error": "The upload could not be saved. Check free disk space and try again."}, 400)
        except Exception:
            self._json({"error": "Could not start video analysis. Please try again."}, 500)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open Vantage's local desktop/web coaching workspace.")
    parser.add_argument("--runs-dir", type=Path, default=Path("output"),
                        help="Completed run directory or directory of runs (default: output).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the workspace in your default browser.")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        server = CoachingServer(("127.0.0.1", args.port), args.runs_dir)
    except OSError as exc:
        print(f"Could not start coaching: {exc}. Try a different --port.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Vantage Coach: {url}\nReading completed runs from {args.runs_dir.resolve()}\nPress Ctrl+C to stop.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
