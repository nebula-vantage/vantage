# Ball detection diagnostic

Run from the repository root:

```sh
.venv/bin/python diagnostics/check_ball_detection.py
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
