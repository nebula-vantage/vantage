import base64
import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
import httpx2
from vantage import coach_engines
from vantage.coach_engines import (
    ENGINE_ORDER,
    FALLBACK_BETA,
    NO_ENGINE,
    TIMED_OUT,
    AnthropicAPIEngine,
    ClaudeCLIEngine,
    CodexCLIEngine,
    EngineCancelled,
    EngineError,
    EngineRequest,
    Image,
    all_engines,
    configuration,
    select_engine,
)

JPEG = b"\xff\xd8\xff\xe0fake-jpeg-payload\xff\xd9"
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
SYSTEM = "You are a pickleball coach."
SUCCESS = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": '{"answer": "text"}',
    "structured_output": {"answer": "Move up together."},
    "total_cost_usd": 0.01,
}

# Every fake CLI records its argv, stdin, and working directory, then runs its body.
PRELUDE = """\
import json, os, subprocess, sys, time
ROOT = {root!r}
args = sys.argv[1:]
if args[:2] == ["login", "status"]:
    with open(os.path.join(ROOT, "login-calls"), "a") as log:
        log.write("x")
    sys.exit({login_exit})
data = sys.stdin.buffer.read()
record = {{"argv": args, "stdin": data.decode(), "cwd": os.getcwd(), "pid": os.getpid()}}
with open(os.path.join(ROOT, "record.json"), "w") as handle:
    json.dump(record, handle)
"""


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def process_gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        for name in (
            "VANTAGE_COACH_ENGINE",
            "VANTAGE_COACH_CLAUDE_MODEL",
            "VANTAGE_COACH_CODEX_MODEL",
            "VANTAGE_COACH_ANTHROPIC_MODEL",
        ):
            os.environ.pop(name, None)
        coach_engines._LOGIN_CACHE.clear()
        self.addCleanup(coach_engines._LOGIN_CACHE.clear)
        quiet = patch.object(coach_engines.LOGGER, "disabled", True)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.addCleanup(self.assert_slots_free)

    def assert_slots_free(self):
        # Every run must return its concurrency slot, even after cancel or timeout.
        self.assertTrue(wait_until(lambda: coach_engines._SLOTS._value == 2))

    def image(self, name="m01.jpg", data=JPEG):
        path = self.root / name
        path.write_bytes(data)
        return path

    def request(self, parts=None, purpose="analysis", timeout_s=20, stable_parts=0):
        if parts is None:
            parts = [
                "Session data",
                Image(self.image(), "Moment m01 · 0:42.3"),
                "Question: what now?",
            ]
        return EngineRequest(SYSTEM, parts, SCHEMA, purpose, timeout_s, stable_parts)

    def fake(self, body, name="fake-cli", login_exit=0):
        path = self.root / name
        path.write_text(
            f"#!{sys.executable}\n"
            + PRELUDE.format(root=str(self.root), login_exit=login_exit)
            + textwrap.dedent(body)
        )
        path.chmod(0o755)
        return str(path)

    def record(self):
        return json.loads((self.root / "record.json").read_text())

    def emit(self, *events, code=0, stderr=""):
        lines = "".join(json.dumps(event) + "\n" for event in events)
        return f"sys.stdout.write({lines!r})\nsys.stderr.write({stderr!r})\nsys.exit({code})\n"


