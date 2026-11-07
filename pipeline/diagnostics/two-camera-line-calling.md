# Two-camera line calling — feasibility study

Question: can two synchronized cameras decide in/out better than the one fixed camera
the pipeline uses today, and where should they go?

## Short answer

Every number in this section uses realistic settings unless marked otherwise: 60 fps,
1080p, today's detector quality (40% of frames missed) and 2 px court-corner clicks.

- **Feasible in simulation, but the second camera belongs behind the *other*
  baseline (centred, or at the diagonal corner), not beside the first.**
  - Two cameras behind the *same* baseline call the near baseline and the near
    sideline well (75–81% of close balls confidently called).
  - The same pair needs early fusion for the far sideline (61%, against 34% with late
    fusion). The far baseline stays out of reach: 3–8% of close balls get a confident
    call.
- **One camera behind each baseline:**
  - **Merging each camera's own result (late fusion):** 95% of errors are under
    5–7 cm on every line. It confidently calls 52–58% of balls landing within 15 cm
    of a line, and those calls are right 98–100% of the time. The rest it reports as
    "too close to call".
  - **Fitting one 3-D flight to both cameras (early fusion):** errors under 4–5 cm,
    and 60–77% of close balls confidently called.
  - **With 1 px automatic calibration:** 59–69% (late) or 72–83% (early). Adding a
    better detector (20% misses) gives 72–82% or 77–85%.
- **Do "both cameras determine the call"? With late fusion, mostly no.**
  - At each baseline the camera behind it does the work. At the near baseline the
    near camera alone and the fused result both call 58%.
  - On the near sideline the far camera adds about 10 points (45% → 55%).
  - Early fusion is what makes both cameras judge each ball: +7 to +8 points at the
    baselines and +19 to +21 on the sidelines.
  - It is also the only mode with a real second opinion. If a player hides the
    bounce from one camera half the time, early fusion still calls 43–65% of close
    balls; late fusion falls to 30–36%.
- **Fine time sync is the easy part for this layout. The coarse step is untested.**
  - Late fusion does not use cross-camera timing beyond matching bounces.
  - Early fusion tolerates 16 ms of clock error with cameras at the two ends.
  - The ball's own motion syncs the cameras to about 2–3 ms (median), with no audio
    or extra hardware.
  - Not simulated: the coarse alignment from seconds down to tens of milliseconds,
    clock drift over a session, and matching bounces when some are missed or false.
    Both fusion modes need them.
- **Today's single-camera estimate is biased.** It puts close far-baseline balls about
  90 cm long and calls them OUT without a warning flag. Software can remove the bias
  on the camera's near half. For the far half it can only say "not callable from this
  camera".
- **For the product:** this calls clear balls reliably and supports stats and heat
  maps. It is not an officiating replacement.
  - With late fusion, about half of the balls landing 4–6 cm from a line are left as
    "too close to call", and 13% of those 10–15 cm away.
  - With early fusion, 64% of balls 4–6 cm away and 97% of those 10–15 cm away get a
    confident call.

Everything here comes from a Monte Carlo simulation
([`two_camera_feasibility.py`](two_camera_feasibility.py)), not from real two-camera
footage, which we do not have yet. Treat the numbers as a best case to validate, not
as a measured accuracy.

## What "syncing the two POVs" involves

1. **Space.** Both cameras are calibrated into the same court coordinates (metres
   from the near-left corner). Today `court.py` stores only a ground-plane homography
   from four clicked corners. Combining views needs each camera's full pose
   (intrinsics, rotation, position), which the same corners can provide
   (perspective-n-point) once the focal length is known.
2. **Time.** Two phones are not genlocked: each captures at its own instants (up to
   half a frame apart, 8 ms at 60 fps), starts recording at a different moment, and
   their clocks drift by tens of parts per million.
3. **Combining.** Two ways were simulated. Having each camera vote IN/OUT
   independently was not simulated.
   - **Late fusion:** each camera fits its own bounce contact and uncertainty; the two
     are merged weighted by uncertainty. Each camera keeps its own clock.
   - **Early fusion:** one 3-D ball flight is fitted to both cameras' pixels
     (triangulation). It uses more information but needs frame-level time sync.

## Why one camera cannot call the far baseline

Across-line court distance covered by one pixel at each line's midpoint, at 1080p
(`--geometry`):

