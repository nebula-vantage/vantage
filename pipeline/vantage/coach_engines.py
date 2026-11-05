"""Run one multimodal coaching request through a local AI CLI or the Anthropic API.

Every engine receives the same request (a system prompt, text interleaved with JPEG
stills, and a strict JSON schema) and returns the parsed JSON object. CLIs run
without a shell, in a private temporary directory and their own process group, so
cancel and timeout stop everything they started. Failures become short,
browser-safe messages; raw CLI output and exception bodies are never returned.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ENGINE_ORDER = ("claude-cli", "codex-cli", "anthropic-api")
MAX_IMAGES = 20
MAX_IMAGE_BYTES = 24 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024
KILL_GRACE_S = 3.0
POLL_S = 0.05
LOGIN_CHECK_TIMEOUT_S = 5
LOGIN_CACHE_S = 60
CLAUDE_MODEL = "opus"
ANTHROPIC_MODEL = "claude-opus-5-5"
ANTHROPIC_MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\[\]=,-]{0,127}")
NO_ENGINE = (
    "No AI coach is available. Install and sign in to Claude Code (claude) or Codex (codex), "
    "or set ANTHROPIC_API_KEY, then restart Vantage."
)
TIMED_OUT = "The coach took too long to respond. Try again."
# Matched only against CLI error text, never against model answers or our own prompt.
SIGN_IN_TEXT = re.compile(
    r"/login|\blog ?in\b|\blogged in\b|not signed in|\bsign ?in\b|\bauthenticat"
    r"|unauthori[sz]ed|invalid api key|\boauth|\b401\b",
    re.IGNORECASE,
)
LIMIT_TEXT = re.compile(
    r"usage limit|limit reached|rate[ _-]?limit|too many requests|\b429\b|quota"
    r"|credit balance|billing",
    re.IGNORECASE,
)
LOGGER = logging.getLogger(__name__)

_SLOTS = threading.BoundedSemaphore(2)
_LOGIN_CACHE: dict[str, tuple[float, bool | None]] = {}
_LOGIN_LOCK = threading.Lock()


class EngineError(RuntimeError):
    """Browser-safe, actionable message (never raw stderr or exception bodies)."""


class EngineCancelled(EngineError):
    def __init__(self, message="Cancelled."):
        super().__init__(message)


@dataclass(frozen=True)
class Image:
    path: Path  # JPEG on disk
    label: str  # short caption; codex also references images by number


@dataclass
class EngineRequest:
    system: str
    parts: list  # ordered str | Image (text and images interleaved)
    schema: dict  # strict JSON Schema for the answer object
    purpose: str  # "analysis" | "chat"
    timeout_s: float
    stable_parts: int = 0  # leading parts identical across this session's requests


def _model(value, variable, default):
    """An explicit override must be valid; an invalid environment value falls back to the default."""
    if value is not None:
        if not isinstance(value, str) or not MODEL_NAME.fullmatch(value):
            raise ValueError("Choose a valid model name.")
        return value
    configured = os.environ.get(variable, "").strip()
    return configured if MODEL_NAME.fullmatch(configured) else default


def _prepare(request):
    """Validate a request and read its images once; returns [(part, jpeg bytes or None)]."""
    if not isinstance(request, EngineRequest):
        raise ValueError("Coach requests must be EngineRequest objects.")
    if not isinstance(request.system, str) or not request.system.strip():
        raise ValueError("The coach request needs a system prompt.")
    if request.purpose not in ("analysis", "chat"):
        raise ValueError("The coach request purpose must be analysis or chat.")
    timeout = request.timeout_s
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("The coach timeout must be a positive number of seconds.")
    if not isinstance(request.schema, dict):
        raise ValueError("The coach response schema must be a JSON object.")
    try:
        json.dumps(request.schema, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("The coach response schema must be valid JSON.") from exc
    parts = request.parts
    stable = request.stable_parts
    if not isinstance(parts, list) or not parts:
        raise ValueError("The coach request needs at least one part.")
    if isinstance(stable, bool) or not isinstance(stable, int) or not 0 <= stable <= len(parts):
        raise ValueError("The coach request's stable prefix is out of range.")
    if sum(isinstance(part, Image) for part in parts) > MAX_IMAGES:
        raise ValueError(f"A coach request can include at most {MAX_IMAGES} images.")
    items, total = [], 0
    for part in parts:
        if isinstance(part, str):
            items.append((part, None))
            continue
        if not isinstance(part, Image) or not isinstance(part.label, str):
            raise ValueError("Coach request parts must be text or images.")
        try:
            with Path(part.path).open("rb") as stream:
                data = stream.read(MAX_IMAGE_BYTES - total + 1)
        except (OSError, TypeError) as exc:
            raise EngineError("A still frame for the coach couldn't be read. Try again.") from exc
        total += len(data)
        if total > MAX_IMAGE_BYTES:
            raise ValueError(
                f"Coach images must total at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
            )
        if not data.startswith(b"\xff\xd8\xff"):
            raise ValueError("Coach images must be JPEG files.")
        items.append((part, data))
    if not any(data is not None or part.strip() for part, data in items):
        raise ValueError("The coach request has no content.")
    return items


def _blocks(items, stable_parts, cache):
    """Anthropic message content: each image follows a text block with its label."""
    blocks, cache_at = [], None
    for index, (part, data) in enumerate(items):
        if data is None:
            if part.strip():
                blocks.append({"type": "text", "text": part})
        else:
            if part.label.strip():
                blocks.append({"type": "text", "text": part.label})
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(data).decode("ascii"),
                    },
                }
            )
        if index == stable_parts - 1 and blocks:
            cache_at = len(blocks) - 1
    if cache and cache_at is not None:
        blocks[cache_at]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _json_object(text):
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _wait(cancel, seconds):
    if cancel is None:
        time.sleep(seconds)
    else:
        cancel.wait(seconds)


def _check(deadline, cancel):
    if cancel is not None and cancel.is_set():
        raise EngineCancelled()
    if time.monotonic() >= deadline:
        raise EngineError(TIMED_OUT)


def _acquire(deadline, cancel):
    """Take one of the shared engine slots, honouring cancel and the request deadline."""
    while True:
        _check(deadline, cancel)
        if _SLOTS.acquire(timeout=POLL_S):
            return


def _feed(stream, data):
    try:
        stream.write(data)
    except (OSError, ValueError):
        pass  # The process exited or stopped reading; its exit status explains why.
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _drain(stream, chunks, limit, overflow):
    size = 0
    try:
        while chunk := stream.read1(64 * 1024):
            if size < limit:
                chunks.append(chunk[: limit - size])
            size += len(chunk)
            if size > limit and overflow is not None:
                overflow.set()
    except (OSError, ValueError):
        pass


def _signal_group(process, sig):
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass  # The whole group has already exited.


def _terminate(process):
    _signal_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        process.wait()


def _run_process(argv, stdin, cwd, deadline, cancel, label, failure):
    """Run argv (never through a shell) in a new process group; return (code, stdout, stderr).

    Cancel, the deadline, and oversized output stop the whole group: SIGTERM, then
    SIGKILL after KILL_GRACE_S. Output is read by helper threads, bounded in memory.
    """
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            start_new_session=True,
        )
    except OSError as exc:
        raise EngineError(
            f"{label} couldn't be started. Check that it is installed, then try again."
        ) from exc
    stdout, stderr, overflow = [], [], threading.Event()
    readers = [
        threading.Thread(
            target=_drain, args=(process.stdout, stdout, MAX_OUTPUT_BYTES, overflow), daemon=True
        ),
        threading.Thread(
            target=_drain, args=(process.stderr, stderr, MAX_ERROR_BYTES, None), daemon=True
        ),
    ]
    threads = [threading.Thread(target=_feed, args=(process.stdin, stdin), daemon=True), *readers]
    for thread in threads:
        thread.start()
    try:
        while process.poll() is None or any(reader.is_alive() for reader in readers):
            _check(deadline, cancel)
            if overflow.is_set():
                raise EngineError(failure)
            _wait(cancel, POLL_S)
    except EngineError:
        _terminate(process)
        raise
    finally:
        for thread in threads:
            thread.join(timeout=1)
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
    return process.returncode, b"".join(stdout), b"".join(stderr)


def _login_state(binary):
    """Cached `codex login status`: True/False, or None when it can't be determined."""
    with _LOGIN_LOCK:
        cached = _LOGIN_CACHE.get(binary)
        if cached and time.monotonic() - cached[0] < LOGIN_CACHE_S:
            return cached[1]
    try:
        completed = subprocess.run(
            [binary, "login", "status"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=LOGIN_CHECK_TIMEOUT_S,
            check=False,
            start_new_session=True,
        )
        state = completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        state = None
    with _LOGIN_LOCK:
        _LOGIN_CACHE[binary] = (time.monotonic(), state)
    return state


class Engine:
    """One way of reaching a model. Subclasses set id/label and implement status() and run()."""

    id = ""
    label = ""
    model: str | None = None

    def _status(self, available, detail):
        return {
            "id": self.id,
            "label": self.label,
            "available": bool(available),
            "detail": detail,
            "model": self.model,
        }

    def status(self) -> dict:
        raise NotImplementedError

    def run(self, request: EngineRequest, cancel: threading.Event | None = None) -> dict:
        raise NotImplementedError


class _CLIEngine(Engine):
    command = ""
    missing = ""

    def __init__(self, binary=None):
        # shutil.which also verifies an explicit path is an executable file.
        self.binary = shutil.which(binary if binary is not None else self.command)

    def status(self):
        return self._status(self.binary, None if self.binary else self.missing)

    def run(self, request, cancel=None):
        items = _prepare(request)
        if not self.binary:
            raise EngineError(self.missing)
        deadline = time.monotonic() + request.timeout_s
        _acquire(deadline, cancel)
        workdir = None
        try:
            workdir = Path(tempfile.mkdtemp(prefix="vantage-coach-")).resolve()
            return self._invoke(request, items, workdir, deadline, cancel)
        finally:
            if workdir is not None:
                shutil.rmtree(workdir, ignore_errors=True)
            _SLOTS.release()

    def _invoke(self, request, items, workdir, deadline, cancel):
        raise NotImplementedError


class ClaudeCLIEngine(_CLIEngine):
    """Claude Code in print mode with no tools except its built-in structured output."""

    id = "claude-cli"
    label = "Claude Code"
    command = "claude"
    missing = "Claude Code (claude) isn't installed. Install it and sign in, then restart Vantage."
    failed = "Claude Code couldn't finish the review. Try again."

    def __init__(self, binary=None, model=None):
        super().__init__(binary)
        self.model = _model(model, "VANTAGE_COACH_CLAUDE_MODEL", CLAUDE_MODEL)

    def _invoke(self, request, items, workdir, deadline, cancel):
        argv = [
            self.binary,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--tools",
            "",
            "--json-schema",
            json.dumps(request.schema, allow_nan=False),
            "--no-session-persistence",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--system-prompt",
            request.system,
            "--model",
            self.model,
            "--effort",
            "high" if request.purpose == "analysis" else "medium",
        ]
        message = {
            "type": "user",
            "message": {"role": "user", "content": _blocks(items, 0, cache=False)},
        }
        stdin = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        code, stdout, stderr = _run_process(
            argv, stdin, workdir, deadline, cancel, self.label, self.failed
        )
        result, errors = None, [stderr.decode("utf-8", "replace")]
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "result":
                result = event
            elif event.get("type") == "assistant" and isinstance(event.get("error"), str):
                errors.append(event["error"])  # e.g. "authentication_failed", "rate_limit"
        if result is not None and result.get("subtype") == "success" and not result.get("is_error"):
            answer = result.get("structured_output")
            if not isinstance(answer, dict):
                answer = _json_object(result.get("result"))
            if answer is not None:
                return answer
            LOGGER.warning("Claude Code returned no structured output (exit %s)", code)
            raise EngineError(self.failed)
        if result is not None:
            errors += [
                value
                for value in (result.get("result"), result.get("subtype"))
                if isinstance(value, str)
            ]
            errors += [value for value in result.get("errors") or [] if isinstance(value, str)]
        LOGGER.warning("Claude Code failed (exit %s)", code)
        text = "\n".join(errors)
        if SIGN_IN_TEXT.search(text):
            raise EngineError(
                "Claude Code isn't signed in. Run `claude` in a terminal, sign in, then try again."
            )
        if LIMIT_TEXT.search(text):
            raise EngineError(
                "Claude Code reached its usage limit. Try again later or choose another coach engine."
            )
        raise EngineError(self.failed)


class CodexCLIEngine(_CLIEngine):
    """OpenAI Codex `exec` with the prompt on stdin, images as --image, read-only sandbox."""

    id = "codex-cli"
    label = "Codex"
    command = "codex"
    missing = (
        "Codex (codex) isn't installed. Install it and run `codex login`, then restart Vantage."
    )
    failed = "Codex couldn't finish the review. Try again."
    sign_in = "Codex isn't signed in. Run `codex login` in a terminal, then try again."

    def __init__(self, binary=None, model=None):
        super().__init__(binary)
        self.model = _model(model, "VANTAGE_COACH_CODEX_MODEL", None)  # None: the codex default

    def status(self):
        if self.binary and _login_state(self.binary) is False:
            return self._status(True, "Not signed in. Run `codex login` in a terminal.")
        return super().status()

    def _invoke(self, request, items, workdir, deadline, cancel):
        schema_path, answer_path = workdir / "schema.json", workdir / "answer.json"
        schema_path.write_text(json.dumps(request.schema, allow_nan=False), encoding="utf-8")
        texts, images = [request.system.strip()], []
        for part, data in items:
            if data is None:
                if part.strip():
                    texts.append(part)
            else:
                images.append(Path(part.path).resolve())
                texts.append(f"[Image {len(images)}: {part.label.strip()}]")
        prompt = "\n\n".join(texts)
        # No positional prompt: codex reads stdin, and -i would swallow a trailing positional.
        argv = [
            self.binary,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "-s",
            "read-only",
            "-C",
            str(workdir),
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "-o",
            str(answer_path),
        ]
        if self.model:
            argv += ["-m", self.model]
        effort = "high" if request.purpose == "analysis" else "medium"
        argv += ["-c", f'model_reasoning_effort="{effort}"']
        argv += [f"--image={path}" for path in images]
        code, stdout, stderr = _run_process(
            argv, prompt.encode("utf-8"), workdir, deadline, cancel, self.label, self.failed
        )
        if code == 0:
            answer = None
            try:
                with answer_path.open("rb") as stream:
                    raw = stream.read(MAX_OUTPUT_BYTES + 1)
                if len(raw) <= MAX_OUTPUT_BYTES:
                    answer = _json_object(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
            if answer is not None:
                return answer
        LOGGER.warning("Codex failed (exit %s)", code)
        raise EngineError(self._failure(prompt, stdout + b"\n" + stderr))

    def _failure(self, prompt, output):
        with _LOGIN_LOCK:
            _LOGIN_CACHE.pop(self.binary, None)  # A failure is a good time to re-check sign-in.
        if _login_state(self.binary) is False:
            return self.sign_in
        # Codex echoes the prompt; only its own error lines may decide the message.
        echoed = set(prompt.splitlines())
        lines = [
            line
            for line in output.decode("utf-8", "replace").splitlines()
            if line not in echoed
            and re.search(
                r"error|fail|denied|unauthori|forbidden|exceeded|limit|login", line, re.IGNORECASE
            )
        ]
        text = "\n".join(lines)
        if SIGN_IN_TEXT.search(text):
            return self.sign_in
        if LIMIT_TEXT.search(text):
            return "Codex reached its usage limit. Try again later or choose another coach engine."
        return self.failed


class AnthropicAPIEngine(Engine):
    """The Claude API through the official SDK; available when ANTHROPIC_API_KEY is set."""

    id = "anthropic-api"
    label = "Claude API"
    failed = "The Claude API couldn't finish the review. Try again."

    def __init__(self, client_factory=None, model=None):
        self.client_factory = client_factory
        self.model = _model(model, "VANTAGE_COACH_ANTHROPIC_MODEL", ANTHROPIC_MODEL)

    def status(self):
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if self.client_factory is None and importlib.util.find_spec("anthropic") is None:
            return self._status(
                False, "The anthropic Python package is missing. Run uv sync, then restart Vantage."
            )
        if not key or "\r" in key or "\n" in key:
            return self._status(
                False, "Set ANTHROPIC_API_KEY to use the Claude API, then restart Vantage."
            )
        return self._status(True, None)

    def run(self, request, cancel=None):
        items = _prepare(request)
        status = self.status()
        if not status["available"]:
            raise EngineError(status["detail"])
        import anthropic

        factory = self.client_factory or anthropic.Anthropic
        # No thinking or sampling parameters: Opus 5.5 rejects disabled thinking and
        # sampling overrides. Effort is the depth control.
        arguments = {
            "model": self.model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "system": [{"type": "text", "text": request.system}],
            "messages": [
                {"role": "user", "content": _blocks(items, request.stable_parts, cache=True)}
            ],
            "output_config": {
                "effort": "high" if request.purpose == "analysis" else "medium",
                "format": {"type": "json_schema", "schema": request.schema},
            },
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        deadline = time.monotonic() + request.timeout_s
        _acquire(deadline, cancel)
        outcome, clients, finished = {}, [], threading.Event()

        def call():
            try:
                clients.append(factory(timeout=request.timeout_s, max_retries=2))
                outcome["response"] = clients[0].beta.messages.create(**arguments)
            except Exception as exc:  # Mapped to a safe message below.
                outcome["error"] = exc
            finally:
                _SLOTS.release()  # Held until the HTTP call really ends, even after cancel.
                finished.set()

        try:
            threading.Thread(target=call, name="vantage-coach-api", daemon=True).start()
        except RuntimeError:
            _SLOTS.release()
            raise EngineError(self.failed) from None
        while not finished.wait(POLL_S):
            try:
                _check(deadline, cancel)
            except EngineError:
                for client in clients:
                    try:
                        client.close()  # Best effort: abandon the in-flight request.
                    except Exception:
                        pass
                raise
        if "error" in outcome:
            LOGGER.warning("Claude API request failed: %s", type(outcome["error"]).__name__)
            raise EngineError(self._message(anthropic, outcome["error"])) from None
        return self._answer(outcome["response"])

    def _message(self, anthropic, error):
        if isinstance(error, anthropic.AuthenticationError):
            return "ANTHROPIC_API_KEY was rejected. Check the key, then restart Vantage."
        if isinstance(error, anthropic.NotFoundError):
            return "The Claude API doesn't recognise the coach model. Check VANTAGE_COACH_ANTHROPIC_MODEL."
        if isinstance(error, anthropic.RateLimitError):
            return "The Claude API rate limit was reached. Try again in a minute or choose another coach engine."
        if isinstance(error, anthropic.APITimeoutError):
            return TIMED_OUT
        if isinstance(error, anthropic.APIConnectionError):
            return "Couldn't reach the Claude API. Check your internet connection and try again."
        return self.failed

    def _answer(self, response):
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            raise EngineError("The AI declined to review this request.")
        if stop in ("max_tokens", "model_context_window_exceeded"):
            raise EngineError("The coach's answer ran too long. Try again.")
        # Fallback/thinking blocks may precede the answer; the first text block is the JSON.
        text = next(
            (
                getattr(block, "text", None)
                for block in getattr(response, "content", None) or []
                if getattr(block, "type", None) == "text"
            ),
            None,
        )
        answer = _json_object(text)
        if answer is None:
            raise EngineError(self.failed)
        return answer


def all_engines() -> dict[str, Engine]:
    """Fresh instances, so binaries and environment changes are picked up; cheap."""
    return {
        engine.id: engine for engine in (ClaudeCLIEngine(), CodexCLIEngine(), AnthropicAPIEngine())
    }


def _auto_order(engines):
    preferred = os.environ.get("VANTAGE_COACH_ENGINE", "").strip()
    return (
        [preferred] + [item for item in ENGINE_ORDER if item != preferred]
        if preferred in engines
        else ENGINE_ORDER
    )


def configuration() -> dict:
    """Every engine's status in ENGINE_ORDER and the one auto-selection would use."""
    engines = all_engines()
    statuses = {identity: engines[identity].status() for identity in ENGINE_ORDER}
    default = next(
        (identity for identity in _auto_order(engines) if statuses[identity]["available"]), None
    )
    return {"engines": [statuses[identity] for identity in ENGINE_ORDER], "default": default}


def select_engine(engine_id: str | None) -> Engine:
    """The named engine, or VANTAGE_COACH_ENGINE / the first available one when None or empty."""
    if engine_id is not None and not isinstance(engine_id, str):
        raise ValueError("Choose a valid coach engine.")
    engines = all_engines()
    if engine_id:
        if engine_id not in engines:
            raise ValueError("Choose a valid coach engine.")
        status = engines[engine_id].status()
        if not status["available"]:
            raise EngineError(status["detail"] or NO_ENGINE)
        return engines[engine_id]
    for identity in _auto_order(engines):
        if engines[identity].status()["available"]:
            return engines[identity]
    raise EngineError(NO_ENGINE)