class ClaudeCLIEngineTests(EngineTestCase):
    def engine(self, body, **kwargs):
        return ClaudeCLIEngine(binary=self.fake(body), **kwargs)

    def test_argv_stdin_and_structured_output(self):
        engine = self.engine(self.emit({"type": "system", "subtype": "init"}, SUCCESS))
        self.assertEqual(engine.run(self.request()), {"answer": "Move up together."})
        record = self.record()
        argv = record["argv"]
        self.assertEqual(argv[:2], ["-p", "--input-format"])
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]), SCHEMA)
        self.assertEqual(argv[argv.index("--system-prompt") + 1], SYSTEM)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--model") + 1], "opus")
        self.assertEqual(argv[argv.index("--effort") + 1], "high")
        for flag in (
            "--no-session-persistence",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--verbose",
        ):
            self.assertIn(flag, argv)
        self.assertTrue(record["stdin"].endswith("\n"))
        self.assertEqual(record["stdin"].count("\n"), 1)
        message = json.loads(record["stdin"])
        self.assertEqual(message["type"], "user")
        self.assertEqual(message["message"]["role"], "user")
        blocks = message["message"]["content"]
        self.assertEqual([block["type"] for block in blocks], ["text", "text", "image", "text"])
        self.assertEqual(blocks[1]["text"], "Moment m01 · 0:42.3")
        self.assertEqual(blocks[2]["source"]["media_type"], "image/jpeg")
        self.assertEqual(base64.b64decode(blocks[2]["source"]["data"]), JPEG)
        self.assertNotIn("cache_control", record["stdin"])
        # A private, fresh working directory that is removed afterwards.
        self.assertTrue(Path(record["cwd"]).name.startswith("vantage-coach-"))
        self.assertFalse(Path(record["cwd"]).exists())

    def test_chat_effort_and_model_from_environment(self):
        body = self.emit(SUCCESS)
        with patch.dict(os.environ, {"VANTAGE_COACH_CLAUDE_MODEL": "claude-opus-5-5[1m]"}):
            engine = self.engine(body)
            self.assertEqual(engine.status()["model"], "claude-opus-5-5[1m]")
            engine.run(self.request(purpose="chat"))
        argv = self.record()["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-5-5[1m]")
        self.assertEqual(argv[argv.index("--effort") + 1], "medium")
        for invalid in ("bad model", "-rf", "x;rm", "a" * 129):
            with (
                self.subTest(invalid=invalid),
                patch.dict(os.environ, {"VANTAGE_COACH_CLAUDE_MODEL": invalid}),
            ):
                self.assertEqual(ClaudeCLIEngine(binary="/nonexistent").model, "opus")

    def test_result_string_is_the_fallback_answer(self):
        result = {**SUCCESS, "result": '{"answer": "From text"}'}
        del result["structured_output"]
        self.assertEqual(
            self.engine(self.emit(result)).run(self.request()), {"answer": "From text"}
        )

    def test_errors_map_to_safe_messages(self):
        cases = (
            (
                {**SUCCESS, "is_error": True, "result": "Invalid API key · Please run /login"},
                1,
                "",
                "isn't signed in",
            ),
            (
                {**SUCCESS, "is_error": True, "result": "Claude AI usage limit reached|1760000000"},
                1,
                "",
                "usage limit",
            ),
            (
                {
                    "type": "result",
                    "subtype": "error_during_execution",
                    "is_error": True,
                    "errors": ["secret-internal-trace"],
                },
                1,
                "",
                "couldn't finish",
            ),
            (None, 1, "secret-internal-trace: Not logged in", "isn't signed in"),
            (None, 0, "", "couldn't finish"),
        )
        for result, code, stderr, expected in cases:
            with self.subTest(expected=expected, result=result):
                events = [result] if result else []
                with self.assertRaises(EngineError) as raised:
                    self.engine(self.emit(*events, code=code, stderr=stderr)).run(self.request())
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn("secret", str(raised.exception))

    def test_assistant_error_field_and_unparseable_answers(self):
        assistant = {"type": "assistant", "error": "rate_limit", "message": {"content": []}}
        failed = {"type": "result", "subtype": "success", "is_error": True, "result": "API Error"}
        with self.assertRaisesRegex(EngineError, "usage limit"):
            self.engine(self.emit(assistant, failed, code=1)).run(self.request())
        # A model answer mentioning "login" must not be mistaken for an auth failure.
        unreadable = {
            **SUCCESS,
            "result": "Please log in to see the answer",
            "structured_output": None,
        }
        with self.assertRaises(EngineError) as raised:
            self.engine(self.emit(unreadable)).run(self.request())
        self.assertEqual(str(raised.exception), ClaudeCLIEngine.failed)
        with self.assertRaisesRegex(EngineError, "couldn't finish"):
            self.engine("print('not json at all')\n").run(self.request())

    def test_timeout_kills_the_whole_process_group(self):
        body = """\
        child = subprocess.Popen(["sleep", "30"])
        with open(os.path.join(ROOT, "child.pid"), "w") as handle:
            handle.write(str(child.pid))
        time.sleep(30)
        """
        started = time.monotonic()
        with self.assertRaises(EngineError) as raised:
            self.engine(body).run(self.request(timeout_s=1.5))
        self.assertEqual(str(raised.exception), TIMED_OUT)
        self.assertNotIsInstance(raised.exception, EngineCancelled)
        self.assertLess(time.monotonic() - started, 6)
        record = self.record()
        child = int((self.root / "child.pid").read_text())
        self.assertTrue(wait_until(lambda: process_gone(child)))
        self.assertTrue(wait_until(lambda: process_gone(record["pid"])))
        self.assertFalse(Path(record["cwd"]).exists())

    def test_cancel_stops_the_process_and_escalates_to_sigkill(self):
        body = """\
        import signal
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        open(os.path.join(ROOT, "ready"), "w").close()
        time.sleep(30)
        """
        engine, cancel, errors = self.engine(body), threading.Event(), []

        def run():
            try:
                engine.run(self.request(timeout_s=60), cancel=cancel)
            except EngineError as exc:
                errors.append(exc)

        worker = threading.Thread(target=run)
        with patch.object(coach_engines, "KILL_GRACE_S", 0.3):
            worker.start()
            self.assertTrue(wait_until(lambda: (self.root / "ready").exists()))
            started = time.monotonic()
            cancel.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], EngineCancelled)
        self.assertTrue(wait_until(lambda: process_gone(self.record()["pid"])))

    def test_cancel_before_start_and_busy_slots_never_launch(self):
        cancel = threading.Event()
        cancel.set()
        engine = self.engine(self.emit(SUCCESS))
        with self.assertRaises(EngineCancelled):
            engine.run(self.request(), cancel=cancel)
        for _ in range(2):
            coach_engines._SLOTS.acquire()
        try:
            with self.assertRaises(EngineError) as raised:
                engine.run(self.request(timeout_s=0.3))
            self.assertEqual(str(raised.exception), TIMED_OUT)
        finally:
            for _ in range(2):
                coach_engines._SLOTS.release()
        self.assertFalse((self.root / "record.json").exists())

    def test_oversized_output_is_rejected(self):
        body = "sys.stdout.write('x' * 5000)\nsys.stdout.flush()\ntime.sleep(30)\n"
        with (
            patch.object(coach_engines, "MAX_OUTPUT_BYTES", 1024),
            self.assertRaises(EngineError) as raised,
        ):
            self.engine(body).run(self.request())
        self.assertEqual(str(raised.exception), ClaudeCLIEngine.failed)

    def test_missing_binary_is_unavailable(self):
        engine = ClaudeCLIEngine(binary=str(self.root / "missing"))
        status = engine.status()
        self.assertEqual(
            status,
            {
                "id": "claude-cli",
                "label": "Claude Code",
                "available": False,
                "detail": ClaudeCLIEngine.missing,
                "model": "opus",
            },
        )
        with self.assertRaisesRegex(EngineError, "isn't installed"):
            engine.run(self.request())