| Camera | near baseline | near sideline (L / R) | far sideline (L / R) | far baseline |
| --- | ---: | ---: | ---: | ---: |
| Today: centre, 3.3 m back, 1.6 m high | 0.9 cm | 1.6 / 1.6 | 3.2 / 3.2 | 19.8 |
| Centre, 3.5 m back, 3 m high | 0.6 | 1.0 / 1.0 | 1.9 / 1.9 | 9.4 |
| Near-left corner, 2 m high | 1.0 | 0.8 / 3.5 | 1.5 / 5.9 | 15.3 |
| Behind the far baseline, 1.6 m high | 19.8 | 3.2 / 3.2 | 1.6 / 1.6 | 0.9 |

- "Today" is the pose recovered from the indoor real-match calibration, with 94° of
  horizontal view.
- Centimetres per pixel grow with distance squared divided by camera height. No
  algorithm recovers that, and calibration error is amplified the same way.
- A second camera beside the first barely helps the far baseline (15 cm/px). A camera
  at the far end sees it at under 1 cm/px.

## Today's estimate is biased

`ball_physics.detect_bounces` projects the ball **centre** of the frame nearest the
bounce through the ground homography.

- **Why it is biased:** at contact the centre is 3.7 cm above the floor. Seen from
  1.6 m up and 16.7 m away, that alone projects about 40 cm beyond the true contact
  (16.7 × 0.037 / 1.56). The nearest frame adds little: its median height above
  contact is under 1 cm.
- **Noise-free, 120 fps, realistic ball (median, 5th–95th percentile):**
  - far baseline: 43 cm long (40–58)
  - near baseline: 8 cm in (4–16)
  - sidelines: 8 cm out (7–10)
- **At 60 fps with noise and misses:**
  - median shift: +8 cm at the near baseline, −12 to −15 cm on the sidelines, −92 cm
    at the far baseline
  - 95% of errors are under 51 cm (near baseline), 30 cm (near sideline), 54 cm (far
    sideline) and 371 cm (far baseline)
- **What players see:** the pipeline already flags calls within 10 cm of a line
  (`line_tolerance_m`, shown as "IN (est.) ?").
  - Near lines and sidelines: 54–69% of close balls get an unflagged call, right
    66–78% of the time.
  - Far baseline: 96% get an unflagged call, right 54% of the time. They are almost
    all called OUT.

**Fix that needs no second camera.** Keep the 2-D bounce detector to find candidates,
then fit a 3-D flight through the camera's projection (`fit_hinge_3d`). With the same
camera:

- **Near baseline:** 5 cm at the 95th percentile, 58% confidently called, all right.
- **Near sideline:** 7 cm, 45% confidently called, all right. With 1 px calibration
  these become 65% and 56%.
- **Far half:** 11% of close far-sideline balls and no far-baseline balls get a
  confident call. The fix replaces wrong calls with "not callable", a visible change
  for single-camera users.

## How the numbers are measured

- **Shots:** balls land uniformly within ±15 cm of the line, half in and half out.
  This is a close-call stress test: in real play most bounces are far from any line.
- **No call:** a fitted estimate is discarded when its uncertainty across the line
  exceeds 10 cm ("not callable from here").
- **p95:** the 95th-percentile |error| across the line, among calls made.
- **Correct %:** IN/OUT right, among calls made.
- **Confident share / accuracy:**
  - The product rule is to call IN/OUT only when the estimate is more than 2σ from
    the line, and otherwise say "too close to call".
  - The share is of *all* close shots; accuracy is among those confident calls.
  - For today's method, which has no σ, "confident" means not flagged.
- **Sample size and comparisons:** 300 shots per line per setting.
  - Every layout and setting sees the same shots, and a camera in the same pose sees
    the same frames.
  - Comparisons between rows are therefore paired: differences above about 4 points
    are real within the simulation. A single share carries about ±3 points of
    standard error.
- **Medians for comparison:**
  - median error behind each baseline: 1.6–1.7 cm (late fusion), 1.1–1.6 cm (early)
  - when ATP line umpires miss a call, the miss averages about 3.3 cm
  - Hawk-Eye reports a 2–4 mm mean error, with about 10 high-speed cameras

## Results

60 fps, 1080p, 40% of frames missed (plus extra misses for small distant balls), 1 px
detector noise, 2 px corner clicks.

