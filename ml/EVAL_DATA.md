# External evaluation data (tennis, badminton, pickleball)

Public clips with per-frame ball labels, for measuring the detector and ball tracker beyond our
own hand-labeled clips. **Evaluation only:** never add them to `ml/dataset.yaml` or copy their
labels into `ml/labels/` (which `build_dataset.py` trains on). Most have no stated license or
are research-only, and the footage belongs to broadcasters or uploaders, so keep it local
(git-ignored), don't redistribute it, and don't ship it in the app.

```sh
uv run python ml/fetch_eval_data.py --list           # sources and what is already fetched
uv run python ml/fetch_eval_data.py --all            # about 5 GB on disk; resumable
uv run python ml/evaluate_external.py --weights ml/models/pickleball-v1.pt
uv run python ml/evaluate_external.py --weights yolo26n.pt --sport tennis --per-clip
```

`fetch_eval_data.py` downloads only the eval-sized subset of each dataset (HTTP range reads
for multi-GB zips) and converts it to `ml/external/eval/<source>/clips/<clip>.mp4` plus
`labels/<clip>.json` in the `ml/labels` format, so the existing tools work on any clip:

```sh
uv run python ml/predict_video.py --weights ml/models/pickleball-v1.pt \
  --video ml/external/eval/tracknet-tennis/clips/game4_clip1.mp4 --output /tmp/g4c1.jsonl
uv run python ml/evaluate_ball.py --labels ml/external/eval/tracknet-tennis/labels/game4_clip1.json \
  --detections /tmp/g4c1.jsonl
```

`evaluate_external.py` runs the model over every clip once at the raw 0.10 threshold (cached
under `reports/external-eval/<weights>-<hash>-<code>-<imgsz>px-conf<threshold>/`, where `<code>`
covers the detection code and library versions, so a retrained `best.pt`, a new setting, or a
library update never reuses old detections), applies the model's ball operating
point from its model card (0.20 for `pickleball-v1`, the threshold the app ships; override with
`--ball-confidence`), and reports recall/precision with the same rules as `evaluate_ball.py`
(1% of the frame diagonal), per source and per sport. To score the app's Core ML path, run
`vantage-analyze` on the same `clips/*.mp4`, save the output as `<dir>/<source>/<clip>.jsonl`,
and pass `--detections-dir <dir>`.

How labels were converted: the label is the ball in play, and absent means no ball in play is
visible (out of frame, hidden, or dead between points, like N in `label_ball.py`). Frames a
source did not label, or whose "no ball" marker also covers visible balls in play, are left out
(not scored), as with skipped frames in `label_ball.py`. Labels are ball centers; the stored
box is a nominal size because scoring compares centers. Extra per-frame fields are kept for
later metrics:
`visibility` (the source's class), `event` (`hit` / `bounce`), and `interpolated` (CVAT
frames between hand keyframes; `--keyframes-only` skips them).

Pull requests are scored automatically on a small subset (`--suite ci`); see "Accuracy check on
pull requests" in `ml/README.md`.

## Fetched sources

229 clips, 82,683 labeled frames (70,844 with a visible ball): pickleball 35,477, tennis
18,510, badminton 28,696. Retrieved 2026-11-04. Hugging Face and GitHub sources are pinned to
the commits that were checked, Kaggle sources to dataset versions, and Google Drive and
SharePoint files to their exact sizes (a changed upload stops the fetch). Every source was
verified by drawing its labels on decoded frames of the converted clips.

