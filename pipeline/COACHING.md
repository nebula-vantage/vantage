# Vantage — Games and coaching in the desktop/web app

Vantage opens to a Games library. Upload and analyze a video once, then open that
game's Overview for playback and measurements or its Coaching tab for review
moments, a practice plan, and questions about the evidence. Both tabs share the
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
Node installation, or frontend build is needed for the local coaching review.
The previous `vantage-coach` command remains an alias for this same app.

Saved games have direct links at `/games/:id` and `/games/:id/coaching`. Reloading,
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
- A downloadable report/plan for taking the review to the next practice.

The local review is deterministic and works offline. Its answers are assembled
from measured evidence and a small curated drill library; they are labeled as
local, not as model-generated responses. Imported statistics and conversation
state are kept in page memory. Reloading clears imported sessions and chat;
completed-run files can be reopened, and practice checkboxes remain in browser
storage. The server never modifies pipeline outputs.

The desktop interface follows the mobile mockups and `Theme.swift`: cool gray
surfaces, white cards, black actions, a dark video panel, and restrained orange
and teal indicators. Bricolage Grotesque, IBM Plex Sans, and IBM Plex Mono are
bundled locally, with their licenses in `vantage/web/fonts/`. No font CDN is needed.

## Optional AI conversation

Set `OPENAI_API_KEY` and `VANTAGE_COACH_MODEL` in the environment before starting the
server. Choose a model available to your API project that supports the Responses
API and structured text output. There is no hard-coded model default. Keep the key
in your shell or secret manager, never in source code or browser settings.

```sh
# With OPENAI_API_KEY and VANTAGE_COACH_MODEL already exported:
uv run vantage-app --open
```

The coach panel exposes AI only when both variables are configured. Enabling AI
for a question sends the compact coaching report, question, and recent
conversation to OpenAI. It sends no video, API key to the browser, source file
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

This release coaches the **session**, not an identified player. The detector does
not establish which participant is you, and a tracking ID is not a stable player
identity. There are no supported metrics for winners, unforced errors, points,
serve accuracy, shot type, technique, or tactical intent. The coach must not
invent these or infer them from missing observations.

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
| `vantage/coaching_ai.py` | Optional provider adapter with bounded context and explicit fallback |
| `vantage/coaching_jobs.py` | Local video uploads, preparation, calibrated pipeline jobs, and cancellation |
| `vantage/coaching_server.py` | Shared app routes, game library, local HTTP API, and range-aware video serving |
| `vantage/coaching_video.py` | Temporary H.264 playback copies of annotated videos |
| `vantage/web/` | Games, Overview, and Coaching views in one browser app; no framework or build step |

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
| `GET /api/config` | Video-analysis availability and upload limits; AI availability and configured model, never credentials |
| `POST /api/analysis?name=clip.mp4` | Upload raw video bytes as `application/octet-stream` and prepare a job |
| `GET /api/analysis/:id` | Poll preparation, calibration, processing, completion, or failure |
| `GET /api/analysis/:id/preview` | Prepared first-frame calibration image |
| `POST /api/analysis/:id/start` | Start the pipeline with `{corners, synthetic}` |
| `POST /api/analysis/:id/cancel` | Cancel an unfinished job |
| `GET /api/sessions` | Completed games with summary metadata and optional thumbnail URLs; unreadable-run notices |
| `GET /api/sessions/:id` | One run's validated statistics and optional media URLs |
| `GET /api/demo` | Explicitly synthetic sample |
| `POST /api/session` | Validate `{stats, name}` for a browser import |
| `POST /api/report` | Build a report from `{stats, focus}` |
| `POST /api/chat` | Answer `{stats, focus, message, history, use_ai}` |

This is a **local desktop service**, bound to `127.0.0.1`, with same-origin checks,
bounded uploads, and an allowlist of files. Uploads and preparation files live
under the selected runs directory's `.uploads/` folder; completed analyses have
their own run folders. It is not a multi-user hosted deployment. Do not expose
it publicly through a proxy. A hosted/mobile rollout needs authentication,
per-user storage, quotas, and a deployed API. Mobile can reuse the report contract
and drill/evidence rules; it must keep provider credentials on that server. No
Swift code or detector changes are included in this release.

Deferred scope: player identity association, shot classification, verified event
labels, cross-session progress, real-time instruction, and native mobile UI.
Those features require additional evidence or infrastructure before credible
personal performance claims can be made.

## Validation

```sh
uv run --locked python -m unittest discover -s pipeline/tests -p 'test_coaching*.py' -v
uv run --locked python -m unittest discover -s pipeline/tests
```

Tests cover evidence quality, malformed inputs, timestamp/measurement boundaries,
focus selection, reproducibility, provider opt-in and failure modes, and real HTTP
requests including media ranges and local-file isolation. Provider tests are
mocked and do not spend API credits. Existing pipeline tests remain unchanged.
