"""Evidence packs for the AI coach: on-court positions, key moments, and still frames."""

import json
import math
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
from coach_fixtures import make_run
from vantage import coach_evidence
from vantage.coach_evidence import (
    COACH_DIR,
    EVIDENCE_VERSION,
    FRAME_NAME,
    FRAMES_DIR,
    EvidenceError,
    build_evidence,
    ensure_evidence,
    extract_moment_frames,
    find_video,
    load_evidence,
)


class CoachEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def run_dir(self, name="game", **options):
        return make_run(self.root / name, **options)

    def frames(self, run):
        return run / COACH_DIR / FRAMES_DIR

    def rewrite_tracks(self, run, change):
        path = run / "tracks.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        path.write_text("".join(json.dumps(change(record)) + "\n" for record in records))

    def assert_moments_well_formed(self, evidence, maximum=12):
        moments = evidence["moments"]
        self.assertTrue(0 < len(moments) <= maximum)
        self.assertEqual(
            [m["id"] for m in moments], [f"m{i:02d}" for i in range(1, len(moments) + 1)]
        )
        times = [m["time_s"] for m in moments]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(b - a >= 1.0 for a, b in zip(times, times[1:], strict=False)))
        for moment in moments:
            self.assertEqual(moment["frame"], f"{moment['id']}.jpg")
            self.assertEqual(
                len(moment["frame_times_s"]), 4 if moment["layout"] == "sequence" else 1
            )
            self.assertEqual(
                (moment["start_s"], moment["end_s"]),
                (min(moment["frame_times_s"]), max(moment["frame_times_s"])),
            )
            self.assertTrue(moment["caption"].startswith(f"Moment {moment['id']} · "))

    def test_positions_drop_the_spectator_and_measure_zones_staggering_and_arrival(self):
        evidence = build_evidence(self.run_dir())
        self.assertEqual(evidence["version"], EVIDENCE_VERSION)
        self.assertEqual(evidence["tracking"]["avg_on_court_players"], 4.0)
        self.assertEqual(evidence["tracking"]["on_court_player_coverage"], 1.0)
        positioning = evidence["positioning"]
        self.assertTrue(positioning["available"])
        self.assertIsNone(positioning["reason"])
        near, far = positioning["sides"]["near"], positioning["sides"]["far"]
        self.assertEqual((near["samples"], near["avg_players"], far["avg_players"]), (40, 2.0, 2.0))
        # 40 frames: the near-right player is 4.2 m back for 25, then at the kitchen for 15.
        self.assertAlmostEqual(near["zone_share"]["kitchen"], 55 / 80, places=2)
        self.assertAlmostEqual(near["zone_share"]["transition"], 25 / 80, places=2)
        self.assertEqual(near["zone_share"]["baseline"], 0.0)
        self.assertAlmostEqual(near["staggered_share"], 25 / 40, places=2)
        self.assertAlmostEqual(near["both_at_kitchen_share"], 15 / 40, places=2)
        self.assertAlmostEqual(near["avg_depth_m"], 2.4, places=2)
        self.assertEqual(near["avg_partner_spacing_m"], 3.0)
        self.assertEqual(far["zone_share"], {"kitchen": 1.0, "transition": 0.0, "baseline": 0.0})
        self.assertEqual((far["both_at_kitchen_share"], far["staggered_share"]), (1.0, 0.0))
        [rally] = positioning["rallies"]
        self.assertEqual((rally["rally_id"], rally["start_s"], rally["end_s"]), (1, 0.5, 3.5))
        self.assertEqual(rally["near"]["kitchen_arrival_s"], 2.0)
        self.assertEqual(rally["far"]["kitchen_arrival_s"], 0.0)
        first = evidence["moments"][0]
        self.assertEqual(
            first["positions"]["near"],
            [
                {"x_m": 1.5, "depth_m": 1.5, "zone": "kitchen"},
                {"x_m": 4.5, "depth_m": 4.2, "zone": "transition"},
            ],
        )
        self.assertIn("staggered 2.7 m", first["caption"])
        self.assertIn("Far: 2 players", first["caption"])
        self.assertIn("both at the kitchen line", first["caption"])
        self.assertEqual(json.loads(json.dumps(evidence, allow_nan=False)), evidence)

    def test_each_side_keeps_its_two_most_confident_players_and_survives_bad_track_lines(self):
        run = self.run_dir()

        def add_bystander(record):
            # Inside the court margin on the near side, but less confident than both players.
            near = record["players"][0]
            record["players"].append(
                {
                    **near,
                    "box": [near["box"][0] + 2, *near["box"][1:]],
                    "confidence": 0.3,
                    "track_id": 99,
                }
            )
            return record

        self.rewrite_tracks(run, add_bystander)
        with (run / "tracks.jsonl").open("a") as stream:
            stream.write("{not json\n")
            stream.write(json.dumps({"index": 41, "time_s": 4.1, "pad": "x" * 70_000}) + "\n")
            stream.write(
                json.dumps(
                    {
                        "index": 42,
                        "time_s": 4.2,
                        "players": [
                            {"box": [1, 2, "3", 4], "confidence": 0.9},
                            {"box": [5, 5, 4, 4], "confidence": 0.9},
                            "player",
                        ],
                    }
                )
                + "\n"
            )
            stream.write('{"index": 43, "time_s": NaN, "players": []}\n')
        evidence = build_evidence(run)
        near = evidence["positioning"]["sides"]["near"]
        # 40 frames with two near players, plus frame 42 (read after the skipped oversized
        # line) whose detections are all invalid; malformed and NaN-time lines are ignored.
        self.assertEqual((near["samples"], near["avg_players"]), (40, round(80 / 41, 2)))
        self.assertTrue(all(len(m["positions"]["near"]) <= 2 for m in evidence["moments"]))
        self.assertAlmostEqual(near["zone_share"]["transition"], 25 / 80, places=2)

    def test_moments_cover_rallies_shots_and_positioning_without_duplicates(self):
        evidence = build_evidence(self.run_dir(duration_s=12.0))
        self.assert_moments_well_formed(evidence)
        moments = evidence["moments"]
        kinds = {m["kind"] for m in moments}
        self.assertTrue({"rally_start", "shot", "positioning", "rally_end", "overview"} <= kinds)
        start = next(m for m in moments if m["kind"] == "rally_start")
        self.assertEqual((start["time_s"], start["layout"], start["rally_id"]), (2.0, "single", 1))
        shots = [m for m in moments if m["kind"] == "shot"]
        self.assertEqual([m["time_s"] for m in shots], [3.0, 6.0, 9.0])
        self.assertEqual(
            [m["title"] for m in shots],
            ["Shot 1 of rally 1", "Shot 2 of rally 1", "Shot 3 of rally 1"],
        )
        self.assertTrue(all(m["layout"] == "sequence" for m in shots))
        self.assertEqual(shots[0]["frame_times_s"], [2.7, 2.9, 3.1, 3.3])
        self.assertIn(
            "2×2 sequence 0:02.7–0:03.3 (read left→right, top→bottom)", shots[0]["caption"]
        )
        flag = next(m for m in moments if m["kind"] == "positioning")
        # Flags skip the serve/return phase and end when the near player reaches the kitchen.
        self.assertTrue(3.5 <= flag["time_s"] < 7.5)
        self.assertEqual((flag["title"], flag["rally_id"]), ("Near side staggered", 1))
        self.assertNotIn(
            "No rallies were detected; moments are evenly spaced over the video.",
            evidence["warnings"],
        )

    def test_videos_without_rallies_still_get_positioning_and_overview_moments(self):
        evidence = build_evidence(self.run_dir(duration_s=12.0, rallies=False))
        self.assert_moments_well_formed(evidence)
        kinds = [m["kind"] for m in evidence["moments"]]
        self.assertTrue(set(kinds) <= {"positioning", "bounce", "overview"})
        self.assertIn("positioning", kinds)
        self.assertGreaterEqual(kinds.count("overview"), 5)
        self.assertTrue(all(m["rally_id"] is None for m in evidence["moments"]))
        self.assertEqual(evidence["positioning"]["rallies"], [])
        self.assertIn(
            "No rallies were detected; moments are evenly spaced over the video.",
            evidence["warnings"],
        )

    def test_moment_cap_keeps_the_highest_priority_buckets(self):
        run = self.run_dir(duration_s=12.0)
        evidence = build_evidence(run, max_moments=3)
        self.assert_moments_well_formed(evidence, maximum=3)
        self.assertEqual(
            [(m["kind"], m["time_s"]) for m in evidence["moments"]],
            [("rally_start", 2.0), ("shot", 3.0), ("shot", 6.0)],
        )
        self.assertEqual(
            sorted(p.name for p in self.frames(run).iterdir()), ["m01.jpg", "m02.jpg", "m03.jpg"]
        )
        for invalid in (0, 21, True, 2.5):
            with self.subTest(max_moments=invalid), self.assertRaises(ValueError):
                build_evidence(run, max_moments=invalid)

    def test_shot_moments_are_shared_across_rallies_and_spread_within_them(self):
        stats = {
            "rallies": [
                {
                    "id": 1,
                    "start_s": 0.0,
                    "end_s": 20.0,
                    "shots": 9,
                    "crossing_times_s": [2.0 * i for i in range(1, 10)],
                },
                {
                    "id": 2,
                    "start_s": 30.0,
                    "end_s": 40.0,
                    "shots": 3,
                    "crossing_times_s": [32.0, 34.0, 36.0],
                },
                {"id": 3, "start_s": 50.0, "end_s": 55.0, "shots": 1, "crossing_times_s": [52.0]},
            ],
            "crossing_events": [],
            "in_out_calls": [],
        }
        moments = coach_evidence._select_moments(stats, [], False, 60.0, 12)
        self.assertEqual(
            [m["time_s"] for m in moments if m["kind"] == "shot"], [6.0, 14.0, 34.0, 52.0]
        )
        self.assertEqual(
            [m["time_s"] for m in moments if m["kind"] == "rally_start"], [0.5, 30.5, 50.5]
        )
        self.assertEqual([m["time_s"] for m in moments if m["kind"] == "rally_end"], [20.0, 40.0])
        self.assertEqual(len(moments), 12)

    def test_frames_are_cropped_labelled_jpegs_inside_the_coach_folder(self):
        run = self.run_dir(duration_s=12.0)
        before = {p for p in run.rglob("*")}
        evidence = build_evidence(run)
        added = {p for p in run.rglob("*")} - before
        self.assertTrue(added)
        self.assertTrue(all(p.is_relative_to(run / COACH_DIR) for p in added))
        self.assertEqual(
            {p.name for p in self.frames(run).iterdir()}, {m["frame"] for m in evidence["moments"]}
        )
        for moment in evidence["moments"]:
            with self.subTest(moment=moment["id"]):
                path = self.frames(run) / moment["frame"]
                self.assertTrue(FRAME_NAME.fullmatch(path.name))
                self.assertEqual(path.read_bytes()[:3], b"\xff\xd8\xff")
                image = cv2.imread(str(path))
                height, width = image.shape[:2]
                if moment["layout"] == "single":
                    self.assertLessEqual(max(height, width), 1280)
                    # Cropped to the court, not the whole 320×180 frame.
                    self.assertTrue(200 < width < 320 and 100 < height < 180)
                else:
                    tile_w, tile_h = (width - 4) / 2, (height - 4) / 2
                    self.assertTrue(tile_w.is_integer() and tile_h.is_integer())
                    self.assertLessEqual(max(tile_w, tile_h), 760)
                    # The separator between the tiles is the dark background.
                    self.assertLess(image[:, int(tile_w) : int(tile_w) + 4].mean(), 40)
                # A dark timestamp label sits at the top-left corner.
                self.assertLess(image[:4, :4].mean(), 40)

    def test_load_evidence_requires_matching_stats_video_and_frames(self):
        run = self.run_dir()
        evidence = build_evidence(run)
        self.assertEqual(load_evidence(run), evidence)
        self.assertEqual(json.loads((run / COACH_DIR / "evidence.json").read_text()), evidence)
        stats = json.loads((run / "stats.json").read_text())
        stats["session_name"] = "Renamed"
        (run / "stats.json").write_text(json.dumps(stats))
        self.assertIsNone(load_evidence(run))
        rebuilt = ensure_evidence(run)
        self.assertNotEqual(rebuilt["stats_sha256"], evidence["stats_sha256"])
        self.assertEqual(load_evidence(run), rebuilt)
        (self.frames(run) / rebuilt["moments"][-1]["frame"]).unlink()
        self.assertIsNone(load_evidence(run))
        rebuilt = build_evidence(run)
        saved = run / COACH_DIR / "evidence.json"
        saved.write_text(json.dumps({**rebuilt, "version": EVIDENCE_VERSION + 1}))
        self.assertIsNone(load_evidence(run))
        saved.write_text("{broken")
        self.assertIsNone(load_evidence(run))
        build_evidence(run)
        shutil.copy2(run / "source.mp4", run / "prepared.mp4")
        (run / "source.mp4").unlink()
        self.assertIsNone(load_evidence(run))  # evidence came from another video
        self.assertIsNone(load_evidence(self.root / "missing"))

    def test_ensure_evidence_reuses_valid_evidence_without_rebuilding(self):
        run = self.run_dir()
        first = ensure_evidence(run)
        with patch(
            "vantage.coach_evidence.build_evidence",
            side_effect=AssertionError("Unexpected rebuild"),
        ):
            self.assertEqual(ensure_evidence(run), first)

    def test_rebuild_removes_stale_moment_frames(self):
        run = self.run_dir(duration_s=12.0)
        build_evidence(run)
        build_evidence(run, max_moments=2)
        self.assertEqual(sorted(p.name for p in self.frames(run).iterdir()), ["m01.jpg", "m02.jpg"])

    def test_chat_stills_survive_a_rebuild_only_for_the_same_stats_and_video(self):
        run = self.run_dir()
        evidence = build_evidence(run)
        extract_moment_frames(run, evidence, 2.0)
        chat = self.frames(run) / "t-000020.jpg"
        build_evidence(run)  # e.g. a forced re-analysis of the same game
        self.assertTrue(chat.is_file())
        stats = json.loads((run / "stats.json").read_text())
        stats["session_name"] = "Analyzed again"
        (run / "stats.json").write_text(json.dumps(stats))
        evidence = ensure_evidence(run)
        self.assertFalse(chat.exists())
        extract_moment_frames(run, evidence, 2.0)
        shutil.copy2(run / "source.mp4", run / "prepared.mp4")
        (run / "source.mp4").unlink()
        ensure_evidence(run)  # evidence now comes from another video
        self.assertFalse(chat.exists())

    def test_on_demand_sequence_is_bounded_reused_and_pruned(self):
        run = self.run_dir()
        evidence = build_evidence(run)
        result = extract_moment_frames(run, evidence, 2.04)
        self.assertEqual(
            (result["id"], result["frame"], result["time_s"]), ("t-000020", "t-000020.jpg", 2.0)
        )
        self.assertEqual(result["frame_times_s"], [1.4, 1.8, 2.2, 2.6])
        self.assertEqual((result["start_s"], result["end_s"]), (1.4, 2.6))
        self.assertEqual(result["positions"]["near"][1]["zone"], "transition")
        self.assertIn(
            "Moment t-000020 · 0:02.0 · Requested moment · 2×2 sequence 0:01.4–0:02.6",
            result["caption"],
        )
        path = self.frames(run) / "t-000020.jpg"
        image = cv2.imread(str(path))
        self.assertEqual(image.shape[2], 3)
        with patch(
            "cv2.VideoCapture", side_effect=AssertionError("Reused frames are not decoded again")
        ):
            self.assertEqual(extract_moment_frames(run, evidence, 2.0), result)
        start = extract_moment_frames(run, evidence, 0)
        self.assertEqual((start["start_s"], start["frame_times_s"][:2]), (0.0, [0.0, 0.0]))
        end = extract_moment_frames(run, evidence, evidence["video"]["duration_s"])
        self.assertEqual(end["end_s"], 3.9)
        for invalid in (-0.1, 4.1, math.nan, math.inf, True, "1", None):
            with self.subTest(at_s=invalid), self.assertRaises(EvidenceError):
                extract_moment_frames(run, evidence, invalid)
        # Keep the 60 most recently used chat sequences and never touch key-moment frames.
        old = time.time() - 3600
        for i in range(70):
            stale = self.frames(run) / f"t-{900000 + i:06d}.jpg"
            stale.write_bytes(b"old")
            os.utime(stale, (old + i, old + i))
        extract_moment_frames(run, evidence, 3.0)
        chat = sorted(p.name for p in self.frames(run).glob("t-*.jpg"))
        self.assertEqual(len(chat), 60)
        self.assertIn("t-000030.jpg", chat)
        self.assertNotIn("t-900000.jpg", chat)
        self.assertIn("t-900069.jpg", chat)
        self.assertIsNotNone(load_evidence(run))

    def test_cancellation_stops_before_evidence_is_saved(self):
        run = self.run_dir()
        with self.assertRaisesRegex(EvidenceError, "^Cancelled.$"):
            build_evidence(run, cancelled=lambda: True)
        stages = []
        with self.assertRaisesRegex(EvidenceError, "^Cancelled.$"):
            build_evidence(
                run,
                progress=stages.append,
                cancelled=lambda: any(s.startswith("Extracting frames (2") for s in stages),
            )
        self.assertEqual(
            stages[:3],
            ["Reading player tracks", "Picking key moments", "Extracting frames (1 of 3)"],
        )
        self.assertFalse((run / COACH_DIR / "evidence.json").exists())
        self.assertIsNone(load_evidence(run))

    def test_missing_homography_keeps_cropped_frames_without_positions(self):
        run = self.run_dir(duration_s=12.0)
        (run / "homography.npy").unlink()
        evidence = build_evidence(run)
        self.assertFalse(evidence["positioning"]["available"])
        self.assertIn("calibration", evidence["positioning"]["reason"])
        self.assertIsNone(evidence["positioning"]["sides"])
        self.assertIsNone(evidence["tracking"]["avg_on_court_players"])
        self.assertIn(evidence["positioning"]["reason"], evidence["warnings"])
        self.assert_moments_well_formed(evidence)
        self.assertTrue(
            {"rally_start", "shot", "bounce", "rally_end"}
            <= {m["kind"] for m in evidence["moments"]}
        )
        for moment in evidence["moments"]:
            self.assertEqual(moment["positions"], {"near": [], "far": []})
            self.assertIn("Player positions unavailable", moment["caption"])
            self.assertTrue((self.frames(run) / moment["frame"]).is_file())
        single = next(m for m in evidence["moments"] if m["layout"] == "single")
        self.assertLess(cv2.imread(str(self.frames(run) / single["frame"])).shape[1], 320)
        (run / "calibration.json").unlink()
        (run / "tracks.jsonl").unlink()
        evidence = build_evidence(run)
        self.assertEqual(cv2.imread(str(self.frames(run) / single["frame"])).shape[1], 320)
        self.assertFalse(evidence["positioning"]["available"])

    def test_missing_tracks_or_players_explain_unavailable_positions(self):
        run = self.run_dir()
        (run / "tracks.jsonl").unlink()
        self.assertIn("tracks", build_evidence(run)["positioning"]["reason"])
        (run / "tracks.jsonl").write_text(
            json.dumps({"index": 0, "time_s": 0.0, "players": []}) + "\n"
        )
        self.assertEqual(
            build_evidence(run)["positioning"]["reason"], "No players were detected on the court."
        )

    def test_video_choice_prefers_clean_files_inside_the_run(self):
        run = self.run_dir()
        self.assertEqual(find_video(run), ((run / "source.mp4").resolve(), False))
        shutil.copy2(run / "source.mp4", run / "annotated.mp4")
        (run / "source.mp4").unlink()
        self.assertEqual(find_video(run), ((run / "annotated.mp4").resolve(), True))
        evidence = build_evidence(run)
        self.assertEqual(
            (evidence["video"]["source"], evidence["video"]["has_overlays"]),
            ("annotated.mp4", True),
        )
        self.assertTrue(any("overlays" in warning for warning in evidence["warnings"]))
        outside = self.root / "outside.mp4"
        (run / "annotated.mp4").rename(outside)
        (run / "prepared.mp4").symlink_to(outside)
        self.assertIsNone(find_video(run))
        with self.assertRaisesRegex(EvidenceError, "no saved video"):
            build_evidence(run)
        with self.assertRaisesRegex(EvidenceError, "no saved video"):
            build_evidence(self.run_dir("silent", with_video=False))

    def test_never_writes_through_a_redirected_coach_folder(self):
        run = self.run_dir()
        outside = self.root / "elsewhere"
        outside.mkdir()
        (run / COACH_DIR).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            build_evidence(run)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertIsNone(load_evidence(run))

    def test_invalid_stats_are_reported_plainly(self):
        run = self.run_dir()
        (run / "stats.json").write_text('{"video": NaN}')
        with self.assertRaisesRegex(EvidenceError, "measurements couldn't be read"):
            build_evidence(run)
        (run / "stats.json").unlink()
        with self.assertRaisesRegex(EvidenceError, "measurements are missing"):
            build_evidence(run)


if __name__ == "__main__":
    unittest.main()
