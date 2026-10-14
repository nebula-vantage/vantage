# Ball detection data and evaluation

Tools for building a labeled pickleball dataset, measuring real ball-tracking accuracy,
and (next) fine-tuning the detector. Serves both the desktop pipeline and the iPhone
app; Core ML export and conversion checks stay in `mobile/model/`.

| File | Purpose |
| --- | --- |
| `label_ball.py` | OpenCV labeling tool, pre-filled from the pipeline |
| `evaluate_ball.py` | Recall/precision of detector and tracker against labels |
| `labeling.py` | Label format, session logic, evaluation (UI-free, tested) |
| `labels/` | Committed labels, one JSON file per video |

Tests: `.venv/bin/python -m unittest discover -s ml`

## Why

Until now the only checks were "Swift matches Python" and visual review. Labels give
ground truth: how often the detector/tracker finds the real ball, and how often it
reports something else. The same labels become training data for a pickleball model.

## 1. Get detections for a video

Either export from the iPhone app (open a run → share → AirDrop `detections.jsonl`) or
run the identical analysis on the Mac:

```sh
cd mobile/ios/VantageKit
swift run -c release --scratch-path ~/Library/Caches/VantageKit-build vantage-analyze \
  ../../artifacts/yolo26n-1280/VantageDetector.mlpackage \
  ../../../assets/pickleball/topcorner60fps.mov ../../reports/swift-detections/topcorner60fps.jsonl
```

## 2. Label

```sh
.venv/bin/python ml/label_ball.py --video assets/pickleball/topcorner60fps.mov \
  --detections mobile/reports/swift-detections/topcorner60fps.jsonl --stride 5
```

Every 5th frame is shown. Orange is the tracker's suggestion, white rings are raw
detector candidates, green is your label. The top-right magnifier shows the area
under the cursor (or the suggestion) at 6×.

| Key | Action |
| --- | --- |
| Enter / Space | Accept the suggestion (or keep your label) and go to the next frame |
| Click | Put the ball here (snaps to a white candidate if close; else a box of the last size) |
| N | No ball visible, next frame |
| S / D / → | Skip (leave unlabeled), next frame |
| A / ← | Previous frame |
| Backspace | Clear this frame's label |
| - / = | Shrink / grow a manual box |
| Q / Esc | Save and quit |

Labels autosave to `ml/labels/<video>.json` after every change; rerun the same command
to resume. Rules that keep the labels trustworthy:

- Label the ball you can actually see, even if it is blurred or partly hidden.
- Press **N** only when you are sure no ball is in view (dead ball, out of frame).
- **Skip** anything ambiguous instead of guessing; skipped frames are not scored.
- Never accept an orange suggestion that sits on a leaf: click the real ball or press N.

## 3. Evaluate

```sh
.venv/bin/python ml/evaluate_ball.py \
  --labels ml/labels/topcorner60fps.json --detections mobile/reports/swift-detections/topcorner60fps.jsonl \
  --labels ml/labels/backcorner60fps.json --detections mobile/reports/swift-detections/backcorner60fps.jsonl
```

Reports recall (visible balls found) and precision (predictions that were the ball)
for the detector alone (`raw best`), the tracker, and the tracker without
static-clutter suppression. A prediction counts as correct within 1% of the frame
diagonal (`--radius-diagonals`). `--export-centers` writes the
`{frame: [x, y] | null}` format accepted by `mobile/model/crop_experiment.py --labels`.

## Labeling plan

1. **Evaluation set first (~300 frames, about 20–30 minutes):** topcorner60fps and
   backcorner60fps at `--stride 5`. Keep these clips evaluation-only: never train on them,
   so scores stay honest.
2. **Training set (~1,000–2,000 frames):** new footage across angles, lighting, and courts,
   ideally 4K60 originals from a raised position, plus plenty of frames with leaves and no
   ball (negatives teach the model that leaves are not balls). Label at `--stride 3–10`.
3. **Fine-tune YOLO26n** on ball (and later paddle/player), export with
   `mobile/model/export_model.py`, re-run analysis, and compare with step 1's numbers.
