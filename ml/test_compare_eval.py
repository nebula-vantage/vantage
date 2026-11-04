import copy
import unittest

from compare_eval import MARKER, cell, report
from eval_data import SOURCES, SUITES
import eval_sources  # noqa: F401  (registers the sources)


def totals(correct, visible, labeled, false_detection, **causes):
    return {"labeled": labeled, "visible": visible, "correct": correct, "false_detection": false_detection,
            "recall": correct / visible, "precision": correct / (correct + false_detection),
            **({"no_detection": 0, "elsewhere": 0, "not_selected": visible - correct} | causes)}


def run(correct=600, false_detection=50, sources=("src",)):
    group = {"tracked": totals(correct, 1000, 1200, false_detection), "raw best": totals(650, 1000, 1200, 200)}
    results = {key: copy.deepcopy(group) for key in ("sport:pickleball", "all:all")}
    results |= {f"source:{s}": copy.deepcopy(group) for s in sources}
    return {"setup": "model m.pt", "suite": "ci", "unfetched": [], "skipped": [],
            "sports": {s: "pickleball" for s in sources}, "results": results}


class ReportTests(unittest.TestCase):
    def test_without_a_base_it_reports_this_change_and_why(self):
        text = report(run(), head_label="this PR (abc1234)", base_error="the base predates this check")
        self.assertTrue(text.startswith(MARKER), "the workflow finds its comment by this marker")
        self.assertIn("No comparison: the base predates this check.", text)
        self.assertIn("| **All** | 60.0% | 92.3% | 65.0% | 76.5% |", text)

    def test_changes_are_flagged_by_size_and_direction(self):
        text = report(run(correct=620, false_detection=80), run())
        self.assertIn("**62.0% (+2.0, 20 frames 🟢)**", text, "recall up")
        self.assertIn("**88.6% (-3.7, 30 frames 🔴)**", text, "precision down: 30 more false detections")
        self.assertIn("65.0% (=)", text, "unchanged detector")
        self.assertIn("**38.0% (-2.0, 20 frames 🟢)**", text, "fewer tracker misses is better")
        self.assertNotIn("differ between the two runs", text)

    def test_small_or_few_frame_changes_are_shown_but_not_flagged(self):
        self.assertEqual(cell((0.603, 603), (0.6, 600)), "60.3% (+0.3, 3 frames)")
        self.assertEqual(cell((0.62, 2), (0.6, 1)), "62.0% (+2.0, 1 frame)", "big swing, but one frame")

    def test_the_displayed_delta_decides(self):
        self.assertEqual(cell((0.6046, 60), (0.6, 50)), "**60.5% (+0.5, 10 frames 🟢)**", "shows +0.5, so flagged")
        self.assertEqual(cell((0.6044, 60), (0.6, 50)), "60.4% (+0.4, 10 frames)")

    def test_different_scored_frames_and_failed_downloads_are_called_out(self):
        head, base = run(), run(sources=("src", "gone"))
        base["results"]["all:all"]["tracked"]["visible"] = 2000
        head["unfetched"] = ["kwyoke-badminton"]
        text = report(head, base, head_label="this PR")
        self.assertIn("scored frames differ", text)
        self.assertIn("| gone (pickleball) | - |", text, "a source only the base scored still gets a row")
        self.assertIn("Not scored for this PR: kwyoke-badminton", text)


class SuiteTests(unittest.TestCase):
    def test_suites_name_registered_sources_with_positive_frame_counts(self):
        for suite in SUITES.values():
            for source, frames in suite.items():
                self.assertIn(source, SOURCES)
                self.assertGreater(frames, 0)


if __name__ == "__main__":
    unittest.main()
