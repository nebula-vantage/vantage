"""The web app and the iPhone app are one product: same palette, same account words.

See docs/app-experience.md. These checks fail when one side changes without the other.
"""

import re
import unittest
from pathlib import Path

from vantage import accounts

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "pipeline" / "vantage" / "web"
IOS = ROOT / "ios"
THEME = IOS / "VantageMobile" / "DesignSystem" / "Theme.swift"
# app.css custom property -> Theme.Colors member.
COLOURS = {
    "bg": "background",
    "surface": "surface",
    "ink": "ink",
    "muted": "inkSecondary",
    "faint": "inkTertiary",
    "line": "hairline",
    "track": "track",
    "accent": "accent",
    "positive": "positive",
    "error": "error",
    "error-surface": "errorSurface",
    "error-line": "errorLine",
    "ink-on-dark": "inkOnDark",
    "video": "videoBackground",
    "court-surround": "courtSurround",
    "court-surface": "courtSurface",
}
ACCOUNT_MESSAGES = (
    accounts.NAME_ERROR,
    accounts.EMAIL_ERROR,
    accounts.PASSWORD_ERROR,
    accounts.SIGN_IN_ERROR,
    accounts.LOCKED_ERROR,
    accounts.CURRENT_PASSWORD_ERROR,
)
SCREEN_COPY = (
    "Create your account",
    "Sign in to Vantage",
    "Your games, replays and coaching, in one place.",
    "Forgot password?",
    "Where your games live",
    "Bring your game into focus.",
    "Your next game starts here.",
)


def _code(text, comment):
    """Source without whole-line comments or anything from the first #Preview on, so copy that
    only survives in a comment, a preview or a test can't satisfy these checks."""
    text = text.split("#Preview", 1)[0]
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(comment))


def swift_sources():
    """The shipped iPhone code: the app and VantageKit's library sources, not its tests."""
    paths = sorted((IOS / "VantageMobile").rglob("*.swift"))
    paths += sorted((IOS / "VantageKit" / "Sources").rglob("*.swift"))
    return "\n".join(_code(path.read_text(), "//") for path in paths)


def web_sources():
    return (WEB / "index.html").read_text() + _code((WEB / "app.js").read_text(), "//")


def literal(text):
    """A string as it appears quoted in code or between HTML tags."""
    return (f'"{text}"', f"`{text}`", f">{text}<", f">{text}\n")


class DesignParityTests(unittest.TestCase):
    def test_web_and_iphone_colours_match(self):
        root = re.search(r":root\s*\{(.*?)\}", (WEB / "app.css").read_text(), re.S).group(1)
        css = dict(re.findall(r"--([\w-]+):\s*#([0-9a-fA-F]{6})\b", root))
        swift = dict(
            re.findall(r"static let (\w+) = Color\(hex: 0x([0-9A-Fa-f]{6})\)", THEME.read_text())
        )
        for web, ios in COLOURS.items():
            with self.subTest(web=web, ios=ios):
                self.assertEqual(css[web].lower(), swift[ios].lower())

    def test_card_radius_matches(self):
        css = re.search(r"--radius:\s*(\d+)px", (WEB / "app.css").read_text()).group(1)
        swift = re.search(r"static let card: CGFloat = (\d+)", THEME.read_text()).group(1)
        self.assertEqual(css, swift)

    def assertShipped(self, text, source, where):
        self.assertTrue(
            any(form in source for form in literal(text)), f"{where} doesn't ship {text!r}"
        )

    def test_account_messages_are_shared_word_for_word(self):
        web, ios = web_sources(), swift_sources()
        for message in ACCOUNT_MESSAGES:
            with self.subTest(message=message):
                # The browser checks name, email and password itself before asking the server.
                if message in (accounts.NAME_ERROR, accounts.EMAIL_ERROR, accounts.PASSWORD_ERROR):
                    self.assertShipped(message, web, "the web app")
                self.assertShipped(message, ios, "the iPhone app")

    def test_screens_use_the_same_copy(self):
        web, ios = web_sources(), swift_sources()
        for text in SCREEN_COPY:
            with self.subTest(text=text):
                self.assertShipped(text, web, "the web app")
                self.assertShipped(text, ios, "the iPhone app")


if __name__ == "__main__":
    unittest.main()
