"""The AI video coach service and its HTTP routes, with a fake engine (no CLIs, no network)."""

import hashlib
import json
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from coach_fixtures import make_run
from vantage import coach_evidence
from vantage.coach_engines import EngineCancelled, EngineError, Image
from vantage.coach_evidence import COACH_DIR, FRAMES_DIR, EvidenceError
from vantage.coaching_server import CoachingServer, SessionLibrary
from vantage.video_coach import (
    ANALYSIS_SCHEMA,
    ANALYSIS_SYSTEM,
    ANALYSIS_TIMEOUT_S,
    CHAT_SCHEMA,
    CHAT_SYSTEM,
    CHAT_TIMEOUT_S,
    NO_VIDEO,
    PROMPT_VERSION,
    CoachService,
    SessionUnavailable,
    mentioned_times,
    sanitize_analysis,
    sanitize_chat,
)


def review(**changes):
    result = {
        "headline": "Get both partners to the kitchen line together.",
        "summary": "The far team lives at the kitchen. The near-right player hangs back in transition.",
        "players": [
            {
                "label": "Near-left player",
                "side": "near",
                "description": "Yellow top.",
                "is_user": True,
            },
            {
                "label": "Near-right player",
                "side": "near",
                "description": "Yellow top.",
                "is_user": False,
            },
        ],
        "strengths": [
            {
                "title": "Far team at the line",
                "detail": "Both far players hold the kitchen line.",
                "moment_ids": ["m02"],
                "time_s": [2.0],
            }
        ],
        "improvements": [
            {
                "title": "Close the gap after the return",
                "priority": "high",
                "observation": "At m02 the near-right player is 4.2 m from the net.",
                "why_it_matters": "Opponents attack the feet of a player in transition.",
                "how_to_fix": "Follow your return in and split-step as they hit.",
                "drill": {
                    "name": "Return and close",
                    "instructions": "Return deep, move to the line.",
                    "target": "8 of 10 returns with both partners at the line by the third shot.",
                },
                "moment_ids": ["m02", "m03"],
                "time_s": [2.1],
            }
        ],
        "moment_notes": [{"moment_id": "m02", "note": "Watch the near-right player's depth."}],
        "next_focus": "Arrive at the kitchen together.",
        "limitations": "Stills cannot show footwork timing.",
    }
    result.update(changes)
    return result


class FakeEngine:
    """Records requests; answers with a canned dict, raises, or waits for cancel."""

    def __init__(self, reply=None, error=None, block=False):
        self.id, self.label, self.model = "fake-cli", "Fake Coach", "fake-1"
        self.reply = reply if reply is not None else review()
        self.error = error
        self.block = block
        self.requests = []
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def status(self):
        return {
            "id": self.id,
            "label": self.label,
            "available": True,
            "detail": None,
            "model": self.model,
        }

    def run(self, request, cancel=None):
        self.requests.append(request)
        self.started.set()
        if self.block:
            if cancel is None or not cancel.wait(10):
                raise AssertionError("The fake engine was never cancelled.")
            self.cancelled.set()
            raise EngineCancelled()
        if self.error is not None:
            raise self.error
        return deepcopy(self.reply)


class FakeEngines:
    def __init__(self, engine):
        self.engine = engine
        self.selected = []

    def configuration(self):
        return {"engines": [self.engine.status()], "default": self.engine.id}

    def select_engine(self, engine_id):
        self.selected.append(engine_id)
        if engine_id not in (None, self.engine.id):
            raise ValueError("Choose a valid coach engine.")
        return self.engine


def session_id(name):
    return hashlib.sha256(name.encode()).hexdigest()[:20]


class CoachTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = Path(self.temp.name).resolve() / "runs"
        self.run = make_run(self.runs / "game")
        self.sid = session_id("game")
        self.engine = FakeEngine()
        self.engines = FakeEngines(self.engine)

    def service(self):
        service = CoachService(SessionLibrary(self.runs), engines=self.engines)
        self.addCleanup(service.close)
        return service

    def wait_for(self, read, done, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = read()
            if done(value):
                return value
            time.sleep(0.02)
        self.fail(f"Timed out waiting; last value: {value}")


class CoachServiceTests(CoachTestCase):
    def finished(self, service, sid=None):
        return self.wait_for(
            lambda: service.status(sid or self.sid),
            lambda status: status["state"] in ("completed", "failed", "cancelled"),
        )

    def test_status_before_analysis_without_video_and_for_unknown_games(self):
        make_run(self.runs / "no-video", with_video=False)
        service = self.service()
        status = service.status(self.sid)
        self.assertEqual(
            (status["available"], status["state"], status["analysis"], status["moments"]),
            (True, "none", None, []),
        )
        status = service.status(session_id("no-video"))
        self.assertEqual((status["available"], status["reason"]), (False, NO_VIDEO))
        with self.assertRaises(EvidenceError):
            service.analyze(session_id("no-video"))
        for unknown in ("demo", "f" * 20, "../game", None, self.sid.upper()):
            with self.subTest(unknown=unknown), self.assertRaises(SessionUnavailable):
                service.status(unknown)
        self.assertEqual(self.engines.selected, [])

    def test_analysis_runs_to_completion_is_saved_and_reloaded(self):
        service = self.service()
        status = service.analyze(self.sid, player="  near-left, yellow top  ")
        self.assertIn(status["state"], ("queued", "preparing", "coaching", "completed"))
        status = self.finished(service)
        self.assertEqual(status["state"], "completed", status["error"])
        self.assertEqual(
            status["analysis"]["headline"], "Get both partners to the kitchen line together."
        )
        self.assertTrue(status["analysis"]["players"][0]["is_user"])
        self.assertEqual(status["meta"]["engine"], "fake-cli")
        self.assertEqual(status["meta"]["engine_label"], "Fake Coach")
        self.assertEqual(status["meta"]["model"], "fake-1")
        self.assertEqual(status["meta"]["player"], "near-left, yellow top")
        self.assertEqual([m["id"] for m in status["moments"]], ["m01", "m02", "m03"])
        self.assertEqual(status["moments"][0]["frame_url"], f"/media/{self.sid}/coach/m01.jpg")
        self.assertEqual(
            set(status["moments"][0]),
            {"id", "time_s", "start_s", "end_s", "kind", "title", "frame_url"},
        )

        request = self.engine.requests[0]
        self.assertEqual(
            (request.system, request.schema, request.purpose, request.timeout_s),
            (ANALYSIS_SYSTEM, ANALYSIS_SCHEMA, "analysis", ANALYSIS_TIMEOUT_S),
        )
        images = [part for part in request.parts if isinstance(part, Image)]
        self.assertEqual(len(images), 3)
        self.assertEqual(request.stable_parts, 4)
        self.assertTrue(all(isinstance(part, Image) for part in request.parts[1:4]))
        self.assertTrue(images[1].label.startswith("Moment m02 · "))
        self.assertTrue(
            all(
                image.path.is_file() and image.path.parent == self.run / COACH_DIR / FRAMES_DIR
                for image in images
            )
        )
        data = json.loads(request.parts[0].split("\n", 1)[1])
        self.assertEqual(
            set(data), {"video", "court", "tracking", "positioning", "moments", "warnings", "stats"}
        )
        self.assertNotIn("source", data["video"])
        self.assertNotIn("frame", data["moments"][0])
        self.assertEqual(data["stats"]["shots_per_rally"], [3])
        self.assertNotIn("/private/never/used.mp4", request.parts[0])
        self.assertIn('"near-left, yellow top"', request.parts[4])
        self.assertTrue(request.parts[5].startswith("Task:"))

        saved = json.loads((self.run / COACH_DIR / "analysis.json").read_text())
        self.assertEqual(saved["prompt_version"], PROMPT_VERSION)
        self.assertEqual(saved["analysis"], status["analysis"])
        self.assertTrue(saved["created_at"].endswith("+00:00"))
        reloaded = self.service().status(self.sid)
        self.assertEqual(
            (reloaded["state"], reloaded["analysis"]), ("completed", status["analysis"])
        )
        self.assertEqual(reloaded["meta"]["elapsed_s"], saved["elapsed_s"])

        # Without force an up-to-date review is returned, not redone.
        self.assertEqual(service.analyze(self.sid)["state"], "completed")
        self.assertEqual(len(self.engine.requests), 1)
        with patch.object(
            coach_evidence, "build_evidence", wraps=coach_evidence.build_evidence
        ) as build:
            service.analyze(self.sid, force=True)
            self.assertEqual(self.finished(service)["state"], "completed")
            self.assertEqual(build.call_count, 1)
        self.assertEqual(len(self.engine.requests), 2)
        self.assertIn("hasn't said", self.engine.requests[1].parts[4])

        # Changed measurements make the saved review stale.
        stats = json.loads((self.run / "stats.json").read_text())
        stats["avg_ball_speed_kmh"] = 30.0
        (self.run / "stats.json").write_text(json.dumps(stats))
        self.assertEqual(self.service().status(self.sid)["state"], "none")

    def test_duplicate_analyze_reuses_the_job_and_cancel_stops_the_engine(self):
        self.engine.block = True
        service = self.service()
        service.analyze(self.sid)
        self.assertTrue(self.engine.started.wait(10))
        status = service.status(self.sid)
        self.assertEqual(
            (status["state"], status["stage"]), ("coaching", "Your coach is watching 3 key moments")
        )
        self.assertIsInstance(status["elapsed_s"], float)
        self.assertEqual(service.analyze(self.sid, force=True)["state"], "coaching")
        self.assertEqual(len(self.engines.selected), 1)
        status = service.cancel(self.sid)
        self.assertEqual(status["state"], "cancelled")
        self.assertTrue(self.engine.cancelled.wait(5))
        time.sleep(0.05)
        status = service.status(self.sid)
        self.assertEqual(
            (status["state"], status["error"], status["analysis"]), ("cancelled", None, None)
        )
        self.assertFalse((self.run / COACH_DIR / "analysis.json").exists())
        # A cancelled game can be analyzed again.
        self.engine.block = False
        service.analyze(self.sid)
        self.assertEqual(self.finished(service)["state"], "completed")

    def test_close_cancels_running_analysis(self):
        self.engine.block = True
        service = CoachService(SessionLibrary(self.runs), engines=self.engines)
        service.analyze(self.sid)
        self.assertTrue(self.engine.started.wait(10))
        service.close()
        self.assertTrue(self.engine.cancelled.is_set())
        self.assertEqual(service.status(self.sid)["state"], "cancelled")
        with self.assertRaises(EngineError):
            service.analyze(self.sid)

    def test_close_cancels_chats_and_waits_for_their_engines(self):
        self.engine.block = True
        service = CoachService(SessionLibrary(self.runs), engines=self.engines)
        errors = []

        def ask():
            try:
                service.chat(self.sid, message="How was our positioning?")
            except EngineError as exc:
                errors.append(exc)

        thread = threading.Thread(target=ask, daemon=True)
        thread.start()
        self.assertTrue(self.engine.started.wait(10))
        service.close()
        # The engine has stopped before close() returns, so its CLI can't outlive the server.
        self.assertTrue(self.engine.cancelled.is_set())
        thread.join(timeout=5)
        self.assertEqual([type(error) for error in errors], [EngineCancelled])

    def test_engine_and_unexpected_errors_fail_with_safe_messages(self):
        service = self.service()
        self.engine.error = EngineError("Claude Code reached its usage limit. Try again later.")
        service.analyze(self.sid)
        status = self.finished(service)
        self.assertEqual(
            (status["state"], status["error"]),
            ("failed", "Claude Code reached its usage limit. Try again later."),
        )
        self.engine.error = RuntimeError("/private/secret/path exploded")
        with self.assertLogs("vantage.video_coach", "ERROR"):
            service.analyze(self.sid)
            status = self.finished(service)
        self.assertEqual(status["state"], "failed")
        self.assertNotIn("/private", status["error"])
        self.engine.error, self.engine.reply = None, {"headline": " ", "summary": ""}
        service.analyze(self.sid)
        self.assertEqual(
            self.finished(service)["error"], "The coach returned an empty response. Try again."
        )
        with self.assertRaises(ValueError):
            service.analyze(self.sid, engine="unknown-engine")
        for bad in (
            {"player": "x" * 201},
            {"player": "near\nside"},
            {"player": 3},
            {"force": "yes"},
            {"engine": 5},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                service.analyze(self.sid, **bad)

    def test_previous_review_stays_visible_while_a_rerun_fails(self):
        service = self.service()
        service.analyze(self.sid)
        first = self.finished(service)
        self.engine.error = EngineError("Codex couldn't finish the review. Try again.")
        service.analyze(self.sid, force=True)
        status = self.finished(service)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["analysis"], first["analysis"])

    def test_sanitize_analysis_drops_unknown_references_and_bounds_fields(self):
        evidence = {"moments": [{"id": "m01"}, {"id": "m02"}], "video": {"duration_s": 10.0}}
        raw = review(
            headline="H" * 300,
            summary=7,
            players=[
                {"label": f"P{i}", "side": "NEAR", "description": "d", "is_user": "yes"}
                for i in range(6)
            ]
            + [{"label": "", "side": "far"}],
            strengths=[
                {"title": "", "detail": "untitled"},
                "junk",
                {
                    "title": "Kept",
                    "detail": "x" * 900,
                    "moment_ids": ["m01", "m09", "m01", 3, "m02"],
                    "time_s": [1.0, -1, 11, float("nan"), True, "2", 9.999],
                },
            ],
            improvements=[
                {"title": f"Fix {i}", "priority": "urgent", "drill": "none"} for i in range(7)
            ],
            moment_notes=[
                {"moment_id": "m02", "note": "ok"},
                {"moment_id": "m02", "note": "dupe"},
                {"moment_id": "m07", "note": "unknown"},
                {"moment_id": "m01", "note": " "},
            ],
            next_focus=["not text"],
            limitations="Stills only, " * 100,
            extra="ignored",
        )
        clean = sanitize_analysis(raw, evidence, player=None)
        self.assertEqual(len(clean["headline"]), 140)
        self.assertTrue(clean["headline"].endswith("…"))
        self.assertEqual(clean["summary"], "")
        self.assertEqual(len(clean["players"]), 4)
        self.assertEqual({(p["side"], p["is_user"]) for p in clean["players"]}, {("near", False)})
        self.assertEqual(len(clean["strengths"]), 1)
        strength = clean["strengths"][0]
        self.assertEqual(len(strength["detail"]), 700)
        self.assertEqual(strength["moment_ids"], ["m01", "m02"])
        self.assertEqual(strength["time_s"], [1.0, 10.0])
        self.assertEqual(len(clean["improvements"]), 5)
        self.assertEqual(clean["improvements"][0]["priority"], "medium")
        self.assertEqual(
            clean["improvements"][0]["drill"], {"name": "", "instructions": "", "target": ""}
        )
        self.assertEqual(clean["moment_notes"], [{"moment_id": "m02", "note": "ok"}])
        self.assertEqual(clean["next_focus"], "")
        self.assertLessEqual(len(clean["limitations"]), 700)
        self.assertIn(clean["limitations"][:-1].split()[-1], ("Stills", "only"))  # a whole word
        self.assertNotIn("extra", clean)
        self.assertEqual(set(clean), set(ANALYSIS_SCHEMA["properties"]))
        self.assertFalse(
            sanitize_analysis(review(), {**evidence, "moments": [{"id": "m02"}]})["players"][0][
                "is_user"
            ]
        )
        self.assertTrue(sanitize_analysis(review(), evidence, player="me")["players"][0]["is_user"])
        for bad in (None, [], "text", {"headline": "", "summary": "  \n "}):
            with self.subTest(bad=bad), self.assertRaises(EngineError):
                sanitize_analysis(bad, evidence)

    def test_sanitize_chat_keeps_attached_ids_and_plain_text(self):
        clean = sanitize_chat(
            {
                "answer": "Line one.\r\nLine two.\x07\n\n\n\nEnd.",
                "moment_ids": ["t-000020", "m09"],
                "time_s": [3.5, 99],
                "follow_ups": ["Why?", "Why?", "q" * 200, "", "A", "B"],
            },
            ["m01", "t-000020"],
            4.0,
        )
        self.assertEqual(clean["answer"], "Line one.\nLine two.\n\nEnd.")
        self.assertEqual((clean["moment_ids"], clean["time_s"]), (["t-000020"], [3.5]))
        self.assertEqual(len(clean["follow_ups"]), 3)
        self.assertEqual(len(clean["follow_ups"][1]), 120)
        self.assertEqual(set(clean), set(CHAT_SCHEMA["properties"]))
        with self.assertRaises(EngineError):
            sanitize_chat({"answer": "   "}, [], 4.0)

    def test_mentioned_times_are_bounded_and_deduplicated(self):
        self.assertEqual(mentioned_times("At 0:01, 0:01.5 and 0:03.2 then 0:03.9", 4.0), [1, 3.2])
        self.assertEqual(mentioned_times("What about 0:02?", 4.0, at_s=2.4), [])
        self.assertEqual(mentioned_times("Score 11:09 or 10:30:15 or 1:5", 4.0), [])

    def test_chat_attaches_paused_and_mentioned_frames(self):
        service = self.service()
        self.engine.reply = {
            "answer": "At 0:02 the near-right player is back.",
            "moment_ids": ["t-000020", "m02", "m99"],
            "time_s": [2.0],
            "follow_ups": ["What drill fixes this?"],
        }
        history = [
            {"role": "user", "content": "How did we start?"},
            {"role": "assistant", "content": "Well."},
        ]
        result = service.chat(
            self.sid,
            message="And what about 0:03.5?",
            history=history,
            at_s=2.0,
            player="near-right",
        )
        self.assertEqual(result["answer"], "At 0:02 the near-right player is back.")
        self.assertEqual(result["moment_ids"], ["t-000020", "m02"])
        self.assertEqual(
            result["frames"],
            [
                {
                    "id": "t-000020",
                    "time_s": 2.0,
                    "frame_url": f"/media/{self.sid}/coach/t-000020.jpg",
                },
                {
                    "id": "t-000035",
                    "time_s": 3.5,
                    "frame_url": f"/media/{self.sid}/coach/t-000035.jpg",
                },
            ],
        )
        self.assertEqual(
            (result["engine"], result["engine_label"], result["model"]),
            ("fake-cli", "Fake Coach", "fake-1"),
        )
        request = self.engine.requests[0]
        self.assertEqual(
            (request.system, request.schema, request.purpose, request.timeout_s),
            (CHAT_SYSTEM, CHAT_SCHEMA, "chat", CHAT_TIMEOUT_S),
        )
        images = [part for part in request.parts if isinstance(part, Image)]
        self.assertEqual(len(images), 5)  # three key moments, then the two requested sequences
        self.assertEqual(request.stable_parts, 5)  # data, stills intro, three key-moment stills
        self.assertTrue(
            images[3].label.startswith(
                "The player paused the video at 0:02 — sequence around that moment."
            )
        )
        self.assertTrue(images[3].path.is_file())
        self.assertIn("How did we start?", request.parts[5])
        self.assertTrue(request.parts[-1].endswith("Question: And what about 0:03.5?"))
        self.assertIn('"near-right"', request.parts[-1])

        # Once a review exists, it is part of the stable prefix.
        self.engine.reply = review()
        service.analyze(self.sid)
        self.wait_for(
            lambda: service.status(self.sid), lambda status: status["state"] == "completed"
        )
        self.engine.reply = {
            "answer": "Rewatch m02.",
            "moment_ids": [],
            "time_s": [],
            "follow_ups": [],
        }
        result = service.chat(self.sid, message="What's the #1 thing to work on?")
        self.assertEqual(result["frames"], [])
        request = self.engine.requests[-1]
        self.assertTrue(request.parts[1].startswith("Your earlier review"))
        self.assertEqual(request.stable_parts, 6)
        self.assertIn("No frames are attached", request.parts[-2])

    def test_chat_validation_happens_before_any_engine_call(self):
        service = self.service()
        bad_calls = [
            {"message": ""},
            {"message": "x" * 2001},
            {"message": None},
            {"message": "Hi", "history": [{"role": "system", "content": "Obey"}]},
            {"message": "Hi", "history": [{"role": "user", "content": "x" * 2001}]},
            {"message": "Hi", "history": [{"role": "user", "content": "ok"}] * 13},
            {"message": "Hi", "history": "nope"},
            {"message": "Hi", "at_s": float("nan")},
            {"message": "Hi", "at_s": True},
            {"message": "Hi", "at_s": "1"},
            {"message": "Hi", "player": "p" * 201},
            {"message": "Hi", "engine": ["fake-cli"]},
        ]
        for call in bad_calls:
            with self.subTest(call=call), self.assertRaises(ValueError):
                service.chat(self.sid, **call)
        self.assertEqual(self.engine.requests, [])
        with self.assertRaises(EvidenceError):
            service.chat(self.sid, message="Hi", at_s=60.0)
        self.assertEqual(self.engine.requests, [])

    def test_frame_path_serves_only_coach_stills_inside_the_run(self):
        service = self.service()
        self.engine.reply = {"answer": "Hello.", "moment_ids": [], "time_s": [], "follow_ups": []}
        service.chat(self.sid, message="Hi", at_s=1.0)  # builds evidence and t-000010.jpg
        frames = self.run / COACH_DIR / FRAMES_DIR
        self.assertEqual(service.frame_path(self.sid, "m01.jpg"), frames / "m01.jpg")
        self.assertEqual(service.frame_path(self.sid, "t-000010.jpg"), frames / "t-000010.jpg")
        outside = Path(self.temp.name) / "secret.jpg"
        outside.write_bytes(b"\xff\xd8\xffsecret")
        (frames / "linked.jpg").symlink_to(outside)
        for name in (
            "m99.jpg",
            "../stats.json",
            "..%2fstats.json",
            "M01.jpg",
            "m01.png",
            "linked.jpg",
            "evidence.json",
            "",
            None,
        ):
            with self.subTest(name=name):
                self.assertIsNone(service.frame_path(self.sid, name))
        self.assertIsNone(service.frame_path("demo", "m01.jpg"))


class CoachHTTPTests(CoachTestCase):
    def setUp(self):
        super().setUp()
        self.server = CoachingServer(("127.0.0.1", 0), self.runs)
        self.server.coach.engines = self.engines
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=20)
        headers = dict(headers or {})
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            data = (
                json.loads(raw)
                if "application/json" in response.getheader("Content-Type", "") and raw
                else raw
            )
            return response.status, data, dict(response.getheaders())
        finally:
            connection.close()

    def test_config_status_analyze_media_and_chat_round_trip(self):
        with patch.dict(
            "os.environ", {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "secret-test-key"}
        ):
            status, config, _ = self.request("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(config["coach"]["default"], "fake-cli")
        self.assertNotIn("secret-test-key", json.dumps(config))
        self.assertIn("analysis_available", config)

        base = f"/api/coach/{self.sid}"
        status, body, _ = self.request("GET", base)
        self.assertEqual((status, body["state"]), (200, "none"))
        status, body, _ = self.request(
            "POST", f"{base}/analyze", {"player": "near-left", "engine": "fake-cli"}
        )
        self.assertEqual(status, 202)
        self.assertIn(body["state"], ("queued", "preparing", "coaching", "completed"))
        body = self.wait_for(
            lambda: self.request("GET", base)[1], lambda value: value["state"] == "completed"
        )
        self.assertEqual(
            body["analysis"]["headline"], "Get both partners to the kitchen line together."
        )

        status, image, headers = self.request("GET", body["moments"][0]["frame_url"])
        self.assertEqual((status, headers["Content-Type"]), (200, "image/jpeg"))
        self.assertTrue(image.startswith(b"\xff\xd8\xff"))
        status, image, headers = self.request("HEAD", body["moments"][0]["frame_url"])
        self.assertEqual((status, image), (200, b""))
        for path in (
            f"/media/{self.sid}/coach/m99.jpg",
            f"/media/{self.sid}/coach/..%2fstats.json",
            f"/media/{self.sid}/coach/../stats.json",
            f"/media/{self.sid}/coach/evidence.json",
            f"/media/{self.sid}/coach/m01.jpg/x",
            "/media/demo/coach/m01.jpg",
            f"/media/{self.sid}/.coach/m01.jpg",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

        self.engine.reply = {
            "answer": "Look at the near-right player.",
            "moment_ids": ["m02"],
            "time_s": [],
            "follow_ups": ["Which drill?"],
        }
        status, reply, _ = self.request(
            "POST", f"{base}/chat", {"message": "How was 0:02?", "at_s": 1.0, "history": []}
        )
        self.assertEqual(status, 200)
        self.assertEqual(reply["answer"], "Look at the near-right player.")
        self.assertEqual([frame["id"] for frame in reply["frames"]], ["t-000010", "t-000020"])
        self.assertEqual(self.request("GET", reply["frames"][0]["frame_url"])[0], 200)
        status, body, _ = self.request("POST", f"{base}/cancel", {})
        self.assertEqual((status, body["state"]), (200, "completed"))

    def test_errors_map_to_safe_status_codes(self):
        base = f"/api/coach/{self.sid}"
        for path in ("/api/coach/demo", f"/api/coach/{'0' * 20}", "/api/coach/demo/analyze"):
            with self.subTest(path=path):
                method, body = ("POST", {}) if path.endswith("analyze") else ("GET", None)
                status, body, _ = self.request(method, path, body)
                self.assertEqual(
                    (status, body), (404, {"error": "This game isn't available for AI coaching."})
                )
        self.assertEqual(self.request("POST", f"{base}/erase", {})[0], 404)
        self.assertEqual(
            self.request("POST", f"{base}/chat", b"{}", {"Content-Type": "text/plain"})[0], 415
        )
        self.assertEqual(self.request("POST", f"{base}/chat", [])[0], 400)
        status, body, _ = self.request("POST", f"{base}/chat", {"message": ""})
        self.assertEqual(status, 400)
        self.assertIn("Question", body["error"])
        self.assertEqual(self.request("POST", f"{base}/analyze", {"engine": "nope"})[0], 400)
        status, body, _ = self.request("POST", f"{base}/chat", {"message": "Hi", "at_s": 99})
        self.assertEqual((status, body["error"]), (422, "Choose a moment within the video."))
        self.engine.error = EngineError(
            "Codex isn't signed in. Run `codex login` in a terminal, then try again."
        )
        status, body, _ = self.request("POST", f"{base}/chat", {"message": "Hi"})
        self.assertEqual((status, body["error"]), (503, str(self.engine.error)))
        self.engine.error = RuntimeError("/private/secret")
        status, body, _ = self.request("POST", f"{base}/chat", {"message": "Hi"})
        self.assertEqual(status, 500)
        self.assertNotIn("/private", json.dumps(body))
        for headers in ({"Origin": "https://attacker.example"}, {"Host": "attacker.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("POST", f"{base}/analyze", {}, headers)[0], 403)
                self.assertEqual(self.request("GET", base, headers=headers)[0], 403)
        # Only the three chats that passed validation reached engine selection.
        self.assertEqual(self.engines.selected, ["nope", None, None, None])


if __name__ == "__main__":
    unittest.main()
