"""Exercise real HTTP requests, local-file boundaries and the browser API contract."""

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from vantage.coaching_server import MAX_BODY, WEB_ROOT, CoachingServer, decode_json


class CoachingServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.run = self.runs / "weekend"
        self.run.mkdir(parents=True)
        self.stats = json.loads((WEB_ROOT / "demo-stats.json").read_text())
        (self.run / "stats.json").write_text(json.dumps(self.stats))
        (self.run / "annotated.mp4").write_bytes(b"0123456789")
        self.server = CoachingServer(("127.0.0.1", 0), self.runs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(conn.close)
        headers = dict(headers or {})
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        data = (
            json.loads(raw)
            if "application/json" in response.getheader("Content-Type", "") and raw
            else raw
        )
        return response.status, data, dict(response.getheaders())

    def test_demo_import_report_chat_round_trip(self):
        status, demo, _ = self.request("GET", "/api/demo")
        self.assertEqual(status, 200)
        self.assertTrue(demo["is_demo"])
        status, session, _ = self.request(
            "POST", "/api/session", {"stats": demo["stats"], "name": "My game"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(session["name"], "My game")
        self.assertIsNone(session["video_url"])
        status, report, _ = self.request(
            "POST", "/api/report", {"stats": session["stats"], "focus": "placement"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(report["focus"], "placement")
        self.assertEqual(report["session_id"], session["id"])
        with patch(
            "vantage.coaching_ai.urlopen", side_effect=AssertionError("No consent, no network")
        ):
            status, reply, _ = self.request(
                "POST",
                "/api/chat",
                {"stats": session["stats"], "message": "What should I practice?"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(reply["source"], "local")
        self.assertTrue(reply["answer"])

    def test_library_lists_only_valid_runs_and_serves_known_media(self):
        invalid = self.runs / "incomplete"
        invalid.mkdir()
        (invalid / "stats.json").write_text("{}")
        status, listing, _ = self.request("GET", "/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["sessions"]), 1)
        self.assertEqual(len(listing["errors"]), 1)
        sid = listing["sessions"][0]["id"]
        status, session, _ = self.request("GET", f"/api/sessions/{sid}")
        self.assertEqual(status, 200)
        self.assertEqual(session["video_url"], f"/media/{sid}/playback.mp4")
        with patch.object(
            self.server.playback, "get", return_value=self.run / "annotated.mp4"
        ) as playback:
            status, body, headers = self.request(
                "GET", session["video_url"], headers={"Range": "bytes=2-5"}
            )
            playback.assert_called_once_with((self.run / "annotated.mp4").resolve())
        self.assertEqual((status, body), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        media_url = f"/media/{sid}/annotated.mp4"
        status, body, _ = self.request("GET", media_url, headers={"Range": "bytes=-3"})
        self.assertEqual((status, body), (206, b"789"))
        for value in ("bytes=30-", "bytes=5-2", "bytes=0-2,4-6", "bytes=-0"):
            self.assertEqual(self.request("GET", media_url, headers={"Range": value})[0], 416)
        status, body, headers = self.request("HEAD", media_url)
        self.assertEqual((status, body, headers["Content-Length"]), (200, b"", "10"))
        self.assertEqual(self.request("GET", f"/media/{sid}/stats.json")[0], 404)
        with patch.object(self.server.playback, "get", side_effect=RuntimeError("private path")):
            status, body, _ = self.request("GET", session["video_url"])
        self.assertEqual(status, 503)
        self.assertNotIn("private path", json.dumps(body))

    def test_cannot_serve_paths_or_symlinks_outside_selected_runs(self):
        outside = self.root / "private"
        outside.mkdir()
        (outside / "stats.json").write_text(json.dumps(self.stats))
        (self.runs / "linked").symlink_to(outside, target_is_directory=True)
        (outside / "private.mp4").write_bytes(b"secret")
        (self.run / "annotated.mp4").unlink()
        (self.run / "annotated.mp4").symlink_to(outside / "private.mp4")
        _, listing, _ = self.request("GET", "/api/sessions")
        self.assertEqual(len(listing["sessions"]), 1)
        sid = listing["sessions"][0]["id"]
        _, session, _ = self.request("GET", f"/api/sessions/{sid}")
        self.assertIsNone(session["video_url"])
        for path in (
            f"/media/{sid}/annotated.mp4",
            "/../pyproject.toml",
            "/%2e%2e/pyproject.toml",
            "/app.js/../coaching_ai.py",
        ):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_rejects_cross_origin_and_dns_rebinding(self):
        for headers in (
            {"Origin": "https://example.com"},
            {"Host": "attacker.example"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            self.assertEqual(self.request("GET", "/api/demo", headers=headers)[0], 403)
            self.assertEqual(
                self.request("POST", "/api/report", {"stats": self.stats}, headers)[0], 403
            )
        origin = f"http://localhost:{self.server.server_port}"
        self.assertEqual(
            self.request("POST", "/api/report", {"stats": self.stats}, {"Origin": origin})[0], 200
        )

    def test_validation_and_private_config(self):
        # Never run the real `codex login status` check from a test.
        coach = {"engines": [], "default": None}
        with (
            patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "secret-key", "VANTAGE_COACH_MODEL": "test-model"},
            ),
            patch("vantage.coach_engines.configuration", return_value=coach),
        ):
            status, config, _ = self.request("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertTrue(config["ai_available"])
        self.assertEqual(config["coach"], coach)
        self.assertNotIn("secret-key", json.dumps(config))
        for payload in (
            {},
            {"stats": {}},
            {"stats": self.stats, "focus": []},
            {"stats": self.stats, "focus": "wins"},
        ):
            self.assertEqual(self.request("POST", "/api/report", payload)[0], 400)
        self.assertEqual(
            self.request(
                "POST", "/api/chat", {"stats": self.stats, "message": "Hi", "use_ai": "true"}
            )[0],
            400,
        )
        self.assertEqual(
            self.request("POST", "/api/report", b"{broken", {"Content-Type": "application/json"})[
                0
            ],
            400,
        )
        self.assertEqual(
            self.request("POST", "/api/report", b"{}", {"Content-Type": "text/plain"})[0], 415
        )
        # Rejection happens from headers, before the server accepts a large upload.
        self.assertEqual(
            self.request(
                "POST",
                "/api/report",
                b"",
                {"Content-Type": "application/json", "Content-Length": str(MAX_BODY + 1)},
            )[0],
            413,
        )
        with self.assertRaises(ValueError):
            decode_json(b'{"number": NaN}')

    def test_static_app_has_security_headers_and_missing_library_is_empty(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Vantage", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertLess(body.index(b'src="/api.js"'), body.index(b'src="/app.js"'))
        status, script, script_headers = self.request("GET", "/api.js")
        self.assertEqual(status, 200)
        self.assertEqual(script, (WEB_ROOT / "api.js").read_bytes())
        self.assertIn("text/javascript", script_headers["Content-Type"])
        self.server.library.root = self.root / "missing"
        self.assertEqual(self.request("GET", "/api/sessions")[1], {"sessions": [], "errors": []})


if __name__ == "__main__":
    unittest.main()