| Setup | Method | near baseline | near sideline | far sideline | far baseline |
| --- | --- | ---: | ---: | ---: | ---: |
| Today: 1 camera | today's estimate | 51 cm / 69% | 30 / 66 | 54 / 65 | 371 / 54 |
| Today: 1 camera | contact fit | 5 / 95 | 7 / 92, 7% none | 14 / 88, 54% none | no call |
| 2 at same baseline corners | late fusion | 3 / 97 | 3 / 95 | 7 / 92, 28% none | no call |
| 2 at same baseline corners | early fusion | 3 / 96 | 3 / 96 | 5 / 94 | 16 / 72, 74% none |
| **1 behind each baseline** | **late fusion** | **5 / 95** | **7 / 92** | **6 / 93** | **5 / 92, 5% none** |
| 1 behind each baseline | early fusion | 5 / 94 | 4 / 95 | 4 / 97 | 4 / 94 |
| Same, both 3 m high, 0.5 m framing room | late fusion | 4 / 97, 14% none | 4 / 95 | 3 / 96 | 6 / 90, 14% none |
| Same, both 3 m high, 0.5 m framing room | early fusion | 5 / 94 | 3 / 96 | 3 / 98 | 4 / 94 |
| Diagonal corners, 2 m | late fusion | 6 / 94 | 6 / 92 | 6 / 93, 5% none | 5 / 93, 5% none |
| Diagonal corners, 2 m | early fusion | 5 / 93 | 4 / 94 | 5 / 94 | 5 / 94 |

Each cell is p95 / correct %, plus the no-call share when it is 5% or more.

Confident share / accuracy, same runs:

| Setup | Method | near baseline | near sideline | far sideline | far baseline |
| --- | --- | ---: | ---: | ---: | ---: |
| Today: 1 camera | today's estimate (unflagged) | 54% / 74% | 61% / 78% | 69% / 66% | 96% / 54% |
| Today: 1 camera | contact fit | 58% / 100% | 45% / 100% | 11% / 97% | none |
| 2 at same baseline corners | late fusion | 75% / 100% | 76% / 100% | 34% / 99% | none |
| 2 at same baseline corners | early fusion | 78% / 99.6% | 81% / 100% | 61% / 100% | 3% / 100% |
| **1 behind each baseline** | **late fusion** | **58% / 100%** | **55% / 100%** | **58% / 100%** | **52% / 98.1%** |
| 1 behind each baseline | early fusion | 65% / 100% | 76% / 100% | 77% / 100% | 60% / 99.4% |
| Same, both 3 m high, 0.5 m framing room | late fusion | 54% / 99.4% | 67% / 100% | 73% / 100% | 47% / 97.9% |
| Same, both 3 m high, 0.5 m framing room | early fusion | 65% / 100% | 80% / 100% | 80% / 100% | 59% / 100% |
| Diagonal corners, 2 m | late fusion | 55% / 100% | 54% / 100% | 59% / 100% | 48% / 99.3% |
| Diagonal corners, 2 m | early fusion | 63% / 100% | 70% / 100% | 72% / 100% | 57% / 100% |

Confident share by how far the ball truly lands from the line (one behind each
baseline, all lines pooled):

| Distance from line | 0–2 cm | 2–4 | 4–6 | 6–8 | 8–10 | 10–15 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Late fusion | 5% | 17% | 42% | 62% | 77% | 87% |
| Early fusion | 8% | 34% | 64% | 78% | 95% | 97% |
| Today's estimate (unflagged; right only 54–78% of the time) | 66% | 75% | 68% | 67% | 71% | 71% |

What this shows:

- **Same-baseline pair (the original idea):** better than opposite ends on the near
  baseline and near sideline (75–81% vs 55–76%). Weaker on the far sideline (late
  34%, early 61%), and the far baseline is out of reach.
- **One behind each baseline:** every line is callable. The paired early-minus-late
  difference is +7 points at the near baseline, +21 near sideline, +19 far sideline
  and +8 far baseline.
- **Height and framing** (3 m against 1.6 m):
  - Raising the cameras with tight framing loses the ball off the bottom of the frame
    after near-baseline bounces: late fusion makes no call on 29–30% of baseline
    balls.
  - 0.5 m of framing room fixes most of that (14%). With it, late fusion gains 12–15
    points on the sidelines and loses 4–5 at the baselines. Early fusion changes by
    −1 to +4, within noise.
  - 1 m of room (103° view) gives back most of the sideline gain.
  - Height mainly matters for what was not simulated: seeing over players at the
    baseline.
