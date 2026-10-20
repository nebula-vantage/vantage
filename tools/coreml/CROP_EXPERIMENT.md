# Ball crop experiment

This is an isolated Python experiment, not a replacement for `main.py` or a live
iPhone capture implementation. It reads the existing weights, config, and custom
ball tracker without changing them. No second physical camera is used.

Every source frame gets the normal full-frame detector pass. Two independent
instances of the existing ball tracker provide the comparison:

- Baseline: full-frame ball candidates only.
- Experiment: full-frame candidates plus one crop from the original frame.

The crop follows the experiment tracker's velocity prediction. When there is no
recent confirmed track, overlapping tiles scan the image one tile per frame.
Every tenth frame also scans even if a track exists, to limit a false track's
ability to monopolize the crop. Crop detections are translated back to source
pixels, internal-edge partial boxes are rejected, and overlapping candidates are
deduplicated before association. Predicted positions only guide the crop; they
are never counted as ball observations.

The default crop is 960 × 960 source pixels, clamped to image dimensions. The
crop is taken **before** model resizing. It cannot recover detail absent from
the recording, and smaller crops may trade context/coverage for apparent size.

## Run

From the repository root, using the existing environment without installing or
changing any dependencies:

```sh
.venv/bin/python mobile/model/crop_experiment.py \
  --video assets/pickleball/topcorner60fps.mov \
  --max-frames 300 \
  --output mobile/reports/my-crop-test
```

Use a new output folder each run. Omit `--max-frames` for the entire clip. Use
`--crop-side` to test different native-pixel crop sizes.

Outputs:

- `comparison.mp4`: baseline on the left; crop-assisted tracker on the right.
  Cyan rectangle marks the searched crop; yellow box/circle marks observations.
  Players are intentionally not annotated in this ball experiment.
- `frames.jsonl`: timestamps, crop locations/modes, raw candidates, both selected
  tracks, confidence, and per-pass elapsed times.
- `report.json`: observed coverage, timing, model checksum, and config snapshot.

Source timestamps come from the decoder. If missing/nonincreasing, a nominal-FPS
fallback is recorded. The comparison MP4 plays at nominal FPS; JSONL retains the
analysis timestamps. Both completed trial runs required zero timestamp fallbacks.

## Initial results

| Clip | Frames evaluated | Baseline observations | With crop | Extra observed frames |
| --- | ---: | ---: | ---: | ---: |
| sideview.MOV | 606 (entire clip) | 602 | 605 | 3 |
| topcorner60fps.mov | 300 (first ~10 seconds) | 135 | 157 | 22 |

Neither trial lost a baseline-observed frame by this presence/absence measure.
This does **not** establish that the two trackers chose the same ball position.
Counts are observations, not verified correct detections. False positives and
far-court recall still need independent labels. One extra observation at frame
113 in the top-corner clip was visually inspected; that is not a systematic
accuracy evaluation.

Local videos:

- [Side-view comparison](../reports/crop-sideview/comparison.mp4)
- [Top-corner comparison](../reports/crop-topcorner/comparison.mp4)

The additional crop pass took roughly 81 ms median for sideview and 110 ms for
topcorner on this Mac's CPU. The runs overlapped and may have competed for CPU;
these are exploratory timings, not controlled or iPhone benchmarks. Video
encoding is excluded. Running both passes on every live frame is not yet a
validated performance target.

## Check accuracy

Provide independent source-pixel ball-center labels in a JSON object keyed by
zero-based frame index, for example `{"123": [500, 220], "124": null}`.
`null` means no visible ball; omit frames that are ambiguous or not reviewed.
Supply `--labels labels.json --label-radius 15` when running. The report counts
correct observations, misses, and false detections on labelled frames only.
A wrong position on a visible-ball frame counts as both a miss and a false
detection. The tolerance is native source pixels, not court distance.

Before promoting to the iPhone app, label a representative far-court segment,
review identity/position differences, then test crop size and inference cadence
on-device. The Swift prototype currently remains the original single-pass
detector, so these results are not Core ML crop validation. Keep the second
physical camera deferred; revisit wide-plus-telephoto only if source-resolution
crops cannot recover sufficient ball detail.
