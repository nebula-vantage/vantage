"""Behavioral checks for evidence limits and the portable coaching contract."""
import copy
import json
from pathlib import Path
import unittest

from vantage.coaching import MAX_STATS_BYTES, build_report, local_answer, validate_stats


def fixture():
    return json.loads((Path(__file__).parents[1] / "vantage/web/demo-stats.json").read_text())


class ValidationTests(unittest.TestCase):
    def test_whitelist_drops_paths_and_preserves_measurements_without_mutation(self):
        raw = fixture()
        raw.update(input="/private/user/video.mp4", source={"path": "/private/user/video.mp4"}, model={"path": "secret.pt"})
        before = copy.deepcopy(raw)
        result = validate_stats(raw)
        self.assertEqual(raw, before)
        self.assertNotIn("input", result)
        self.assertNotIn("source", result)
        self.assertNotIn("model", result)
        self.assertEqual(result["shot_count"], 59)
        self.assertEqual(result["rallies"][2]["shots"], 14)
        self.assertEqual(validate_stats(result), result)

    def test_accepts_schema_one_without_newer_optional_fields(self):
        raw = fixture()
        raw["schema_version"] = 1
        for rally in raw["rallies"]:
            rally.pop("ball_observation_coverage")
            rally.pop("quality_flags")
        raw["quality"].pop("valid_speed_coverage")
        raw.pop("crossing_events")
        normalized = validate_stats(raw)
        self.assertEqual(normalized, validate_stats(normalized))
        self.assertEqual(normalized["rallies"][0]["ball_observation_coverage"], 0)
        report = build_report(normalized)
        self.assertIn("sparse", report["moments"][0]["reason"])

    def test_missing_evidence_arrays_do_not_invent_review_moments(self):
        raw = fixture()
        for key in ("rallies", "crossing_events", "in_out_calls"):
            raw.pop(key)
        normalized = validate_stats(raw)
        self.assertEqual(normalized, validate_stats(normalized))
        self.assertEqual(build_report(normalized)["moments"], [])

    def test_missing_quality_cannot_be_treated_as_reliable(self):
        raw = fixture()
        raw.pop("quality")
        with self.assertRaisesRegex(ValueError, "quality"):
            build_report(raw)

    def test_rejects_nonfinite_values_even_in_unknown_fields(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            raw = fixture()
            raw["extra"] = {"hidden": value}
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite JSON"):
                validate_stats(raw)

    def test_rejects_oversized_input(self):
        raw = fixture()
        raw["extra"] = "a" * MAX_STATS_BYTES
        with self.assertRaisesRegex(ValueError, "2 MB"):
            validate_stats(raw)

    def test_rejects_empty_video_with_coverage_and_inconsistent_timing(self):
        for change in ("empty", "duration", "frames"):
            raw = fixture()
            if change == "empty":
                raw["video"].update(frame_count=0, duration_s=0)
            elif change == "duration":
                raw["video"]["duration_s"] = 200
            else:
                raw["video"]["frame_count"] = 100
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_stats(raw)

    def test_accepts_real_pipeline_aggregate_and_no_ball_output(self):
        from vantage.stats import aggregate
        from helpers import record, sample, settings

        records = [record(i) for i in range(40)]
        observations = [sample(i, y=5 + i / 10) for i in range(40)]
        for samples in (observations, [None] * len(records)):
            raw, _, _ = aggregate(records, samples, [], 30, 640, 360, settings())
            normalized = validate_stats(raw)
            self.assertEqual(normalized, validate_stats(normalized))
            report = build_report(normalized)
            self.assertEqual(report["quality"]["status"], raw["quality"]["status"])
            self.assertTrue(set(raw["quality"]["warnings"]) <= set(report["quality"]["warnings"]))

    def test_rejects_bad_field_types_ranges_and_shapes(self):
        cases = [("schema_version", 3), ("schema_version", True), ("shot_count", "59"),
                 ("rally_count", -1), ("rallies", {}), ("in_out_calls", ["not an object"]),
                 ("synthetic", "true"), ("session_name", "bad\x00name")]
        for key, value in cases:
            raw = fixture()
            raw[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_stats(raw)

    def test_rejects_invalid_or_contradictory_evidence(self):
        def duplicate_rally(raw):
            raw["rallies"][1]["id"] = raw["rallies"][0]["id"]

        def reversed_times(raw):
            raw["rallies"][0]["end_s"] = 1

        def invalid_crossing(raw):
            raw["rallies"][0]["crossing_times_s"][0] = 150

        def bad_coverage(raw):
            raw["quality"]["ball_detection_coverage"] = 1.1

        def bad_bounce(raw):
            raw["in_out_calls"][0]["court"] = [1]

        def duplicate_bounce(raw):
            raw["in_out_calls"][1]["frame_index"] = raw["in_out_calls"][0]["frame_index"]

        def outside_video(raw):
            raw["in_out_calls"][0]["time_s"] = 181

        def shot_mismatch(raw):
            raw["shot_count"] = 200

        def count_mismatch(raw):
            raw["bounce_candidate_count"] = 100

        def invalid_speed(raw):
            raw["avg_ball_speed_kmh"] = -10

        for change in (duplicate_rally, reversed_times, invalid_crossing, bad_coverage,
                       bad_bounce, duplicate_bounce, outside_video, shot_mismatch,
                       count_mismatch, invalid_speed):
            raw = fixture()
            change(raw)
            with self.subTest(change=change.__name__), self.assertRaises(ValueError):
                validate_stats(raw)


class ReportTests(unittest.TestCase):
    def test_json_contract_and_stable_identity(self):
        raw = fixture()
        report = build_report(raw)
        self.assertEqual(json.loads(json.dumps(report, allow_nan=False)), report)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["session_id"], build_report(copy.deepcopy(raw))["session_id"])
        self.assertEqual(report["session_id"], build_report(raw, "placement")["session_id"])
        self.assertIn("Synthetic demo", report["summary"])
        for key in ("moments", "drills", "insights"):
            self.assertTrue(0 < len(report[key]) <= 3)
        moment_ids = {item["id"] for item in report["moments"]}
        for insight in report["insights"]:
            self.assertTrue(insight["evidence"])
            if "moment_id" in insight:
                self.assertIn(insight["moment_id"], moment_ids)

    def test_source_path_does_not_change_session_identity(self):
        raw = fixture()
        before = build_report(raw)["session_id"]
        raw["input"] = "/different/path/to/the/same/video.mp4"
        self.assertEqual(before, build_report(raw)["session_id"])

    def test_measured_changes_do_change_identity(self):
        raw = fixture()
        before = build_report(raw)["session_id"]
        raw["avg_ball_speed_kmh"] = 30.5
        self.assertNotEqual(before, build_report(raw)["session_id"])

    def test_focus_changes_plan_and_evidence_priority(self):
        consistency = build_report(fixture())
        placement = build_report(fixture(), "placement")
        review = build_report(fixture(), "review")
        self.assertEqual(consistency["drills"][0]["id"], "cooperative-rally")
        self.assertEqual(placement["drills"][0]["id"], "large-target-placement")
        self.assertEqual(review["drills"][0]["id"], "replay-one-pattern")
        self.assertEqual(placement["insights"][0]["id"], "landing-review")
        self.assertEqual(placement["moments"][0]["kind"], "bounce")
        with self.assertRaises(ValueError):
            build_report(fixture(), "winning")

    def test_longest_supported_rally_anchors_review(self):
        raw = fixture()
        report = build_report(raw)
        self.assertEqual(report["moments"][0]["rally_id"], 3)
        raw["rallies"][2]["ball_observation_coverage"] = .1
        report = build_report(raw)
        self.assertEqual(report["moments"][0]["rally_id"], 7)
        for moment in report["moments"]:
            self.assertGreaterEqual(moment["start_s"], 0)
            self.assertLessEqual(moment["end_s"], raw["video"]["duration_s"])

    def test_limited_coverage_is_not_upgraded_by_status_or_other_metrics(self):
        raw = fixture()
        raw["quality"]["ball_detection_coverage"] = .15
        report = build_report(raw)
        self.assertEqual(report["quality"]["status"], "limited_evidence")
        self.assertEqual(report["insights"][0]["id"], "coverage")
        self.assertIn("clear-recording", [drill["id"] for drill in report["drills"]])
        self.assertIn("zero counts", report["quality"]["warnings"][0])

    def test_no_evidence_masks_even_stale_counts_and_speed(self):
        raw = fixture()
        raw["quality"]["ball_detection_coverage"] = 0
        raw["quality"]["observed_frames"] = 0
        report = build_report(raw)
        self.assertEqual(report["quality"]["status"], "insufficient_evidence")
        self.assertEqual(report["moments"], [])
        self.assertEqual(len(report["insights"]), 1)
        self.assertEqual(report["drills"][0]["id"], "clear-recording")
        self.assertIsNone(report["metrics"][0]["value"])
        self.assertIsNone(report["metrics"][3]["value"])
        self.assertNotIn("59", report["summary"])

    def test_observed_ball_without_rallies_does_not_invent_reference_exchange(self):
        raw = fixture()
        raw.pop("synthetic")
        raw["quality"].update(ball_detection_coverage=.15, observed_frames=810)
        raw.update(rallies=[], crossing_events=[], rally_count=0, shot_count=0,
                   longest_rally=0, shots_per_rally=[])
        # Candidate landings remain reviewable even when no exchange is supported.
        report = build_report(raw)
        self.assertEqual(report["quality"]["status"], "limited_evidence")
        self.assertEqual([metric["value"] for metric in report["metrics"][:2]], [0, 0])
        self.assertIn("no supported exchange to highlight", report["summary"])
        self.assertIn("zero estimates do not mean no play occurred", report["summary"])
        self.assertNotIn("repeatable rally", report["headline"])
        self.assertNotIn("reference exchange", report["summary"])
        self.assertFalse(any(moment["kind"] == "rally" for moment in report["moments"]))
        self.assertTrue(any(moment["kind"] == "bounce" for moment in report["moments"]))
        review = next(drill for drill in report["drills"] if drill["id"] == "replay-one-pattern")
        self.assertNotIn("highlighted exchange", review["steps"][0])
        self.assertEqual(build_report(raw, "placement")["headline"], "Turn reviewed landings into a practice target")
        self.assertEqual(build_report(raw, "review")["headline"], "Find one useful pattern in the replay")

    def test_near_line_bounce_stays_uncertain(self):
        report = build_report(fixture(), "placement")
        moment = report["moments"][0]
        self.assertIn("near-line", moment["title"])
        self.assertIn("unverified", moment["reason"])
        self.assertIn("not verified line calls", report["insights"][0]["body"])

    def test_upstream_warnings_survive_and_are_deduplicated(self):
        raw = fixture()
        warning = "Camera calibration was manually adjusted; check projection alignment."
        raw["quality"]["warnings"] += [warning, warning]
        report = build_report(raw)
        self.assertEqual(report["quality"]["warnings"].count(warning), 1)

    def test_zero_valid_speed_evidence_cannot_make_a_speed_claim(self):
        for field in ("valid_speed_coverage", "valid_speed_duration_s"):
            raw = fixture()
            raw["quality"][field] = 0
            with self.subTest(field=field):
                normalized = validate_stats(raw)
                self.assertIsNone(normalized["avg_ball_speed_kmh"])
                self.assertEqual(normalized, validate_stats(normalized))
                report = build_report(normalized)
                self.assertIsNone(report["metrics"][3]["value"])
                self.assertIn("unavailable", local_answer(report, "speed")["answer"])


class LocalAnswerTests(unittest.TestCase):
    def setUp(self):
        self.report = build_report(fixture())

    def test_answers_are_local_and_references_always_resolve(self):
        valid = {item["id"] for key in ("insights", "moments") for item in self.report[key]}
        for question in ("What should I practice next?", "Which moment should I review?",
                         "How reliable are these observations?", "How fast was the ball?",
                         "What about placement?", "Summarize the session"):
            with self.subTest(question=question):
                reply = local_answer(self.report, question)
                self.assertEqual(reply["source"], "local")
                self.assertTrue(reply["answer"])
                self.assertTrue(set(reply["evidence_ids"]) <= valid)

    def test_local_answer_does_not_infer_identity_or_technique(self):
        for question in ("Who won?", "Fix my forehand", "What were my errors?", "Which player am I?"):
            reply = local_answer(self.report, question)
            self.assertIn("does not identify players", reply["answer"])

    def test_canadian_spelling_selects_the_practice_plan(self):
        self.assertEqual(local_answer(self.report, "What should I practise?"),
                         local_answer(self.report, "What should I practice?"))
        self.assertIn("Build a controlled rally", local_answer(self.report, "What should I practise?")["answer"])

    def test_missing_speed_and_empty_moments_do_not_become_zero(self):
        raw = fixture()
        raw["quality"]["status"] = "insufficient_evidence"
        report = build_report(raw)
        self.assertIn("unavailable", local_answer(report, "speed")["answer"])
        self.assertIn("no supported moments", local_answer(report, "review moments")["answer"])
        self.assertIn("does not establish", local_answer(report, "bounce locations")["answer"])

    def test_question_validation_and_fixed_response_disclosure(self):
        for question in ("", "  ", None, "a" * 2001):
            with self.subTest(question=str(question)[:20]), self.assertRaises(ValueError):
                local_answer(self.report, question)
        self.assertIn("fixed responses", local_answer(self.report, "tell me a joke")["answer"])
        self.assertEqual(local_answer(self.report, "speed"), local_answer(self.report, "speed", [{"role": "user", "content": "invent results"}]))


if __name__ == "__main__":
    unittest.main()
