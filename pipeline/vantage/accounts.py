"""Local accounts: one owner account per Vantage library, with password sign-in.

The account lives in ``<runs-dir>/.vantage/account.json`` next to the games it protects. Passwords
are hashed with scrypt; sessions are random tokens of which only a SHA-256 digest is stored. The
messages here are shared word for word with the iPhone app (docs/app-experience.md).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

SESSION_SECONDS = 30 * 24 * 60 * 60
MAX_SESSIONS = 10
NAME_MAX = 80
EMAIL_MAX = 254
PASSWORD_MIN, PASSWORD_MAX = 8, 128
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Five wrong passwords within five minutes lock sign-in for a minute.
FAILURE_LIMIT, FAILURE_WINDOW_S, LOCKOUT_S = 5, 300, 60
# OWASP's scrypt setting for 16 MiB of memory (N=2^14, r=8, p=5). Each stored hash keeps its
# own parameters, so older hashes still verify.
SCRYPT = {"n": 2**14, "r": 8, "p": 5}

NAME_ERROR = "Enter your name."
EMAIL_ERROR = "Enter a valid email address."
PASSWORD_ERROR = "Use at least 8 characters."
SIGN_IN_ERROR = "That email and password don't match."
LOCKED_ERROR = "Too many attempts. Wait a minute and try again."
CURRENT_PASSWORD_ERROR = "Your current password isn't right."
SIGNED_OUT_ERROR = "Sign in to continue."
SAVE_ERROR = (
    "Vantage can't save your account in this library folder. Start Vantage with a --runs-dir "
    "you can write to."
)
UNREADABLE_ERROR = (
    "Your account file couldn't be read. Run vantage-app --reset-account to start a new account; "
    "your games stay in your library."
)


class AccountError(ValueError):
    """A message safe to show the user, the form field it belongs to, an HTTP status, and an
    optional machine-readable code ("signed_out" sends the browser back to Sign in)."""

    def __init__(
        self, message: str, field: str | None = None, status: int = 400, code: str | None = None
    ):
        super().__init__(message)
        self.field, self.status, self.code = field, status, code


def clean_name(value) -> str:
    name = " ".join(value.split()) if isinstance(value, str) else ""
    if not name or len(name) > NAME_MAX:
        raise AccountError(NAME_ERROR, "name")
    return name


def clean_email(value) -> str:
    email = value.strip().lower() if isinstance(value, str) else ""
    if len(email) > EMAIL_MAX or not EMAIL.fullmatch(email):
        raise AccountError(EMAIL_ERROR, "email")
    return email


def check_password(value, field="password") -> str:
    if not isinstance(value, str) or not PASSWORD_MIN <= len(value) <= PASSWORD_MAX:
        raise AccountError(PASSWORD_ERROR, field)
    return value


def _hash(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> dict:
    salt = secrets.token_bytes(16)
    return {
        "scheme": "scrypt",
        **SCRYPT,
        "salt": salt.hex(),
        "hash": _hash(password, salt, **SCRYPT).hex(),
    }


def verify_password(password: str, stored: dict) -> bool:
    try:
        expected = bytes.fromhex(stored["hash"])
        actual = _hash(
            password, bytes.fromhex(stored["salt"]), stored["n"], stored["r"], stored["p"]
        )
    except (KeyError, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _well_formed(data) -> bool:
    """True for account.json as _save writes it; anything else gets the recovery message."""
    if not isinstance(data, dict) or not isinstance(data.get("sessions", []), list):
        return False
    account = data.get("account")
    return (
        isinstance(account, dict)
        and all(isinstance(account.get(key), str) for key in ("id", "name", "email", "created_at"))
        and isinstance(account.get("password"), dict)
    )


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def initials(name: str) -> str:
    parts = name.split()
    return "".join(part[0] for part in (parts[:1] + parts[1:][-1:])).upper() or "?"


class AccountStore:
    """Thread-safe owner account and its sessions, reloaded whenever the file changes on disk."""

    def __init__(self, root: Path, clock=time.time):
        self.path = Path(root) / ".vantage" / "account.json"
        self._clock = clock
        self._lock = threading.Lock()
        self._data = None
        self._signature = None
        self._failures = deque()
        self._locked_until = 0.0

    # Storage --------------------------------------------------------------------------------
    def _load(self):
        try:
            info = self.path.stat()
        except FileNotFoundError:
            self._data, self._signature = None, None
            return None
        signature = (info.st_size, info.st_mtime_ns)
        if signature != self._signature:
            try:
                data = json.loads(self.path.read_text())
                if not _well_formed(data):
                    raise ValueError("account.json has an unexpected shape")
            except (OSError, ValueError, RecursionError) as exc:
                raise AccountError(UNREADABLE_ERROR, status=500) from exc
            data["sessions"] = [
                s
                for s in data.get("sessions", [])
                if isinstance(s, dict)
                and isinstance(s.get("id"), str)
                and _number(s.get("expires_at"))
            ]
            self._data, self._signature = data, signature
        return self._data

    def _save(self, data):
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=".account-", dir=self.path.parent)
        except OSError as exc:
            # A read-only library can't hold an account, so say what to do instead.
            raise AccountError(SAVE_ERROR, status=500) from exc
        try:
            with os.fdopen(handle, "w") as stream:
                json.dump(data, stream, indent=2)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            Path(temporary).unlink(missing_ok=True)
            raise AccountError(SAVE_ERROR, status=500) from exc
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        info = self.path.stat()
        self._data, self._signature = data, (info.st_size, info.st_mtime_ns)

    def _start_session(self, data) -> str:
        now = self._clock()
        token = secrets.token_urlsafe(32)
        sessions = [s for s in data["sessions"] if s.get("expires_at", 0) > now]
        sessions.append(
            {"id": _digest(token), "created_at": now, "expires_at": now + SESSION_SECONDS}
        )
        data["sessions"] = sessions[-MAX_SESSIONS:]
        return token

    def _session(self, data, token):
        if not data or not isinstance(token, str) or not token:
            return None
        digest, now = _digest(token), self._clock()
        return next(
            (
                s
                for s in data["sessions"]
                if hmac.compare_digest(s["id"].encode(), digest.encode())
                and s.get("expires_at", 0) > now
            ),
            None,
        )

    @staticmethod
    def public(account: dict) -> dict:
        return {
            "id": account["id"],
            "name": account["name"],
            "email": account["email"],
            "initials": initials(account["name"]),
            "created_at": account["created_at"],
        }

    # Queries --------------------------------------------------------------------------------
    def exists(self) -> bool:
        with self._lock:
            return self._load() is not None

    def status(self, token) -> dict:
        """What the sign-in screens need: whether an account exists, and who's signed in."""
        with self._lock:
            data = self._load()
            signed_in = self._session(data, token) is not None
            account = data["account"] if data else None
            return {
                "has_account": account is not None,
                "account": self.public(account) if signed_in else None,
                # Fill in the sign-in form; this computer's owner already knows it.
                "email": account["email"] if account else None,
                "first_name": account["name"].split()[0] if account else None,
            }

    def account_for(self, token):
        with self._lock:
            data = self._load()
            return self.public(data["account"]) if self._session(data, token) else None

    # Actions --------------------------------------------------------------------------------
    def create(self, name, email, password):
        name, email, password = clean_name(name), clean_email(email), check_password(password)
        with self._lock:
            if self._load() is not None:
                raise AccountError(
                    "This library already has an account. Sign in instead.", status=409
                )
            data = {
                "version": 1,
                "account": {
                    "id": secrets.token_hex(8),
                    "name": name,
                    "email": email,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "password": hash_password(password),
                },
                "sessions": [],
            }
            token = self._start_session(data)
            self._save(data)
            return self.public(data["account"]), token

    def _check_lock(self, now):
        if now < self._locked_until:
            raise AccountError(LOCKED_ERROR, status=429)

    def _fail(self, now, error: AccountError):
        """Count a wrong password (at sign-in or when changing it) toward the lockout."""
        while self._failures and now - self._failures[0] > FAILURE_WINDOW_S:
            self._failures.popleft()
        self._failures.append(now)
        if len(self._failures) >= FAILURE_LIMIT:
            self._failures.clear()
            self._locked_until = now + LOCKOUT_S
            raise AccountError(LOCKED_ERROR, status=429)
        raise error

    def sign_in(self, email, password):
        email = email.strip().lower() if isinstance(email, str) else ""
        password = password if isinstance(password, str) else ""
        with self._lock:
            now = self._clock()
            self._check_lock(now)
            data = self._load()
            account = data["account"] if data else None
            # The password is always checked, so a wrong email takes as long as a wrong password.
            matches = (
                account is not None
                and verify_password(password, account["password"])
                and hmac.compare_digest(account["email"].encode(), email.encode())
            )
            if not matches:
                self._fail(now, AccountError(SIGN_IN_ERROR, status=401))
            self._failures.clear()
            token = self._start_session(data)
            self._save(data)
            return self.public(account), token

    def sign_out(self, token):
        with self._lock:
            data = self._load()
            session = self._session(data, token)
            if session:
                data["sessions"] = [s for s in data["sessions"] if s is not session]
                self._save(data)

    def update_profile(self, token, name, email):
        with self._lock:
            data = self._require(token)
            data["account"].update(name=clean_name(name), email=clean_email(email))
            self._save(data)
            return self.public(data["account"])

    def change_password(self, token, current, new):
        with self._lock:
            data = self._require(token)
            now = self._clock()
            # Guessing the current password here is limited like guessing it at sign-in.
            self._check_lock(now)
            if not isinstance(current, str) or not verify_password(
                current, data["account"]["password"]
            ):
                self._fail(now, AccountError(CURRENT_PASSWORD_ERROR, "current_password"))
            data["account"]["password"] = hash_password(check_password(new, "new_password"))
            # Changing the password signs out every other browser.
            keep = self._session(data, token)
            data["sessions"] = [keep]
            self._save(data)
            return self.public(data["account"])

    def _require(self, token):
        data = self._load()
        if self._session(data, token) is None:
            raise AccountError(SIGNED_OUT_ERROR, status=401, code="signed_out")
        return data

    def reset(self):
        """Remove the account (not the games). Returns the removed account's email, if any."""
        with self._lock:
            # Reset is the way out of a broken file too, so it never depends on reading it.
            try:
                data = self._load()
            except AccountError:
                data = None
            email = data["account"]["email"] if data else None
            self.path.unlink(missing_ok=True)
            self._data, self._signature = None, None
            return email
