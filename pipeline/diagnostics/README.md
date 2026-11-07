# Ball detection diagnostic

Run from the repository root:

```sh
uv run python pipeline/diagnostics/check_ball_detection.py
```

Use `--input VIDEO`, `--output-dir DIRECTORY`, or `--max-frames 900` to change the
video, output location, or limit analysis to the first 900 consecutive frames.
The default processes `assets/videoplayback.mp4` into `output/ball-motion-diagnostic/`.

The diagnostic calls the production `Detector` once per frame. It records raw YOLO
ball candidates and the independently tracked ball in `frames.jsonl`. Player ByteTrack
never filters the ball candidates. It does not run inference twice or skip frames.
`summary.json` contains counts, configuration, dimensions, and elapsed time.
JPEG examples show raw candidates in yellow and distinguish rejected candidates,
a selected ball, and no raw prediction. Examples are the first 12 qualifying frames
per category spaced at least two seconds apart, not a representative random sample.

Coverage is not ground-truth recall or accuracy. Candidates may include wall signs
and other-court balls; missing detections may include occluded or off-screen balls.
Production video outputs and detection settings are not changed by this diagnostic.

The earlier combined-ByteTrack results are preserved under `output/ball-diagnostic/`
and documented in [the original findings](ball-detection-findings.md). Those results
were captured before the motion-tracker change; the current diagnostic measures the
new pipeline and will not reproduce the legacy post-ByteTrack stage.

## Two-camera line-calling simulation

```sh
uv run python pipeline/diagnostics/two_camera_feasibility.py --self-check
uv run python pipeline/diagnostics/two_camera_feasibility.py --experiments all
```

A Monte Carlo study, not a video diagnostic: it simulates pickleball bounces near the
lines and compares today's bounce estimate with one- and two-camera contact fits. Results
go to `output/two-camera-feasibility/summary.json`; `--tables` reprints them. See
[two-camera line calling](two-camera-line-calling.md) for the findings.
