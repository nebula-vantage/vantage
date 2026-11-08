# Vantage app experience: web and iPhone

The desktop/web app (`pipeline/vantage/web/`) and the iPhone app (`ios/VantageMobile/`) are one
product. They use the same names, the same flow, the same words and the same design tokens.
When you change one of them, check this page and change the other to match, or note here why it
differs.

## Principles

- **One product.** A screen on the iPhone and its web counterpart have the same title, the same
  primary action and the same copy. Platform conventions decide layout only, such as a sidebar on
  desktop and a sheet on iPhone.
- **One primary action per screen.** Secondary actions are text buttons or links. App-wide
  chrome (the web sidebar's Upload video button) doesn't count against a page's content.
- **Everything lives in one place.** Navigation (sidebar, tabs, breadcrumb) plus at most one
  "next step" suggestion; no feature gets two other entry points on the same screen, and no page
  repeats its own title (a game's breadcrumb reads "← Games", not the game's name again).

## Brand and tokens

- **Mark:** the orange V with a slash from the landing page (`site/index.html`, `icon-logo`).
- **Wordmark:** "vantage." in Bricolage Grotesque Bold with an orange period, as on the landing
  page.
- **Type:** Bricolage Grotesque for headings and numbers, IBM Plex Sans for body text, and IBM
  Plex Mono capitals for eyebrows and labels.

| Token | Value | Web (`app.css`) | iPhone (`Theme.swift`) |
| --- | --- | --- | --- |
| Background | `#F5F6F8` | `--bg` | `Colors.background` |
| Surface | `#FFFFFF` | `--surface` | `Colors.surface` |
| Ink | `#0F141A` | `--ink` | `Colors.ink` |
| Secondary text | `#5B6573` | `--muted` | `Colors.inkSecondary` |
| Tertiary text | `#9096A0` | `--faint` | `Colors.inkTertiary` |
| Hairline | `#DCE0E6` | `--line` | `Colors.hairline` |
| Track | `#E9ECF0` | `--track` | `Colors.track` |
| Accent | `#E8590C` | `--accent` | `Colors.accent` |
| Positive | `#0F766E` | `--positive` | `Colors.positive` |
| Error | `#9D3027` | `--error` | `Colors.error` |
| Error banner fill / border | `#FFF7F5` / `#E3BBB6` | `--error-surface` / `--error-line` | `Colors.errorSurface` / `Colors.errorLine` |
| Text on the dark panel | `#C3CCD5` | `--ink-on-dark` | `Colors.inkOnDark` |
| Brand panel, video | `#151B22` | `--video` | `Colors.videoBackground` |
| Card radius | 18 | `--radius` | `Radius.card` |

`pipeline/tests/test_design_parity.py` fails if these colours drift apart.

## Structure

```
Signed out   Create account  (first launch, no account yet)
             Sign in         (an account exists, but you're signed out)
Signed in    Games           Home: upload a video, open a game
             └ Game          Overview · 3D replay · Coaching (iPhone: Overview only for now)
             Account         Profile, password, where your games are saved, sign out
```

- **Upload video** is the one primary action. On the web it's the sidebar button and the Games
  upload tile. On iPhone it's the Games upload tile.
- **Account** opens from your initials: the sidebar account chip on the web, and the avatar
  button in the Games header on iPhone.
- **Game header:** eyebrow `PICKLEBALL · ANALYZED <date>` (`PICKLEBALL · IMPORTED` for a browser
  import, `PICKLEBALL · SYNTHETIC FOOTAGE` for the sample, whose title already says "Sample
  game"), then the game's name as the page title. The web adds the Overview · 3D replay ·
  Coaching tabs beneath it.
- Developer tools such as debug playback appear in debug builds only.

## Accounts

There is one account per library: per runs directory on the web, per device on iPhone. The
account and the games stay on that computer or iPhone. Nothing is synced between them yet; a
hosted account service can replace the local store later without changing these screens.

- **Web:** `pipeline/vantage/accounts.py` stores the account in `<runs-dir>/.vantage/account.json`
  (mode 0600), so the runs directory must be writable. Passwords are hashed with scrypt (N=2^14,
  r=8, p=5), and sign-in sets an HttpOnly, SameSite=Strict session cookie that lasts 30 days. Every `/api/` and `/media/` request needs that session,
  except the account endpoints themselves.
- **iPhone:** the account is stored in Application Support (left out of backups, because the
  password hash can't be restored with it), with the PBKDF2-SHA256 password hash (600,000
  iterations) in the Keychain. You stay signed in until you sign out.
- On both, the sign-in lockout lives in memory, so restarting the app clears it.

### Shared screens

The sign-in screens have a dark brand panel and a form: side by side on desktop, with the
panel on top on phones (the iPhone app, and the web app below 960 px).

**Brand panel:** background `#151B22` (it runs under the iPhone status bar). The accent mark
(its cut takes the panel colour) and the white wordmark with its accent period, then the headline in white on two
lines, "Your game." / "A new perspective.", then three short lines in `#C3CCD5`, each led by
an accent-coloured line icon (upload arrow, target, check):

- Upload a match from one fixed camera.
- See the rally, the ball and the court.
- Take a focused plan into your next session.

A perspective court outline (from the web's `auth-court` SVG, with an accent ball) sits at the
bottom of the panel.

**Form:** on the page background, not in a card. Eyebrow, title (display font), body, then
fields. Field labels are sentence case in IBM Plex Sans SemiBold ("Email", not "EMAIL"). Inputs
are white with a hairline border, 12-point corners and at least 48 points tall; an invalid
field's border turns to the error colour and its message sits under it. Errors that belong to
the whole form ("That email and password don't match.") sit in a tinted banner above the
fields. The primary button spans the form's width. **Forgot password?** sits at the right of
the Password label row.

**Create account.** Shown when there's no account yet.

| Part | Text |
| --- | --- |
| Eyebrow | GET STARTED |
| Title | Create your account |
| Body | Your games, replays and coaching, in one place. |
| Fields | Name ("Your name"), Email ("you@example.com"), Password ("At least 8 characters", with a Show/Hide toggle) |
| Button | Create account (busy: Creating account…) |
| Footnote | Your account and games are saved on this computer. (iPhone: on this iPhone.) |

**Sign in.** Shown when an account exists and you're signed out.

| Part | Text |
| --- | --- |
| Eyebrow | WELCOME BACK |
| Title | Sign in to Vantage |
| Body | Pick up where you left off, {first name}. |
| Fields | Email (filled in with the account's email), Password (Show/Hide toggle) |
| Button | Sign in (busy: Signing in…) |
| Link | Forgot password? |
| Empty fields | An empty email or password is never sent, so it can't count toward the lockout. The iPhone disables Sign in until both have text; the web keeps it enabled (browsers hide autofilled passwords from scripts until you interact) and focuses the empty field. |

**Forgot password.** You can't recover a local account, so this resets it and keeps the games.

- **Web:** shows inline help: "Run `uv run vantage-app --reset-account` in the terminal where
  you start Vantage, then reload this page. Your games stay in your library."
- **iPhone:** a confirmation titled "Reset your account?" with the message "This removes the
  account from this iPhone so you can create a new one. Your games stay on this iPhone." and a
  destructive "Reset account" button.

**Validation and errors.** Both apps show these exact strings under the field or form:

| Rule | Message |
| --- | --- |
| Name is 1–80 characters after trimming | Enter your name. |
| Email matches `^[^@\s]+@[^@\s]+\.[^@\s]+$`, up to 254 characters (stored trimmed and lowercased) | Enter a valid email address. |
| Password is 8–128 characters | Use at least 8 characters. |
| Wrong email or password | That email and password don't match. |
| Five wrong passwords within five minutes (at sign-in or as the current password when changing it) lock both for 60 seconds | Too many attempts. Wait a minute and try again. |
| Current password is wrong when changing it | Your current password isn't right. |
| iPhone storage failures | Your account couldn't be saved. Try again. / Your account couldn't be reset. Try again. |
| Web: the runs directory is read-only | Vantage can't save your account in this library folder. Start Vantage with a --runs-dir you can write to. |
| Web: Vantage isn't running or can't say whether an account exists | Eyebrow VANTAGE, title "Vantage can't open your account", the error ("Couldn't reach Vantage. Check that it's running, then try again." or the account-file recovery message) and a Try again button instead of the form |

### Account screen

| Part | Text |
| --- | --- |
| Title | Account |
| Header | Initials avatar, name, email |
| Profile section | "Profile": Name and Email fields, Save changes button (secondary; enabled once something changes). Confirmation: "Profile saved." |
| Password section | "Password": Current password, New password, Change password button (secondary; enabled once both have text). Confirmation: "Password changed." |
| Storage section | "Where your games live". Web: "Your account and games are saved on this computer. Videos are analyzed here; AI coaching sends still frames only when you ask for a review." iPhone: "Your account and games are saved on this iPhone. Videos are analyzed on the device." |
| Sign out | Sign out (secondary button). You return to Sign in with your email filled in. |

The Account screen has no primary button: none of its actions is the one thing you came to do.
On the web it's a page (title "Account" in the page header); on iPhone it's a sheet (title in
the navigation bar, with Done).

## Games screen copy

| Part | Text |
| --- | --- |
| Eyebrow | YOUR LIBRARY |
| Title | Games |
| Body | Your game. A clearer picture. A next step. |
| Upload tile | "Bring your game into focus." / "Upload a match video. Review the play. Find your next practice focus." / action "Analyze a video" |
| List heading | Your games, with the count ("2 games") |
| Empty state | "Your next game starts here." / "Uploaded games and their analysis stay together in this library." |
| Game card | A cover (the video thumbnail, or a court drawing on the dark panel colour) with a white `PICKLEBALL` label at the top left and the duration on a dark badge at the bottom right; then "Analyzed <date>" (e.g. "Analyzed Nov 7, 2026"), the name, a dot-led status line, and a footer ending "Open game →". The web's status line is the tracking quality ("Analysis ready to review") and its footer starts with "Replay + coaching"; the iPhone shows the share of frames with the ball tracked and has no coaching yet. |
| Sample | Named "Sample game" everywhere. On the web it's offered once: in the empty state when the library is empty, otherwise next to the game count. |