| Source | Sport | Camera | Clips | Labeled (absent) | License | Notes |
| --- | --- | --- | ---: | ---: | --- | --- |
| [`arnav-pickleball`](https://github.com/arnavchokshi/pickleball/tree/main/eval_clips/ball) | pickleball | fixed club/tournament cameras: low and mid corner, mid and high behind the baseline; 30/60 fps | 4 | 1,891 (0) | not stated | 1,571 labels are CVAT interpolations (`--keyframes-only` keeps the 320 hand keyframes) |
| [`rochester-pickleball`](https://github.com/AndrewDettor/TrackNet-Pickleball) | pickleball | fixed elevated pro-stream camera behind the baseline; 30 fps | 1 (7 min) | 10,589 (125) | not stated | the labeling tool's default "no ball" also covers visible balls, so absent only when the ball left the frame |
| [`tnv2pic-pickleball`](https://www.kaggle.com/datasets/kagmanedai/tnv2pic) | pickleball | corner cameras, 60 fps: a Vietnamese tournament stream (zooms) and a fixed US rec-doubles tripod | 3 | 22,997 (7,118) | not stated | labels look like model pseudo-labels; "no ball" counts as absent only in runs of 1 s or more (between points) |
| [`tracknet-tennis`](https://arxiv.org/abs/1907.03698) | tennis | broadcast behind the baseline; game4 is a low fixed ITF camera; 30 fps | 37 | 7,898 (249) | not stated | game4 plus game8-10, the WASB-SBDT test split (papers score it with a few-pixel tolerance, so our numbers are not directly comparable; game4 is in WASB's training split, so don't score WASB/TrackNet checkpoints on it); occluded frames left out; 402 hit/bounce events |
| [`tennis-analytics`](https://www.kaggle.com/datasets/benediktvoss/tennisanalytics) | tennis | fixed standing-height camera behind the baseline (one rear corner); amateur clay; 30 fps | 6 | 1,782 (232) | Apache 2.0 | visibility classes; 58 hit/bounce events; court keypoints and player boxes exist in the source but are not converted |
| [`yonggest-tennis`](https://huggingface.co/datasets/yonggest/tennis-track-26) | tennis | fixed raised camera centered behind the baseline; club hard courts; 4K 59.94 fps | 2 | 852 (0) | not stated | closest to a raised Vantage phone; unlabeled spare balls in view |
| [`ballyolo-tennis`](https://doi.org/10.5061/dryad.3bk3j9m13) | tennis | fixed amateur cameras: low corners and one behind the baseline; 30/60 fps | 4 | 3,591 (0) | GitHub copy (downloaded): research and academic use only; Dryad release: labels CC0-1.0, videos CC BY-NC-ND 4.0 | two clips needed hand-verified one-frame label shifts |
| [`tenis-backview`](https://www.kaggle.com/datasets/gastonarielfrancois/tenis-backview) | tennis | fixed head-height camera behind the baseline, 10 courts; 30/60 fps | 10 | 2,237 (0) | CC0 per Kaggle (footage is third-party) | unlabeled frames often show the ball, so they are left out |
| [`racketvision-tennis`](https://github.com/OrcustD/RacketVision) | tennis | ATP broadcast, a few low or corner cameras; 25-60 fps | 43 | 2,150 (203) | MIT (clips from YouTube broadcasts) | official test split; 50 sampled frames per clip; 43 matches |
| [`racketvision-badminton`](https://github.com/OrcustD/RacketVision) | badminton | BWF broadcast, elevated behind the baseline; 25 fps | 46 | 2,297 (349) | MIT (same) | official test split; 50 sampled frames per clip |
| [`tracknetv2-badminton`](https://hackmd.io/Nf8Rh1NrSrqNUzmO0sQKZw) | badminton | amateur: fixed low indoor camera behind the baseline; test: broadcast; 30 fps | 55 | 20,299 (2,231) | not stated | test uses TrackNetV3's corrected labels and scored spans; TrackNetV3/WASB checkpoints were trained on the amateur part |
| [`kwyoke-badminton`](https://github.com/kwyoke/Badminton-hit-detection) | badminton | fixed amateur camera at court level, behind the baseline or a back corner; 25-30 fps | 18 | 6,100 (1,332) | not stated | 214 hit events; two matches' tracks re-aligned by hand-found frame shifts |

Sources with no absent labels can't show false alarms on empty frames: there, precision only
counts detections in the wrong place. Clip-level details (frame shifts, dropped frames, label
quirks) are in each source's docstring in `eval_sources.py` and in `source.json`.

## Baseline (2026-11-04)

Tracked recall / precision from `evaluate_external.py` (PyTorch, 1280 px), each model at the
ball threshold it ships with, as in `ml/README.md`: `pickleball-v1` at 0.20, the generic COCO
`yolo26n` at 0.10. Raw-detector numbers and every clip are in the `--per-clip` output.

| Sport | Labeled (visible) | COCO yolo26n | pickleball-v1 |
| --- | ---: | ---: | ---: |
| pickleball | 35,477 (28,234) | 42.6% / 87.5% | 60.0% / 92.2% |
| tennis | 18,510 (17,826) | 33.5% / 92.9% | 39.9% / 89.4% |
| badminton | 28,696 (24,784) | 8.6% / 60.5% | 14.6% / 91.7% |

Pickleball recall is close to the held-out topcorner clip in PyTorch (62.8%, `ml/README.md`),
from fixed amateur cameras (`arnav-pickleball` 58.6%) to a pro stream (`rochester-pickleball`
65.8%).
Tennis varies with ball size: fixed cameras near the baseline do well (`tenis-backview` 79.4%),
while small far balls in 4K or at standing height do not (`yonggest-tennis` 14.7%,
`tennis-analytics` 18.2%). The model was never trained on shuttlecocks, so badminton is a
lower bound for a multi-sport detector. Fine-tuning on pickleball also helped tennis and
badminton recall over the COCO model. Misses are detector misses: 44.6% of visible balls got no
ball detection at all, and only 4.3% were detected but not picked by the tracker. Charts, the
full JSON output, and the analysis are in
[`ml/results/external-eval-2026-11-04/`](results/external-eval-2026-11-04/README.md).

Not fetched automatically but worth adding. Each needs an adapter in `eval_sources.py` first:
`fetch_roboflow.py` writes training-side data (`ml/external/<dir>`, listed in
`ml/DATA_SOURCES.md`), and the evaluators read videos with labels, not image exports.

| Dataset | Why | How |
| --- | --- | --- |
| [owl-q3a4r/pickleball-ball-tracking](https://universe.roboflow.com/owl-q3a4r/pickleball-ball-tracking) | 480 consecutive frames, amateur outdoor doubles, tripod at the corner (MIT) | Roboflow account: fork, generate a version without resizing, export (sequential frame names) |
| [pickleball-tvtgk/pickleball_ball-jia5b](https://universe.roboflow.com/pickleball-tvtgk/pickleball_ball-jia5b) v2 | 1,322 frames from one fixed phone behind an indoor baseline (CC BY 4.0); sampled frames, so detection only | Roboflow API key; export version 2 (native resolution) |
| [nduongctu/pickleball-p2](https://www.kaggle.com/datasets/nduongctu/pickleball-p2) and [pickleball-1](https://www.kaggle.com/datasets/nduongctu/pickleball-1) | about 44k labeled frames from one PPA singles broadcast (Kaggle tag MIT; footage rights unclear) | frames are individual JPGs; per-file Kaggle downloads work without login |
| [TrackNetV4 tennis](https://tracknetv4.github.io/) | amateur fixed elevated tennis with several balls and neighboring courts | research-only data agreement by request |
| [CalTennis](https://ilonadem.github.io/caltennis-website/) | multi-view tennis from fixed phones on tripods at 60 fps, with camera calibrations (CC BY-NC 4.0, 120 GB) | no ball labels: self-label a few rallies with `label_ball.py` |

## Raw footage to label ourselves

Openly licensed, fixed or near-fixed cameras, verified 2026-11-04. Label with `ml/label_ball.py`,
but pass `--labels` with a path outside `ml/labels/` (for example
`ml/external/eval/self-labeled/<clip>.json`): `build_dataset.py` trains on every file in
`ml/labels/`, and NC/ND footage must never become training data.

- Pickleball: YouTube [pickleball4you](https://www.youtube.com/@pickleball4you) (CC BY; full
  amateur and senior tournament matches), CC BY videos from
  [BT Pickleball](https://www.youtube.com/@BTPICKLEBALL) and
  [Craig vs Pickleball](https://www.youtube.com/@CraigvsPickleball) (fixed phone-like camera at
  60 fps; check each video's license line, only some are CC).
- Tennis: Wikimedia Commons
  [2026 US Open spectator clips](https://commons.wikimedia.org/wiki/Category:2026_US_Open_(tennis))
  (CC BY-SA 4.0, raised side/corner phone view, 60 fps), Internet Archive
  [Attleboro HS tennis](https://archive.org/details/DoubleACS_GirlsTennis0317) (CC BY-NC-ND 3.0,
  fixed elevated camera), [Tennis-Lab multiview](https://huggingface.co/datasets/Motoki098/tennis-lab-multiview-sample)
  (CC BY-NC-ND 4.0, three synchronized fixed cameras).
- Badminton: YouTube [2026 YONEX Arise International Challenge court streams](https://www.youtube.com/watch?v=M4vUm6wl6pc)
  (CC BY, locked-off full-court view at 60 fps), [RacketDB](https://github.com/muhabdulhaq/racketdb)
  (CC BY 4.0, raised behind-baseline 4K amateur footage).

Avoid Coverr: its license forbids using clips to evaluate AI models.

## For later metrics (no per-frame ball positions)

- Bounce and hit timing: [TenniSet](https://github.com/HaydenFaulkner/Tennis),
  [E2E-Spot tennis](https://github.com/jhong93/spot), [tennis-bounce-hit-benchmark](https://github.com/David-dsv/tennis-bounce-hit-benchmark)
  (CC BY 4.0, non-broadcast fixtures), [ShuttleSet](https://github.com/wywyWang/CoachAI-Projects/tree/main/ShuttleSet)
  (badminton strokes, rally boundaries, court homography), the `event` fields above (TrackNet
  tennis, TennisAnalytics, kwyoke badminton).
- Court calibration: [TennisCourtDetector](https://github.com/yastrebksv/TennisCourtDetector)
  (14 keypoints, 8,841 broadcast stills); TennisAnalytics and arnavchokshi/pickleball (fetched
  above) also label court keypoints; Roboflow pickleball court-keypoint sets such as
  [pb-rrerm/pb-9bsin](https://universe.roboflow.com/pb-rrerm/pb-9bsin) (CC BY 4.0).
- Ball speed: no open dataset gives speed ground truth aligned to video. Grand Slam serve
  speeds in [Sackmann's point-by-point data](https://github.com/JeffSackmann) (CC BY-NC-SA 4.0)
  are the closest, aligned to broadcast footage by hand.
- Padel analogue with homographies: [PadelTracker100](https://zenodo.org/records/14653706)
  (CC BY 4.0, fixed raised camera, per-frame ball).

This list came from checking 154 candidates for live links, stated licenses, and label formats
(2026-11-04). Not used: AI Hub's Korean tennis and badminton sets (access limited to Korea),
BadmintonSkill-23 and THETIS (no ball positions), Coverr (license forbids AI evaluation), and
Roboflow pickleball sets already used for training (`ml/DATA_SOURCES.md`).
