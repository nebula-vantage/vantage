# Ball detection diagnostic — existing recording

Analyzed all **11,283 frames** of `assets/videoplayback.mp4` (376.48 seconds,
640×360, 29.97 FPS), using the production YOLO26n model and unchanged settings.
One inference pass captured raw predictions before ByteTrack, its output, and
BallSelector's final selection. CPU analysis took 514.7 seconds;
this is not an iPhone benchmark.

| Stage | Frames with a ball candidate | Coverage of all frames |
| --- | ---: | ---: |
| Raw YOLO, confidence ≥ 0.10 | 3,207 | 28.42% |
| After ByteTrack | 197 | 1.75% |
| After BallSelector (current production result) | 196 | 1.74% |

ByteTrack removed all ball candidates from **3,010 of 3,207 raw-positive frames
(93.86%)**. BallSelector removed the remaining candidate in only one additional
frame. All 11,283 final selected-ball records, including boxes, scores, and track
IDs, exactly match the saved production `output/tracks.jsonl`.

There were 3,459 raw ball boxes. Of these, 845 were below the 0.15 new-track
threshold. Thresholds alone do not explain all losses: many higher-confidence
candidates were also dropped. ByteTrack requires track confirmation and uses
box-overlap matching with confidence fusion. Small moving boxes and intermittent
predictions are a poor fit for these settings. With score fusion, matching cost
is `1 - IoU * confidence`; the configured 0.80 first-association threshold and
0.70 unconfirmed-association threshold further restrict low-confidence matches.

As an offline diagnostic only, feeding raw candidates directly through the existing
BallSelector produced selections in **3,140 frames (27.83%)**.
This is not a validated improvement in accuracy, and production code was not changed.

## Visual evidence

- [Close-up sequence, frames 161–172](../output/ball-diagnostic/sequence-161-172.jpg):
  the visible ball has no raw detection in frames 163–164. Frames 162 and 165 have
  correctly located raw detections but no post-tracker ball. Tracking retains
  detections in frames 166–169, then drops correctly located raw detections in
  frames 170–172 (confidence approximately 0.255, 0.202, 0.198).
- [False-positive example, frame 105](../output/ball-diagnostic/raw_dropped-00105.jpg):
  a wall sign is labeled as a sports ball. More raw candidates do not necessarily
  mean more correct detections.
- [Side-by-side first 30 seconds](../output/ball-diagnostic/comparison-first-30s.mp4):
  raw candidates on the left, post-ByteTrack candidates on the right. Added circles
  make tiny boxes easier to see. Video verified by decoding all 900 frames at
  1280×400 with source FPS; no audio.

These are qualitative spot checks, not an exhaustively labeled accuracy evaluation.
Coverage counts include false positives, occlusions, and periods when the ball is
outside the frame. They must not be described as recall. The 360p source also limits
ball detail; resizing to 1280 does not recreate missing information.

## Recommended next implementation

Separate ball observations from player tracking: retain ByteTrack for people and
feed raw ball detections into a dedicated motion-based ball tracker that handles
short gaps, reacquisition, and sudden changes of direction. Evaluate against manually
labeled clips so wall signs and other-court balls are not treated as improvements.
Then assess how much custom ball training and better source footage improve the
remaining detector misses. A runtime migration alone would not resolve these failures.

## Reproduce and inspect

These are historical results from the combined-ByteTrack implementation. The current
`.venv/bin/python diagnostics/check_ball_detection.py` measures the new motion tracker;
it does not recreate the old tracking stage.
See [diagnostic instructions](README.md). Raw per-frame observations are in
[frames.jsonl](../output/ball-diagnostic/frames.jsonl); configuration and counts in
[summary.json](../output/ball-diagnostic/summary.json); full-run equality validation
and raw-selector replay in [validation.json](../output/ball-diagnostic/validation.json).
