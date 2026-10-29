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

## Rally evaluation

`eval_rallies.py` scores the pipeline's play segments against hand-labeled rallies.
Run the pipeline once per clip, then tune `CONFIG["rallies"]` and rerun the evaluation.
It replays the cached `tracks.jsonl` and saved calibration without inference or
rendering, so each run takes seconds:

```sh
uv run vantage --input input/clip.mp4 --output-dir output/clip
uv run python pipeline/diagnostics/eval_rallies.py output/clip ml/labels/rallies/clip.json
```

Label each clip in `ml/labels/rallies/<clip>.json`. Times are seconds in the
source video; a rally starts at serve contact and ends when the ball is dead:

```json
{"video": "clip.mp4", "rallies": [[4.2, 15.8], [31.0, 38.5]]}
```

The report shows how many labeled rallies were kept (at least 90% inside a play
segment), how much play was lost to cuts, how much downtime was kept, and
segments that match no labeled rally. Lost play is the worse error when cutting.
Tune on some clips and report results on others, so the numbers aren't measured on
the same footage the thresholds were fitted to.
