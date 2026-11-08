"""Local accounts: validation, sessions, lockout, and the sign-in gate on the web app."""

import contextlib
import io
import json
import stat
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from vantage import accounts
from vantage.accounts import AccountError, AccountStore
from vantage.coaching_server import WEB_ROOT, CoachingServer, main


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.store = AccountStore(self.root, clock=self.clock)

    def create(self):
        return self.store.create("  Sam   Rivera ", " Sam@Example.com ", "correct horse")

    def assertAccountError(self, message, call, *args):
        with self.assertRaises(AccountError) as caught:
            call(*args)
        self.assertEqual(str(caught.exception), message)
        return caught.exception

    def test_validation_messages_match_the_iphone_app(self):
        for name in ("", "   ", None, "x" * 81):
            self.assertAccountError(
                "Enter your name.", self.store.create, name, "a@b.co", "12345678"
            )
        for email in ("", "sam", "sam@example", "a b@example.com", None, "a@b." + "c" * 260):
            self.assertAccountError(
                "Enter a valid email address.", self.store.create, "Sam", email, "12345678"
            )
        for password in ("", "1234567", None, "x" * 129):
            error = self.assertAccountError(
                "Use at least 8 characters.", self.store.create, "Sam", "a@b.co", password
            )
            self.assertEqual(error.field, "password")
        self.assertFalse(self.store.exists())

    def test_create_cleans_fields_and_signs_in(self):
        account, token = self.create()
        self.assertEqual(account["name"], "Sam Rivera")
        self.assertEqual(account["email"], "sam@example.com")
        self.assertEqual(account["initials"], "SR")
        self.assertEqual(self.store.account_for(token), account)
        status = self.store.status(token)
        self.assertTrue(status["has_account"])
        self.assertEqual(status["account"], account)
        signed_out = self.store.status(None)
        self.assertIsNone(signed_out["account"])
        self.assertEqual(signed_out["email"], "sam@example.com")
        self.assertEqual(signed_out["first_name"], "Sam")
        error = self.assertAccountError(
            "This library already has an account. Sign in instead.", self.create
        )
        self.assertEqual(error.status, 409)

    def test_password_is_hashed_and_the_file_is_private(self):
        self.create()
        raw = self.store.path.read_text()
        self.assertNotIn("correct horse", raw)
        self.assertEqual(json.loads(raw)["account"]["password"]["scheme"], "scrypt")
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.store.path.parent.stat().st_mode), 0o700)

    def test_sign_in_accepts_any_email_case_and_rejects_wrong_details(self):
        self.create()
        account, token = self.store.sign_in("SAM@example.com ", "correct horse")
        self.assertEqual(self.store.account_for(token), account)
        message = "That email and password don't match."
        self.assertAccountError(message, self.store.sign_in, "sam@example.com", "wrong horse")
        self.assertAccountError(message, self.store.sign_in, "other@example.com", "correct horse")
        self.assertAccountError(message, self.store.sign_in, None, None)

    def test_five_failures_lock_sign_in_for_a_minute(self):
        self.create()
        for _ in range(4):
            self.assertRaises(AccountError, self.store.sign_in, "sam@example.com", "nope nope")
        locked = "Too many attempts. Wait a minute and try again."
        error = self.assertAccountError(locked, self.store.sign_in, "sam@example.com", "nope nope")
        self.assertEqual(error.status, 429)
        # Even the right password waits out the lock.
        self.clock.now += 59
        self.assertAccountError(locked, self.store.sign_in, "sam@example.com", "correct horse")
        self.clock.now += 2
        self.store.sign_in("sam@example.com", "correct horse")

    def test_failures_outside_the_window_do_not_count(self):
        self.create()
        for _ in range(4):
            self.assertRaises(AccountError, self.store.sign_in, "sam@example.com", "nope nope")
        self.clock.now += accounts.FAILURE_WINDOW_S + 1
        error = self.assertAccountError(
            "That email and password don't match.",
            self.store.sign_in,
            "sam@example.com",
            "nope nope",
        )
        self.assertEqual(error.status, 401)

    def test_sessions_expire_and_sign_out_revokes_only_that_session(self):
        _, first = self.create()
        _, second = self.store.sign_in("sam@example.com", "correct horse")
        self.store.sign_out(first)
        self.assertIsNone(self.store.account_for(first))
        self.assertIsNotNone(self.store.account_for(second))
        self.clock.now += accounts.SESSION_SECONDS + 1
        self.assertIsNone(self.store.account_for(second))
        self.assertIsNone(self.store.account_for("not-a-token"))
        self.assertIsNone(self.store.account_for(None))

    def test_profile_and_password_changes(self):
        _, token = self.create()
        _, other = self.store.sign_in("sam@example.com", "correct horse")
        account = self.store.update_profile(token, "Sam R", "sam.r@example.com")
        self.assertEqual((account["name"], account["email"]), ("Sam R", "sam.r@example.com"))
        self.assertAccountError("Enter your name.", self.store.update_profile, token, "", "a@b.co")
        error = self.assertAccountError(
            "Your current password isn't right.",
            self.store.change_password,
            token,
            "wrong horse",
            "battery staple",
        )
        self.assertEqual(error.field, "current_password")
        error = self.assertAccountError(
            "Use at least 8 characters.",
            self.store.change_password,
            token,
            "correct horse",
            "short",
        )
        self.assertEqual(error.field, "new_password")
        self.store.change_password(token, "correct horse", "battery staple")
        # Other browsers are signed out; this one stays signed in.
        self.assertIsNotNone(self.store.account_for(token))
        self.assertIsNone(self.store.account_for(other))
        self.assertRaises(AccountError, self.store.sign_in, "sam.r@example.com", "correct horse")
        self.store.sign_in("sam.r@example.com", "battery staple")
        error = self.assertAccountError(
            "Sign in to continue.", self.store.update_profile, "stale", "Sam", "a@b.co"
        )
        self.assertEqual(error.status, 401)

    def test_reset_removes_the_account_but_not_games_and_running_servers_notice(self):
        game = self.root / "weekend"
        game.mkdir()
        (game / "stats.json").write_text("{}")
        _, token = self.create()
        # A second store, like the reset command, removes the file under a running server.
        self.assertEqual(AccountStore(self.root).reset(), "sam@example.com")
        self.assertTrue((game / "stats.json").is_file())
        self.assertIsNone(self.store.account_for(token))
        self.assertFalse(self.store.exists())
        self.assertIsNone(self.store.reset())
        self.create()

    def test_wrong_password_changes_count_toward_the_lockout(self):
        _, token = self.create()
        for _ in range(4):
            self.assertRaises(
                AccountError, self.store.change_password, token, "nope nope", "battery staple"
            )
        locked = "Too many attempts. Wait a minute and try again."
        error = self.assertAccountError(
            locked, self.store.change_password, token, "nope nope", "battery staple"
        )
        self.assertEqual(error.status, 429)
        # The lock covers sign-in too, and the right current password waits it out.
        self.assertAccountError(locked, self.store.sign_in, "sam@example.com", "correct horse")
        self.assertAccountError(
            locked, self.store.change_password, token, "correct horse", "battery staple"
        )
        self.clock.now += accounts.LOCKOUT_S + 1
        self.store.change_password(token, "correct horse", "battery staple")

    def test_signed_out_profile_changes_say_so_with_a_code(self):
        self.create()
        error = self.assertAccountError(
            "Sign in to continue.", self.store.change_password, "stale", "a", "b"
        )
        self.assertEqual((error.status, error.code), (401, "signed_out"))

    def test_a_read_only_library_explains_itself(self):
        locked = self.root / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o700)
        store = AccountStore(locked)
        error = self.assertAccountError(
            "Vantage can't save your account in this library folder. Start Vantage with a "
            "--runs-dir you can write to.",
            store.create,
            "Sam",
            "sam@example.com",
            "correct horse",
        )
        self.assertEqual(error.status, 500)
        self.assertFalse(store.exists())

    def test_wrong_shaped_account_files_get_the_recovery_message_and_can_be_reset(self):
        account = {
            "id": "a1",
            "name": "Sam",
            "email": "sam@example.com",
            "created_at": "2026-11-07T00:00:00+00:00",
            "password": accounts.hash_password("correct horse"),
        }
        shapes = [
            {"account": account, "sessions": None},
            {"account": account, "sessions": 3},
            {"account": {}},
            {"account": {**account, "email": None}},
            {"account": {**account, "password": "plain"}},
            [],
        ]
        message = (
            "Your account file couldn't be read. Run vantage-app --reset-account to start a new "
            "account; your games stay in your library."
        )
        self.store.path.parent.mkdir(parents=True)
        for shape in shapes:
            with self.subTest(shape=shape):
                self.store.path.write_text(json.dumps(shape))
                self.assertAccountError(message, self.store.status, None)
                self.assertAccountError(message, self.store.sign_in, "sam@example.com", "x")
                AccountStore(self.root).reset()
                self.assertFalse(self.store.path.exists())
        # Sessions that aren't well formed are ignored, not fatal.
        self.store.path.write_text(
            json.dumps(
                {
                    "account": account,
                    "sessions": [{"id": 5}, {"id": "x", "expires_at": "soon"}, "junk"],
                }
            )
        )
        self.assertIsNone(self.store.account_for("token"))
        self.store.sign_in("sam@example.com", "correct horse")

    def test_a_corrupt_account_file_explains_how_to_recover(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text("{not json")
        error = self.assertAccountError(
            "Your account file couldn't be read. Run vantage-app --reset-account to start a new "
            "account; your games stay in your library.",
            self.store.account_for,
            "token",
        )
        self.assertEqual(error.status, 500)
        self.assertIsNone(self.store.reset())
        self.assertFalse(self.store.path.exists())


class SignInGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = Path(self.temp.name) / "runs"
        run = self.runs / "weekend"
        run.mkdir(parents=True)
        (run / "stats.json").write_text((WEB_ROOT / "demo-stats.json").read_text())
        (run / "prepared.mp4").write_bytes(b"0123456789")
        self.server = CoachingServer(("127.0.0.1", 0), self.runs)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.cookie_name = f"vantage_session_{self.server.server_port}"

    def request(self, method, path, body=None, headers=None, cookie=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        headers = dict(headers or {})
        if cookie:
            headers["Cookie"] = f"{self.cookie_name}={cookie}"
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        data = json.loads(raw) if "json" in response.getheader("Content-Type", "") else raw
        return response.status, data, response

    def session_cookie(self, response):
        header = response.getheader("Set-Cookie")
        self.assertIsNotNone(header)
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Strict", header)
        self.assertIn("Path=/", header)
        return header.split(";")[0].split("=", 1)[1], header

    def test_pages_load_signed_out_but_data_and_media_need_a_session(self):
        for path in ("/", "/games", "/sign-in", "/create-account", "/account", "/app.js"):
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 200, path)
        listing = self.request("GET", "/api/sessions")
        self.assertEqual(listing[0], 401)
        self.assertEqual(listing[1], {"error": "Sign in to continue.", "code": "signed_out"})
        session_id = next(iter(self.server.library.directories()))
        for path in ("/api/config", "/api/demo", f"/media/{session_id}/prepared.mp4"):
            self.assertEqual(self.request("GET", path)[0], 401, path)
        for path in ("/api/report", "/api/analysis", f"/api/coach/{session_id}/analyze"):
            self.assertEqual(self.request("POST", path, {})[0], 401, path)
        status, _, _ = self.request("GET", "/api/sessions", cookie="forged-token")
        self.assertEqual(status, 401)

    def test_create_sign_out_and_sign_in_round_trip(self):
        status, account_status, _ = self.request("GET", "/api/account")
        self.assertEqual(status, 200)
        self.assertFalse(account_status["has_account"])
        status, created, response = self.request(
            "POST",
            "/api/account/create",
            {"name": "Sam Rivera", "email": "sam@example.com", "password": "correct horse"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["account"]["initials"], "SR")
        token, header = self.session_cookie(response)
        self.assertIn(f"Max-Age={30 * 24 * 60 * 60}", header)
        self.assertEqual(self.request("GET", "/api/sessions", cookie=token)[0], 200)
        _, signed_in, _ = self.request("GET", "/api/account", cookie=token)
        self.assertEqual(signed_in["account"]["email"], "sam@example.com")

        status, _, response = self.request("POST", "/api/account/sign-out", {}, cookie=token)
        self.assertEqual(status, 200)
        cleared, header = self.session_cookie(response)
        self.assertEqual(cleared, "")
        self.assertIn("Max-Age=0", header)
        self.assertEqual(self.request("GET", "/api/sessions", cookie=token)[0], 401)
        _, signed_out, _ = self.request("GET", "/api/account")
        self.assertEqual(
            (signed_out["email"], signed_out["first_name"]), ("sam@example.com", "Sam")
        )

        status, error, _ = self.request(
            "POST", "/api/account/sign-in", {"email": "sam@example.com", "password": "nope nope"}
        )
        self.assertEqual((status, error["error"]), (401, "That email and password don't match."))
        status, _, response = self.request(
            "POST",
            "/api/account/sign-in",
            {"email": "sam@example.com", "password": "correct horse"},
        )
        self.assertEqual(status, 200)
        token, _ = self.session_cookie(response)
        self.assertEqual(self.request("GET", "/api/sessions", cookie=token)[0], 200)

    def test_other_localhost_cookies_do_not_hide_the_session(self):
        _, token = self.server.accounts.create("Sam", "sam@example.com", "correct horse")
        header = (
            'username-localhost-8888="2|1:0|10:17|bad\\"quote"; _xsrf=2|abc; '
            f"{self.cookie_name}={token}; theme=dark"
        )
        status, _, _ = self.request("GET", "/api/sessions", headers={"Cookie": header})
        self.assertEqual(status, 200)
        other_port = f"vantage_session_{self.server.server_port + 1}={token}"
        self.assertEqual(
            self.request("GET", "/api/sessions", headers={"Cookie": other_port})[0], 401
        )

    def test_form_errors_name_their_field(self):
        status, error, _ = self.request(
            "POST", "/api/account/create", {"name": "Sam", "email": "sam", "password": "x" * 8}
        )
        self.assertEqual(status, 400)
        self.assertEqual(error, {"error": "Enter a valid email address.", "field": "email"})
        status, error, _ = self.request("POST", "/api/account/profile", {"name": "Sam"})
        self.assertEqual(error, {"error": "Sign in to continue.", "code": "signed_out"})
        self.assertEqual(status, 401)
        self.assertEqual(self.request("POST", "/api/account/delete", {})[0], 404)
        status, _, _ = self.request(
            "POST", "/api/account/sign-in", b"x", {"Content-Type": "text/plain"}
        )
        self.assertEqual(status, 415)

    def test_cross_site_sign_in_is_refused(self):
        status, _, _ = self.request(
            "POST",
            "/api/account/sign-in",
            {"email": "sam@example.com", "password": "correct horse"},
            {"Origin": "https://example.com"},
        )
        self.assertEqual(status, 403)


class ResetCommandTests(unittest.TestCase):
    def test_reset_account_command_keeps_games(self):
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            AccountStore(runs).create("Sam", "sam@example.com", "correct horse")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--runs-dir", str(runs), "--reset-account"]), 0)
            self.assertIn("Removed the account for sam@example.com", output.getvalue())
            self.assertFalse(AccountStore(runs).exists())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(["--runs-dir", str(runs), "--reset-account"])
            self.assertIn("has no account", output.getvalue())
            (runs / ".vantage").mkdir(exist_ok=True)
            (runs / ".vantage" / "account.json").write_text("{broken")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(["--runs-dir", str(runs), "--reset-account"])
            self.assertIn("Removed an unreadable account file", output.getvalue())
            self.assertFalse((runs / ".vantage" / "account.json").exists())


if __name__ == "__main__":
    unittest.main()
