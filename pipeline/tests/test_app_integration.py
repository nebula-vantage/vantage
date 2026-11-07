"""HTTP contracts for one Games app sharing saved analyses and coaching."""

import hashlib
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch

from replay_fixtures import doubles, write_run
from vantage.coaching_server import WEB_ROOT, CoachingServer
from vantage.replay import build_replay


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.run = self.runs / "weekend"
        self.run.mkdir(parents=True)
        self.stats = json.loads((WEB_ROOT / "demo-stats.json").read_text())
        self.stats["session_name"] = "Saturday practice"
        self.write_stats()
        self.sid = hashlib.sha256(b"weekend").hexdigest()[:20]
        jobs = patch("vantage.coaching_server.AnalysisJobs", return_value=Mock())
        jobs.start()
        self.addCleanup(jobs.stop)
        self.server = CoachingServer(("127.0.0.1", 0), self.runs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def write_stats(self):
        (self.run / "stats.json").write_text(json.dumps(self.stats))

    def request(self, method, path, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            raw = response.read()
            body = (
                json.loads(raw)
                if raw and "application/json" in response.getheader("Content-Type", "")
                else raw
            )
            return response.status, body, dict(response.getheaders())
        finally:
            connection.close()

    def listed_game(self):
        status, listing, _ = self.request("GET", "/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(listing["errors"], [])
        self.assertEqual(len(listing["sessions"]), 1)
        return listing["sessions"][0]

    def test_game_and_coaching_deep_links_reload_the_same_app(self):
        status, shell, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        routes = (
            "/games",
            f"/games/{self.sid}",
            f"/games/{self.sid}/coaching",
            f"/games/{self.sid}/replay",
            "/games/sample",
            "/games/sample/coaching",
            "/games/sample/replay",
        )
        for route in routes:
            with self.subTest(route=route):
                status, body, route_headers = self.request("GET", route)
                self.assertEqual((status, body), (200, shell))
                self.assertEqual(route_headers["Content-Type"], headers["Content-Type"])
                self.assertIn("text/html", route_headers["Content-Type"])
                self.assertIn("frame-ancestors 'none'", route_headers["Content-Security-Policy"])
                status, body, head_headers = self.request("HEAD", route)
                self.assertEqual((status, body), (200, b""))
                self.assertEqual(int(head_headers["Content-Length"]), len(shell))

    def test_app_routes_do_not_turn_unknown_or_traversal_paths_into_the_shell(self):
        for route in (
            "/unknown",
            "/games/not-a-session",
            "/games/" + "a" * 19,
            "/games/" + "a" * 21,
            "/games/" + "A" * 20,
            f"/games/{self.sid}/private",
            f"/games/{self.sid}/replay/extra",
            "/games/sample/source.mp4",
            "/games/../../pyproject.toml",
            "/games/%2e%2e/pyproject.toml",
        ):
            with self.subTest(route=route):
                self.assertEqual(self.request("GET", route)[0], 404)
                self.assertEqual(self.request("HEAD", route)[0], 404)

    def test_replay_is_built_from_saved_tracking_once_and_rebuilt_when_it_changes(self):
        write_run(self.run, fps=30.0, frames=30, players=doubles)
        with patch("vantage.coaching_server.build_replay", wraps=build_replay) as built:
            status, replay, _ = self.request("GET", f"/api/sessions/{self.sid}/replay")
            self.assertEqual(status, 200)
            self.assertEqual(replay["measurement_type"], "estimated_3d_reconstruction")
            self.assertEqual(len(replay["players"]), 4)
            self.assertFalse(replay["synthetic"])
            self.assertEqual(self.request("GET", f"/api/sessions/{self.sid}/replay")[1], replay)
            self.assertEqual(built.call_count, 1)
            tracks = self.run / "tracks.jsonl"
            tracks.write_text(tracks.read_text() + "\n")
            self.assertEqual(self.request("GET", f"/api/sessions/{self.sid}/replay")[0], 200)
            self.assertEqual(built.call_count, 2)

    def test_replay_without_tracking_explains_what_is_missing(self):
        status, body, _ = self.request("GET", f"/api/sessions/{self.sid}/replay")
        self.assertEqual(status, 422)
        self.assertIn("Analyze its video again", body["error"])
        self.assertNotIn(str(self.root), body["error"])
        status, body, _ = self.request("GET", f"/api/sessions/{'0' * 20}/replay")
        self.assertEqual(status, 404)

    def test_sample_game_has_a_synthetic_replay_and_the_renderer_is_served(self):
        status, replay, _ = self.request("GET", "/api/demo/replay")
        self.assertEqual(status, 200)
        self.assertTrue(replay["synthetic"])
        self.assertEqual(len(replay["players"]), 4)
        status, script, headers = self.request("GET", "/replay.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers["Content-Type"])
        self.assertIn(b"VantageReplay", script)

    def test_game_summary_shares_saved_measurements_and_analysis_time(self):
        analyzed_at = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        os.utime(self.run / "stats.json", (analyzed_at.timestamp(), analyzed_at.timestamp()))
        game = self.listed_game()
        self.assertEqual(game["id"], self.sid)
        self.assertEqual(game["name"], "Saturday practice")
        self.assertTrue(game["is_demo"])
        self.assertEqual(game["duration_s"], self.stats["video"]["duration_s"])
        self.assertEqual(game["rally_count"], self.stats["rally_count"])
        self.assertEqual(game["shot_count"], self.stats["shot_count"])
        self.assertEqual(
            game["quality"],
            {
                "status": self.stats["quality"]["status"],
                "coverage": self.stats["quality"]["ball_detection_coverage"],
            },
        )
        parsed = datetime.fromisoformat(game["analyzed_at"].replace("Z", "+00:00"))
        self.assertEqual(parsed, analyzed_at)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)
        status, session, _ = self.request("GET", f"/api/sessions/{game['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(session["name"], game["name"])
        self.assertEqual(session["stats"]["shot_count"], game["shot_count"])

    def test_insufficient_evidence_is_missing_counts_in_the_games_list(self):
        self.stats.update(
            rally_count=0,
            shot_count=0,
            longest_rally=0,
            bounce_candidate_count=0,
            rallies=[],
            crossing_events=[],
            shots_per_rally=[],
            in_out_calls=[],
            avg_ball_speed_kmh=None,
        )
        self.stats["quality"].update(
            status="heuristic",
            ball_detection_coverage=0,
            observed_frames=0,
            valid_speed_duration_s=0,
            valid_speed_coverage=0,
        )
        self.write_stats()
        game = self.listed_game()
        self.assertEqual(game["quality"], {"status": "insufficient_evidence", "coverage": 0})
        self.assertIsNone(game["rally_count"])
        self.assertIsNone(game["shot_count"])
        # Keep the engine's raw zero counts in the full analysis; only presentation is missing.
        _, session, _ = self.request("GET", f"/api/sessions/{self.sid}")
        self.assertEqual(session["stats"]["rally_count"], 0)
        self.assertEqual(session["stats"]["shot_count"], 0)

    def test_listing_checks_media_presence_without_decoding_or_transcoding(self):
        (self.run / "annotated.mp4").write_bytes(b"deliberately not a decodable video")
        thumbnail = b"\x89PNG\r\n\x1a\nsaved-thumbnail"
        (self.run / "thumbnail.png").write_bytes(thumbnail)
        with (
            patch.object(
                self.server.playback, "get", side_effect=AssertionError("No list-time conversion")
            ),
            patch("cv2.VideoCapture", side_effect=AssertionError("No list-time video probing")),
            patch("subprocess.run", side_effect=AssertionError("No list-time subprocess")),
        ):
            game = self.listed_game()
        self.assertTrue(game["has_video"])
        self.assertEqual(game["thumbnail_url"], f"/media/{self.sid}/thumbnail.png")
        status, body, headers = self.request("GET", game["thumbnail_url"])
        self.assertEqual((status, body), (200, thumbnail))
        self.assertEqual(headers["Content-Type"], "image/png")
        status, body, headers = self.request("HEAD", game["thumbnail_url"])
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(int(headers["Content-Length"]), len(thumbnail))

    def test_missing_media_and_optional_synthetic_flag_have_honest_defaults(self):
        self.stats.pop("synthetic")
        self.write_stats()
        game = self.listed_game()
        self.assertFalse(game["is_demo"])
        self.assertFalse(game["has_video"])
        self.assertIsNone(game["thumbnail_url"])
        (self.run / "prepared.mp4").write_bytes(b"saved prepared video")
        self.assertTrue(self.listed_game()["has_video"])

    def test_thumbnail_video_and_directory_symlinks_cannot_escape_the_library(self):
        outside = self.root / "private"
        outside.mkdir()
        (outside / "stats.json").write_text(json.dumps(self.stats))
        (outside / "video.mp4").write_bytes(b"private video")
        (outside / "thumbnail.png").write_bytes(b"private thumbnail")
        (self.runs / "linked").symlink_to(outside, target_is_directory=True)
        (self.run / "thumbnail.png").symlink_to(outside / "thumbnail.png")
        (self.run / "annotated.mp4").symlink_to(outside / "video.mp4")
        game = self.listed_game()
        self.assertFalse(game["has_video"])
        self.assertIsNone(game["thumbnail_url"])
        linked_sid = hashlib.sha256(b"linked").hexdigest()[:20]
        for path in (
            f"/media/{self.sid}/thumbnail.png",
            f"/media/{self.sid}/annotated.mp4",
            f"/media/{linked_sid}/thumbnail.png",
            f"/api/sessions/{linked_sid}",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_new_app_media_does_not_expose_source_video_or_arbitrary_files(self):
        (self.run / "source.mp4").write_bytes(b"private uploaded source")
        (self.run / "private.txt").write_text("private data")
        for name in (
            "source.mp4",
            "private.txt",
            "stats.json",
            "../private.txt",
            "%2e%2e/private.txt",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.request("GET", f"/media/{self.sid}/{name}")[0], 404)
        game = self.listed_game()
        self.assertFalse(game["has_video"])
        self.assertNotIn(str(self.root), json.dumps(game))


if __name__ == "__main__":
    unittest.main()
