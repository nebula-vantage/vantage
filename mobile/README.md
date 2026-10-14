# Vantage mobile

On-device (iPhone) version of Vantage plus the tooling that converts and validates
the detector model for Core ML. This folder is independent of the desktop pipeline
in the repository root: it has its own Python environment, dependencies, model
copies, and reports. Continue using `.venv/bin/python main.py ...` for Mac analysis.

```
mobile/
├── ios/                      iPhone app (SwiftUI)
│   ├── VantageMobile.xcodeproj
│   ├── project.yml           XcodeGen spec mirroring the project (optional)
│   ├── VantageMobile/        App sources (folder-synced: new files build automatically)
│   │   ├── App/              App entry point and run list (import + history)
│   │   ├── Library/          Saved runs on disk (Documents/Runs/<id>/)
│   │   └── Playback/         Video player with detection/track overlay
│   └── VantageKit/           Swift package: UI-free logic, testable on the Mac
│       ├── Sources/VantageKit/       Detection records, Core ML detector, video analyzer,
│       │                             ball tracker + trajectory, playback timeline
│       ├── Sources/vantage-analyze/  Mac CLI running the same analysis on a video
│       └── Tests/                    Tracker parity (vs Python), behavior, timeline
├── model/                    Core ML export, parity checks, tracker fixtures, crop experiment (Python)
├── scripts/run_on_iphone.sh  Build, sign, install, and launch on a connected iPhone
├── scripts/test.sh           Run all mobile tests (Swift + Python)
├── artifacts/                Exported .mlpackage files (generated, git-ignored)
└── reports/                  Comparison and experiment outputs (generated, git-ignored)
```

`artifacts/` is not committed. The app bundles the fine-tuned pickleball model,
`artifacts/pickleball-v1-1280/VantageDetector.mlpackage`. On a fresh clone, export it
from the committed weights before building:

```sh
mobile/.venv/bin/python mobile/model/export_model.py --weights ml/models/pickleball-v1.pt \
  --ball-confidence 0.20 --output mobile/artifacts/pickleball-v1-1280
```

On the held-out topcorner clip it tracks the ball in 61.6% of visible-ball frames at
96.2% precision on-device, versus 39.6% / 97.0% for the generic COCO model (details in
`ml/models/pickleball-v1.json` and `ml/README.md`). To compare against COCO, export
`yolo26n.pt` to `artifacts/yolo26n-1280` and run `vantage-analyze` with each package.

## iPhone app

Current features:

- Import a video from Files and run the detector on every frame on-device, with
  progress and cancel. The screen stays awake during analysis; keep the app open.
- Each analysis is saved as a run (`Documents/Runs/<id>/`: the copied video,
  `detections.jsonl`, `thumbnail.jpg`, `run.json`). Runs are listed on the home
  screen; swipe to delete. Interrupted analyses are discarded on next launch.
- Playback: tap a run to watch the video with players (green), the tracked ball
  (yellow ring with track ID and confidence; orange dashed when interpolated), a
  0.5 s trail of that one track, and paddles (cyan) drawn on top. Raw ball
  candidates can be shown from the overlay menu to judge the detector. Play/pause (or tap the video), scrub, step frame by frame, and
  slow down to 0.5× / 0.25×. The overlay toggles live in the toolbar menu; the
  share button exports `detections.jsonl`.

The overlay reads the player's current time every display frame and looks up the
analyzed frame by source timestamp, so boxes stay aligned when scrubbing or stepping.

### Ball tracking

`VantageKit/BallTracker.swift` is a port of the desktop `ball_tracker.py`: motion
prediction, speed gating, short-loss retention, turn fallback, stationary-clutter
release, static-clutter suppression (spots that keep producing detections, such
as leaves), and two-observation acquisition, all in capture-time seconds.
`BallTrajectory` ports the desktop interpolation of gaps up to 0.20 s within one
track (not its display-only smoothing or coasting). Interpolated positions are
never counted as detections.

Tracking runs from the saved raw detections when a run is opened, so runs analyzed
before tracking existed are tracked too, and tuning `BallTrackerConfig` needs no
re-analysis. The analyzer also tracks inline to store the tracked-frame count
(`trackedBallFrames` in `run.json`; absent on older runs, which show "ball seen").

**Parity with the desktop:** `make_tracker_fixtures.py` feeds the raw ball
candidates of real on-device runs through the Python tracker and records each
frame's selection. The Swift tests replay the same candidates and require
identical boxes, confidences, track IDs, and interpolated frames. Current fixtures:

| Clip | Frames | Tracked | Interpolated | Tracks |
| --- | ---: | ---: | ---: | ---: |
| sideview | 606 | 604 | 1 | 1 |
| backcorner60fps | 456 | 122 | 18 | 16 |
| topcorner60fps | 1244 | 377 | 125 | 23 |

Static-clutter suppression removed leaf/debris tracking: frames tracked on objects
that never move fell from 350 to 4 (topcorner) and 51 to 17 (backcorner), and
track fragments from 56 to 23 and 22 to 16, with sideview unchanged.

All 2,306 frames match exactly; a test also fails if Swift defaults drift from
`config.py`. Tracker parity is not detector parity: Core ML's square-letterboxed
input yields more ball candidates than the desktop's rectangular input, and the
remaining fragmentation (missed frames) reflects the generic COCO detector, not
the port. Track IDs are internal; the player shows a single "ball".

Not yet included: player track IDs, court calibration, speed, match stats, or
heatmaps. Paddle class 38 remains a tennis-racket proxy, as in the desktop pipeline.

### Run on your iPhone (free Apple ID, no paid developer program)

From the repository root:

```sh
mobile/scripts/run_on_iphone.sh            # auto-detects the paired iPhone
mobile/scripts/run_on_iphone.sh <UDID>     # or pick one: xcrun devicectl list devices
```

First time only:

1. In Xcode → Settings → Accounts, add your Apple ID (a free Personal Team is fine).
   The project's `DEVELOPMENT_TEAM` must be your team ID; change it in
   Signing & Capabilities if you are not the original author.
2. Connect the iPhone by USB, unlock it, and tap **Trust This Computer**.
   Enable **Developer Mode** (Settings → Privacy & Security) if prompted.
3. After the first install, on the iPhone open Settings → General →
   **VPN & Device Management** → *Apple Development: your email* → **Trust**.

Free-team limitations: the install expires after **7 days** (rerun the script),
at most 3 sideloaded apps per device, and no TestFlight/push/iCloud capabilities.
Core ML, AVFoundation, and file import all work.

The script puts DerivedData in `~/Library/Developer/Xcode/DerivedData/`.
Building inside this iCloud-synced `~/Documents` tree makes codesign fail with
*"resource fork, Finder information, or similar detritus not allowed"*.

Wireless deploys: after one USB session, enable *Connect via network* in
Xcode → Window → Devices and Simulators.

The app's Documents folder is visible in the Files app (On My iPhone → Vantage).
To copy outputs to the Mac:

```sh
xcrun devicectl device copy from --device <UDID> --domain-type appDataContainer \
  --domain-identifier com.vantage.detectorprototype --source Documents --destination ./phone-out
```

### Simulator / unsigned build

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild \
  -project mobile/ios/VantageMobile.xcodeproj -scheme VantageMobile \
  -configuration Debug -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath ~/Library/Developer/Xcode/DerivedData/VantageMobile-sim \
  CODE_SIGNING_ALLOWED=NO build
```

Core ML runs on CPU in the simulator, so timings there are not representative.
Debug builds accept `-openLatestRun` (open the newest run) and `-seek <seconds>`
launch arguments for screenshot checks without UI interaction:
`xcrun simctl launch <sim> com.vantage.detectorprototype -openLatestRun -seek 3.06`.

### Tests and Mac tools

```sh
mobile/scripts/test.sh    # VantageKit swift tests + mobile/model python tests
```

`swift test` needs a scratch path outside `~/Documents` (the script sets it): the
test bundle is codesigned, which fails on iCloud-synced files.

Run the exact on-device analysis on the Mac (same model, preprocessing, tracker):

```sh
cd mobile/ios/VantageKit
swift run -c release --scratch-path ~/Library/Caches/VantageKit-build vantage-analyze \
  ../../artifacts/yolo26n-1280/VantageDetector.mlpackage ../../../assets/pickleball/sideview.MOV /tmp/sideview.jsonl
```

Regenerate tracker parity fixtures after changing either tracker (from the repository root):

```sh
.venv/bin/python mobile/model/make_tracker_fixtures.py /tmp/sideview.jsonl \
  mobile/ios/VantageKit/Tests/VantageKitTests/Fixtures/tracker-sideview.json