- **Diagonal corners** are close to centred cameras with late fusion (−4 to +1) and
  slightly worse with early fusion (−2 to −6).
- **Uncertainty is well calibrated in simulation.**
  - 93–99% of errors fall within 2σ, against 95.4% expected.
  - Across every two-camera cell in this run, 27 of 10,031 confident calls were wrong
    (0.27%).
  - Accuracy dips to 96–98% on lines a layout covers weakly. This holds only within
    the simulated error sources.

## Time sync

Early fusion with a residual clock error between the cameras. Each cell is p95 /
confident share; the "behind each baseline" row shows the worst line.

| Clock error | 0 ms | 2 ms | 4 ms | 8 ms | 16 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Same baseline, near baseline | 3 cm / 78% | 4 / 77% | 6 / 74% | 9 / 66% | 17 / 50% |
| One behind each baseline, worst line | 5 cm / 60% | 5 / 58% | 5 / 57% | 5 / 56% | 6 / 52% |

- **Why the layouts differ:** a timing error moves the ball along its direction of
  travel, mostly down the court. Cameras at the two ends look down the court, so
  they barely notice it.
- **Sync error is not part of σ.** A same-end pair with 8–16 ms of error becomes
  overconfident: confident accuracy 94–97.5%.
- **Late fusion** does not use cross-camera timing.
- **Rolling shutter:** an uncorrected 12 ms readout changed nothing measurable.

**Self-sync from the ball, no audio or hardware.** Search for the time offset that
puts camera B's ball positions on the epipolar lines of camera A's positions
(interpolated in time). Residual error, median / p95:

| Setup | 8 shots, 2 px clicks | 32 shots, 2 px clicks | 8 shots, perfect calibration |
| --- | ---: | ---: | ---: |
| Same baseline corners | 1.6 / 5.6 ms | 1.1 / 3.4 ms | 0.3 / 1.1 ms |
| One behind each baseline | 3.0 / 10.2 ms | 1.8 / 4.9 ms | 1.0 / 4.4 ms |
| Diagonal corners | 2.4 / 8.4 ms | 1.7 / 5.9 ms | 1.0 / 2.8 ms |

- Calibration error and the shot count limit it more than frame rate does: medians
  move by up to 1.4 ms between 30 and 120 fps.
- Pooling a rally's worth of shots keeps the p95 well inside what early fusion
  tolerates behind each baseline.
- This assumes a starting offset already within ±20 ms. The coarse alignment and
  drift caveats in the short answer apply.

## Other sensitivities

All for one camera behind each baseline, at the realistic defaults.

**Frame rate.** Worst-line p95 / range of confident shares across lines:

| fps | 30 | 60 | 120 | 240 |
| --- | ---: | ---: | ---: | ---: |
| Late fusion | 8 cm / 18–24% (53–57% none) | 7 / 52–58% | 5 / 64–83% | 4 / 68–85% |
| Early fusion | 7 cm / 35–50% (10–26% none) | 5 / 60–77% | 4 / 69–83% | 4 / 71–84% |
| Today's estimate, near baseline p95 | 109 cm | 51 | 29 | 18 |

- With 40% of frames missed, 30 fps leaves too few frames on each side of the bounce.
- 120 fps adds 12–25 points for late fusion and 2–9 for early fusion, at about twice
  the detection compute and storage, with less light per frame.

**Calibration** is the biggest software lever:

| Corner-click error | 0 px | 1 px | 2 px | 4 px | 2 px + focal length σ 3% |
| --- | ---: | ---: | ---: | ---: | ---: |
| Late fusion | 4 cm / 65–73% | 4 / 59–69% | 7 / 52–58% | 13 / 26–43% | 8 / 51–60% |
| Early fusion | 3 cm / 75–85% | 4 / 72–83% | 5 / 60–77% | 9 / 38–60% | 7 / 57–76% |

- **Clicks:** `court.py` takes clicks on a preview capped at 1280×800, so one preview
  pixel is 1.5 source pixels at 1080p (3 at 4K). Realistic clicking is therefore
  2–4 px.
- **What automatic calibration buys:** going from 2 to 1 px gains 7–11 points (late)
  or 6–12 (early), and the single camera's near lines go from 58/45% to 65/56%.
  Slipping to 4 px loses 15–29 or 16–22 points.
- **Focal length:** an unknown focal length is not covered by the uncertainty. Only
  71–86% of sideline errors stay within 2σ, and up to 3 confident calls per line are
  wrong. Use the phone's lens intrinsics.

