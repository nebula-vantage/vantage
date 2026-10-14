# Ball detection data and evaluation

Tools for building a labeled pickleball dataset, measuring real ball-tracking accuracy,
and (next) fine-tuning the detector. Serves both the desktop pipeline and the iPhone
app; Core ML export and conversion checks stay in `mobile/model/`.

| File | Purpose |
| --- | --- |
| `label_ball.py` | OpenCV labeling tool, pre-filled from the pipeline |
| `evaluate_ball.py` | Recall/precision of detector and tracker against labels |
| `fetch_roboflow.py` | Download a public Roboflow dataset, refusing NC/ND/unknown licenses |
| `dataset.yaml` | Training-set spec: holdout clips, label folders, external datasets, teacher |
| `build_dataset.py` | Build the YOLO training set (player, ball, paddle) from the spec |
| `train.py` | Fine-tune YOLO26n at 1280 px on the Apple GPU |
| `predict_video.py` | Run any checkpoint on a video, writing app-format detections.jsonl |
| `labeling.py`, `vantage_classes.py` | Label format, session logic, evaluation, class mapping |
| `labels/` | Committed labels, one JSON file per video |
| `DATA_SOURCES.md` | Attribution for downloaded datasets (written by fetch_roboflow.py) |

Tests: `.venv/bin/python -m unittest discover -s ml`. Generated data lives in the
git-ignored `ml/external/`, `ml/datasets/`, and `ml/runs/`.

## Current baseline (topcorner60fps evaluation set, 164 visible balls)

| Model | Path | Tracked recall | Tracked precision |
| --- | --- | ---: | ---: |
| Generic COCO YOLO26n | on-device (Core ML) | 39.6% | 97.0% |
| Generic COCO YOLO26n | PyTorch (`predict_video.py`) | 40.2% | 97.1% |

57% of visible balls get no detection at all (median 8 px), so the detector, not the
tracker, limits recall. A fine-tuned model must beat these numbers on this held-out clip.

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

## 4. Fine-tune

```sh
# a. Public data (free key: roboflow.com -> Settings -> API Keys). Store it once, privately,
#    outside the repo (or export ROBOFLOW_API_KEY for the session):
mkdir -p ~/.config/vantage && read -rs "?Roboflow API key: " KEY && printf %s "$KEY" > ~/.config/vantage/roboflow_api_key \
  && chmod 600 ~/.config/vantage/roboflow_api_key && unset KEY
.venv/bin/python ml/fetch_roboflow.py WORKSPACE/PROJECT/VERSION --info   # check license/classes
.venv/bin/python ml/fetch_roboflow.py WORKSPACE/PROJECT/VERSION          # download + attribution
#    then add it to ml/dataset.yaml under external: with its class mapping

# b. Build, train, evaluate on the held-out clip
.venv/bin/python ml/build_dataset.py
.venv/bin/python ml/train.py --data ml/datasets/pickleball-v1/data.yaml --name pickleball-v1
.venv/bin/python ml/predict_video.py --weights ml/runs/pickleball-v1/weights/best.pt \
  --video assets/pickleball/topcorner60fps.mov --output /tmp/topcorner-v1.jsonl
.venv/bin/python ml/evaluate_ball.py --labels ml/labels/topcorner60fps.json --detections /tmp/topcorner-v1.jsonl

# c. If it beats the baseline: export for the app and confirm on the Core ML path
mobile/.venv/bin/python mobile/model/export_model.py \
  --weights ml/runs/pickleball-v1/weights/best.pt --output mobile/artifacts/pickleball-v1-1280
```

The fine-tuned model has classes player, ball, paddle. Player and paddle labels are
pseudo-labels from the generic COCO model wherever a source does not label them, so the
new model keeps detecting people and paddles (paddle quality is bounded by the COCO
racket proxy). The app maps classes to its canonical IDs by name, so a new model is a
drop-in replacement; for the desktop pipeline set
`CONFIG["model"] = {"path": ".../best.pt", "classes": {"player": 0, "ball": 1, "paddle": 2}}`.

Smoke test lesson: fine-tuning on 150 frames of one clip (sideview) dropped held-out
recall from 40% to 1.8%. A model learns the clips it sees, so varied data (courts,
angles, lighting, ball colors) matters more than volume from one recording, and every
model must be checked on the held-out clips before it replaces the current one.

## Labeling plan

1. **Evaluation set first (~300 frames, about 20–30 minutes):** topcorner60fps and
   backcorner60fps at `--stride 5`. Keep these clips evaluation-only: never train on them,
   so scores stay honest.
2. **Training set (~1,000–2,000 frames):** new footage across angles, lighting, and courts,
   ideally 4K60 originals from a raised position, plus plenty of frames with leaves and no
   ball (negatives teach the model that leaves are not balls). Label at `--stride 3–10`.
3. **Fine-tune YOLO26n** on ball (and later paddle/player), export with
   `mobile/model/export_model.py`, re-run analysis, and compare with step 1's numbers.