```

### Detector details

Any Ultralytics YOLO export works: the detector reads the model's `names` metadata and
maps classes to canonical IDs by name (`person`/`player` -> 0, `sports ball`/`ball`/
`pickleball` -> 32, `tennis racket`/`paddle` -> 38; see `DetectionClass`). The generic
COCO model and a fine-tuned player/ball/paddle model (see `ml/README.md`) both produce
the same detections.jsonl IDs. A model without a ball class is rejected.

The detector explicitly letterboxes with 114-valued padding, then calls Vision
with an already-square input to avoid an additional crop. It requests CPU and
Neural Engine execution; actual operation placement remains Core ML's decision.
Video processing runs on a separate actor, writes JSONL incrementally, and does
not drop source frames to keep up with playback.

Exported records contain source presentation timestamps, oriented image
dimensions, detector latency, class IDs, confidence, and boxes in
top-left-origin source pixels. Source timestamps handle variable frame timing;
edited slow-motion playback timing still requires capture metadata before it can
represent physical speed.

## Model tooling (`model/`)

Run from the repository root. Do not activate or install into the desktop `.venv`.

```sh
uv venv --python .venv/bin/python mobile/.venv
uv pip install --python mobile/.venv/bin/python -r mobile/model/requirements.txt
mobile/.venv/bin/python mobile/model/export_model.py
mobile/.venv/bin/python mobile/model/compare.py \
  --video assets/pickleball/sideview.MOV \
  --samples 24 --output mobile/reports/my-sideview-run
```

Tests: `mobile/scripts/test.sh` (includes `.venv/bin/python -m unittest discover -s mobile/model`).

Export and comparison commands refuse to overwrite an existing output directory.
Use a new `--output` path for subsequent runs. For another export size, provide
both `--size` and `--output`; provide the matching `--size` and `--package` to
the comparison.

The exporter copies the checkpoint before conversion, records its SHA-256 and
tool versions in `manifest.json`, and disables automatic dependency installation.
The original checkpoint stays untouched. `nms=False` preserves YOLO26's NMS-free
end-to-end output, `[1, 100, 6]`, with rows `[x1, y1, x2, y2, confidence, class]`.
FP16 is the default; `--precision 32` provides an investigation baseline.

The separate [ball crop experiment](model/CROP_EXPERIMENT.md) compares the
desktop detector with a second crop pass. It has not replaced either the desktop
pipeline or the Swift detector.

### Validation results

On 24 evenly spaced frames of `assets/pickleball/sideview.MOV`, with confidence
0.10 and matching IoU ≥ 0.50:

| Comparison | Player candidates matched | Ball candidates matched | Paddle candidates matched |
| --- | --- | --- | --- |
| Desktop PyTorch → FP16 Core ML | 96 / 97 | 53 / 55 | 94 / 130 |
| Square PyTorch → FP16 Core ML | 96 / 96 | 59 / 83 | 101 / 130 |
| Square PyTorch → FP32 Core ML | 96 / 96 | 60 / 83 | 98 / 130 |

These fractions describe retained reference candidates, **not ground-truth
accuracy**. FP16 Core ML produced 73 ball candidates versus the desktop's 55;
extra detections may be false positives. Square-input candidate differences remain
unresolved, and FP32 did not eliminate them. Do not declare conversion parity or
replace the working desktop model based on these samples.

Local detailed reports (git-ignored): `reports/sideview-validated/report.json`
(FP16), `reports/sideview-fp32/report.json` (FP32), and
`reports/vision-smoke.json` (Swift Vision vs Python, one frame).

The Swift smoke test matched all 13 Python Core ML detections on that frame;
box IoUs were at least 0.997. Core Image resizing is not guaranteed to be
pixel-identical to OpenCV preprocessing. Mac FP16 median prediction time was
about 29 ms versus 46 ms for desktop PyTorch (short Mac experiment, not an
iPhone or sustained-thermal benchmark).

### Swift Vision smoke test on Mac

```sh
swiftc -module-cache-path /private/tmp/vantage-swift-module-cache \
  mobile/ios/VantageKit/Sources/VantageKit/{Detection,Detector}.swift mobile/model/vision_smoke.swift \
  -o /private/tmp/vantage-vision-smoke
/private/tmp/vantage-vision-smoke \
  mobile/artifacts/yolo26n-1280/VantageDetector.mlpackage \
  mobile/reports/sideview-validated/source.png
```

## Next steps

1. Player tracking (ByteTrack port or per-court-quadrant identity), with fixture
   comparisons against Python like the ball tracker.
2. Port calibration and analytics (shots, bounces, rallies), then heatmaps.
3. Fine-tune the detector on pickleball (ball/paddle/player) and re-export.
4. Benchmark sustained processing, memory, and thermals on iPhone 17 Pro;
   evaluate smaller inputs, crop-assisted detection, and live capture.

References: [Ultralytics Core ML export](https://docs.ultralytics.com/integrations/coreml/),
[Apple Vision requests](https://developer.apple.com/documentation/vision/vncoremlrequest),
[raw model observations](https://developer.apple.com/documentation/vision/vncoremlfeaturevalueobservation).
