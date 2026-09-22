# Vantage — offline pickleball video analysis

A Python CLI that runs pretrained YOLO26 nano + ByteTrack on one fixed-camera
video, calibrates the court with four clicks, and exports an annotated video and
estimated statistics. No model training, web server, or real-time requirements.

## Setup and run

Python 3.10+ is supported; Python 3.13 is the tested environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p input
# Put your fixed-camera game video at input/sample.mp4, then:
python main.py --input input/sample.mp4
```

For the video already supplied with this project:

```bash
python main.py --input assets/videoplayback.mp4
```

`--input` defaults to `input/sample.mp4`; `--output-dir` defaults to `output`.
Missing input produces an actionable error before importing the ML libraries.
Paths are relative to the current working directory. For offline processing,
first install requirements and download `yolo26n.pt` while online:

```bash
python -c 'from ultralytics import YOLO; YOLO("yolo26n.pt")'
```

`lap` is explicitly installed because ByteTrack needs its assignment solver;
this prevents Ultralytics trying to install it during an offline run. A desktop
OpenCV build (`opencv-python`, not the headless build) is needed for first-time
calibration. CPU is the portable default. Apple Silicon users may change
`CONFIG["detection"]["device"]` to `"mps"`; CUDA users can choose `"0"`.

## Court calibration

On the first frame, click the **outer court corners** in this order:

1. Near-left
2. Near-right
3. Far-right
4. Far-left

Press **Enter** to confirm, **R** to reset, or **Esc** to cancel. The preview is
scaled for your display; saved coordinates use original pixels. The court maps
to x=0–6.10 m and y=0–13.41 m, with the net at y=6.705 m.

The program saves `output/homography.npy` and `output/calibration.json`. A matching
calibration is reused on subsequent runs. If the camera moves, zooms, or crops,
run `python main.py --recalibrate`. A resolution mismatch triggers recalibration
automatically. For separate camera setups, use separate output directories.

## Outputs

- `annotated.mp4`: source FPS and dimensions, player boxes/IDs, detected ball box,
  a fading 15-position trail, estimated IN/OUT bounce markers, and estimated
  rally/shot counts. Yellow is observed ball evidence; orange hollow points are
  interpolated/coasted positions. Missing-ball status is explicit. Near-line
  bounce calls show a question mark. Audio is not copied. Odd input dimensions
  receive one black padding pixel for MPEG-4 compatibility.
- `stats.json`: video metadata, rally count, shots per rally, longest rally in
  estimated shots, average projected speed in km/h, timestamped bounce calls,
  rally details, and data-quality warnings.
- `tracks.jsonl`: one record per frame with timestamps, native-pixel player,
  paddle, and selected ball boxes, confidences, and nullable ByteTrack IDs.
- `homography.npy` and `calibration.json`: reusable court calibration.

Stdout contains **only the final statistics JSON**. Progress and diagnostics go
to stderr, so redirecting is safe:

```bash
python main.py --input input/sample.mp4 > run-stats.json
```

Detection and rendering use two video passes. Only compact records are retained,
not decoded frames. The output is fully decoded to verify frame count and format
before final artifacts replace previous results. Failed processing leaves prior
results intact. The three output files are replaced individually after success;
this is not a transactional multi-file filesystem commit.

## What the estimates mean

- A **shot** is a supported crossing of the projected net line, not a detected
  paddle impact. Serves or shots that do not cross are not counted.
- A **rally** is a group containing at least one crossing, separated from the next
  group by at least two seconds of ball loss or inactivity. It is not official
  scoring and can split a real rally when detection is poor.
- **Speed** is smoothed 2-D displacement on the court plane, using consecutive
  observed frames and excluding projection spikes. A homography cannot recover
  an airborne ball's 3-D position or true speed.
- A **bounce candidate** has supported descending/ascending image-y motion and a
  better piecewise fit than a straight line. Nearby paddle detections suppress
  some hits, but perspective and missed paddles still cause ambiguity. Bounds
  include the lines; near-boundary calls carry an uncertainty flag.
- Ball gaps up to 0.20 s can be interpolated. Up to 0.10 s of coasting is used only
  for display. Events are never inferred from coasting or across long gaps;
  crossings require uninterrupted observed evidence. Track changes split paths.
- Generic COCO weights often miss small pickleballs and pickleball paddles.
  The pipeline still writes a watchable annotated video when no ball is found.
  Speed is then `null`, and counts are accompanied by insufficient-evidence
  warnings. Zero counts are not proof that no play occurred.

The timing model uses frame index / source FPS and writes constant-FPS output.
Convert variable-frame-rate footage to constant FPS first if exact timing matters.
The camera must remain fixed throughout the clip, and all four court corners must
be identifiable. People outside the court can also be detected as players.

## Configuration and code structure

All tunable parameters, units, colours, and thresholds are commented in the one
`CONFIG` dictionary in `config.py`. To switch models, replace its `model` entry:

```python
"model": {"path": "pickleball.pt", "classes": {"player": 0, "ball": 1, "paddle": 2}},
```

The default is `yolo26n.pt` with COCO person=0, sports ball=32, tennis racket=38.
There is no fallback download of a different model if loading fails: failures
name the requested weights and explain how to prepare an offline run.

| File | Responsibility |
| --- | --- |
| `main.py` | CLI, input checks, two-pass orchestration, output publication |
| `config.py` | Model/class mapping and all tuning parameters |
| `records.py` | Shared typed frame, detection, trajectory, bounce, rally records |
| `detector.py` | Model loading, ByteTrack, ball candidate selection |
| `court.py` | Calibration UI, validated cache, projective mapping |
| `ball_physics.py` | Segments, smoothing, interpolation/coasting, bounce estimates |
| `stats.py` | Crossings, rally grouping, speed, quality metadata |
| `visualize.py` | Overlays, fading trails, video writing and decode verification |

## Tests

```bash
python -m unittest discover -v
```

Tests use synthetic trajectories and generated MP4 files, including an injected
detector; they do not download weights or open calibration windows. They cover
calibration geometry/cache validation, candidate selection, missing data, track
changes, bounce/paddle ambiguity, boundaries, crossings, rally grouping, speed,
no-ball output, stdout JSON, and failed-run cleanup.

Tested dependency versions: Python 3.13.7, Ultralytics 8.4.159, OpenCV 5.0.0.93,
NumPy 2.5.3, and lap 0.5.13. The requirements use compatible ranges so Python 3.10
can resolve releases that still support it.

Reference: [Ultralytics tracking API](https://docs.ultralytics.com/modes/track/).
