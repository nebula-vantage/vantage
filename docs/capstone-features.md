# Vantage — Capstone Feature List

Vantage is the SE490 capstone of team Nebula (Muneeb Farrukh, Faseeh Irfan, Jacob Zhou, Peter Wang, Derek Li). It is an iPhone app that turns video from one phone camera into racket-sport measurements, starting with pickleball: players, ball, paddles, court position and speed. A desktop Python pipeline is the offline reference. The core claim (abstract v2) is reliable measurements from a single phone camera in real time, with low delay, within a phone's processing and memory limits. The method combines visual tracking with court geometry and is evaluated against hand-labelled footage, independent measurements, an offline baseline and stress tests. Fall builds and benchmarks the tracking pipeline: shot and swing speed, landing zones, player movement and placement heat maps. Winter turns measurements into insights: placement and coverage patterns, and how tracking errors change them. The midpoint deck, the latest source, narrows fall to post-match analysis of recorded or imported video plus a real accuracy test on a frozen hand-labelled set (NEB-32). It runs in four steps: (1) freeze the test set and record a baseline; (2) improve tracking by ignoring neighbouring courts, training a custom detector and linking player tracks; (3) connect the iPhone app with a capture app, a live stats overlay if the phone is fast enough, and a session report; (4) court validation, including sustained phone speed. LiDAR and guaranteed live stats move to "Later". On main (fe5b1df), the desktop pipeline runs end to end on heuristics. The iOS app imports from Photos, runs the pickleball-v1 detector and a parity-exact ball tracker on device, and saves runs, but it computes no stats and has no capture or player identity. Two branches are in flight. origin/jacob/rally-detection detects audio hit onsets and uses them for rally grouping and play segments; shots are still net crossings. origin/peter/ios-hit-onsets (open PR #6, which also carries Jacob's two commits) ports onset detection to iOS.

**Sources used:** 4A abstracts v1 and v2 and their revision history (pre-61b2bc4, 16ce77e, f221941, 64509af, 2b214a0, a7f20b9); SE463 D3 domain doc (assumptions, exceptions, variations, domain model); pitch decks (Vantage_Capstone_Pitch, also called Deck B, and Deck A); idea doc; midpoint deck (slides, notes, mockups); GTM draft (slides and notes); waitlist survey CSV (N=34); repo @ fe5b1df plus branches origin/jacob/rally-detection and origin/peter/ios-hit-onsets. Not read: D2 (the AI coaching spec), Linear, any SE490 rubric, and the Google Form's contents (metadata only).

**Keys.**
- Status:
  - `done`
  - `partial`
  - `in-flight`: work exists only on an unmerged branch.
  - `not started`
  - `(ext.)`: outside the repo, so it can't be verified here.
- Term:
  - `fall`, `winter`, `stretch` or `unspecified`.
  - `(inf.)`: the term is inferred; no source schedules the feature.
  - The only stretch goal any source names is technique feedback (INS-07).
- Acceptance: `(proposed)` means the value appears in no source and needs team sign-off. Bullets marked *Implied* are inferred features; the reason is given in the bullet.
- Paths:
  - `pv/` = `pipeline/vantage/`
  - `VM/` = `ios/VantageMobile/`
  - `VK/` = `ios/VantageKit/Sources/VantageKit/`
- Source shorthand:
  - D3 `A#`/`E#`/`V#` = D3 assumption, exception or variation number; DM = D3 domain model.
  - `Pitch s#` = Vantage_Capstone_Pitch slide number.
  - MP = midpoint deck.
  - `Idea §#` = idea doc section.

## At a glance

| Area | # features | done | partial | in-flight | not started |
|---|---|---|---|---|---|
| Capture & input | 13 | 1 | 4 | 0 | 8 |
| Court calibration | 6 | 1 | 1 | 0 | 4 |
| Detection & tracking | 13 | 0 | 8 | 1 | 4 |
| Measurements & stats | 24 | 0 | 9 | 0 | 15 |
| Visualization & playback | 9 | 0 | 3 | 1 | 5 |
| Insights & coaching | 11 | 0 | 0 | 0 | 11 |
| Session/history & sharing | 13 | 1 | 1 | 0 | 11 |
| Real-time/on-device performance | 6 | 0 | 1 | 0 | 5 |
| Accuracy & evaluation | 18 | 0 | 5 | 0 | 13 |
| Platform/ops | 4 | 1 | 1 | 0 | 2 |
| Business/GTM | 8 | 2 | 2 | 0 | 4 |
| **Total** | **125** | **6** | **35** | **2** | **82** |

By term: fall 77, winter 15, stretch 14, unspecified 19. By priority: must 47, should 35, could 43.

**Changes from the draft list.**
- **Split:**
  - CAL-01 → CAL-01a–c
  - CAP-07 → CAP-07a–b
  - TRK-07 → TRK-07a–c
  - MEA-03 → MEA-03a–c
  - MEA-10 → MEA-10a–e (its calibration-projection part moved to CAL-01c)
  - EVAL-01 → EVAL-01a–d
  - SES-06 → SES-06a–d
  - GTM-04 → GTM-04a–c
- **New:** CAP-10–12, TRK-10–11, MEA-17–18, INS-11, SES-10, PERF-06, EVAL-13–15, OPS-04, GTM-06.
- **Status corrections:**
  - partial → not started: TRK-09, EVAL-07, OPS-03, PERF-04, and SES-06 (now the SES-06a–d split).
  - not started → partial: CAL-03.
- **Raised to must:** MEA-02, TRK-06, EVAL-03, EVAL-13.
- **Rewritten:** PERF-03 is now the requirement that the PERF-02 benchmark verifies. CAP-01 and VIS-03 are narrowed so they no longer overlap other features.

---

## 1. Capture & input

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| CAP-01 | Import a saved match video | fall | must | done | (proposed) A 6-min iPhone .MOV imported from Photos finishes on an iPhone with progress; cancel works at any point; the run reopens after relaunch with identical raw detections. |
| CAP-02 | In-app match recording with the iPhone camera | fall | must | not started | (proposed) A 60-min doubles session recorded in-app at 1080p and ≥60 fps is saved as a run with audio and analyzed without a separate import; <1% dropped frames. |
| CAP-03 | Camera setup check before recording | fall | should | not started | (proposed) Blocks or warns when any court corner is out of frame; every setup that passes meets the EVAL-13 gates on the EVAL-07 angle set. |
| CAP-04 | Match setup: format and players | fall | should | not started | (proposed) Singles/doubles sets the expected player count (2/4) for tracking and per-player stats; practice sessions are labelled and listed separately. |
| CAP-05 | Video timing integrity | fall (inf.) | should | partial | (proposed) For 240 fps slow-motion, edited and variable-frame-rate clips, the app uses true capture timestamps or flags the clip before showing speeds; speeds from the original and the converted clip agree within 2%. |
| CAP-06 | Imported file validation | unspecified | could | partial | (proposed) Corrupt, truncated and unsupported-codec files each produce a specific error within 5 s, before inference, with no half-saved run. |
| CAP-07a | Camera permission handling | fall (inf.) | should | not started | (proposed) With camera access denied, the record button explains why, deep-links to Settings and offers import. |
| CAP-07b | Recording interruption recovery | fall (inf.) | should | not started | (proposed) An incoming call mid-recording keeps all footage up to the interruption and marks the run incomplete. |
| CAP-08 | Analyze a full session, one game or a segment | unspecified | could | not started | (proposed) The user trims start and end; only that range is processed and all stats cover only that range. |
| CAP-09 | Non-pickleball footage check | unspecified | could | not started | (proposed) On 5 non-pickleball clips, the app reports that no pickleball play was found and shows no stats. |
| CAP-10 | Multiple camera positions and orientations | fall | should | partial | (proposed) For every placement in the EVAL-07 envelope, portrait and landscape, ball recall, landing error and shot/rally counts meet the EVAL-13 gates; out-of-envelope placements warn. |
| CAP-11 | Indoor and outdoor footage support | fall | should | partial | (proposed) The test set has ≥2 indoor and ≥2 outdoor clips; ball recall and landing error per setting are within 10 points of each other. |
| CAP-12 | Image-quality assessment for recorded and imported footage | unspecified | should | not started | (proposed) On clips degraded with low light, glare and 480p downscaling, the clip or segment is flagged and no stat in it is shown as "estimated". |

- **CAP-01** — Pick a saved video (Photos on iPhone, a file on desktop), normalize it on desktop, show progress and cancel, and create a run; this includes footage recorded by someone else. Analysis turnaround is PERF-01 and stats are MEA-10. *Why:* recorded video is the fall product and the entry path for every evaluation clip. *Status:* iOS PhotosPicker import with progress and cancel (`VM/Features/Games/GamesListView.swift:46`, `VM/Library/RunImporter.swift`). There is no Files picker, and iOS does not normalize frame rate (it uses presentation timestamps). Desktop does ffmpeg constant-frame-rate conversion (`pv/video_input.py`, `pv/main.py:40`). Imports run one at a time with the app in the foreground. No iPhone run of the acceptance test is recorded. *Src:* D3 V2 and updated abstract; Pitch s4; MP s5 mockup; GTM Positioning.
- **CAP-02** — Record a session inside Vantage, with video and audio, saved straight into a run. *Why:* a single phone camera is the core input in every source; midpoint step 3 names "an iPhone capture app" (NEB-44/45/47). *Status:* no camera capture anywhere; iOS only imports. Audio must be kept for TRK-07a. *Src:* v2; D3 V1, DM; Pitch s3; MP notes Next steps, s5 mockup "Record match".
- **CAP-03** — Checklist with a live preview: phone on a stand behind the baseline, all four corners in frame, LiDAR present or not, framing and lighting warnings. *Why:* every stat relies on D3's visible-markings and stable-camera assumptions. It is cheap once CAP-02 exists. *Status:* no setup or preview screen. *Src:* MP notes and s5 mockup; D3 A6–A8; Idea §3 (6–8 ft behind the baseline); Survey 20/34 "easy to set up".
- **CAP-04** — "New game" flow: format (singles, doubles, practice) and opponent before recording. The sport picker offers pickleball only during the capstone. *Why:* it gives TRK-03 and MEA-07 the expected player count and labels the session. *Status:* the games list has import only. *Src:* MP s5 mockups ("New game", "FORMAT Singles · Doubles · Practice", "Serve practice"); D3 V4.
- **CAP-05** — Time-based stats use true elapsed time. Normalize variable frame rate, and detect edits, missing frames, slow motion or retimed playback before showing speeds. *Implied:* the term is inferred from the fall speed stats. *Status:*
  - Desktop converts only non-MP4 input, or any input given `--prepare` (`pv/video_input.py:17-18`, `pv/main.py:40-42`), and times frames as index / fps (`pv/main.py:101`). A variable-frame-rate .mp4 is not detected.
  - iOS uses presentation timestamps (`VK/VideoAnalyzer.swift:62`).
  - Neither surface detects edits or slow motion.

  *Src:* D3 A11, E13; v2 "frame rates".
- **CAP-06** — Reject or flag missing, corrupt, truncated or unsupported files with a clear error before analysis. *Implied.* *Status:*
  - iOS gives specific errors for: no video track, unsupported format, undecodable video, invalid timestamps, early decode stop and zero frames (`VK/VideoAnalyzer.swift:38-85`). It also deletes the partial run (`VM/Library/RunImporter.swift:78-83`).
  - Desktop has equivalent checks (`pv/main.py:56-66, 98-111`).
  - Gaps: only the track and format checks run before inference; there is no up-front codec or duration probe; corrupt and truncated files get the same error.

  *Src:* D3 E3, A3.
