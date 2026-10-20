# Independent ball tracking — implementation and validation

YOLO now runs once per frame through `predict()`. Only person boxes enter ByteTrack.
Raw ball candidates enter `BallTracker`; raw paddle detections support contact
suppression. Ball and player identity numbers are scoped to their class.

The ball tracker uses position and time-based velocity prediction, a speed gate,
short-gap retention, and a position fallback for sudden direction changes. Acquisition
requires two observations with measurable displacement. Long loss creates a new ID;
stationary acquisition is rejected and tracks that stop moving are released. Predictions
are used for matching only, never emitted as measured detections. These are heuristic
rules, not a learned classifier for distinguishing the correct court's ball.

## Results on the existing clip

Replayed all 11,283 cached raw YOLO observations from the existing 640×360, 29.97 FPS
recording with unchanged weights and detection threshold:

| Stage | Selected-ball frames | Coverage |
| --- | ---: | ---: |
| Previous combined ByteTrack + selector | 196 | 1.74% |
| Independent ball motion tracker | 2,407 | 21.33% |
| Raw YOLO candidates available | 3,207 | 28.42% |

The motion tracker produces 288 separate identities across this clip. This is still
fragmented tracking. Increased coverage is not measured recall or accuracy: there
are false positives, and the model still misses many visible ball positions.

A fresh inference run on the first 900 original video frames exactly matches the
cached replay for **every raw prediction and selected ball record**. It retains 225
ball frames (25%), compared with 6 in the legacy first-900-frame output. The full-video
numbers above are cached-detection replay, not a second full YOLO inference run.

Visual review confirms recovery of the actual ball in frames 162, 165, and 170–172,
which the former tracking stage dropped. Frames 163–164 remain missing because there
was no raw detector observation; the tracker does not fabricate replacements.

- [Before/after video, first 30 seconds](../output/ball-motion-replay/comparison-first-30s.mp4)
- [Recovered observation at frame 170](../output/ball-motion-replay/comparison-170.jpg)
- [Full replay measurements and configuration](../output/ball-motion-replay/summary.json)
- [Fresh inference diagnostic](../output/ball-motion-diagnostic/summary.json)

The comparison video uses cached detections, verified against fresh inference, and
was fully decoded to verify 900 frames at the source FPS. Its circles highlight
measured ball boxes; they do not represent uncertainty or synthesized observations.

All **32 automated tests pass**, covering motion association, non-overlapping weak
observations, direction changes, short/long losses, stationary clutter, invalid data,
30/120 FPS equivalence, actual ByteTrack integration with synthetic model results,
and the downstream calibration, trajectory, statistics, and video pipeline.

## Tracker and capture choices

A separate unmodified ByteTrack instance still uses overlap-based association. A
ball-specific motion tracker avoids the measured bottleneck without another neural
network. DeepSORT's standard appearance model is trained for pedestrian re-identification;
it is not a validated descriptor for a ball only a few pixels wide. See the
[original DeepSORT implementation](https://github.com/nwojke/deep_sort).

Record new footage at 60 or 120 FPS to test additional *captured* ball positions,
while checking exposure, lighting, resolution, and sustained phone throughput.
Increasing this existing video's FPS by duplication or interpolation does not add
observations, and slower playback does not help a pipeline already processing every
frame. Keep capture-time timing for speed estimates. Apple's
[AVFoundation capture formats](https://developer.apple.com/documentation/avfoundation/capture-device-formats)
provide the native capture configuration. This Python pipeline still assumes constant
FPS; slow-motion retiming and variable-frame-rate input require care as documented
in the main README. No iPhone performance benchmark has been run.

## Reproduce

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python diagnostics/replay_ball_tracking.py
.venv/bin/python diagnostics/check_ball_detection.py --max-frames 900
```

Replay requires the previous raw-detection diagnostic under `output/ball-diagnostic/`.
The previous production annotated video and statistics were preserved as the baseline;
new analysis is in the separate diagnostic/replay folders. Normal CLI runs now use
the independent ball tracker automatically.
