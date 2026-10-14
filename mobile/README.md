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
│   └── VantageMobile/        Sources (folder-synced: new files build automatically)
│       ├── App/              App entry point and screens
│       └── Analysis/         Core ML detector and video frame analysis
├── model/                    Core ML export, parity checks, crop experiment (Python)
├── scripts/run_on_iphone.sh  Build, sign, install, and launch on a connected iPhone
├── artifacts/                Exported .mlpackage files (generated, git-ignored)
└── reports/                  Comparison and experiment outputs (generated, git-ignored)
```

`artifacts/` is not committed. On a fresh clone, run the export (below) before
building the app; the Xcode project bundles
`artifacts/yolo26n-1280/VantageDetector.mlpackage`.

## iPhone app

Current features: import a video from Files, run the detector on every frame
on-device, show progress/timing, cancel, and share timestamped JSONL detections.

Not yet included: tracking IDs, court calibration, speed, match stats, or
heatmaps. Detections are raw candidates; the ball-frame count is not
ball-tracking accuracy. Paddle class 38 remains a tennis-racket proxy, as in the
desktop pipeline.

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

### Detector details

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

Tests: `.venv/bin/python -m unittest discover -s mobile/model`

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
  mobile/ios/VantageMobile/Analysis/Detector.swift mobile/model/vision_smoke.swift \
  -o /private/tmp/vantage-vision-smoke
/private/tmp/vantage-vision-smoke \
  mobile/artifacts/yolo26n-1280/VantageDetector.mlpackage \
  mobile/reports/sideview-validated/source.png
```

## Next steps

1. Port the desktop ball tracker and player ByteTrack, with fixture comparisons
   against Python. Preserve observed-versus-estimated distinctions.
2. Port calibration and analytics, then heatmaps.
3. Fine-tune the detector on pickleball (ball/paddle/player) and re-export.
4. Benchmark sustained processing, memory, and thermals on iPhone 17 Pro;
   evaluate smaller inputs, crop-assisted detection, and live capture.

References: [Ultralytics Core ML export](https://docs.ultralytics.com/integrations/coreml/),
[Apple Vision requests](https://developer.apple.com/documentation/vision/vncoremlrequest),
[raw model observations](https://developer.apple.com/documentation/vision/vncoremlfeaturevalueobservation).
