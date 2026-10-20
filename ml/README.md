# Ball detection data and evaluation

Tools for building a labeled pickleball dataset, measuring real ball-tracking accuracy,
and (next) fine-tuning the detector. Serves both the desktop pipeline and the iPhone
app; Core ML export and conversion checks stay in `tools/coreml/`.

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

Tests: `uv run python -m unittest discover -s ml`. Generated data lives in the
git-ignored `ml/external/`, `ml/datasets/`, and `ml/runs/`.

## Current baseline (topcorner60fps evaluation set, 164 visible balls)

| Model | Path | Tracked recall | Tracked precision |
| --- | --- | ---: | ---: |
| Generic COCO YOLO26n | on-device (Core ML) | 39.6% | 97.0% |
| Generic COCO YOLO26n | PyTorch (`predict_video.py`) | 40.2% | 97.1% |
| **pickleball-v1** (ball conf ≥ 0.20) | **on-device (Core ML)** | **61.6%** | **96.2%** |
| pickleball-v1 (ball conf ≥ 0.20) | PyTorch | 62.8% | 97.2% |
| pickleball-v1 (ball conf ≥ 0.10) | PyTorch | 64.0% | 90.5% |

With the COCO model, 57% of visible balls got no detection at all (median 8 px); with
pickleball-v1, 29%. The app ships pickleball-v1. Its weights and model card (data,
training, validation, held-out results, known errors, export command) are in
`ml/models/`. The 0.20 operating point was chosen on this clip; confirm it on another
labeled clip (e.g. backcorner60fps) before relying on the exact numbers.

Each model's ball-confidence threshold is stored in its Core ML metadata
(`export_model.py --ball-confidence`, read by the app's `Detector`), so the app always
uses the threshold that model was evaluated with.

## Why

Until now the only checks were "Swift matches Python" and visual review. Labels give
ground truth: how often the detector/tracker finds the real ball, and how often it
reports something else. The same labels become training data for a pickleball model.

## 1. Get detections for a video

Either export from the iPhone app (open a run → share → AirDrop `detections.jsonl`) or
run the identical analysis on the Mac:

```sh
cd ios/VantageKit
swift run -c release --scratch-path ~/Library/Caches/VantageKit-build vantage-analyze \
  ../../artifacts/yolo26n-1280/VantageDetector.mlpackage \
  ../../assets/pickleball/topcorner60fps.mov ../../reports/swift-detections/topcorner60fps.jsonl
```

## 2. Label

```sh
uv run python ml/label_ball.py --video assets/pickleball/topcorner60fps.mov \
  --detections reports/swift-detections/topcorner60fps.jsonl --stride 5
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
uv run python ml/evaluate_ball.py \
  --labels ml/labels/topcorner60fps.json --detections reports/swift-detections/topcorner60fps.jsonl \
  --labels ml/labels/backcorner60fps.json --detections reports/swift-detections/backcorner60fps.jsonl
```

Reports recall (visible balls found) and precision (predictions that were the ball)
for the detector alone (`raw best`), the tracker, and the tracker without
static-clutter suppression. A prediction counts as correct within 1% of the frame
diagonal (`--radius-diagonals`). `--export-centers` writes the
`{frame: [x, y] | null}` format accepted by `tools/coreml/crop_experiment.py --labels`.

## 4. Fine-tune

```sh
# a. Public data (free key: roboflow.com -> Settings -> API Keys). Store it once, privately,
#    outside the repo (or export ROBOFLOW_API_KEY for the session):
mkdir -p ~/.config/vantage && read -rs "?Roboflow API key: " KEY && printf %s "$KEY" > ~/.config/vantage/roboflow_api_key \
  && chmod 600 ~/.config/vantage/roboflow_api_key && unset KEY
uv run python ml/fetch_roboflow.py WORKSPACE/PROJECT/VERSION --info   # check license/classes
uv run python ml/fetch_roboflow.py WORKSPACE/PROJECT/VERSION          # download + attribution
#    then add it to ml/dataset.yaml under external: with its class mapping

# b. Build, train, evaluate on the held-out clip
uv run python ml/build_dataset.py
uv run python ml/train.py --data ml/datasets/pickleball-v1/data.yaml --name pickleball-v1
uv run python ml/predict_video.py --weights ml/runs/pickleball-v1/weights/best.pt \
  --video assets/pickleball/topcorner60fps.mov --output /tmp/topcorner-v1.jsonl
uv run python ml/evaluate_ball.py --labels ml/labels/topcorner60fps.json --detections /tmp/topcorner-v1.jsonl

# c. If it beats the baseline: export for the app and confirm on the Core ML path
uv run python tools/coreml/export_model.py \
  --weights ml/runs/pickleball-v1/weights/best.pt --output artifacts/pickleball-v1-1280
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
   `tools/coreml/export_model.py`, re-run analysis, and compare with step 1's numbers.