class CodexCLIEngineTests(EngineTestCase):
    ANSWER = """\
    output = args[args.index("-o") + 1]
    with open(os.path.join(ROOT, "schema-seen.json"), "w") as handle:
        handle.write(open(args[args.index("--output-schema") + 1]).read())
    with open(output, "w") as handle:
        json.dump({"answer": "Split step earlier."}, handle)
    """

    def engine(self, body, login_exit=0, **kwargs):
        return CodexCLIEngine(binary=self.fake(body, login_exit=login_exit), **kwargs)

    def test_prompt_on_stdin_and_images_in_label_order(self):
        first, second = self.image("m01.jpg"), self.image("m02.jpg")
        parts = [
            "Session data",
            Image(first, "Moment m01"),
            "",
            "Between moments",
            Image(second, "Moment m02"),
            "Question: how was our spacing?",
        ]
        result = self.engine(self.ANSWER).run(self.request(parts, purpose="chat"))
        self.assertEqual(result, {"answer": "Split step earlier."})
        record = self.record()
        argv = record["argv"]
        self.assertEqual(
            argv[:6],
            [
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "-s",
            ],
        )
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertEqual(argv[argv.index("-C") + 1], record["cwd"])
        self.assertEqual(argv[argv.index("--color") + 1], "never")
        self.assertEqual(argv[argv.index("-c") + 1], 'model_reasoning_effort="medium"')
        self.assertNotIn("-m", argv)
        # Images are the trailing arguments; nothing positional follows them.
        self.assertEqual(argv[-2:], [f"--image={first.resolve()}", f"--image={second.resolve()}"])
        self.assertTrue(
            all(
                item.startswith("-") or argv[index - 1].startswith("-")
                for index, item in enumerate(argv)
                if index
            )
        )
        self.assertEqual(json.loads((self.root / "schema-seen.json").read_text()), SCHEMA)
        self.assertEqual(
            record["stdin"],
            "\n\n".join(
                [
                    SYSTEM,
                    "Session data",
                    "[Image 1: Moment m01]",
                    "Between moments",
                    "[Image 2: Moment m02]",
                    "Question: how was our spacing?",
                ]
            ),
        )
        self.assertFalse(Path(record["cwd"]).exists())

    def test_model_and_analysis_effort(self):
        with patch.dict(os.environ, {"VANTAGE_COACH_CODEX_MODEL": "gpt-5.5-codex"}):
            engine = self.engine(self.ANSWER)
        self.assertEqual(engine.status()["model"], "gpt-5.5-codex")
        engine.run(self.request())
        argv = self.record()["argv"]
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.5-codex")
        self.assertEqual(argv[argv.index("-c") + 1], 'model_reasoning_effort="high"')
        self.assertIsNone(CodexCLIEngine(binary="/nonexistent").model)

    def test_failures_map_to_safe_messages(self):
        echo = "sys.stderr.write(data.decode() + '\\n')\n"  # Codex echoes the prompt, which may say "log in".
        cases = (
            ("sys.exit(0)\n", 0, "couldn't finish"),
            ("open(args[args.index('-o') + 1], 'w').write('[1, 2]')\n", 0, "couldn't finish"),
            (
                "sys.stderr.write('ERROR: unexpected status 401 Unauthorized')\nsys.exit(1)\n",
                0,
                "isn't signed in",
            ),
            ("sys.exit(1)\n", 1, "isn't signed in"),
            (
                "sys.stderr.write('ERROR: You hit your usage limit.')\nsys.exit(1)\n",
                0,
                "usage limit",
            ),
            (
                echo + "sys.stderr.write('ERROR: stream disconnected secret-trace')\nsys.exit(1)\n",
                0,
                "couldn't finish",
            ),
        )
        for body, login_exit, expected in cases:
            with self.subTest(body=body):
                coach_engines._LOGIN_CACHE.clear()
                parts = ["Why can't I log in to the error-free kitchen?"]
                with self.assertRaises(EngineError) as raised:
                    self.engine(body, login_exit=login_exit).run(self.request(parts))
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn("secret", str(raised.exception))

    def test_status_reports_sign_in_and_caches_the_check(self):
        engine = self.engine(self.ANSWER, login_exit=1)
        for _ in range(3):
            status = engine.status()
        self.assertTrue(status["available"])
        self.assertIn("Not signed in", status["detail"])
        self.assertEqual((self.root / "login-calls").read_text(), "x")
        coach_engines._LOGIN_CACHE.clear()
        self.assertIsNone(self.engine(self.ANSWER, login_exit=0).status()["detail"])

    def test_timeout_and_cancel(self):
        body = "open(os.path.join(ROOT, 'ready'), 'w').close()\ntime.sleep(30)\n"
        with self.assertRaisesRegex(EngineError, "too long"):
            self.engine(body).run(self.request(timeout_s=0.8))
        self.assertTrue(wait_until(lambda: process_gone(self.record()["pid"])))
        cancel = threading.Event()
        threading.Timer(0.5, cancel.set).start()
        with self.assertRaises(EngineCancelled):
            self.engine(body).run(self.request(timeout_s=30), cancel=cancel)


class FakeMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []
        self.release = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.release is not None:
            self.release.wait(10)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def response(text='{"answer": "Stay low."}', stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="fallback"), SimpleNamespace(type="text", text=text)],
    )


def status_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(
        "secret-body", response=httpx2.Response(status, request=request), body={"secret": "body"}
    )


class AnthropicAPIEngineTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        os.environ["ANTHROPIC_API_KEY"] = "test-key-never-sent-to-network"
        self.options = []

    def engine(self, outcome, **kwargs):
        self.messages = FakeMessages(outcome)

        def factory(**options):
            self.options.append(options)
            return SimpleNamespace(beta=SimpleNamespace(messages=self.messages), close=lambda: None)

        return AnthropicAPIEngine(client_factory=factory, **kwargs)

    def test_request_shape_caches_the_stable_prefix(self):
        parts = ["Session data", Image(self.image(), "Moment m01"), "", "Question"]
        engine = self.engine(response())
        self.assertEqual(
            engine.run(self.request(parts, timeout_s=30, stable_parts=3)), {"answer": "Stay low."}
        )
        self.assertEqual(self.options, [{"timeout": 30, "max_retries": 2}])
        call = self.messages.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual(call["max_tokens"], 16000)
        self.assertEqual(call["system"], [{"type": "text", "text": SYSTEM}])
        self.assertEqual(
            call["output_config"],
            {"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        self.assertEqual(call["betas"], [FALLBACK_BETA])
        self.assertEqual(call["fallbacks"], "default")
        for absent in ("thinking", "temperature", "top_p", "top_k", "extra_body"):
            self.assertNotIn(absent, call)
        [message] = call["messages"]
        self.assertEqual(message["role"], "user")
        blocks = message["content"]
        self.assertEqual([block["type"] for block in blocks], ["text", "text", "image", "text"])
        # The empty third part ends the stable prefix, so the image carries the breakpoint.
        self.assertEqual(
            [index for index, block in enumerate(blocks) if "cache_control" in block], [2]
        )
        self.assertEqual(blocks[2]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(base64.b64decode(blocks[2]["source"]["data"]), JPEG)

    def test_chat_effort_no_stable_prefix_and_model_override(self):
        with patch.dict(os.environ, {"VANTAGE_COACH_ANTHROPIC_MODEL": "claude-sonnet-5-5"}):
            engine = self.engine(response())
        engine.run(self.request(purpose="chat"))
        call = self.messages.calls[0]
        self.assertEqual(call["model"], "claude-sonnet-5-5")
        self.assertEqual(call["output_config"]["effort"], "medium")
        self.assertNotIn("cache_control", json.dumps(call["messages"]))

    def test_stop_reasons_and_unreadable_answers(self):
        for outcome, expected in (
            (response(stop_reason="refusal"), "declined"),
            (response(stop_reason="max_tokens"), "too long"),
            (response(text="not json"), "couldn't finish"),
            (response(text="[1]"), "couldn't finish"),
            (SimpleNamespace(stop_reason="end_turn", content=[]), "couldn't finish"),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(EngineError, expected):
                self.engine(outcome).run(self.request())

    def test_sdk_errors_map_to_safe_messages(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = (
            (status_error(anthropic.AuthenticationError, 401), "ANTHROPIC_API_KEY was rejected"),
            (status_error(anthropic.RateLimitError, 429), "rate limit"),
            (status_error(anthropic.NotFoundError, 404), "VANTAGE_COACH_ANTHROPIC_MODEL"),
            (status_error(anthropic.InternalServerError, 500), "couldn't finish"),
            (anthropic.APITimeoutError(request=request), "too long"),
            (
                anthropic.APIConnectionError(message="secret-body", request=request),
                "internet connection",
            ),
            (RuntimeError("secret-body"), "couldn't finish"),
        )
        for error, expected in cases:
            with (
                self.subTest(error=type(error).__name__),
                patch.object(coach_engines.LOGGER, "disabled", False),
                self.assertLogs("vantage.coach_engines", level="WARNING") as logs,
            ):
                with self.assertRaises(EngineError) as raised:
                    self.engine(error).run(self.request())
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn("secret", str(raised.exception) + "".join(logs.output))
                self.assertIsNone(raised.exception.__cause__)

    def test_availability_requires_api_key(self):
        engine = self.engine(response())
        self.assertEqual(
            engine.status(),
            {
                "id": "anthropic-api",
                "label": "Claude API",
                "available": True,
                "detail": None,
                "model": "claude-opus-5-5",
            },
        )
        for key in ("", "  ", "bad\nkey"):
            with self.subTest(key=key), patch.dict(os.environ, {"ANTHROPIC_API_KEY": key}):
                self.assertFalse(engine.status()["available"])
                self.assertIn("ANTHROPIC_API_KEY", engine.status()["detail"])
                with self.assertRaisesRegex(EngineError, "ANTHROPIC_API_KEY"):
                    engine.run(self.request())
        self.assertEqual(self.messages.calls, [])

    def test_cancel_returns_promptly_and_slot_is_released_when_the_call_ends(self):
        engine = self.engine(response())
        self.messages.release = threading.Event()
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(EngineCancelled):
            engine.run(self.request(), cancel=cancel)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(coach_engines._SLOTS._value, 1)  # The abandoned call still holds its slot.
        self.messages.release.set()


class RequestValidationTests(EngineTestCase):
    def test_image_count_size_and_type_limits(self):
        engine = AnthropicAPIEngine(client_factory=lambda **_: None)
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        image = Image(self.image(), "frame")
        with self.assertRaisesRegex(ValueError, "at most 20 images"):
            engine.run(self.request([image] * 21))
        with (
            patch.object(coach_engines, "MAX_IMAGE_BYTES", len(JPEG) * 2 - 1),
            self.assertRaisesRegex(ValueError, "total at most"),
        ):
            engine.run(self.request([image, image]))
        with self.assertRaisesRegex(ValueError, "JPEG"):
            engine.run(self.request([Image(self.image("x.jpg", b"\x89PNG...."), "png")]))
        with self.assertRaisesRegex(EngineError, "couldn't be read"):
            engine.run(self.request([Image(self.root / "missing.jpg", "gone")]))

    def test_malformed_requests_are_rejected_before_running(self):
        engine = ClaudeCLIEngine(binary=self.fake("sys.exit(0)\n"))
        good = self.request()
        for change in (
            {"purpose": "review"},
            {"timeout_s": 0},
            {"timeout_s": float("nan")},
            {"timeout_s": True},
            {"stable_parts": 4},
            {"stable_parts": -1},
            {"parts": []},
            {"parts": ["  ", ""]},
            {"parts": [b"bytes"]},
            {"schema": {"bad": float("nan")}},
            {"schema": []},
            {"system": " "},
        ):
            with self.subTest(change=change):
                fields = {**good.__dict__, **change}
                with self.assertRaises(ValueError):
                    engine.run(EngineRequest(**fields))
        self.assertFalse((self.root / "record.json").exists())


class FakeEngine(coach_engines.Engine):
    def __init__(self, identity, available):
        self.id, self.label, self.available = identity, identity.title(), available

    def status(self):
        return self._status(self.available, None if self.available else f"{self.id} is not set up.")


class SelectionTests(EngineTestCase):
    def engines(self, *available):
        engines = {
            identity: FakeEngine(identity, identity in available) for identity in ENGINE_ORDER
        }
        return patch.object(coach_engines, "all_engines", return_value=engines)

    def test_auto_selection_follows_engine_order_and_environment_override(self):
        with self.engines("codex-cli", "anthropic-api"):
            self.assertEqual(select_engine(None).id, "codex-cli")
            self.assertEqual(select_engine("").id, "codex-cli")
            self.assertEqual(configuration()["default"], "codex-cli")
            with patch.dict(os.environ, {"VANTAGE_COACH_ENGINE": "anthropic-api"}):
                self.assertEqual(select_engine(None).id, "anthropic-api")
                self.assertEqual(configuration()["default"], "anthropic-api")
            for preference in ("claude-cli", "unknown-engine"):
                with (
                    self.subTest(preference=preference),
                    patch.dict(os.environ, {"VANTAGE_COACH_ENGINE": preference}),
                ):
                    self.assertEqual(select_engine(None).id, "codex-cli")
        with self.engines("claude-cli", "codex-cli", "anthropic-api"):
            self.assertEqual(select_engine(None).id, "claude-cli")
            self.assertEqual(
                [item["id"] for item in configuration()["engines"]], list(ENGINE_ORDER)
            )

    def test_explicit_unknown_unavailable_and_none_available(self):
        with self.engines("anthropic-api"):
            self.assertEqual(select_engine("anthropic-api").id, "anthropic-api")
            with self.assertRaises(ValueError):
                select_engine("gpt-cli")
            with self.assertRaises(ValueError):
                select_engine(3)
            with self.assertRaisesRegex(EngineError, "claude-cli is not set up"):
                select_engine("claude-cli")
        with self.engines():
            with self.assertRaises(EngineError) as raised:
                select_engine(None)
            self.assertEqual(str(raised.exception), NO_ENGINE)
            self.assertIsNone(configuration()["default"])

    def test_real_engines_resolve_binaries_and_key(self):
        with patch.object(coach_engines.shutil, "which", return_value=None):
            config = configuration()
            self.assertEqual(
                [item["available"] for item in config["engines"]], [False, False, False]
            )
            self.assertIsNone(config["default"])
            self.assertTrue(all(item["detail"] for item in config["engines"]))
        claude, codex = self.fake("sys.exit(0)\n", "claude"), self.fake("sys.exit(0)\n", "codex")
        with (
            patch.object(
                coach_engines.shutil, "which", side_effect={"claude": claude, "codex": codex}.get
            ),
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            engines = all_engines()
            self.assertEqual(list(engines), list(ENGINE_ORDER))
            self.assertEqual(engines["claude-cli"].binary, claude)
            self.assertEqual(engines["codex-cli"].binary, codex)
            config = configuration()
            self.assertEqual([item["available"] for item in config["engines"]], [True, True, True])
            self.assertEqual(config["default"], "claude-cli")


if __name__ == "__main__":
    unittest.main()
