import math
from pathlib import Path
import tempfile
import unittest

from labeling import (LabelSession, best_raw_balls, evaluate, label_centers, load_labels, save_labels,
                      tracked_balls)


def frame(t, xs, conf=0.5):
    return {"timeSeconds": t, "width": 640, "height": 360, "inferenceMilliseconds": 1,
            "detections": [{"classID": 32, "confidence": conf, "box": [x - 3, 97, x + 3, 103]} for x in xs]
            + [{"classID": 0, "confidence": 0.9, "box": [10, 10, 60, 200]}]}


def session(candidates, suggestions, order=None):
    n = len(candidates)
    return LabelSession(order=order or list(range(n)), times=[i / 30 for i in range(n)],
                        candidates=candidates, suggestions=suggestions)


class LabelSessionTests(unittest.TestCase):
    def test_accept_uses_suggestion_and_advances(self):
        s = session([[]] * 3, [[1, 1, 5, 5], None, None])
        self.assertTrue(s.accept())
        self.assertEqual(s.labels[0], {"time_s": 0.0, "ball": [1, 1, 5, 5], "origin": "suggestion"})
        self.assertEqual(s.frame, 1)
        self.assertFalse(s.accept(), "no suggestion and no label: nothing to accept")
        self.assertEqual(s.frame, 1)

    def test_accept_keeps_clicked_label_over_suggestion(self):
        s = session([[([100, 100, 106, 106], .3)]], [[1, 1, 5, 5]])
        s.click(104, 102, snap_radius=10)
        self.assertEqual(s.label["origin"], "candidate")
        s.accept()
        self.assertEqual(s.labels[0]["ball"], [100, 100, 106, 106])

    def test_click_far_from_candidates_makes_manual_box_of_recent_size(self):
        s = session([[([100, 100, 106, 106], .3)], []], [None, None])
        s.click(103, 103, snap_radius=10)  # snaps: 6 px box
        s.move(1)
        s.click(300, 200, snap_radius=10)
        self.assertEqual(s.label, {"time_s": 1 / 30, "ball": [297.0, 197.0, 303.0, 203.0], "origin": "manual"})
        s.resize(2)
        self.assertEqual(s.label["ball"], [294.0, 194.0, 306.0, 206.0])

    def test_absent_clear_navigation_and_resume(self):
        s = session([[]] * 4, [None] * 4, order=[0, 2])
        s.mark_absent()
        self.assertEqual((s.labels[0]["ball"], s.frame), (None, 2))
        s.move(5)
        self.assertEqual(s.frame, 2, "navigation is clamped")
        s.clear()
        s.first_unlabeled()
        self.assertEqual(s.frame, 2)
        self.assertEqual(s.counts(), {"labeled": 1, "ball": 0, "absent": 1, "suggestions_accepted": 0})

    def test_save_load_round_trip_and_centers(self):
        labels = {7: {"time_s": .2, "ball": [0, 0, 4, 2], "origin": "manual"},
                  3: {"time_s": .1, "ball": None, "origin": "absent"}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sub" / "clip.json"
            save_labels(path, labels, video="v.mov", video_size=(640, 360), detections=None)
            self.assertEqual(load_labels(path), labels)
            self.assertEqual(list(path.parent.iterdir()), [path], "no temp files left behind")
        self.assertEqual(label_centers(labels), {"3": None, "7": [2.0, 1.0]})


class EvaluationTests(unittest.TestCase):
    def test_counts_correct_missed_and_false(self):
        labels = {0: {"ball": [0, 0, 10, 10]}, 1: {"ball": [0, 0, 10, 10]},
                  2: {"ball": None}, 3: {"ball": [50, 50, 60, 60]}}
        predictions = [[1, 1, 11, 11], [100, 100, 110, 110], [5, 5, 9, 9], None, [0, 0, 1, 1]]
        result = evaluate(predictions, labels, radius=5)
        self.assertEqual({k: result[k] for k in ("labeled", "visible", "correct", "missed", "false_detection")},
                         {"labeled": 4, "visible": 3, "correct": 1, "missed": 2, "false_detection": 2})
        self.assertAlmostEqual(result["recall"], 1 / 3)
        self.assertAlmostEqual(result["precision"], 1 / 3)

    def test_predictors_on_detections(self):
        # Moving ball plus a brighter static distractor at x=600.
        frames = [frame(i / 30, [100 + 10 * i]) for i in range(5)]
        for f in frames:
            f["detections"].append({"classID": 32, "confidence": 0.9, "box": [597, 97, 603, 103]})
        self.assertEqual(best_raw_balls(frames)[2], [597, 97, 603, 103], "detector alone picks the distractor")
        tracked = tracked_balls(frames)
        self.assertIsNone(tracked[0])
        self.assertTrue(all(math.isclose((b[0] + b[2]) / 2, 100 + 10 * i) for i, b in enumerate(tracked) if b))


if __name__ == "__main__":
    unittest.main()