- **CAP-07a** — If camera access is denied or revoked, explain why, deep-link to Settings and offer import. *Implied:* the term is inferred from CAP-02. *Status:* no capture yet. *Src:* D3 A2, E1.
- **CAP-07b** — If recording is interrupted by a call, another app, shutdown or camera failure, finalize the file, keep the footage and mark the run incomplete. *Implied:* the term is inferred from CAP-02. *Status:* no capture yet. *Src:* D3 E2.
- **CAP-08** — Choose what to analyze (trim, or pick one game) instead of the whole file. *Why:* faster results; also enables INS-11. *Status:* both surfaces process the whole file. *Src:* D3 V3.
- **CAP-09** — Detect videos with no pickleball play, or a different sport, and say so instead of producing stats. *Implied.* *Status:* desktop `quality.status` can be `insufficient_evidence` (`pv/stats.py:176`), but nothing identifies the sport; iOS has no check. *Src:* D3 A5, E4.
- **CAP-10** — Produce calibrated stats from each supported placement (behind the baseline, corner, side) in portrait or landscape, using placement-specific logic where needed, and warn outside the EVAL-07 envelope. *Why:* the sources disagree on placement, and the net-crossing shot rule fails from behind the baseline. *Status:* clips from three viewpoints run only as parity fixtures. iOS maps portrait orientation (`VK/VideoAnalyzer.swift:21`). Shots depend on net crossings (`pv/stats.py:45`). No accuracy is measured per placement. *Src:* D3 V6; 64509af; MP NEB-31; Pitch s3 notes ("side of the court").
- **CAP-11** — Detection, tracking and calibration work indoors (artificial light, multi-court floors) and outdoors (sun, hard shadows, wind), and the training and test data cover both. *Why:* the pitch baseline clip is indoor and the midpoint 99% clip is outdoor. GTM defers outdoor venues, so outdoor support could quietly drop out. *Status:* the pipeline has run on both kinds of clip (MP technical-progress slides), but there is no per-setting accuracy, and TRK-01's held-out test is a single clip. *Src:* D3 V5; MP technical progress.
- **CAP-12** — Measure exposure, glare, shadow, blur and effective resolution per clip and per segment. Warn, and downgrade the affected stats through MEA-08. *Implied:* D3 names the exception but gives no method. *Why:* CAP-03 covers only in-app recording, and import is today's only input path. *Status:* no quality check on either surface. *Src:* D3 E7, A8.

