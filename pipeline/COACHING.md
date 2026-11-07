# Vantage — Games and coaching in the desktop/web app

Vantage opens to a Games library. Upload and analyze a video once, then open that
game's Overview for playback and measurements or its Coaching tab for review
moments, a practice plan, and questions about the evidence. Saved games with video
also get an [AI video coach](#ai-video-coach) that looks at still frames from the
game and answers follow-up questions. Both tabs share the
same selected game and video; switching tabs keeps the playback position and
coaching conversation. The app runs on a local Python server. The iPhone app and
public marketing site remain separate; this release does not add account syncing.

## Run it

From the repository root:

```sh
uv sync --locked
uv run vantage-app --open
```

Open <http://127.0.0.1:8765/games> if you omit `--open`. A new library starts with an
empty state; **Explore sample game** explicitly opens the synthetic sample. No API key,
Node installation, or frontend build is needed for the local coaching review. The AI
video coach additionally needs Claude Code, Codex, or an Anthropic API key (see below).
The previous `vantage-coach` command remains an alias for this same app.

Saved games have direct links at `/games/:id`, `/games/:id/replay`, and
`/games/:id/coaching`. Reloading,
browser Back/Forward, and returning to Games preserve the selected route. The
library lists completed analyses from `--runs-dir`, with duration, tracking
coverage, and thumbnails when available. Its date is the analysis file's timestamp,
not the date the match was played. Loading the library does not decode the videos.

To analyze your footage in the browser:

1. Choose **Upload video** and select an MP4, MOV, M4V, WebM, or AVI file.
2. Let the app prepare a constant-frame-rate video and show its first frame.
3. Mark the outer court corners in order: **near-left, near-right, far-right,
   far-left**. You can undo/reset marks or enter pixel coordinates with the keyboard.
4. Choose **Run analysis**. Progress comes from the detector and renderer.
5. When analysis finishes, open the new game from Games. Its Overview plays the
   annotated video and shows measurements; **Coaching** uses the same analysis
   for review moments and a practice plan. No second upload or statistics import is required.

The camera must remain fixed and the whole court must be visible. The current
model and court dimensions are for pickleball. Uploads are limited to 512 MiB,
20 minutes, 72,000 frames, and roughly 4K resolution. High-frame-rate clips may hit
the frame limit before 20 minutes. Processing runs locally on this computer, using
CUDA or Apple MPS when available and CPU otherwise. Large clips can take several minutes. The model's detections,
tracking, projected statistics, bounce candidates, and video overlays all come
from the existing pipeline; no demo measurements are substituted.

Video analysis uses the bundled `ml/models/pickleball-v1.pt` weights. For a packaged
installation outside this repository, set `VANTAGE_MODEL_PATH` to those weights
before starting the server. A missing model disables upload analysis with an
actionable message; saved-run coaching still works. The model must use class IDs
player=0, ball=1, paddle=2. There is no automatic download or model substitution.

You can close the analysis panel while processing and reopen it from its status
banner. Reloading the page resumes polling the saved job ID while the server is
running. Server restarts end unfinished jobs; completed sessions remain on disk.
Cancelling discards unfinished results. During video preparation, cancellation
discards the prepared result after conversion returns.

Alternatively, run the same analysis from the CLI:

```sh
uv run vantage --input input/game.mp4 --output-dir output/game
uv run vantage-app --runs-dir output --open
```

`--runs-dir` accepts a completed run or a folder containing completed runs. The
workspace reads `stats.json` from that directory and its immediate subdirectories;
it does not recursively scan your computer. A run's `annotated.mp4` (or
`prepared.mp4`) and `landing_heatmap.png` are available when present. Annotated
video is converted to a browser-compatible H.264 copy on first playback, using the
existing FFmpeg dependency. This can take a moment for long recordings. The copy
is reused during this server session, stored in a private temporary directory,
and removed when the server closes. Original analysis files remain unchanged. Use `--port`
to run another workspace on a different port. `python -m vantage.coaching_server`
is equivalent to the installed entry point.

