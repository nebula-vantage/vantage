# Core ML tooling

Converts the trained detector to Core ML for the [iPhone app](../../ios/README.md) and checks
the conversion against PyTorch. The versions that matter for a reproducible export
(coremltools, torch, numpy, ultralytics) are pinned in the `coreml` dependency group of
`pyproject.toml`; `uv sync` installs them.

| File | Purpose |
| --- | --- |
| `export_model.py` | Export a YOLO checkpoint to `artifacts/<name>/VantageDetector.mlpackage` with a manifest |
| `compare.py` | Compare PyTorch and Core ML detections on sampled frames |
| `make_tracker_fixtures.py` | Run the desktop tracker on app detections to produce Swift parity fixtures |
| `crop_experiment.py` | Ball crop-pass experiment ([CROP_EXPERIMENT.md](CROP_EXPERIMENT.md)) |
| `vision_smoke.swift` | Swift Vision vs Python check on one frame (macOS) |

The app bundles `artifacts/pickleball-v1-1280/VantageDetector.mlpackage`. On a fresh clone:

```sh
uv run python tools/coreml/export_model.py --weights ml/models/pickleball-v1.pt \
  --ball-confidence 0.20 --output artifacts/pickleball-v1-1280
```

## Usage

Run from the repository root after `uv sync`.

```sh
uv run python tools/coreml/export_model.py
uv run python tools/coreml/compare.py \
  --video assets/pickleball/sideview.MOV \
  --samples 24 --output reports/my-sideview-run
```

Tests: `uv run python -m unittest discover -s tools/coreml` (also part of `scripts/test.sh`).

Export and comparison commands refuse to overwrite an existing output directory.
Use a new `--output` path for subsequent runs. For another export size, provide
both `--size` and `--output`; provide the matching `--size` and `--package` to
the comparison.

The exporter copies the checkpoint before conversion, records its SHA-256 and
tool versions in `manifest.json`, and disables automatic dependency installation.
The original checkpoint stays untouched. `nms=False` preserves YOLO26's NMS-free
end-to-end output, `[1, 100, 6]`, with rows `[x1, y1, x2, y2, confidence, class]`.
FP16 is the default; `--precision 32` provides an investigation baseline.

The separate [ball crop experiment](CROP_EXPERIMENT.md) compares the
desktop detector with a second crop pass. It has not replaced either the desktop
pipeline or the Swift detector.

## Validation results

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

## Swift Vision smoke test on Mac

```sh
swiftc -module-cache-path /private/tmp/vantage-swift-module-cache \
  ios/VantageKit/Sources/VantageKit/{Detection,Detector}.swift tools/coreml/vision_smoke.swift \
  -o /private/tmp/vantage-vision-smoke
/private/tmp/vantage-vision-smoke \
  artifacts/yolo26n-1280/VantageDetector.mlpackage \
  reports/sideview-validated/source.png
```

References: [Ultralytics Core ML export](https://docs.ultralytics.com/integrations/coreml/).