## 2. Court calibration

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| CAL-01a | Desktop 4-corner court calibration | fall | must | done | (proposed) On every test clip, projected kitchen and centre lines fall within 10 px (at 1080p) of the painted lines. |
| CAL-01b | iOS corner-marking UI | fall | must | not started | (proposed) The user marks 4 corners in under 60 s; saved as calibration.json in the desktop schema. (The idea doc's 60-second figure was for automatic detection, not manual marking.) |
| CAL-01c | VantageKit homography and court projection | fall | must | not started | (proposed) The same corners give the same homography and court coordinates as desktop within 1 cm; projected lines within 10 px on every test clip. |
| CAL-02 | Camera-motion detection and recalibration | unspecified | should | not started | (proposed) When the phone is bumped, the affected frames are flagged or recalibrated within 2 s, and no stat uses a stale homography. |
| CAL-03 | Calibration sanity check | unspecified | could | partial | (proposed) Marks that give an implausible court (aspect-ratio error >10%, projected net line off-frame) are rejected with a re-mark prompt. |
| CAL-04 | Automatic court-line detection | stretch (inf.) | could | not started | Idea doc: "60-second court calibration". (proposed) Detected corners within 0.15 m of manual marks on 80% of test clips. |

- **CAL-01a** — The player clicks four corners; the pipeline fits a homography to the 6.10 × 13.41 m court, caches calibration.json and supports `--recalibrate`. *Why:* court geometry is the spatial reference for every stat and half of the "visual + geometric" contribution. *Status:* done on desktop (`pv/court.py:20, 61`); needs a desktop display. *Src:* DM ("Player --marks--> Court calibration marked corners"); D3 A6; v2; Pitch s5, s8; MP Plan & Scope.
- **CAL-01b** — Mark the corners on iPhone, on a frame from the recording or import, and save them with the run. *Why:* no iPhone stat can be in court units without it, so it blocks EVAL-08. *Status:* only the `CourtCalibration` Codable contract exists (`VK/GameStats.swift:59`). *Src:* as CAL-01a; MP s5 mockup ("All four court corners in frame").
- **CAL-01c** — Port the homography and image-to-court projection into VantageKit. This was the "port calibration projection" part of the old MEA-10. *Why:* the input to MEA-10a–d. *Status:* the contract exists; no homography or projection code. *Src:* as CAL-01a; MP "Connect the app".
- **CAL-02** — Detect when the phone moves, rotates, zooms or falls, and flag or recalibrate the affected frames. *Implied.* *Why:* one bump silently corrupts the rest of the session. *Status:* both surfaces assume a fixed camera. *Src:* D3 A7, E5.
- **CAL-03** — Reject implausible marks (obscured, cropped, or another sport's lines) and ask the player to re-mark. *Implied.* *Status:* desktop `compute_homography` rejects marks that are non-finite, off-frame, crossing or non-convex, cover <0.5% of the frame, or give a singular homography, and the click window prompts a re-mark (`pv/court.py:20-34, 110-115`). There is no check against the court's real shape or other-sport lines, and nothing on iOS. *Src:* D3 E6.
- **CAL-04** — Detect baselines, sidelines and the kitchen line automatically. *Why:* faster setup. Only the earliest idea doc proposes it, as Phase 1; D3's player-marked corners and the repo's 4-click method superseded it. The term is inferred. *Status:* none. *Src:* Idea §2, §3, §7.

## 3. Detection & tracking

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| TRK-01 | Custom pickleball detector (ball, player, paddle) | fall | must | partial | MP: "Target missed balls; re-test the same gates." (proposed) On the frozen set (≥2 clips, none used for tuning), tracked ball recall ≥80% at precision ≥95%, with the same model on desktop and iOS. |
| TRK-02 | Ball tracking through blur, occlusion and misses | fall | must | partial | v2 metric "tracking continuity". (proposed) ≥90% of in-play frames have an observed or interpolated ball within 0.3 m of the label; median continuous segment per rally ≥1 s. |
| TRK-03 | Player detection and per-frame tracking | fall | must | partial | Pitch s6: "4 / 4 players detected and labelled on court". (proposed) Each on-court player detected in ≥95% of frames; median footpoint error ≤0.3 m. |
| TRK-04 | Persistent player identity | fall | must | not started | (proposed) Over a full doubles game, each player keeps one identity in ≥95% of tracked frames (IDF1 ≥0.9), through crossings and end changes. |
| TRK-05 | Restrict analysis to the filmed court | fall | must | partial | (proposed) On multi-court clips, no player or ball outside the calibrated court plus a 2 m margin contributes to any stat. |
| TRK-06 | Paddle detection, tracking and player association | fall | must | partial | (proposed) Paddle detected in ≥80% of labelled contact frames and assigned to the correct player ≥90% of the time. |
| TRK-07a | Audio hit-onset detection | fall | should | in-flight | (proposed) ≥95% of labelled paddle contacts produce an onset within 0.1 s on desktop and iPhone; onsets from other courts are rejected. |
| TRK-07b | Visual paddle-contact detection | fall | should | partial | (proposed) Ball direction changes near a paddle flag ≥85% of labelled contacts with ≤10% false candidates. |
| TRK-07c | Shot events: hit fusion and bounce/net/contact disambiguation | fall | must | not started | GTM: "reach 95%+ shot detection on our hand-labelled test set". (proposed) Recall and precision ≥95% with a 0.1 s matching window. |
| TRK-08 | Rally segmentation | fall | must | partial | (proposed) On ≥3 labelled clips not used for tuning, ≥90% of rallies detected with start and end within 1 s; <5% of in-play time lost. |
| TRK-09 | Geometry-assisted motion estimation | fall | must | not started | v2: the combined approach "improves measurement accuracy over simpler baselines while keeping up with incoming video" (measured in EVAL-05). |
| TRK-10 | Single-camera depth estimation for ball flight | fall | should | not started | (proposed) Against EVAL-03 radar speeds, 3-D speed error ≥30% lower than the 2-D projection; ball height at the net within 0.2 m. |
| TRK-11 | Frame-rate- and resolution-independent tracking | fall | should | partial | (proposed) One clip resampled to 30/60/240 fps and downscaled to 720p gives ball recall within 10 points of native, with landing and speed error within the EVAL-13 gates. |

- **TRK-01** — A detector trained on pickleball footage for ball, players and paddles, with the same weights on desktop and iPhone. *Why:* an explicit midpoint step ("training a custom detector", NEB-34/40/41), and every stat depends on it. *Status:*
  - pickleball-v1 was trained for 21 epochs and was still improving when stopped (`ml/train.py`, `ml/build_dataset.py`, 13 Roboflow datasets). It ships in the app as Core ML.
  - On held-out topcorner60fps, it tracks the ball at 61.6% recall / 96.2% precision, against 39.6% / 97.0% for COCO (`ml/README.md:25-31`). The 0.20 threshold was tuned on that same clip.
  - Player labels and most paddle labels are pseudo-labels. Desktop still defaults to `yolo26n.pt` (`pv/config.py:5`).

  *Src:* MP notes, Next steps; Pitch s5.
- **TRK-02** — Keep the small, fast ball tracked through blur, short occlusion and missed detections, using velocity prediction, short-loss retention, gap interpolation and static-clutter suppression. *Why:* it drives speed, landing, heat maps, shots and rallies, and v2 names blur and occlusion as core challenges. *Status:*
  - Desktop tracker interpolates gaps up to 0.20 s, with smoothing and coasting (`pv/ball_tracker.py`, `pv/ball_physics.py:21`).
  - The Swift port matches Python exactly on 2,306 frames (`VK/BallTracker.swift`, `VK/BallTrajectory.swift`) but lacks display smoothing and coasting.
  - Tracks fragment (288 identities on videoplayback.mp4). Held-out recall is 61.6%.

  *Src:* v2; v1; D3 E8; Pitch s6; MP technical progress.
- **TRK-03** — Detect and track every on-court player in each frame (2 in singles, 4 in doubles). *Why:* the basis for movement, coverage and per-player stats. *Status:* desktop assigns ByteTrack per-track IDs (`pv/detector.py:30`, `pv/stats.py:122`), but spectators and other-court players count as players. iOS draws raw boxes with no IDs (`VM/Playback/DetectionOverlay.swift`). *Src:* v2; D3 A10; Pitch s6; MP demo overlay "Players: 4".
- **TRK-04** — Keep each player's identity for the whole match, through crossings, similar clothing and end changes, and flag when identity becomes ambiguous. *Why:* an explicit midpoint step ("linking player tracks"); without it there are no per-player stats. *Status:* desktop per-track IDs fragment, and iOS has none. The app says "Per-player stats need the app to tell players apart". *Src:* MP notes Next steps; D3 A12, E10.
- **TRK-05** — Ignore neighbouring courts, spectators and stray balls; only the calibrated court feeds the stats. *Why:* an explicit midpoint step, and the test and pilot venues are multi-court clubs. *Status:*
  - Main drops bounces more than 2 m outside the court (`pv/ball_physics.py:144-149`) and nulls player court positions beyond 2 m (`pv/motion_stream.py:31-37`).
  - Every person still counts as a player track (`pv/stats.py:122-159`), and balls on adjacent courts still feed speed and crossings.
  - In flight: the rally branch rejects audio rallies with <15% tracked-ball frames. iOS has nothing.

  *Src:* MP notes; D3 E11.
- **TRK-06** — Detect each paddle, track it, and associate it with its player. Raised to must. *Why:* swing speed (MEA-02, a fall commitment) depends on it, and v2 names rackets as one of the three tracked objects. *Status:*
  - Paddle boxes come from COCO's tennis-racket class (the desktop default) and from pickleball-v1's paddle class, which was trained on pseudo-labels. iOS draws them (`VM/Playback/DetectionOverlay.swift:59-60`).
  - The 94/130 paddle agreement figure (Core ML vs PyTorch) is for COCO yolo26n; no such figure exists for pickleball-v1.
  - Paddles get no IDs (`pv/detector.py:65-67`) and are not associated with a player.

  *Src:* v2; Pitch s5 notes; D3 E9.
- **TRK-07a** — Detect paddle-hit sounds as timed onsets on desktop and iPhone. *Why:* D3 lists audio as an input, and it works from behind the baseline, where net crossings fail. *Status:* in flight.
  - origin/jacob/rally-detection adds `pv/audio.py` but uses the onsets only to group rallies.
  - PR #6 ports detection to iOS (`VK/HitOnsets.swift`). It saves hits.json and shows HIT only in debug playback. It matched 18/18 desktop hits on a Mac; it has not run on an iPhone.

  *Src:* DM "Session video images / audio"; branch commits.
- **TRK-07b** — Flag a contact when the ball changes direction near a paddle. *Implied:* the sources name no detection method. *Why:* a visual signal for noisy venues and an input to fusion. *Status:* desktop candidates are flagged unverified (`pv/motion_stream.py:80-104`) and are not evaluated; iOS has nothing. *Src:* Pitch s5; D3 E12.
- **TRK-07c** — Fuse audio and visual candidates into the official shot events, and tell contacts apart from bounces, net contact and other movement. *Why:* GTM's headline 95%+ bar; shot counts and per-shot speed and placement build on it. *Status:* main counts net crossings as shots (`pv/stats.py:45`), which almost never fire from behind the baseline, and both branches still set `shot_count` to `len(crossings)`. Bounces near paddles are suppressed (`pv/ball_physics.py:139`). There is no labelled shot evaluation. *Src:* GTM Positioning; D3 E12; Pitch s4; MP demo overlay "Shots (est.): 0".
- **TRK-08** — Find each rally's start and end. Rallies are the unit for counts and they drive downtime removal. *Why:* a core D3 function, and the pitch commits rally counts to fall. *Status:*
  - Main keeps observed-ball spans that contain at least one net crossing. It splits rallies on ≥2 s of ball loss or of inactivity at ≤1 km/h (`pv/stats.py:79-119`). This rule has never been evaluated.
  - On the rally branch (which ships only inside PR #6), an intermediate rule kept 0/3 labelled rallies on court1-a (commit 73c8d3d). The audio rule replacing it (≥3 hits ≤4 s apart) kept 3/3, but its thresholds were tuned on that same clip.

  *Src:* D3 abstract; Pitch s4; MP notes.
- **TRK-09** — Use court geometry inside the motion estimate, for example to constrain ball flight to the court plane and net or to correct tracks, rather than only projecting positions afterwards. This is v2's stated contribution, and EVAL-05 tests it. *Status:* not started. Tracking is image-plane only (`pv/ball_tracker.py`, `pv/detector.py`). The homography only projects finished tracks (`pv/ball_physics.py:37-64`, `pv/motion_stream.py:32`) and gates the derived values (for example speeds above 180 km/h, `pv/stats.py:14-15`). *Src:* v2; pre-61b2bc4 "probabilistic motion estimation".
- **TRK-10** — Estimate the ball's height and 3-D trajectory from one camera, for example by fitting a ballistic arc between hit and bounce or using the known net height and court plane. *Implied:* the sources name limited depth as a core challenge but give no method; it is likely built inside TRK-09. It is separate from the cut LiDAR fusion. *Why:* MEA-01's radar target can't be met with a 2-D floor projection. *Status:* speed is a court-plane projection (`pv/stats.py:18`, `pv/motion_stream.py:107`), and nothing estimates height. *Src:* v2; v1; a7f20b9; Pitch s7 "Uncertain depth".
- **TRK-11** — Scale every tracker, bounce and rally parameter with true frame time and image size, so one configuration works from 30 to 240 fps and from 720p to 4K. This includes how the detector's input size is chosen so small balls stay detectable. *Why:* the drafts require handling different frame rates and video quality, and v2 evaluates across them. *Status:* desktop parameters are in seconds and image diagonals (`pv/config.py:15-93`), mirrored in Swift; there is no accuracy comparison across rates or resolutions. *Src:* 64509af; 2b214a0; v1; MP notes.

## 4. Measurements & stats

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| MEA-01 | Shot (ball) speed per shot | fall | must | partial | (proposed) Per-shot speed within 10% of a radar gun (EVAL-03) on ≥30 shots from ≥2 angles. |
| MEA-02 | Swing (paddle) speed | fall | must | not started | (proposed) Within 15% of a hand-measured high-speed-video reference on ≥20 swings. |
| MEA-03a | Bounce detection and landing position | fall | must | partial | (proposed) ≥80% of labelled bounces detected with court-plane error ≤0.5 m. |
| MEA-03b | Landing-zone classification | fall | must | not started | 2b214a0 metric: "landing zone accuracy". (proposed) Zone (kitchen, mid, deep) correct ≥85% of the time. |
| MEA-03c | IN/OUT line calls with a "too close to call" state | fall | should | partial | (proposed) Agrees with labels ≥90%, excluding calls within 0.10 m of a line, which show as close calls. |
| MEA-04 | Player court position and movement paths | fall | must | partial | v2 metric "position ... error". (proposed) Median footpoint error ≤0.3 m against labels. |
| MEA-05 | Movement metrics (distance, sprint, coverage, back to centre) | fall | should | partial | (proposed) Distance within 10% of a measured walked path; court-covered % reported per player per game. |
| MEA-06 | Rally and shot counts, rally-length stats | fall | must | partial | (proposed) On labelled clips, rally count exact and shot count within 5%; rallies cut off by the recording are flagged and excluded from averages. |
| MEA-07 | Per-player stats and "this is me" selection | fall | should | not started | (proposed) The user picks themselves once per session; ≥95% of shots and movement attributed to the right person on labelled doubles. |
| MEA-08 | Measurement quality and per-stat availability | fall | should | partial | (proposed) Every stat shows available, estimated or unavailable from documented thresholds; nothing is shown below threshold. |
| MEA-09 | Structured event log and stats schema | fall | should | partial | (proposed) iOS and desktop write the same stats.json and events.jsonl schema for a clip, and the GameStats decoder reads both. |
| MEA-10a | iOS rally and shot computation | fall | must | not started | (proposed) Counts on iPhone equal the desktop stats.json exactly for every test clip. |
| MEA-10b | iOS bounce, landing, zone and IN/OUT computation | fall | must | not started | (proposed) Landing positions within 1 cm of desktop, and identical zones and IN/OUT, on every test clip. |
| MEA-10c | iOS speed computation | fall | must | not started | (proposed) Per-shot and average speeds within 1% of desktop. |
| MEA-10d | iOS per-player movement | fall | must | not started | (proposed) Per-player positions and distance within 1% of desktop. |
| MEA-10e | iOS writes stats.json; Games list and Game Detail show it | fall | must | partial | (proposed) After on-device analysis, every tile shows a value or an explicit unavailable state, with no manual file copying. |
| MEA-11 | Shot type classification | stretch (inf.) | could | not started | (proposed) ≥80% accuracy on ≥200 labelled shots. |
| MEA-12 | Serve and return metrics | stretch (inf.) | could | not started | (proposed) Serve in/out agrees with labels ≥90%; return-depth class ≥85%. |
| MEA-13 | Point outcomes and automatic scorekeeping | stretch (inf.) | could | not started | (proposed) Automatic score matches the true score in ≥90% of games. |
| MEA-14 | Shot height and net clearance | stretch (inf.) | could | not started | (proposed) Net clearance within 0.15 m of a reference. |
| MEA-15 | Ball spin estimation | stretch (inf.) | could | not started | (proposed) Spin class (topspin, flat, slice) correct ≥75% on 240 fps labelled clips. |
| MEA-16 | Reaction time to the opponent's shot | stretch (inf.) | could | not started | (proposed) Within 0.1 s of hand labels on 50 shots. |
| MEA-17 | Out-of-frame action handling | fall | could | not started | (proposed) No swing speed or attributed shot is reported for off-frame contacts; movement paths show explicit gaps. |
| MEA-18 | Manual match score entry | fall | could | not started | (proposed) Scores entered after a session appear on the Games row and summary header and persist across relaunch. |

- **MEA-01** — Ball speed for each shot, from the ball track and court geometry: per-shot, top and average, in km/h or mph. *Why:* a fall target in v1, v2 and the pitch, and listed (without a term) in D3 and the midpoint mockups; survey 21/34. *Status:*
  - Desktop reports a time-weighted `avg_ball_speed_kmh` and a per-frame projected km/h (`pv/stats.py:18`, `pv/motion_stream.py:107`). This is a 2-D floor projection, not true flight speed. There is no per-shot or top speed, and nothing is validated.
  - It needs TRK-07c for per-shot values and TRK-10 for true speed. The iOS tile always shows "—".

  *Src:* v2; D3 abstract; Pitch s4; MP mockup "TOP SHOT 141 km/h"; Survey.
- **MEA-02** — How fast each player swings the paddle, and their top swing speed. Raised to must. *Why:* the pitch notes call it part of "the feature set we're committing to this fall", and v2 and D3 list it. The midpoint plan names no individual statistic and keeps "one-camera stats". It is the riskiest stat because it depends on TRK-06. Survey 26/34. *Status:* neither surface computes it, and the iOS app has no swing tile; "Top swing" exists only in the midpoint mockup. *Src:* v2; D3 abstract; Pitch s4 and notes; MP s6 mockup; Survey.
- **MEA-03a** — Detect bounces, tell them apart from contacts, and project them onto the court as landing spots. *Why:* a fall target in v1, v2 and the pitch, and the input to heat maps and winter placement patterns; survey 30/34. *Status:* desktop finds bounces with a hinge fit, suppresses candidates near paddles and rejects any more than 2 m outside the court (`pv/ball_physics.py:86-149`). None of this is evaluated. The iOS CourtDiagram is empty. *Src:* v2; a7f20b9; D3 abstract; Pitch s4; MP notes; Survey.
- **MEA-03b** — Classify each landing into a zone (kitchen, mid, deep). *Why:* v2 names "landing zones", and they feed the INS-01 patterns. *Status:* desktop draws kitchen lines on the heatmap (`pv/heatmap.py:83-86`) but classifies no zones; iOS has nothing. *Src:* v2; 2b214a0; Pitch s4.
- **MEA-03c** — An estimated in/out call for each bounce, with a "too close to call" state near the lines. *Implied:* no design source asks for line calls; the basis is the repo's existing IN/OUT labels and the idea doc's serve in-percentage. *Status:* desktop labels IN/OUT (est.) with a near-boundary flag (`pv/ball_physics.py:86-100`), not evaluated. iOS In/Out tiles and legend stay empty. *Src:* Idea §5; repo.
- **MEA-04** — Each player's court position over time and the path they trace. *Why:* a fall target in v2 and the pitch, and the basis for coverage insights. *Status:* desktop writes per-frame player footpoint `court_m` to the `--stream` NDJSON (`pv/motion_stream.py`). There are no per-player paths because IDs fragment (TRK-04), and iOS has nothing. *Src:* v2; a7f20b9; D3 abstract; Pitch s4.
- **MEA-05** — Per-player distance, top sprint speed, % of own half covered, and average time back to centre after a shot. *Why:* the midpoint Movement tab; D3 "court coverage"; survey 20/34. *Status:* desktop computes partial distance per track ID with jump rejection (`pv/motion_stream.py:43`). It is unvalidated and fragmented by ID, and the other metrics don't exist. iOS Distance is hard-coded to "—". *Src:* MP Movement mockup; D3 abstract; Survey.
- **MEA-06** — Count rallies and shots, and report average rally length in shots, the longest rally and the distribution. Rallies cut off at the start or end of the recording are flagged. *Why:* committed fall stats that replace hand logging; survey 12/34 "Count the shots in each point". *Status:*
  - Desktop counts with net crossings (`pv/stats.py:45, 79`).
  - Audio rally counting is in flight, but on that branch shot count, shots per rally and longest rally still use net crossings (branch `pv/stats.py:174-177`).
  - The iOS tiles are wired but show "—" (`VM/Features/GameDetail/GameDetailView.swift:68`).

  *Src:* D3 abstract, E15; Pitch s4; MP mockup; Idea §5; Survey.
- **MEA-07** — Attribute stats to individual players. The user picks which tracked person is them and switches between self, opponent and everyone. *Why:* the GTM wedge ("live per-player stats") and the app's player toggle. It is a should because the capstone evaluation is about measurement accuracy. Needs TRK-04. *Status:* iOS has only a UI shell: the toggle changes nothing and the per-player tiles are hard-coded "—" (`VM/Features/GameDetail/GameDetailView.swift:50`, `PlayerToggle.swift`). *Src:* D3 V7, A13, E14; GTM Positioning; MP mockup "You | A. Chen".
- **MEA-08** — Report how much of the session was tracked and give each stat a state (estimated, limited evidence or unavailable); show partial results instead of failing. *Why:* D3 names "quality" as an output (E17); the midpoint says "Coverage isn't accuracy"; GTM claims only what the prototype does. *Status:* desktop `quality.status` carries warnings and coverage fractions (`pv/stats.py:176`), and the heatmap shows a LIMITED EVIDENCE label. iOS shows only a "% of frames tracked" badge. *Src:* DM; D3 E17; Pitch s6 overlay; MP mockup and Plan & Scope.
- **MEA-09** — A machine-readable event log (hits, bounces, rallies), tracks and session stats, with provenance and re-analysis from cached tracks, shared by both surfaces. *Implied:* the only source is the midpoint "event log" note; the schema and provenance are repo design choices that MEA-10 parity and EVAL-02 need. *Status:* done on desktop: stats.json schema 2, events.jsonl and tracks.jsonl with SHA-256 provenance, and `--reanalyze` (`pv/stats.py:162-176`, `pv/tracking_cache.py:26`). iOS writes only detections.jsonl; hits.json is in PR #6. *Src:* MP "Added Oct 1: heat map, event log".
- **MEA-10a** — Port rally and shot computation into VantageKit, consuming the TRK-07c and TRK-08 outputs, including HitOnsets. *Why:* an explicit midpoint step ("Feed measured outputs into the stats screens", NEB-44/45/47), and the pitch says everything runs on the phone. *Status:* `GameStats.compute` exists only as a comment (`VK/GameStats.swift:16-17`). *Src:* MP Next steps; Pitch s7.
- **MEA-10b** — Port bounce, landing, zone and IN/OUT computation to VantageKit. Needs CAL-01c and MEA-03a/b. *Status:* not started. *Src:* as MEA-10a.
- **MEA-10c** — Port speed computation to VantageKit. Needs CAL-01c and MEA-01. *Status:* not started. *Src:* as MEA-10a.
- **MEA-10d** — Port per-player positions, paths and distance to VantageKit. Needs CAL-01c, TRK-04 and MEA-04. *Status:* not started. *Src:* as MEA-10a.
- **MEA-10e** — Write stats.json on the iPhone after analysis, and show it in the Games list and Game Detail. *Status:* partial; the contract and UI exist, the engine does not.
  - Exists: the Codable contract (matching desktop schema 2), the stats.json loader (`VM/Library/RunStore.swift:72-91`) and the tile wiring (`GameDetailView.swift:68-114`, `GameRow.swift:10-16`).
  - The only stat computed on the phone is the tracked-ball fraction (`VK/VideoAnalyzer.swift:79-80`). The tiles stay blank unless a desktop stats.json is copied into the run folder by hand. `GameStats.sample` is used only in `#Preview`.

  *Src:* as MEA-10a.
- **MEA-11** — Label each shot as a dink, drive, drop or serve, and show the shot mix. *Why:* survey 28/34. The idea doc listed it as MVP, but no later source kept it; the term is inferred. *Status:* none. *Src:* Idea §4; Survey.
- **MEA-12** — Serve in-percentage, serve speed, and return depth (deep vs shallow); builds on MEA-01 and MEA-03. The term is inferred. *Status:* none. *Src:* Idea §5; MP Profile mockup "BEST SERVE 141 km/h"; Survey 26/34.
- **MEA-13** — How each point ended, an automatic score, and win/loss breakdowns. Manual score entry is MEA-18. The term is inferred. *Status:* none. *Src:* Idea §3, §5; Survey 16/34.
- **MEA-14** — How high shots travel and how much they clear the net by. *Implied:* survey only; needs TRK-10. The term is inferred. *Status:* none. *Src:* Survey 27/34.
- **MEA-15** — How much spin each shot carries. *Implied:* survey only, and very hard to measure from one camera. The term is inferred. *Status:* none. *Src:* Survey 25/34.
- **MEA-16** — Time from the opponent's contact to the player's first movement. *Implied:* survey only; related to MEA-05's back-to-centre time. The term is inferred. *Status:* none. *Src:* Survey 27/34.
- **MEA-17** — When a player or paddle is out of frame during a hit, swing or movement, mark the affected per-shot and per-player stats as unavailable for that span and show the gap. *Implied.* *Why:* avoids silent interpolation. *Status:* none. *Src:* D3 E9, A10.
- **MEA-18** — Let the player enter or edit game scores after a session, so the Games list and summary show the result. *Implied:* the mockups show scores, but no source says how they are obtained. *Status:* none. *Src:* MP s5–6 mockups ("6-4 3-6 7-5").

## 5. Visualization & playback

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| VIS-01 | Shot-placement heat map and landing-spot view | fall | must | partial | (proposed) The Court tab toggles landing spots and heat map from the session's bounces, on a fixed scale so two sessions compare side by side. |
| VIS-02 | Movement path and court-coverage views | fall | must | not started | (proposed) The Movement tab draws each identity-linked player's path for any rally or the session, plus a session coverage map. |
| VIS-03 | Session report: shell, Overview and Shots tabs | fall | must | partial | GTM pilot default: "Match reports delivered within 24 hours". (proposed) Wherever evidence suffices, the Overview shows rallies, shots, top and average speed with no placeholder dashes; any single measurement can be opened on its own. |
| VIS-04 | Annotated replay with tracking and stats overlay | fall | should | partial | (proposed) Any rally replays on iPhone at 1×, 0.5× or 0.25× with ball trail, landing markers and running shot and rally counts. |
| VIS-05 | Condensed playback with downtime removed | unspecified | should | in-flight | Idea doc example: "Reduces a 45-minute court session into 12 minutes of active play". (proposed) <5% of rally time lost and ≥80% of downtime removed on labelled clips. |
| VIS-06 | Highlight clips and venue clip pack | fall | could | not started | (proposed) Each pilot session gets a clip pack of opted-in players only, delivered with the 24-hour report. |
| VIS-07 | Swing and movement trace lines on video | stretch (inf.) | could | not started | (proposed) A player-path and swing-path overlay can be toggled during replay. |
| VIS-08 | Side-by-side video comparison | stretch (inf.) | could | not started | (proposed) Two rallies play in sync side by side. |
| VIS-09 | Top-down animated rally replay | stretch (inf.) | could | not started | (proposed) Any rally animates on the court diagram in sync with the video. |

- **VIS-01** — A top-down court diagram that switches between individual landing spots and a density heat map, filterable by player. *Why:* placement heat maps are a fall output in v1, v2 and the pitch, and appear in D3 and the midpoint mockups. *Status:* desktop renders a heatmap PNG with dots and a LIMITED EVIDENCE label (`pv/heatmap.py:45`). It is scaled to its own peak, so sessions can't be compared. On iOS, the CourtDiagram is an empty court with a static In/Out/Close-call legend (`GameDetailView.swift:94-110`); a heat-map overlay is only planned, in a code comment (`VM/DesignSystem/Components/CourtDiagram.swift:6`). *Src:* v2; D3 V9; Pitch s4; MP s3, s6 mockups.
- **VIS-02** — Draw each selected player's movement path on the court diagram, with an aggregate coverage view. *Why:* a fall output in the pitch, also listed in a7f20b9 and D3. Needs TRK-04 and MEA-04. *Status:* desktop has no path plot (positions exist only in the `--stream` NDJSON), and iOS has no Movement tab. *Src:* D3 V10 and abstract; Pitch s4; MP notes.
- **VIS-03** — The per-session report shell, with two tabs. Overview shows score, video card, frames-tracked badge, per-player shot and speed tiles, rally tiles and a rally-length chart. Shots is the second tab. It also covers viewing one measurement alone (D3 V8). The Court tab is VIS-01 and the Movement tab is VIS-02. *Why:* "a session report" is a midpoint fall step; it is the pilots' deliverable and the demo. *Status:* iOS Game Detail shows the video, a tracked-% badge and "—" tiles, with no tabs (`VM/Features/GameDetail/GameDetailView.swift`, `GameVideoCard.swift`); desktop outputs files only. *Src:* D3 abstract, V8; Pitch s4; MP notes, s6; GTM Sales process.
- **VIS-04** — Replay with player boxes, ball trail, IN/OUT markers and running counts, at normal and slow speeds. *Why:* in the pitch prototype and the midpoint overview; survey 25/34 normal video, 23/34 slow motion; mostly built already. *Status:* desktop writes annotated.mp4 without audio (`pv/visualize.py:112`). iOS overlays players, ball, trail and paddles (`VM/Playback/OverlayVideo.swift`, `DetectionOverlay.swift`), but slow motion and frame stepping exist only in the debug inspector (`VM/Playback/PlayerView.swift`), and there is no stats overlay. *Src:* Pitch s6; MP s6 mockup; Survey.
- **VIS-05** — Cut the dead time between rallies so the player reviews only active play. *Why:* an explicit D3 function; needs TRK-08. *Status:* in flight on origin/jacob/rally-detection, which writes `play_segments` (rallies padded 1 s and merged) to stats.json and marks "Play: dead ball (cut)" on the annotated video. On court1-a it loses 0.4 s of play and keeps 10.4 of 20 s of downtime. There is no cut-video export, and nothing on iOS. *Src:* D3 abstract; Idea §4.
- **VIS-06** — Short clips of notable shots and mistakes; for venue pilots, a clip pack of the players who opted in. *Why:* a GTM pilot deliverable (Nov 18–Dec 4), not part of the capstone evaluation; survey 25/34. Needs TRK-08, VIS-05 and SES-06a. *Status:* none. *Src:* GTM Sales process; Idea §4; Survey.
- **VIS-07** — Lines on the video that trace the swing and the player's movement. *Implied:* survey only. The term is inferred. *Status:* only a fading ball trail exists, on both surfaces. *Src:* Survey 22/34.
- **VIS-08** — Two clips playing side by side to compare play. *Implied:* survey only. The term is inferred. *Status:* none. *Src:* Survey 16/34.
- **VIS-09** — An animated bird's-eye replay of a rally. *Implied:* survey only, and the least-chosen viewing option. The term is inferred. The desktop court-plane stream could drive it. *Status:* none. *Src:* Survey 12/34.

## 6. Insights & coaching

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| INS-01 | Shot-placement pattern detection | winter | must | not started | (proposed) Patterns agree with a coach's reading ≥80% on labelled sessions; each reports its supporting shot count and %. |
| INS-02 | Court-coverage pattern detection | winter | must | not started | (proposed) Coverage gaps agree with a coach ≥80%; changes reported across ≥2 sessions. |
| INS-03 | AI coach explanations of repeated patterns | winter (inf.) | should | not started | (proposed) Every explanation cites its evidence (shot count, zone, %); players and coaches rate clarity ≥4/5. |
| INS-04 | Coaching advice and practice drills per weakness | winter (inf.) | should | not started | (proposed) Each weakness links to ≥1 drill; a coach panel judges ≥80% of recommendations appropriate. |
| INS-05 | Evidence gating and grounding for insights | winter (inf.) | should | not started | (proposed) Below the EVAL-09 threshold no pattern or drill is produced; a review of 20 sessions finds no contradictory or ungrounded recommendations. |
| INS-06 | Drill suitability from the player profile | winter (inf.) | could | not started | (proposed) No drill is recommended that needs a partner or equipment the player marked unavailable. |
| INS-07 | Technique feedback (stroke mechanics) | stretch (winter) | could | not started | (proposed) Flagged faults agree with a coach ≥75% on a labelled technique set. |
| INS-08 | Error and shot-outcome analysis | stretch (inf.) | could | not started | (proposed) Error type agrees with labels ≥80% on 100 labelled errors. |
| INS-09 | Kitchen and transition-game metrics | stretch (inf.) | could | not started | (proposed) Kitchen-line time within 5 percentage points of hand labels. |
| INS-10 | Doubles partner-coordination analysis | stretch (inf.) | could | not started | (proposed) Partner spacing reported per rally; gap events agree with a coach ≥75%. |
| INS-11 | In-session quick feedback between games | winter (inf.) | could | not started | (proposed) Within 2 min of a game ending, a one-screen recap and ≤2 evidence-cited tips; none below the INS-05 threshold. |

- **INS-01** — Find recurring placement patterns within and across sessions, such as shots repeatedly landing short or in the same zone, and report the evidence behind each. *Why:* the winter claim in v2. Needs MEA-03a/b and MEA-07. *Status:* there is no insights layer. *Src:* v2; v1 ("shots repeatedly landing short"); D3 abstract; Idea §4.
- **INS-02** — Find recurring coverage patterns, such as areas left open and positioning habits, and how they change across sessions. *Why:* the winter claim in v2 and v1. Needs MEA-04, MEA-05 and TRK-04. *Status:* none. *Src:* v2; v1; D3 abstract; Survey 28/34.
- **INS-03** — An AI coach turns the session analysis into short, plain-language explanations of repeated patterns, delivered after play. *Why:* D3 (the SE463 requirements deliverable, Oct 30) adds an AI coach. The survey asks for simple tips (23/34), mostly later (27/34) or after play (25/34). Whether D3's additions are SE490 capstone scope is unconfirmed; v2's evaluated claim is the patterns themselves. *Status:* none; the coaching spec is in D2, which was not read. *Src:* D3 abstract, DM; Survey.
- **INS-04** — Identify weaknesses and recommend advice and drills, one area or one weakness at a time. *Why:* in D3 and v1 ("something specific to focus on in practice"), and tied for the top survey request (30/34); v2 stops at patterns. *Status:* none. *Src:* D3 abstract, V11, V12; v1; Survey.
- **INS-05** — Report a pattern or recommendation only with enough evidence; each must trace back to metrics, and none may contradict another. *Implied.* *Why:* protects players from bad advice; the threshold comes from EVAL-09. *Status:* none; desktop `quality.status` is a starting signal. *Src:* D3 E16, A15, E20; f221941.
- **INS-06** — Take skill, goals, physical ability, equipment, partner and court space into account so drills are doable. *Implied:* no profile input is described. *Status:* none. *Src:* D3 A16, E21.
- **INS-07** — Feedback on contact point relative to the body, swing path, stance and footwork; likely needs pose estimation and labelled examples of good technique. *Why:* the only stretch goal any source names (pitch, winter); survey 26–28/34. *Status:* no pose estimation; the pipeline outputs boxes only. *Src:* Pitch s4 notes, s8; Survey.
- **INS-08** — Forced vs unforced errors, net vs out, which shots miss and which win, and how consistently a shot is repeated. Needs MEA-11 and MEA-13. The idea doc listed forced/unforced errors as MVP, but no later source kept it; the term is inferred. *Status:* none. *Src:* Idea §4; Survey 27/34, 22/34.
- **INS-09** — Third-shot drop success, speed-up win rate, time at the kitchen line, and kitchen entry speed. Kitchen-line time can be derived from MEA-04. The term is inferred. *Status:* none. *Src:* Idea §2, §5.
- **INS-10** — How doubles partners move together: spacing, shifting together and gaps. *Implied:* survey only; needs TRK-04. The term is inferred. *Status:* none. *Src:* Survey 28/34.
- **INS-11** — A short recap and one or two tips after each game within a session. *Implied:* survey only; D3 frames coaching as after play. Needs CAP-08, PERF-01 or PERF-06, and INS-05. *Status:* none. *Src:* survey tip timing (between games 16/34, while playing 7/34, between points 3/34); "I get tips while playing" 15/34.

## 7. Session/history & sharing

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| SES-01 | Saved sessions library | fall | must | done | (proposed) Saved runs persist across relaunch and app updates with identical raw detections; tracking is reproducible for a fixed tracker version. |
| SES-02 | Saved-data integrity | unspecified | could | partial | (proposed) A run with a missing or modified video or detections file shows as broken with a remove option and never opens with mismatched overlays. |
| SES-03 | Two-session comparison | winter (inf.) | should | not started | (proposed) The user picks two sessions and sees each stat side by side with the difference, including a fixed-scale heat-map comparison. |
| SES-04 | Multi-session progress trends | winter (inf.) | should | not started | (proposed) For any stat, a trend across ≥5 sessions, showing each session's evidence quality. |
| SES-05 | Share and export session reports | unspecified | could | not started | (proposed) A report exports as a PDF or image that opens on a stock phone; a failed share shows the reason. |
| SES-06a | Pilot and data-collection consent and deletion process | fall | must | not started | (proposed) All pilot and test footage has a logged consent record; any participant's footage is deleted within 48 h of a request. |
| SES-06b | In-app video visibility and privacy settings | unspecified | should | not started | (proposed) Runs are private by default; the user controls whether they are visible outside the app (Files app, sharing). |
| SES-06c | Share safeguards (preview, confirm recipient) | unspecified | could | not started | (proposed) Every share previews its contents and confirms the recipient before sending. |
| SES-06d | Protect other people in the footage | unspecified | could | not started | (proposed) People who have not authorized sharing are blurred or excluded from shared clips. |
| SES-07 | Profile and preferences | unspecified | could | not started | (proposed) Chosen units and dominant hand apply on every stats screen and persist across launches. |
| SES-08 | "Cool facts" comparisons with friends | unspecified | could | not started | The team must define the comparison metric first. |
| SES-09 | Share match stats with the other three players | unspecified | could | not started | (proposed) Each other player opens and claims only their own stats from a share link. |
| SES-10 | User accounts and sign-in | unspecified | could | not started | (proposed) Signing in restores the profile and sessions on a second device; without signing in the app still works fully offline. |

- **SES-01** — Save each session's video and analysis, then browse, reopen and delete sessions. *Why:* a core D3 function and the midpoint's "Record. Review. Repeat."; a prerequisite for cross-session insights. *Status:* done on iOS.
  - Each run is saved to `Documents/Runs/<id>/` with its video, detections.jsonl, thumbnail and run.json (`VM/Library/RunStore.swift`, `AnalysisRun.swift`).
  - Delete is in the context menu; the README still says swipe.
  - Tracking is recomputed when a run opens (`VK/DetectionTimeline.swift:30`), so a tracker change in an app update can make overlays disagree with the list's tracked % (`VM/Features/Games/GameRow.swift:14`). No stats are saved.

  *Src:* D3 abstract, A18; MP s5.
- **SES-02** — Detect saved sessions whose video or analysis was deleted, changed or no longer matches, and flag them instead of showing wrong data. *Implied.* *Status:*
  - At launch, iOS deletes run folders without a valid run.json (`VM/Library/RunStore.swift:33-36`). It logs and ignores a bad or newer-schema stats.json (`:72-91`).
  - Desktop validates its tracking cache before `--reanalyze` (`pv/tracking_cache.py:26-55`).
  - iOS never checks that the video and detections still match. A missing detections file silently drops the overlays (`GameVideoCard.swift:84-87`).

  *Src:* D3 E19.
- **SES-03** — Compare a player's stats between two sessions, all stats or one chosen measurement. *Why:* in D3, the pitch (Deck B) and a7f20b9; the term is inferred from v1's winter "across sessions" work. Needs cross-session identity (SES-10 or another method), fixed-scale heat maps (VIS-01) and EVAL-15. *Status:* none. *Src:* D3 V14, V15; Pitch s3; a7f20b9.
- **SES-04** — Trend charts across several sessions, plus lifetime totals. *Why:* in D3, and tied for the top survey request (30/34 "Show if I am improving over time"). The term is inferred. *Status:* none. *Src:* D3 V14 and abstract; Pitch s3 notes; Survey.
- **SES-05** — Share or export selected results or the full report, with or without coaching content. *Why:* D3 variations. The midpoint mockups put a share control on every session screen, so analysis-only sharing could move to fall. *Status:* the only export is a developer-only ShareLink for detections.jsonl in the debug inspector (`VM/Playback/PlayerView.swift`). *Src:* D3 V16, V17, E24; Idea §4; MP s6 mockups (share icon).
- **SES-06a** — Film pilot and test-set games only with logged participant consent, and delete footage on request. *Why:* needed before OPS-01 can use pilot footage; GTM pilots require a consent plan. Pilots start by Nov 18. *Status:* the midpoint notes commit to it, but no consent record or deletion process exists in the repo. *Src:* MP notes (User outreach); GTM Sales process.
- **SES-06b** — Let users control who can see their videos. *Why:* survey 20/34; the midpoint Profile mockup has a "Privacy" entry. *Status:* none. Runs stay on the device, but `UIFileSharingEnabled` and `LSSupportsOpeningDocumentsInPlace` (`ios/VantageMobile.xcodeproj/project.pbxproj:174, 176`) expose every run's video and detections in the Files app and Finder. *Src:* Survey; MP Profile mockup.
- **SES-06c** — Preview what a share includes and confirm the recipient; can ship with SES-05. *Implied.* *Status:* none. *Src:* D3 E23.
- **SES-06d** — Block or blur people in the footage who have not authorized sharing. *Implied.* *Status:* none. *Src:* D3 A4, E22.
- **SES-07** — A profile with lifetime totals (games, hours, best serve) and preferences: units, dominant hand, live stats, LiDAR assist, storage. *Why:* midpoint mockup only. *Status:* no profile screen. *Src:* MP notes, Profile mockup.
- **SES-08** — Fun comparison facts to show friends. It is a one-line placeholder, and "accurate" is undefined. *Status:* none. *Src:* Deck A s3; MP s3.
- **SES-09** — After a doubles match, the recorder shares stats with the other three players, who claim them and join free. *Why:* a GTM growth loop; needs SES-10 and a backend that no source describes. *Status:* the app is local-only. *Src:* GTM Go-to-market and notes.
- **SES-10** — An optional account that ties a profile, sessions and claimed stats to one person across devices. *Implied.* *Why:* a prerequisite for SES-09, GTM-04b/c and cross-session identity. *Status:* the app is local-only. *Src:* MP Profile mockup ("ACCOUNT").

## 8. Real-time/on-device performance

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| PERF-01 | Post-match analysis on iPhone with bounded turnaround | fall | must | partial | GTM: "Match reports delivered within 24 hours". (proposed) A 60-min session finishes full analysis on the target iPhone within 60 min of the session ending (≤1× real time). |
| PERF-02 | iPhone sustained-speed benchmark (NEB-33) | fall | must | not started | v2: "sustained processing rate, and processor and memory use". (proposed) End-to-end fps, CPU, peak memory, thermal state and battery over a 60-min run on ≥2 iPhone models. "Real time" = processing fps ≥ capture fps for the whole run. |
| PERF-03 | Full hour on one phone (requirement verified by PERF-02) | fall | should | not started | GTM: "track a full hour on one phone". (proposed) 60 min of recording and tracking with no crash or thermal shutdown, peak memory <1.5 GB, ≤40% battery on a current iPhone. |
| PERF-04 | Resource-aware, resumable analysis | unspecified | should | not started | (proposed) An analysis interrupted by backgrounding or termination resumes from the last processed frame; an import that won't fit in storage is refused up front. |
| PERF-05 | Live stats while recording | fall (contingent) | should | not started | v2 metric "capture-to-display delay". (proposed) Over a 20-min live session, median delay ≤500 ms and 95th percentile ≤1 s; live stats agree with post-match stats within the EVAL-04 tolerance. |
| PERF-06 | Real-time stream-processing pipeline and speed-up | fall (contingent) | should | not started | (proposed) On the target iPhone, processing fps ≥ capture fps for 20 min with <1% dropped updates and no growing delay. |

- **PERF-01** — Run the full analysis on the phone after the match, fast enough to review courtside. This is also the fallback if live processing can't keep up. *Why:* the midpoint's biggest risk ("Slow phone → post-match"); D3 frames analysis as "after play"; survey 20/34 want results quickly. *Status:* iOS analyzes saved videos frame by frame on the device (`VK/VideoAnalyzer.swift`), in the foreground and one at a time. It runs detection and ball tracking only (no stats; see MEA-10). Timing has only been measured on a Mac (11 ms/frame). *Src:* MP notes, Next steps; D3 V13; GTM; f221941; Survey.
- **PERF-02** — Benchmark detection and end-to-end speed on real iPhones over long runs, with CPU, memory, thermal state and battery. The result decides live vs post-match, and the same run verifies PERF-03. *Why:* core v2 metrics; midpoint NEB-33 and "sustained phone speed". *Status:*
  - No iPhone benchmark has been run.
  - Instrumentation exists: each iOS run logs per-frame detector latency to detections.jsonl and the mean to run.json (`VK/VideoAnalyzer.swift:66-88`). It excludes decode, tracking and I/O.
  - On a Mac, Core ML runs at about 11 ms/frame (`tools/coreml/compare.py`).

  *Src:* v2; Pitch s8; MP Team process, Plan & Scope, Next steps.
- **PERF-03** — Record and track a full hour on one phone within battery, memory and thermal limits. This is the requirement; PERF-02's 60-minute run verifies it. *Why:* GTM's "to earn it" bar; covers real open-play and league sessions. Needs CAP-02. *Status:* none. *Src:* GTM Positioning; v2; D3 A17; Survey 12/34.
- **PERF-04** — Check storage and battery before starting. Survive backgrounding, low battery and termination by saving progress and resuming, or fail with a specific message. *Implied.* *Status:* not started; only mitigations exist.
  - iOS disables auto-lock during import (`VM/Library/RunImporter.swift:48`) and asks the user to keep the app open (`GamesListView.swift:146`).
  - A run killed mid-analysis is silently deleted at the next launch (`RunStore.swift:33-36`).
  - Desktop keeps earlier outputs on Ctrl-C (`pv/main.py:165-167`) but cannot resume.

  *Src:* D3 E18, A17.
- **PERF-05** — Stats such as speed, landing spots and counts update on screen during play with low capture-to-display delay. A setup toggle trades live updates for more accurate post-match stats. It runs on PERF-06. *Why:* real time on the phone is v2's headline claim and is in both pitch decks. But the midpoint Plan & Scope slide moved live stats to "Later", while its notes still list "a live stats overlay" in the fall app step. Contingent on PERF-02. *Status:* no live capture or real-time analysis anywhere; desktop `--stream` emits data at processing speed. *Src:* v2; f221941; Pitch s3; MP Plan & Scope, notes, Match setup mockup.
- **PERF-06** — Run capture, Core ML inference, tracking and stats as concurrent stages with bounded queues and a processing schedule (frame skipping, asynchronous inference, crops). Includes speed-up work on model size, input resolution and quantization, and counts dropped frames. *Why:* "real-time stream processing" is one of the four parts of v2's approach; the pitch has a weeks 7–9 speed-up phase. Contingent on PERF-02. *Status:* VideoAnalyzer processes saved files one frame at a time; crop-assisted detection is prototyped only on a Mac (`tools/coreml/crop_experiment.py`). *Src:* v2; f221941; Pitch s8; MP Plan & Scope ("Measure, then speed up"); pre-61b2bc4 ("dropped updates").

## 9. Accuracy & evaluation

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| EVAL-01a | Labelling tools for all annotation types | fall | must | partial | (proposed) Tools label ball, bounces/landing points, paddle contacts, rally start/end and player footpoints in a versioned format the harness reads. |
| EVAL-01b | Select and label held-out clips | fall | must | partial | (proposed) ≥4 held-out clips from ≥2 angles, indoor and outdoor, labelled for every EVAL-01a type. |
| EVAL-01c | Freeze and version the test set (NEB-32) | fall | must | not started | (proposed) A manifest with file hashes; clips are excluded from training and threshold tuning, enforced by a check. |
| EVAL-01d | Committed baseline report | fall | must | not started | MP checkpoint: "Measured baseline". (proposed) Baseline metrics for the current pipeline on the frozen set, committed to the repo. |
| EVAL-02 | Accuracy harness for every reported measurement | fall | must | partial | (proposed) One command outputs every v2 metric on the frozen set; a small fixture version runs in CI. |
| EVAL-03 | Independent reference measurements for speed and landing | fall | must | not started | (proposed) ≥30 shots with radar-gun speeds and ≥30 bounces with measured court positions, synced to test-set video. |
| EVAL-04 | Real-time vs offline reference comparison | fall | must | partial | a7f20b9: an offline baseline "will reveal the accuracy cost of meeting real-time constraints". (proposed) Difference in ball recall, speed error and landing error between phone and offline configurations on the frozen set. |
| EVAL-05 | Visual-only vs geometry-assisted ablation | fall | must | not started | v2: "establish whether the combined approach improves measurement accuracy over simpler baselines while keeping up with incoming video". (proposed) Position, speed and landing error for both variants, plus iPhone fps. |
| EVAL-06 | Detection model and processing-schedule comparison | fall | should | partial | (proposed) An accuracy-vs-fps table on the frozen set and on an iPhone for ≥3 model or schedule options. |
| EVAL-07 | Recording-condition stress tests (NEB-31) | fall | must | not started | a7f20b9: "quantify changes in accuracy and delay and identify when estimates become unreliable". (proposed) Accuracy and fps for ≥3 camera positions, 30 and 60 fps, 2 resolutions, indoor and outdoor; a published supported-setup envelope. |
| EVAL-08 | On-court validation of the full path | fall | must | not started | MP checkpoints: "Measured baseline · Integrated pipeline · Court validation". (proposed) At a real court, record, analyze and view stats end to end on an iPhone; accuracy against same-session labels reported with sustained fps. |
| EVAL-09 | Tracking-error impact on insights | winter | must | not started | (proposed) Inject measured error distributions into labelled sessions, report how often each derived pattern changes, and derive a minimum-evidence threshold. |
| EVAL-10 | Head-to-head benchmark against PB Vision | unspecified | could | not started | GTM: 95%+ shot detection, compared on the same clips. |
| EVAL-11 | Time saved vs manual logging | unspecified | could | not started | (proposed) For 3 sessions, minutes spent logging by hand vs with Vantage. |
| EVAL-12 | Player and coach trials of insight usefulness | winter | could | not started | v1: insights "understandable and useful in practice". (proposed) ≥5 players and 2 coaches rate usefulness ≥4/5. |
| EVAL-13 | Numeric targets and fixed regression gates | fall | must | not started | MP: "re-test the same gates". (proposed) A committed targets file with a threshold per metric; the harness reports pass/fail; every NEB-34/40/41 change records its gate results. |
| EVAL-14 | One-on-one feedback sessions with waitlist users | fall | could | not started | (proposed) ≥5 sessions before the fall demo; findings logged as issues linked to feature IDs. |
| EVAL-15 | Cross-session measurement repeatability | winter | could | not started | (proposed) Re-marking corners 5 times changes landings ≤0.15 m and speeds ≤3%; the trend view marks smaller changes as "no change". |

- **EVAL-01a** — Extend `ml/labeling.py` beyond ball positions to bounces and landing points, paddle contacts, rally start and end, and player footpoints. *Why:* every accuracy claim needs labels of its type; the old single EVAL-01 hid this gap. *Status:* a ball-only tool exists (`ml/label_ball.py`, `ml/labeling.py`). Court1-a rally labels exist only on the rally branch (`ml/labels/rallies/court1-a.json`). *Src:* MP NEB-32; v2; Pitch s9.
- **EVAL-01b** — Choose and label held-out clips across angles and settings. Needs OPS-01 and SES-06a. *Status:* labels are committed for one clip only (`ml/labels/topcorner60fps.json`: 224 frames, 164 visible balls). The backcorner60fps labels are referenced but missing. There are no player, paddle, bounce, shot or speed labels. *Src:* MP NEB-32; Survey 32/34 "The results are correct."
- **EVAL-01c** — Freeze the set with a hashed manifest, excluded from training and tuning. *Why:* the pickleball-v1 threshold was tuned on the only held-out clip. *Status:* no named frozen set exists. *Src:* MP Next steps ("Freeze test data").
- **EVAL-01d** — Record and commit the baseline that every later change is measured against. *Why:* the first midpoint checkpoint. *Status:* not started. A one-clip, ball-only comparison already exists (`ml/README.md:25-31`). *Src:* MP Next steps, checkpoints; MP Plan & Scope ("Add: accuracy testing").
- **EVAL-02** — One command scores a pipeline version on the frozen set for position, speed and landing error, shot and rally precision and recall, and tracking continuity. *Why:* these are v2's test metrics, and the harness makes every change measurable. *Status:* `ml/evaluate_ball.py` reports pooled ball recall and precision. `pipeline/diagnostics/eval_rallies.py` is in flight on the rally branch. Nothing scores speed, landing, shots, positions or continuity. *Src:* v2; 2b214a0; Pitch s9.
- **EVAL-03** — Ground truth independent of the camera, for example a radar gun for speed and measured landing marks. Raised to must. *Why:* every abstract version and the pitch name it alongside labelled recordings. It is the only way to validate speed (MEA-01), which can't be hand-labelled from video. The instrument is still open. *Status:* none. *Src:* v2; Pitch s9; f221941 ("independent reference measurements").
- **EVAL-04** — Run a slower, more accurate offline configuration on the same footage as the phone configuration, and measure what real-time costs. *Why:* a core comparison in v2, v1 and the pitch. *Status:*
  - Treating desktop as the offline reference is an inference.
  - The Swift tracker matches Python exactly (`ios/VantageKit/Tests/VantageKitTests/BallTrackerParityTests.swift`).
  - On labelled topcorner60fps, Core ML pickleball-v1 tracks at 61.6% recall / 96.2% precision vs 62.8% / 97.2% for PyTorch (`ml/README.md:25-31`).
  - The 96/97 and 53/55 counts are COCO candidate retention, not accuracy. No heavier offline configuration exists.

  *Src:* v2; v1; Pitch s9.
- **EVAL-05** — Compare visual tracking alone with geometry-assisted estimation (TRK-09) on the same labelled footage. *Why:* v2 judges its core contribution with this comparison. *Status:* no geometry-assisted variant exists yet. *Src:* v2.
- **EVAL-06** — Compare models, thresholds, crop strategies and processing schedules for accuracy, continuity and delay. *Why:* explicit in v2, and it justifies the model choice. *Status:* COCO vs pickleball-v1 is compared on topcorner60fps (39.6% vs 61.6% tracked recall), as is conf 0.10 vs 0.20. Crop detection is prototyped (`tools/coreml/crop_experiment.py`) and adds 81–110 ms/frame on a Mac CPU. There is no schedule comparison and no iPhone timing. *Src:* v2; f221941.
- **EVAL-07** — Vary camera position, image quality, frame rate and indoor/outdoor setting to find where estimates stay reliable. Publish the supported-setup envelope that feeds CAP-03 and CAP-10. *Why:* a stated v2 outcome; NEB-31 is in progress outside the repo. *Status:* not started in the repo. The three-viewpoint clips are only Swift/Python parity fixtures (`tools/coreml/make_tracker_fixtures.py`), and only topcorner60fps has labels. There is one qualitative finding: from behind the baseline, net crossings fail (commit 73c8d3d). *Src:* v2; Pitch s9; MP NEB-31; D3 V5, V6; Idea §7.
- **EVAL-08** — On a real court, run capture, pipeline and app stats end to end on an iPhone, and measure accuracy and sustained speed. This is the working demo. *Why:* the final midpoint checkpoint and the pitch's weeks 10–12. *Status:* blocked by CAP-02, CAL-01b/c, MEA-10 and VIS-03. *Src:* MP Next steps, checkpoints; Pitch s8; 2b214a0 ("a demonstration of live statistics and heat maps").
- **EVAL-09** — Measure how tracking and measurement errors change the derived placement and coverage patterns, and use the result to set the INS-05 thresholds. *Why:* part of v2's winter claim. Needs INS-01/02 and the EVAL-02 error distributions. *Status:* none. *Src:* v2.
- **EVAL-10** — Run PB Vision on the same labelled clips and compare shot detection. *Why:* GTM says "ideally"; a competitive claim, not needed for the capstone. *Status:* none. *Src:* GTM notes.
- **EVAL-11** — Compare the time to collect stats with Vantage against manual logging. *Why:* in v1, 2b214a0, a7f20b9 and the pitch evaluation slide (skipped in Deck A); dropped from v2. *Status:* none. *Src:* v1; Pitch s9.
- **EVAL-12** — Court trials in which players and coaches judge the winter insights. *Why:* in v1, 64509af and 2b214a0, but dropped from v2; partly covered by the GTM-02 pilots. *Status:* none. *Src:* v1; 2b214a0.
- **EVAL-13** — After the baseline, set signed-off numeric targets per metric and encode them as pass/fail gates that every tracking change re-runs. Must is a judgment call: the midpoint "Improve tracking" step says "re-test the same gates", and drafts through 64509af said early trials would set error and delay targets. *Status:* only Swift/Python parity tests run in CI. *Src:* MP Next steps; pre-61b2bc4; f221941; 64509af.
- **EVAL-14** — Short one-on-one sessions with opted-in waitlist users covering setup, import and the report. *Why:* the waitlist was designed to recruit for these. *Status:* none; the survey CSV lacks the 1:1 question. *Src:* MP Waitlist slide and notes.
- **EVAL-15** — Check that stats don't shift because of setup noise: re-mark the corners of one clip 5 times, and record the same drill on 2 days. *Why:* cross-session comparison (SES-03/04) is meaningless without repeatability. *Status:* none. *Src:* 2b214a0 ("consistent measurements across sessions"); Pitch s2.

## 10. Platform/ops

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| OPS-01 | Real-court match video collection with consent | fall | must | partial | (proposed) ≥3 venues and ≥2 phone models recorded with logged consent before the test set is frozen. |
| OPS-02 | Automated tests and CI | fall | should | done | MP: "Automated tests: 22 → 57". (proposed) Every PR passes CI, including Swift/Python parity tests. |
| OPS-03 | Beta distribution of the iOS app | fall | should | not started | (proposed) A signed build installs on ≥10 non-team iPhones without a cable and stays valid ≥90 days. |
| OPS-04 | Supported-device list and capability check | fall | should | not started | (proposed) Unsupported devices get an explanation and post-match-only mode; PERF-02 covers every supported tier. |

- **OPS-01** — Collect consented match video from real courts, with new angles and phones, for development, the test set and stress tests. Needs SES-06a. *Why:* pitch weeks 1–3; the midpoint and GTM tie pilot footage to NEB-32, and all evaluation depends on it. *Status:* a handful of team clips are in the team Drive (since PR #5), plus 13 license-filtered Roboflow datasets (`ml/fetch_roboflow.py`, `ml/DATA_SOURCES.md`). No pilot footage yet; pilots start by Nov 18. *Src:* Pitch s8; GTM Sales process; MP notes.
- **OPS-02** — Automated tests for the pipeline, ML tooling, Core ML export and VantageKit, run in CI with an iOS build. *Status:* done: about 61 pipeline, 16 ml, 11 tools/coreml and 24 Swift tests (`scripts/test.sh`). CI on Xcode 27.1 exports the model and builds the unsigned app (`.github/workflows/ci.yml`). The app target itself has no tests. *Src:* MP Technical progress.
- **OPS-03** — Get the app onto testers' and venues' phones, for example through TestFlight. *Implied:* GTM's "Beta invite" step and the pilots need it, but no method is named. *Status:* not started.
  - The only route is a free-Personal-Team sideload (`ios/scripts/run_on_iphone.sh`).
  - It needs a Mac with Xcode 27.1 and a paired iPhone, and a reinstall every 7 days (`ios/README.md:98-136`).
  - CI builds unsigned (`.github/workflows/ci.yml:62-66`).

  *Src:* GTM Go-to-market, Sales process.
- **OPS-04** — Publish the minimum iPhone model and iOS version. Detect Neural Engine support, camera frame-rate modes and LiDAR, then choose live vs post-match or warn. *Implied.* *Why:* PERF-02 needs named target models, OPS-03 needs a supported list, and the waitlist collects phone models. *Status:* none. *Src:* D3 A1; MP Waitlist slide and notes; MP mockups ("LiDAR detected on this iPhone").

## 11. Business/GTM

| ID | Feature | Term | Priority | Status | Acceptance |
|---|---|---|---|---|---|
| GTM-01 | Waitlist survey and beta-invite prioritization | fall | could | done (ext.) | Survey CSV: 30/34 respondents joined the waitlist. |
| GTM-02 | Venue and coach pilot program with scored success criteria | fall | should | partial (ext.) | GTM pilot criteria: ball tracking holds on their court (hand-labelled sample); reports within 24 h; ≥60% of filmed players open their report; director or coach rates ≥4/5 and names a next step. |
| GTM-03 | GTM outbound engine (internal tool) | fall | could | done (ext.) | GTM deck: every account scored and routed with the score explained; term targets are in the GTM deck. |
| GTM-04a | Pricing hypothesis tests in pilots | fall | could | not started | (proposed) Each pilot records willingness to pay against the stated tiers. |
| GTM-04b | Court-hour usage metering | winter | could | not started | (proposed) Tracked court-hours recorded per venue within 1% of session duration. |
| GTM-04c | Plan entitlements and enforcement | winter | could | not started | (proposed) Plan limits enforced per account. |
| GTM-05 | Coach and venue layer | winter (inf.) | could | not started | GTM pilot default: "Director or coach rates it 4/5+ and names a next step". |
| GTM-06 | Social and community marketing | fall | could | partial (ext.) | (proposed) Content posted on a regular schedule; waitlist sign-ups attributed by channel. |

- **GTM-01** — A public waitlist form that doubles as a survey. Best-fit sign-ups are invited first, and a club with 2+ sign-ups moves up the list. *Why:* informs priorities; not part of the capstone evaluation. *Status:* done outside the repo. The form went live Oct 6 (midpoint notes, matching its Drive creation time); the slide says Oct 2. The survey CSV has 34 responses, 30 of whom joined the waitlist. The app is not connected to it. *Src:* MP Waitlist slide; GTM Playbook.
- **GTM-02** — Free two-week court pilots with 2–4 filmed sessions, scored against ≥3 written criteria, leading to design-partner agreements. Needs SES-06a, plus VIS-03 and PERF-01 (or the desktop pipeline meanwhile). *Why:* supplies footage (OPS-01) and stakeholder feedback. *Status:* outreach is under way outside the repo, but no pilot has started (start by Nov 18, decide by Dec 4). The fall pilot targets are in the GTM deck. *Src:* GTM Sales process, notes, Go-to-market.
- **GTM-03** — Internal Python tooling that sources, scores, routes and sequences outreach. A test fails if any message claims stats the prototype doesn't produce. *Status:* described in the GTM deck only; it is not in any vantage branch, so it can't be verified here. *Src:* GTM engine slide and notes.
- **GTM-04a** — Test the hypothesis prices in the pilots: free player stats plus paid Player Pro, Coach and Venue plans, with venues priced per tracked court-hour or monthly (amounts in the GTM deck). *Why:* GTM calls the prices "hypotheses we test in the pilots"; survey 27/34 "does not cost too much". *Status:* none. *Src:* GTM Go-to-market; Survey.
- **GTM-04b** — Meter tracked court-hours per venue for billing. *Implied:* venue pricing is per court-hour. Needs SES-10. *Status:* none. *Src:* GTM Go-to-market ("Paid plan winter: venue plan").
- **GTM-04c** — Enforce plan entitlements. *Implied.* Needs SES-10. *Status:* none. *Src:* GTM Go-to-market.
- **GTM-05** — Product features for coaches and venues on top of player stats, undefined beyond reports and clip packs. The term is inferred from "winter: venue plan". *Status:* none. *Src:* GTM Our Wedge, Positioning.
- **GTM-06** — TikTok content, a Slack community and Ottawa pickleball community outreach that drive waitlist sign-ups. *Status:* outside the repo: Slack is set up, and TikTok scripts and Ottawa outreach are in progress (Derek). *Src:* MP Teamwork slide and notes; MP User outreach slide.

---

## Cut or deferred

- **LiDAR depth assist and LiDAR validation reference** — Deferred. It started as a core fusion input (16ce77e), became optional in f221941 ("the core design does not require it"), then a "where feasible" validation reference in v2. The midpoint moved it to "Later". If it is revived, f221941 requires comparing it with video alone first. Sources: MP Plan & Scope; v2; f221941; Pitch s8; MP Profile mockup.
- **Live stats as a guaranteed fall deliverable** — Made contingent. Post-match analysis is the committed fall product. Live stats (PERF-05, on PERF-06) are still attempted if the NEB-33 benchmark allows. Sources: MP Plan & Scope ("Later: LiDAR, live stats"), Next steps ("BIGGEST RISK Slow phone → post-match").
- **Video + LiDAR 3-D motion fusion, 3-D heat map and 3-D animated replay** — Cut as a core design element in f221941, and present only in skipped legacy slides. The 3-D replay has survey demand (22/34) but depends on this cut reconstruction. Single-camera 3-D ball flight without LiDAR is kept as TRK-10. Sources: 16ce77e; Deck A slide 15 (legacy, skipped: "3D Motion Fusion — Camera + LiDAR depth", "SHOT DENSITY (3D HEATMAP)"); Deck A slide 16 ("AI 3D motion estimation").
- **Racket-mounted IMU sensors** — Removed in f221941. They also conflict with "one phone, one camera". Sources: pre-61b2bc4; Deck A slide 17 (legacy, skipped).
- **Court-mounted cameras and multi-camera rigs** — Narrowed to a single phone camera in 64509af; multi-camera is future work, and installed hardware is the competitor category. Sources: f221941; 64509af; Pitch s3 ("No multi-camera rig to set up"); Pitch s4 ("Future: multiple synced cameras"; notes: "multiple synced cameras are future work"); MP Plan & Scope ("Keep: one-camera stats"); GTM Positioning ("One iPhone, nothing installed").
- **Other racket sports (badminton, tennis, table tennis, squash)** — Deferred beyond the capstone. Shuttle tracking was dropped in 64509af, and D3 treats other sports as an exception (E4). The design should stay extensible. Sources: f221941 → 64509af; MP s1 ("Starting with pickleball"); MP Match setup mockup; Survey (badminton 13/34, tennis 11/34).
- **Prescriptive player movement suggestions** — Only in 64509af; 2b214a0 replaced them with factual "player movement". D3's coverage advice (INS-04) partly reintroduces the idea, under evidence gating.
- **Within-rally speed-variation view** — In one draft (2b214a0) only, and removed in a7f20b9.
- **Biomechanics and joint-angle diagnostics** — Only in skipped legacy Deck A slide 12; narrowed into the winter stretch goal INS-07.
- **Cloud or server-side processing** — Only in the idea doc (§3). The pitch (s7) and v2 commit to on-phone processing. Note that SES-09, SES-10 and GTM-04b/c would need a backend for accounts and sharing; see open questions.
- **Handheld or moving-camera footage** — Out of scope. A stable camera is a D3 assumption (A7); movement is handled only as an exception (CAL-02).
- **Outdoor-only venue pilots this term** — Deferred to spring, because GTM holds outdoor-only venues until courts reopen. Outdoor test footage for CAP-11 and EVAL-07 must therefore come from the team.
- **Live coaching tips during play** — Not planned. Only 7/34 survey respondents want tips while playing, against 27/34 later, and D3 frames coaching as after play. INS-11 (between games) is the closest feature kept.

## Conflicts between sources

1. **Live vs post-match.**
   - v1, v2 ("in real time") and both pitch decks promise stats during play. D3 describes analysis "after play".
   - The midpoint Plan & Scope slide moves live stats to "Later" and names "Slow phone → post-match" as the biggest risk. The same deck's notes still list "a live stats overlay" in the fall "Connect the app" step.
   - Resolution: post-match is the committed fall product (PERF-01, VIS-03). Live stats stay fall/should, contingent on NEB-33 (PERF-05, PERF-06).
2. **LiDAR.** The pitch schedules it for fall weeks 4–6, v2 says "where feasible", and the midpoint says "Later". Resolution: deferred.
3. **Calibration method.** The idea doc proposes automatic line detection ("60-second court calibration", Phase 1). The pitch plan says only "calibrate to the court". D3's domain model has the player mark the corners, and the midpoint camera check needs all four corners in frame. Resolution: manual corner marking (CAL-01a–c, matching the repo); automatic detection is a could (CAL-04).
4. **Camera placement.** The idea doc says behind the baseline at 6–8 ft. The pitch says "at the side of the court". The midpoint mockup says behind the baseline, with NEB-31 still comparing angles. Resolution: behind the baseline is the default, and EVAL-07 sets the envelope (CAP-10). The repo's net-crossing shot rule barely fires from behind the baseline.
5. **Sport scope.** The abstracts say "racket sports", and early drafts included shuttles. D3 is pickleball-only and treats other sports as an exception. The midpoint mockups list four sports and use a tennis singles example, while its title says "Starting with pickleball". Resolution: pickleball only for the capstone.
6. **Winter scope.**
   - v2: placement and coverage patterns plus a tracking-error study; no coaching.
   - D3 (the SE463 requirements deliverable, Oct 30): adds an AI coach, advice, drills, and sharing/export.
   - v1: adds a practice focus.
   - Pitch: names only technique feedback, as a stretch goal.
   - Idea doc: lists shot classification and forced/unforced errors as MVP.

   No source ranks D3 against v2. Resolution: v2's patterns and error study are winter musts (INS-01/02, EVAL-09). D3's coach and drills are shoulds (INS-03/04), pending confirmation that D3's additions are SE490 scope. Technique feedback is the only source-named stretch goal; idea-doc-only and survey-only items are stretch by inference.
7. **Session summaries and cross-session comparison.** v2 drops both. Deck B lists "Compare across matches", which Deck A (edited Oct 7) replaced with "Cool Facts!". D3 (Oct 30) keeps two-session and multi-session comparison, and the midpoint keeps a session report. Resolution: the summary is fall/must (VIS-03); comparison is winter/should (SES-03/04).
8. **Stakeholder trials and time saved.** Time saved appears in v1, 2b214a0, a7f20b9 and the pitch evaluation slide (skipped in the latest Deck A). Player and coach trials appear only in v1, 64509af and 2b214a0. v2 drops both, and the midpoint and GTM replace them with venue and coach pilots. Resolution: pilots are GTM-02; EVAL-11 and EVAL-12 are could.
9. **Swing speed.** v2, D3 and the pitch notes ("committing to this fall") list it. The midpoint fall plan names no individual statistic; it keeps "one-camera stats", and a mockup shows "Top swing". Resolution: fall/must (MEA-02), with TRK-06 raised to must; it is the riskiest stat.
10. **Processing location.** The idea doc offers cloud sync, the pitch says "Everything runs on a phone", and D3 mentions only device resources. Resolution: on-device.
11. **Ball tracking numbers.** These are different metrics on different clips: the pitch reports 21% coverage on a 6-minute indoor clip, the midpoint 99% on a 20-second 240 fps clip, and the repo 61.6% tracked recall on held-out topcorner60fps. The midpoint itself says "Coverage isn't accuracy".
12. **Singles vs doubles.** D3 V4 treats doubles as the baseline, and the prototype tracks 4 players, but the midpoint mockups use a tennis singles example.
13. **Waitlist launch date.** The midpoint slide says Oct 2. Its notes say Oct 6, which matches the form's Drive creation time (Oct 7 01:31 UTC, the evening of Oct 6 Eastern). Treat Oct 6 as the launch date. Separately, the survey CSV (N=34, Oct 16–20) does not contain the questions the slide describes (phone model and tripod, 1:1 feedback, home club).
14. **Repo docs vs code (status only).** `ios/README` says "Import from Files" and swipe to delete; the app uses PhotosPicker and a context-menu delete.

## Open questions for the team

1. **Numeric targets.** The only stated numbers are GTM's: 95%+ shot detection, a full hour on one phone, and the pilot criteria. Every other acceptance value here is "(proposed)". Who signs off on them (EVAL-13), and should they go into the next specification deliverable?
2. **D3 scope.** Are the SE463 D3 additions committed SE490 capstone scope? They are the AI coach and drills, session comparison and trends, sharing/export, and privacy safeguards. The answer sets the priority of INS-03/04/06, SES-03/04/05 and SES-06c/d.
3. **Rubric.** Which SE490 grading criteria apply? The draft list cited a rubric (for example "Technical Engagement" and "working demo") that is not among the sources and could not be found. If the team has it, add it as a cited source.
4. **Live stats.** Is the live overlay a fall deliverable (midpoint notes) or "Later" (Plan & Scope)? What NEB-33 result triggers the post-match-only fallback?
5. **Linear mapping.** What exactly are NEB-31/32/33/34/40/41/44/45/47 in Linear? Mapping them to these IDs would let the list be tracked as issues. Linear was not read.
6. **D2 coaching spec.** D3 says the AI coaching is "specified in D2", which was not read. Does D2 define pattern types, a drill catalogue, whether an LLM is used, and whether coaching runs on the device or on a server?
7. **Independent references.** Which instrument provides independent speed and landing ground truth (radar gun, measured marks, LiDAR)? Who labels bounces, hits, rallies and player positions for the frozen set?
8. **Offline baseline.** Is the desktop pipeline officially v2's "slower offline analysis"? That is inferred. Should the desktop default switch from `yolo26n.pt` to pickleball-v1 so both surfaces evaluate the same model?
9. **Swing-speed method.** Will swing speed use paddle tracking or pose estimation?
10. **Audio signal.** Should audio hit onsets be the official shot and rally signal? The thresholds were tuned on one clip. Should origin/jacob/rally-detection get its own PR rather than riding inside PR #6?
11. **Placements and devices.** Which camera positions must be supported, and which iPhone models are the benchmark targets (OPS-04)?
12. **User identity.** How does a user say which player they are (MEA-07), and how is that identity kept across sessions for trends (SES-03/04, SES-10)?
13. **Backend.** Is a backend in capstone scope? Sharing with the other three players, accounts, pricing tiers and court-hour metering all need one, and the app is local-only today.
14. **Consent.** How will consent from everyone in the footage be recorded, and how are deletion requests handled (SES-06a)? Should Files-app file sharing be turned off outside developer builds (SES-06b)?
15. **Survey sheet.** Is there a second response sheet with the questions the midpoint slide describes (phone model and tripod, 1:1 feedback, home club)? The CSV that was read doesn't have them.
16. **Automatic calibration.** Is automatic court-line detection wanted at all, or is manual marking final?
17. **Cool Facts.** Should "Cool Facts" be defined or dropped? What "accuracy" would it compare between friends?

## Suggested fall-term must-do (remaining)

These are the 41 must/fall features not yet done, ordered by dependency and grouped by the midpoint's four steps. Pilots start by Nov 18, so items 1–3 are time-critical.

| # | ID | Feature | Status | Needs |
|---|---|---|---|---|
| | | **Step 1 — Freeze test data and record the baseline** | | |
| 1 | SES-06a | Pilot and data-collection consent and deletion process | not started | — |
| 2 | PERF-02 | iPhone sustained-speed benchmark (first run now on detection and tracking; rerun after MEA-10e and CAP-02) | not started | — |
| 3 | OPS-01 | Real-court video collection with consent | partial | SES-06a |
| 4 | EVAL-01a | Labelling tools for all annotation types | partial | — |
| 5 | EVAL-01b | Select and label held-out clips | partial | OPS-01, EVAL-01a |
| 6 | EVAL-03 | Independent speed and landing references (collect in the same sessions) | not started | OPS-01 |
| 7 | EVAL-01c | Freeze and version the test set | not started | EVAL-01b |
| 8 | EVAL-02 | Accuracy harness for every measurement | partial | EVAL-01a |
| 9 | EVAL-01d | Committed baseline report | not started | EVAL-01c, EVAL-02 |
| 10 | EVAL-13 | Numeric targets and regression gates | not started | EVAL-01d |
| | | **Step 2 — Improve tracking (desktop reference first)** | | |
| 11 | TRK-05 | Restrict analysis to the filmed court | partial | CAL-01a (done) |
| 12 | TRK-01 | Custom pickleball detector | partial | EVAL-01c |
| 13 | TRK-02 | Ball tracking through blur, occlusion and misses | partial | TRK-01 |
| 14 | TRK-03 | Player detection and per-frame tracking | partial | TRK-01, TRK-05 |
| 15 | TRK-04 | Persistent player identity | not started | TRK-03 |
| 16 | TRK-06 | Paddle detection, tracking and player association | partial | TRK-01, TRK-03 |
| 17 | TRK-07c | Shot events (fusion and disambiguation) | not started | TRK-07a (in flight, PR #6), TRK-07b, TRK-02, TRK-06 |
| 18 | TRK-08 | Rally segmentation | partial | TRK-07a, TRK-07c |
| 19 | TRK-09 | Geometry-assisted motion estimation | not started | TRK-02, CAL-01a |
| 20 | EVAL-05 | Visual-only vs geometry-assisted ablation | not started | TRK-09, EVAL-02 |
| | | **Measurements (desktop reference)** | | |
| 21 | MEA-03a | Bounce detection and landing position | partial | TRK-02, TRK-07c |
| 22 | MEA-03b | Landing-zone classification | not started | MEA-03a |
| 23 | MEA-01 | Shot speed per shot | partial | TRK-07c, EVAL-03 (TRK-10 for true flight speed) |
| 24 | MEA-02 | Swing speed | not started | TRK-06 |
| 25 | MEA-04 | Player court position and movement paths | partial | TRK-04 |
| 26 | MEA-06 | Rally and shot counts, rally-length stats | partial | TRK-07c, TRK-08 |
| | | **Step 3 — Connect the app** | | |
| 27 | CAL-01c | VantageKit homography and projection | not started | — |
| 28 | CAL-01b | iOS corner-marking UI | not started | CAL-01c |
| 29 | MEA-10a | iOS rally and shot computation | not started | TRK-07c, TRK-08 |
| 30 | MEA-10b | iOS bounce, landing, zone and IN/OUT | not started | CAL-01c, MEA-03a, MEA-03b |
| 31 | MEA-10c | iOS speed computation | not started | CAL-01c, MEA-01 |
| 32 | MEA-10d | iOS per-player movement | not started | CAL-01c, MEA-04 |
| 33 | MEA-10e | iOS stats.json and stats screens | partial | MEA-10a–d |
| 34 | VIS-03 | Session report shell, Overview and Shots tabs | partial | MEA-10e |
| 35 | VIS-01 | Heat map and landing-spot view | partial | MEA-10b |
| 36 | VIS-02 | Movement path and coverage views | not started | MEA-10d |
| 37 | CAP-02 | In-app recording (can start in parallel at any time) | not started | — |
| 38 | PERF-01 | Post-match analysis turnaround on iPhone | partial | MEA-10e, PERF-02 |
| | | **Step 4 — Court validation** | | |
| 39 | EVAL-04 | Real-time vs offline comparison | partial | EVAL-02, MEA-10e |
| 40 | EVAL-07 | Recording-condition stress tests | not started | EVAL-02, OPS-01 |
| 41 | EVAL-08 | On-court validation of the full path | not started | CAP-02, CAL-01b, MEA-10e, VIS-03, PERF-02 |

Several should-level features unblock these musts:
- TRK-07a (audio onsets, PR #6) for TRK-07c and TRK-08.
- TRK-10 (single-camera depth), so MEA-01 can meet a radar target.
- TRK-07b (visual contacts) as a second hit signal.
- OPS-04 (supported devices), to name the PERF-02 targets.