**Detector misses.** Base miss rate on top of the extra misses for small, distant
balls; 40% matches pickleball-v1's 62% tracked recall.

| Base missed frames | 20% | 40% | 60% |
| --- | ---: | ---: | ---: |
| Late fusion | 5 cm / 60–74% | 7 / 52–58% | 8 / 28–32% (29–36% none) |
| Early fusion | 4 cm / 64–79% | 5 / 60–77% | 6 / 39–62% (4–14% none) |
| Today's estimate, near / far baseline p95 | 34 / 243 cm | 51 / 371 | 89 / 682 |

**Occlusion near contact.** With probability p, a camera loses every frame within
±50 ms of the bounce, as when a player stands in front of it. The two cameras are
affected independently.

| p | 0 | 0.25 | 0.5 |
| --- | ---: | ---: | ---: |
| Late fusion | 52–58% (3–5% none) | 43–49% (11–15% none) | 30–36% (21–33% none) |
| Early fusion | 60–77% | 54–71% | 43–65% (2–7% none) |

- With late fusion each line depends on one camera, so a blocked near camera means no
  call.
- Early fusion keeps calling from the other view. That is the practical value of
  "both cameras determine the call".
- Real misses also come in bursts for other reasons (blur at contact, track drops),
  which this independent-frame model does not capture.

## Recommendation

1. **Fix the single-camera estimate first.** It is pure software and helps every
   current user.
   - Store the full camera pose at calibration.
   - Replace the nearest-frame projection with the contact fit.
   - Report "too close to call" or "not callable from this camera" from its
     uncertainty.
2. **Automate calibration:** sub-pixel court-line detection plus the phone's lens
   intrinsics, saving the residuals so their uncertainty can be propagated.
   - Going from 2 to 1 px adds 6–12 points of confident calls with two cameras, and
     7–11 on a single camera's near lines.
   - Slipping to 4 px loses 15–29.
3. **Put the second camera behind the other baseline**, not beside the first.
   - Centred is slightly better than diagonal corners.
   - A mount of about 3 m with about 0.5 m of framing room behind the baseline is
     worth it for seeing over players. It is roughly neutral for early fusion.
4. **Capture at 120 fps if light allows.** It adds 12–25 points for late fusion at
   today's detector quality. 60 fps is the minimum.
   - Lock exposure with a fast shutter against motion blur, fix focus, shoot
     landscape on a stable mount, and calibrate lens distortion.
5. **Start with late fusion.** Each phone analyzes its own video exactly as today. A
   merge step matches bounces by time and combines contact points and uncertainties.
   - Only `tracks.jsonl`-sized data moves: no video, and no frame sync.
   - It still needs the coarse alignment step (event matching), which was not
     simulated.
6. **Then add early fusion with ball-based self-sync.** It adds 7–21 points of
   confident calls and is the only mode that survives one camera being blocked.

### Fit with the codebase

- **`court.py`:** estimate the focal length or read device intrinsics, and solve pose
  with SQPnP. OpenCV's IPPE returned poses hundreds of pixels off for an exactly
  centred camera. Save K, R, t and the click residuals in `calibration.json`.
- **`ball_physics.py`:** keep the hinge detector for candidates and add the contact
  fit. The fit needs care:
  - a physics-aware start (a weak velocity ridge, plus the other side of the flight
    mirrored through a bounce)
  - refinement on true pixel error, with an explicit skid
  - a one-sided speed penalty above 22 m/s, because one camera barely constrains
    velocity along its line of sight
  - a capped drag speed and required convergence

  Without these, single-camera fits run away along the line of sight. `in_out` gains
  a "too close" result when |distance| < 2σ.
- **New merge step** (`vantage fuse RUN_A RUN_B`, or two uploads for one game in the
  web app): coarse event alignment, self-sync, bounce matching, and fusion. Fused
  calls go in `stats.json` / `events.jsonl`, naming the contributing cameras.
- **iOS:** the app only imports video today. Two phones can record separately and
  both files can be analyzed. In-app capture with locked exposure comes later.

## Simulation setup and limits

- **Court and ball:** pickleball court 6.10 × 13.41 m; ball radius 37 mm.
- **True ball physics, varied per shot:**
  - drag coefficient 0.33–0.50
  - spin lift (Magnus) coefficient −0.15 to 0.15
  - vertical restitution 0.55–0.68 and horizontal retention 0.70–0.90
  - a 2–4 ms skid on the floor
