# Vantage iOS app

On-device (iPhone) version of Vantage. `VantageMobile/` is the SwiftUI app; the analysis
logic lives in the `VantageKit` Swift package, which has no UI and is testable on a Mac.
The Core ML model it bundles is exported by [`tools/coreml/`](../tools/coreml/README.md)
from weights trained in [`ml/`](../ml/README.md). The desktop pipeline in
[`pipeline/`](../pipeline/README.md) is the reference the Swift tracker is tested against.

```
ios/
├── VantageMobile.xcodeproj
├── Config/                   Signing.xcconfig (committed) + your Local.xcconfig (git-ignored)
├── VantageMobile/            App sources (folder-synced: new files build automatically)
│   ├── App/                  App entry point and run list (import + history)
│   ├── Library/              Saved runs on disk (Documents/Runs/<id>/)
│   └── Playback/             Video player with detection/track overlay
├── VantageKit/               Swift package: UI-free logic, testable on the Mac
│   ├── Sources/VantageKit/       Detection records, Core ML detector, video analyzer,
│   │                             ball tracker + trajectory, playback timeline
│   ├── Sources/vantage-analyze/  Mac CLI running the same analysis on a video
│   └── Tests/                    Tracker parity (vs Python), behavior, timeline
└── scripts/run_on_iphone.sh  Build, sign, install, and launch on a connected iPhone
```

`artifacts/` (at the repository root) is not committed. The app bundles the fine-tuned
pickleball model, `artifacts/pickleball-v1-1280/VantageDetector.mlpackage`. On a fresh
clone, export it from the committed weights before building:

```sh
uv run python tools/coreml/export_model.py --weights ml/models/pickleball-v1.pt \
  --ball-confidence 0.20 --output artifacts/pickleball-v1-1280
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

`VantageKit/Sources/VantageKit/BallTracker.swift` is a port of the desktop
`pipeline/vantage/ball_tracker.py`: motion
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

**Parity with the desktop:** `tools/coreml/make_tracker_fixtures.py` feeds the raw ball
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
`pipeline/vantage/config.py`. Tracker parity is not detector parity: Core ML's square-letterboxed
input yields more ball candidates than the desktop's rectangular input, and the
remaining fragmentation (missed frames) reflects the generic COCO detector, not
the port. Track IDs are internal; the player shows a single "ball".

Not yet included: player track IDs, court calibration, speed, match stats, or
heatmaps. Paddle class 38 remains a tennis-racket proxy, as in the desktop pipeline.

### Run on your iPhone (free Apple ID, no paid developer program)

First time only:

1. In Xcode → Settings → Accounts, add your Apple ID (a free Personal Team is fine).
2. Set up signing. Copy `ios/Config/Local.xcconfig.example` to `ios/Config/Local.xcconfig`
   (git-ignored) and fill in your team ID and a bundle ID suffix such as `.yourname`.
   Bundle IDs are unique across Apple, so each person's team needs its own. To find your
   team ID: in Xcode → Settings → Accounts → your team → **Manage Certificates…**, add an
   **Apple Development** certificate if there isn't one, then run
   `security find-certificate -c "Apple Development" -p | openssl x509 -noout -subject`.
   Your team ID is the `OU=` value. Don't set the team in the target's Signing &
   Capabilities tab: that writes it into the shared project file (`scripts/test.sh` fails
   if a team or bundle ID appears there).
   If you already installed the app as `com.vantage.detectorprototype`, leave the suffix
   empty to keep that install and its saved runs.
3. Connect the iPhone by USB, unlock it, and tap **Trust This Computer**.
   Enable **Developer Mode** (Settings → Privacy & Security) if prompted.

Then, from the repository root:

```sh
ios/scripts/run_on_iphone.sh            # auto-detects the paired iPhone
ios/scripts/run_on_iphone.sh <UDID>     # or pick one: xcrun devicectl list devices
```

After the first install, on the iPhone open Settings → General →
**VPN & Device Management** → *Apple Development: your email* → **Trust**, then run
the script again.

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
  --domain-identifier <your bundle ID> --source Documents --destination ./phone-out
```

### Simulator / unsigned build

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild \
  -project ios/VantageMobile.xcodeproj -scheme VantageMobile \
  -configuration Debug -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath ~/Library/Developer/Xcode/DerivedData/VantageMobile-sim \
  CODE_SIGNING_ALLOWED=NO build
```

Core ML runs on CPU in the simulator, so timings there are not representative.
Debug builds accept `-openLatestRun` (open the newest run) and `-seek <seconds>`
launch arguments for screenshot checks without UI interaction:
`xcrun simctl launch <sim> <your bundle ID> -openLatestRun -seek 3.06`.

### Tests and Mac tools

```sh
scripts/test.sh    # every suite: VantageKit swift tests + all Python tests
```

`swift test` needs a scratch path outside `~/Documents` (the script sets it): the
test bundle is codesigned, which fails on iCloud-synced files.

Run the exact on-device analysis on the Mac (same model, preprocessing, tracker):

```sh
cd ios/VantageKit
swift run -c release --scratch-path ~/Library/Caches/VantageKit-build vantage-analyze \
  ../../artifacts/yolo26n-1280/VantageDetector.mlpackage ../../assets/pickleball/sideview.MOV /tmp/sideview.jsonl
```

Regenerate tracker parity fixtures after changing either tracker (from the repository root):

```sh
uv run python tools/coreml/make_tracker_fixtures.py /tmp/sideview.jsonl \
  ios/VantageKit/Tests/VantageKitTests/Fixtures/tracker-sideview.json
```

### Detector details

Any Ultralytics YOLO export works: the detector reads the model's `names` metadata and
maps classes to canonical IDs by name (`person`/`player` -> 0, `sports ball`/`ball`/
`pickleball` -> 32, `tennis racket`/`paddle` -> 38; see `DetectionClass`). The generic
COCO model and a fine-tuned player/ball/paddle model (see [`ml/README.md`](../ml/README.md)) both produce
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

## Next steps

1. Player tracking (ByteTrack port or per-court-quadrant identity), with fixture
   comparisons against Python like the ball tracker.
2. Port calibration and analytics (shots, bounces, rallies), then heatmaps.
3. Fine-tune the detector on pickleball (ball/paddle/player) and re-export.
4. Benchmark sustained processing, memory, and thermals on iPhone 17 Pro;
   evaluate smaller inputs, crop-assisted detection, and live capture.

References: [Apple Vision requests](https://developer.apple.com/documentation/vision/vncoremlrequest),
[raw model observations](https://developer.apple.com/documentation/vision/vncoremlfeaturevalueobservation).