You can also import a desktop `stats.json` from Games and attach its matching
video. Imported games are labeled as temporary and last only for the current tab;
reload requires importing them again. The video stays in the browser. Use the analyzed, constant-frame-rate video
so review timestamps align. Browser-attached video must use a supported codec
(H.264 MP4 is recommended); only server-opened runs receive the playback conversion. Importing
statistics does not analyze a raw video.

## What is included

- A Games library with shared video upload, browser court calibration, background analysis,
  progress, and cancellation; coaching lives inside each saved game.
- A session review with coverage, estimated metrics, and concise evidence cards.
- Three focuses: rally consistency, placement, and video review. Changing focus
  changes the review priorities and practice plan.
- Timestamped review moments, linked to video playback when video is available.
- Estimated landing locations from the imported evidence, including uncertain
  candidates. These are not verified line calls.
- A short plan with instructions, duration, and a target for each drill. Completed
  drill checkboxes persist in this browser, separately for each session and focus.
- A local evidence assistant and optional generative AI follow-up questions.
- An AI video coach for saved games with video: a written review grounded in key-moment
  stills, and a chat that can look at the moment you paused on.
- A [3D replay](#3d-replay) of the whole game that you can watch from any angle, with
  your own court position measured against the play.
- A downloadable report/plan for taking the review to the next practice. When an AI
  coach review exists, the export includes it.

The local review is deterministic and works offline. Its answers are assembled
from measured evidence and a small curated drill library; they are labeled as
local, not as model-generated responses. Imported statistics and conversation
state are kept in page memory. Reloading clears imported sessions and chat;
completed-run files can be reopened, and practice checkboxes remain in browser
storage. The server never modifies pipeline outputs. The AI video coach keeps its
own files in a `.coach/` folder inside the run (see [Files](#files-on-disk)).

The desktop interface follows the mobile mockups and `Theme.swift`: cool gray
surfaces, white cards, black actions, a dark video panel, and restrained orange
and teal indicators. Bricolage Grotesque, IBM Plex Sans, and IBM Plex Mono are
bundled locally, with their licenses in `vantage/web/fonts/`. No font CDN is needed.

## 3D replay

Each saved game's **3D replay** tab redraws the match on an illustrated court that you can
orbit, zoom, and pan, in the style of the landing page's replay card. Play it through or
scrub the timeline, which marks rallies (or, without rallies, stretches of tracked ball
flight) and bounce candidates. Camera buttons switch between:

- **Original**: the recording's own viewpoint. With **Line up with footage**, the video
  plays underneath the reconstruction so you can check how well they agree.
- **Angled**, **Overhead**, and **Sideline**: the sideline view shows how high the ball flew
  over the net.
- **Behind you**: follows your court position from behind, looking across the net.

Pick your court position (Near left, Near right, Far left, Far right), or click yourself in
the replay. The replay then draws your recent movement, your distance to your kitchen line,
and your spacing from your partner. The side panel shows, for the current moment, your court
zone, your distance to the kitchen line, partner spacing, how far away and how high the ball
is, and your speed. For the whole game it shows the share of time you spent at the kitchen
line, in the transition zone, and at the baseline, plus distance covered and average partner
spacing. Your choice is remembered per game in this browser. A synced inset of the original
video plays alongside; click it to hide it.

Keyboard, while focus is anywhere in the replay or its side panel: Space plays or pauses,
←/→ skip 2 s (Shift for 1/30 s), `[`/`]` jump between rallies, 1–5 switch cameras, and +/−
zoom. Scrolling only zooms after you click the replay, so the page still scrolls past it.

How it is built (`vantage/replay.py`): the four calibration corners fix the court plane and,
assuming square pixels and a centred lens, the camera's focal length and pose. If the court
doesn't recede enough to tell, a typical phone lens is assumed and the replay says so.
Players stand where their box bottoms meet the court. Up to two court slots per side follow
them across tracker ID changes, and a smoother weights each position by how many metres a
pixel covers there. The ball is airborne, so its height comes from fitting gravity-only
flight arcs to consecutive observations. A bounce candidate at an arc's end, or across a
short gap, pins that arc to the court. Short arcs lean on an assumed 1 m rally height and
are drawn fainter with shorter dashes, as are brief gaps bridged with estimated flight.

Every position is an estimate from one camera, not a measurement. Ball flying straight at
the camera is the hardest case: its height is least certain there. Court slots are not
identities, so partners who cross over can swap labels. The sample game's replay is
generated play that follows its rallies, labelled synthetic. Imported analyses have no
tracking data, so they have no replay. The replay is computed when you first open it
(about 0.1 s for a 30 s clip) and is cached while its run files are unchanged; nothing is
written to the run folder.

For automation and recorded demos, `replay.js` exposes `VantageReplay`: `seek`, `play`, `speed`,
`view`, `choose`, `toggle`, `camera`/`preset` (orbit cameras in degrees and metres), and
`capture(true)` with `step(dt)`, which stops the animation loop so time, camera moves, and the
synced video advance one exact frame at a time.

## AI video coach

The AI video coach reviews a saved game the way a coach would review it with you
afterwards: it looks at still frames from key moments of your video, together with
Vantage's measurements, and writes a review you can talk through. It works on saved
games in the `--runs-dir` library (uploaded or CLI runs) whose run folder still has a
video: `source.mp4`, `prepared.mp4`, or `annotated.mp4`, preferred in that order. The
sample game and browser imports have no saved run on the server, so they keep the
local session guide and the optional
[OpenAI text chat](#optional-openai-text-chat).

### Using it

1. Open a saved game and choose **Coaching**. The **AI video coach** card sits above the
   coaching focus.
2. Optionally say which player you are (for example "near side, white shirt"). The coach
   then looks for that player in the frames and focuses the review on them and their
   partner. The description is saved in this browser for the game.
3. Choose **Analyze my game**. Vantage first builds the evidence (reading player tracks,
   picking key moments, extracting frames; about a second for a short clip), then the
   engine reviews it. A review usually takes one to three minutes. You can keep watching,
   switch tabs, or leave the game; progress resumes when you return. **Cancel** stops the
   engine, including its CLI process.
4. The review has a headline and summary, the players it could tell apart, what's
   working, prioritised things to work on (each with what was seen, why it matters, how to
   fix it, and a drill with a measurable target), a strip of the key-moment stills with
   notes, a focus for the next session, and its limitations. Every timestamp and
   thumbnail plays the video from one second before that moment.
5. **Re-analyze** runs a fresh review from rebuilt evidence. The previous review stays on
   screen until the new one finishes, and stays if the new one fails or is cancelled.

While the AI coach is active, the **Ask your coach** chat talks to it instead of the
local session guide. With **Include the current video moment** checked (the default),
each question also sends a 2×2 sequence of stills around the paused or playing video
time; **Ask about this moment** asks what to improve at that exact time. Times typed
in the question as `m:ss` (for example "what happened at 0:42?") attach up to two more
sequences. Chat works before a review exists. Answers usually take 10–60 seconds.

Completed reviews are saved with the game and survive restarts. A server restart
ends a review that is still running.

### Engines

The coach runs through whichever AI is available on this computer. Nothing is
installed or signed in by Vantage.

| Engine | Needs | Default model | Your data goes to |
| --- | --- | --- | --- |
| Claude Code (`claude-cli`) | The `claude` CLI on `PATH`, signed in | `opus` | Anthropic, under your Claude Code sign-in |
| Codex (`codex-cli`) | The `codex` CLI on `PATH`, signed in with `codex login` | Codex's default | OpenAI, under your Codex sign-in |
| Claude API (`anthropic-api`) | `ANTHROPIC_API_KEY` in the server's environment | `claude-opus-5-5` | The Anthropic API, billed to that key |

Without a request for a specific engine, Vantage uses `VANTAGE_COACH_ENGINE` when it
names an available engine, and otherwise the first available one in the order above.
When more than one engine is available, the card shows a **Coach** picker; your choice
is remembered in this browser. A CLI counts as available when its binary is found;
Vantage can't confirm a Claude Code sign-in in advance, and shows "Not signed in"
next to Codex when `codex login status` fails. If no engine is available, the card
explains how to set one up. Restart Vantage after changing any of these variables.

| Variable | Effect |
| --- | --- |
| `VANTAGE_COACH_ENGINE` | Preferred engine: `claude-cli`, `codex-cli`, or `anthropic-api` |
| `VANTAGE_COACH_CLAUDE_MODEL` | Model for Claude Code (default `opus`) |
| `VANTAGE_COACH_CODEX_MODEL` | Model for Codex (default: Codex's own default) |
| `VANTAGE_COACH_ANTHROPIC_MODEL` | Model for the Claude API (default `claude-opus-5-5`) |
| `ANTHROPIC_API_KEY` | Enables the Claude API engine. Claude Code may also use it under its own credential rules |

Model names that aren't plain identifiers are ignored. `VANTAGE_COACH_MODEL` and
`OPENAI_API_KEY` belong to the separate OpenAI text chat, not to this coach.

How the engines are run:

- **No shell, isolated folder.** CLIs are started directly (never through a shell),
  in a new empty temporary folder that is deleted afterwards, in their own process
  group. Cancel, a timeout (7 minutes for a review, 3 minutes for a chat), or stopping
  Vantage with Ctrl+C stops the whole group. At most two AI requests run at once.
  Reviews run one at a time in the background, with at most eight queued or running
  across all games, and at most four chat questions can be in progress.
- **Claude Code** runs in print mode with `--tools ""` (no file, shell, or web tools),
  `--setting-sources ""` (ignores your settings and `CLAUDE.md` files),
  `--strict-mcp-config` (no MCP servers), `--disable-slash-commands`, and
  `--no-session-persistence`.
- **Codex** runs `codex exec --ephemeral --ignore-user-config --ignore-rules` with its
  `read-only` sandbox. That sandbox still lets the model run read-only commands, so it
  could read files your user account can read. The prompt doesn't ask it to, and treats
  any text in frames as data, but that is an instruction, not an enforced boundary.
  Choose Claude Code or the Claude API if that matters to you.
- **Claude API** uses the official `anthropic` SDK with structured JSON output, the
  server-side model fallback beta, and prompt caching for the parts a chat reuses.
- Each review or chat uses your plan's usage limits or API billing. Vantage asks
  neither CLI to keep a session history; how long a provider retains requests follows
  your account's terms and settings.

### What is sent

A **review** sends:

- The coach instructions (fixed text in `video_coach.py`).
- Measurements as JSON: the video's duration, frame rate, and size; court geometry;
  tracking quality, rally and shot counts, average ball speed, bounce-candidate count,
  and up to five quality warnings; estimated player positions per side, overall and
  per rally; and the key moments (time, kind, title, and each counted player's measured
  position).
- About 12 still JPEGs, one per key moment, cropped to the court and stamped with
  their time. Detected shots are 2×2 sequences of four frames 0.2 s apart; other
  moments are single frames.
- The player description, if you gave one.

A **chat question** sends the same measurements; your saved review, if any; stills for
up to six key moments (those the review cites first); the last 12 chat messages; any
frame sequences for the current or mentioned times; the player description; and the
question.

Nothing else leaves your computer: not the video file or its audio, `tracks.jsonl`,
the `stats.json` document, file or folder names, the game's name, or other games.
Engine answers are never trusted as-is. Vantage keeps only the expected fields,
shortens long text, drops moment ids it didn't send and times outside the video, and
marks a player as you only if you described yourself. Error messages in the browser
are short fixed texts; raw CLI output and provider error bodies are neither shown nor
logged.

### Files on disk

Everything the coach writes stays in `<run>/.coach/`, next to the run's own files,
which are never modified:

| File | Contents |
| --- | --- |
| `evidence.json` | Measured positions, the chosen key moments, and their captions. Rebuilt when `stats.json` or the chosen video changes, or on **Re-analyze** |
| `frames/m01.jpg`… | Key-moment stills |
| `frames/t-000652.jpg`… | Chat stills, named by tenths of a second. At most 60 are kept (least recently used removed first); they are cleared when the evidence is rebuilt for a changed game |
| `analysis.json` | The last completed review, with the engine, model, time, player description, and how long it took. Ignored once `stats.json` changes or a new Vantage release changes the coach's prompt |

Deleting a game's `.coach` folder is safe; the coach rebuilds what it needs. The
games library ignores dot-folders.

### Evidence boundaries for the AI coach

- **Stills, not video.** The coach sees a dozen sampled frames (plus chat frames), not
  motion or sound. It can't judge timing, swing path, shot selection, or who hit the
  ball from stills, and is told to say so and point you to the time to rewatch.
- **Positions are estimates.** Each player's position is the bottom centre of their
  detection box projected through the court calibration: expect about 0.5 m of error,
  more on the far side and when players overlap or the net hides them. Near-side boxes
  end at the rear heel, so a player with toes on the kitchen line measures about 2.6–3.0 m
  from the net; the kitchen zone therefore counts players up to about 3.0 m (the 2.13 m
  line plus 0.9 m). Baseline means 5.2 m or more from the net; staggered means partners
  at least 2.5 m apart in depth.
- **Bystanders.** People within 1.5 m of a sideline or 4 m of a baseline count as on court
  (the two most confident per side), so line judges or walkers can be included. The first
  two seconds of each rally, when one-up-one-back is normal, aren't flagged.
- **Not an identity.** Tracking IDs don't identify people. "Which player are you?" is a
  description the model matches by eye in the stills, and it can pick the wrong person.
- **Ball events stay heuristic.** Rallies, shots, and bounce candidates are the same
  estimates as elsewhere in the app. With no detected rallies, moments are spread over the
  video instead. Bounce candidates are not line calls.
- **Overlays.** If only `annotated.mp4` is available, the stills include the analysis
  boxes and labels; the coach is told they are not part of play.
- **Advice, not fact.** The review is a model's opinion from this evidence. Vantage checks
  its references, not its judgement. Check what it says against the video.

## Optional OpenAI text chat

This older, text-only option remains for the sample game, imported games, and
computers without an AI video coach engine. The chat hides it while the AI video coach
is active. Set `OPENAI_API_KEY` and `VANTAGE_COACH_MODEL` in the environment before starting the
server. Choose a model available to your API project that supports the Responses
API and structured text output. There is no hard-coded model default. Keep the key
in your shell or secret manager, never in source code or browser settings.

```sh
# With OPENAI_API_KEY and VANTAGE_COACH_MODEL already exported:
uv run vantage-app --open
```

The coach panel exposes this option only when both variables are configured. Enabling it
for a question sends the compact coaching report, question, and recent
conversation to OpenAI. Unlike the AI video coach, it sends no video or frames. It also
sends no API key to the browser, source file
paths, raw tracking records, or original statistics document. The API may incur
charges. Questions stay local unless AI is selected. Model answers are advisory;
the report remains the source of measured facts.

The adapter uses the [OpenAI Responses API](https://developers.openai.com/api/docs/guides/text)
with `store: false`, a bounded conversation, timeouts, and validated evidence
references. Provider failures, refusals, incomplete output, or invalid references
produce an explicitly labeled local fallback. `store: false` disables response
storage; it is not a promise about every provider retention policy. See OpenAI's
[data controls](https://developers.openai.com/api/docs/guides/your-data).

## Evidence boundaries

The measurements describe the **session**, not an identified player. The detector does
not establish which participant is you, and a tracking ID is not a stable player
identity. There are no supported metrics for winners, unforced errors, points,
serve accuracy, shot type, technique, or tactical intent. The coach must not
invent these or infer them from missing observations. The AI video coach may comment on
what a still shows, such as paddle position or stance, or on a player you describe;
those are a model's visual opinions, not measurements (see
[its evidence boundaries](#evidence-boundaries-for-the-ai-coach)).

Rallies are groups of observed net crossings, separated by ball loss or inactivity.
Counts can split or miss actual play. Projected ball speed is a 2-D court-plane
estimate, not true airborne speed. Bounce locations remain candidates even when
tracking coverage is high; near-boundary calls need visual review. Coverage means
the share of frames with an observed ball, not detector accuracy or a probability
that the coaching is correct.

Limited evidence prioritizes review and recording improvements. No ball evidence
produces an explicit insufficient-evidence state and no invented performance
assessment. Practice drills are suggestions to try, not diagnoses established by
the video. The demo is synthetic and must never be mistaken for an analyzed match.

## Architecture and mobile handoff

| Component | Responsibility |
| --- | --- |
| `vantage/coaching.py` | Validate pipeline stats, select evidence, build a versioned report, answer local questions |
| `vantage/coaching_ai.py` | Optional OpenAI text-chat adapter with bounded context and explicit fallback |
| `vantage/coaching_jobs.py` | Local video uploads, preparation, calibrated pipeline jobs, and cancellation |
| `vantage/coaching_server.py` | Shared app routes, game library, local HTTP API, and range-aware video serving |
| `vantage/coaching_video.py` | Temporary H.264 playback copies of annotated videos |
| `vantage/replay.py` | 3D replay: camera pose from the calibration, court-slot player tracks, gravity-fitted ball flight, and the synthetic sample replay |
| `vantage/coach_evidence.py` | AI coach evidence: on-court player positions from `tracks.jsonl`, key-moment selection, and court-cropped stills in `.coach/` (deterministic, no AI) |
| `vantage/coach_engines.py` | Runs one request (text, JPEG stills, strict JSON schema) through the `claude` CLI, the `codex` CLI, or the Anthropic API, with cancel, timeouts, and safe error messages |
| `vantage/video_coach.py` | AI coach prompts and answer schemas, sanitising answers, the background review worker and saved reviews, and chat |
| `vantage/web/` | Games, Overview, 3D replay, and Coaching views in one browser app; no framework or build step. `replay.js` draws the replay with Canvas 2D |

The pure Python engine depends only on the standard library. It accepts desktop
statistics schemas 1 and 2 and produces coaching schema 1. Validation drops local
paths and provenance, limits collection sizes, and rejects nonfinite and invalid
measurements. `session_id` is a stable hash of normalized statistics. Changing a
focus does not change session identity.

The report contains `headline`, `summary`, `quality`, `metrics`, `insights`,
`moments`, `drills`, and `suggested_questions`. Each insight carries its evidence;
moments carry timestamps; drills carry steps and a success target. The frontend
consumes this contract rather than embedding coaching logic in its components.

| API | Purpose |
| --- | --- |
| `GET /api/config` | Video-analysis availability and upload limits; OpenAI chat availability; `coach`: each AI coach engine's availability, model, and the default engine. Never credentials |
| `POST /api/analysis?name=clip.mp4` | Upload raw video bytes as `application/octet-stream` and prepare a job |
| `GET /api/analysis/:id` | Poll preparation, calibration, processing, completion, or failure |
| `GET /api/analysis/:id/preview` | Prepared first-frame calibration image |
| `POST /api/analysis/:id/start` | Start the pipeline with `{corners, synthetic}` |
| `POST /api/analysis/:id/cancel` | Cancel an unfinished job |
| `GET /api/sessions` | Completed games with summary metadata and optional thumbnail URLs; unreadable-run notices |
| `GET /api/sessions/:id` | One run's validated statistics and optional media URLs |
| `GET /api/demo` | Explicitly synthetic sample |
| `GET /api/sessions/:id/replay` | A saved game's 3D replay: court, recorded camera, player samples, ball flight pieces (`p0`, `v0`, and quality per time span), events, and warnings. 422 explains what is missing (no tracking, bad calibration) |
| `GET /api/demo/replay` | Synthetic 3D replay for the sample game |
| `POST /api/session` | Validate `{stats, name}` for a browser import |
| `POST /api/report` | Build a report from `{stats, focus}` |
| `POST /api/chat` | Answer `{stats, focus, message, history, use_ai}` |
| `GET /api/coach/:id` | AI coach status for a saved game: availability, review state, stage and elapsed time, the saved review and its engine, and key moments with still URLs |
| `POST /api/coach/:id/analyze` | Queue a review with `{engine?, player?, force?}`; `force` re-analyzes. Returns 202 with the status |
| `POST /api/coach/:id/cancel` | Cancel a queued or running review; returns the status |
| `POST /api/coach/:id/chat` | Ask the AI coach `{message, history?, engine?, at_s?, player?}`; waits for the answer (up to 3 minutes) and returns `{answer, moment_ids, time_s, follow_ups, frames, engine, engine_label, model}` |
| `GET /media/:id/coach/:name` | A coach still (`m01.jpg`, `t-000652.jpg`) from the game's `.coach/frames/` folder |

AI coach routes answer 404 for games without a saved run on this server (including the
sample and imports), 400 for invalid input, 422 when the game's video or measurements
can't be used, and 503 when no engine is available or the engine fails, with a short
message that says what to do.

This is a **local desktop service**, bound to `127.0.0.1`, with same-origin checks,
bounded uploads, and an allowlist of files. Uploads and preparation files live
under the selected runs directory's `.uploads/` folder; completed analyses have
their own run folders. It is not a multi-user hosted deployment. Do not expose
it publicly through a proxy. A hosted/mobile rollout needs authentication,
per-user storage, quotas, and a deployed API. Mobile can reuse the report contract
and drill/evidence rules; it must keep provider credentials on that server. The AI
video coach's CLI engines rely on sign-ins on this computer, so a hosted version would
use the API engine instead. No Swift code or detector changes are included in this release.

Deferred scope: player identity association, shot classification, verified event
labels, cross-session progress, real-time instruction, and native mobile UI.
Those features require additional evidence or infrastructure before credible
personal performance claims can be made.

## Validation

```sh
uv run --locked python -m unittest discover -s pipeline/tests -p 'test_coaching*.py' -v
uv run --locked python -m unittest discover -s pipeline/tests -p 'test_coach_*.py' -v
uv run --locked python -m unittest discover -s pipeline/tests -p 'test_video_coach.py' -v
uv run --locked python -m unittest discover -s pipeline/tests -p 'test_replay.py' -v
uv run --locked python -m unittest discover -s pipeline/tests
```

Run tests with `discover -s pipeline/tests` (as above) so shared helpers such as
`coach_fixtures.py` import. Tests cover evidence quality, malformed inputs,
timestamp/measurement boundaries, focus selection, reproducibility, provider opt-in
and failure modes, and real HTTP requests including media ranges and local-file
isolation. AI coach tests build a small synthetic run (video, calibration, tracks) and
cover position zones, moment selection, stills, cache invalidation, engine command
lines and error mapping, cancellation and timeouts, answer sanitising, the review
worker, chat frames, and the HTTP routes. They use fake CLIs and fake clients: no test
runs `claude` or `codex`, calls a provider, or spends API credits. Replay tests view
synthetic games through a known camera and check that the camera, ball flight heights,
bounce bridges, and player slots come back within tolerance.