- **What the estimators assume:** nominal drag, no spin, and a 3 ms skid.
- **Line rule:** a ball is in if any part of its skid touches the court.
- **Shots:** each lands near a baseline or a left or right sideline, in either half.
  Horizontal speed is 5–16 m/s, descent 8–35°.
- **Cameras:**
  - pinhole, 1920×1080, framed to the whole court plus 25 cm, or more behind the
    near baseline where stated
  - 85–103° of horizontal view, so the 0.5× ultra-wide lens, with distortion
    calibrated out
  - each camera has its own capture phase
  - cameras sit 3.3–3.5 m behind the baselines; many courts have less run-off, and a
    closer camera needs a wider lens than the 0.5× provides
- **Detector:** 1 px centre noise and a 40% base miss rate. Below 8 px across, recall
  falls in proportion to size, to 40% of normal at 3.2 px and below. This is an
  assumption; the 8 px figure is the COCO model's median missed-ball size.
- **Calibration:** four corner clicks with 2 px error; pose by SQPnP with known
  intrinsics. Click error is propagated into each fit's uncertainty.
- **Checks:**
  - With nominal physics and no noise, the fits recover the first touch to within
    3 mm.
  - With the realistic ball and no noise: within 2.6 cm for one camera and 0.7 cm for
    two (`--self-check`).

Not modelled:

- Occlusion beyond the ±50 ms contact-blocking test; burst misses in general.
- Motion-blur bias in the detected centre; balls on other courts; false or missed
  bounce candidates. The bounce is assumed found, and the fits search around the true
  contact time.
- Coarse alignment, drift, and bounce matching between cameras.
- Wind and real lens distortion. The physics ranges above have not been measured for
  pickleballs.
- Detection noise grows for small or blurred balls; here it is a constant 1 px.
- Today's estimate is given the ideal frame, so its real error is somewhat worse.
- 1080p only; 4K halves the pixel size at four times the detection cost.

## Validation plan

1. **Record team-only sessions** with one phone behind each baseline. Add a third phone
   at 240 fps on the court surface, looking along one line, as ground truth; the ITF
   tests Hawk-Eye against a high-speed camera on the surface.
2. **Collect about 300 bounces within 15 cm per instrumented line.** With 0 wrong in n
   confident calls, the 95% upper bound on the error rate is about 3/n, so bounding
   it at 2% needs about 150 confident calls. At late fusion's realistic 52–58%
   confident share, that means about 300 close bounces.
3. **Count close bounces per hour from existing recordings first,** to turn that target
   into sessions.
4. **Rotate the ground-truth phone** across a near baseline, the far baseline and a
   sideline.
5. **Log for every bounce:** frames per side, whether players hid the ball near
   contact, and the reason for every no-call.

## Reproduce

```sh
uv run python pipeline/diagnostics/two_camera_feasibility.py --self-check
uv run python pipeline/diagnostics/two_camera_feasibility.py --geometry
uv run python pipeline/diagnostics/two_camera_feasibility.py --experiments all --trials 300
uv run python pipeline/diagnostics/two_camera_feasibility.py --tables
```

- `--self-check` and `--geometry` take seconds.
- The full run takes about 13 minutes on a 12-core Mac (seed 20261105) and writes
  `output/two-camera-feasibility/summary.json`.
- `--tables` prints both tables for every setting. Coverage (`within_2sigma_pct`),
  wrong confident calls (`confident_wrong`) and the per-distance shares
  (`confident_by_band_pct`) are in the JSON.

External context:

- [PlayReplay](https://pickleball.com/news/pickleball-inc-partners-with-playreplay-to-bring-automated-line-calls-and-ai-tracking-to-the-sport-of-pickleball):
  PPA Tour, multi-camera, ITF Silver.
- [Owl AI](https://thekitchenpickle.com/blogs/news/major-league-pickleball-owl-ai-automatic-line-calls):
  MLP, phone or broadcast video.
- Hawk-Eye: [accuracy](https://spectrum.ieee.org/hawkeye-in-the-crosshairs-at-wimbledon-again),
  [how electronic line calling works](https://platform-static-files.s3.amazonaws.com/HawkEye/document/2016/08/15/1e6cdaa4-2b70-4975-b722-7dca82b8e546/ELC_How_it_Works.pdf).
- [Visual multi-camera sync](https://neurips.cc/virtual/2025/poster/118089).
