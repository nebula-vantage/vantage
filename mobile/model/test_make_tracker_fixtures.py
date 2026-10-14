import unittest

from make_tracker_fixtures import build_fixture, swift_config


def frame(t, balls):
    return {"timeSeconds": t, "width": 640, "height": 360, "inferenceMilliseconds": 1,
            "detections": [{"classID": 32, "confidence": 0.5, "box": [x - 2, 98, x + 2, 102]} for x in balls]
            + [{"classID": 0, "confidence": 0.9, "box": [10, 10, 50, 200]}]}


class MakeTrackerFixturesTests(unittest.TestCase):
    def test_records_selection_track_and_interpolation(self):
        # Moving ball with a two-frame gap (frames 3-4), which the trajectory interpolates.
        frames = [frame(i / 30, [] if i in (3, 4) else [100 + i * 10]) for i in range(8)]
        fixture = build_fixture(frames, "synthetic")
        rows = fixture["frames"]
        self.assertIsNone(rows[0]["ball"])  # acquisition needs two moving observations
        self.assertEqual(rows[1]["ball"], [108, 98, 112, 102, 0.5, 1])
        self.assertEqual([r["interpolated_track"] for r in rows], [None, None, None, 1, 1, None, None, None])
        self.assertEqual(rows[2]["candidates"], [[118, 98, 122, 102, 0.5]])  # players excluded
        self.assertEqual(fixture["summary"], {"frames": 8, "tracked": 5, "interpolated": 2, "tracks": 1})

    def test_config_uses_swift_property_names(self):
        config = swift_config()
        self.assertEqual(config["confidenceWeight"], 0.15)
        self.assertEqual(len(config), 14)


if __name__ == "__main__":
    unittest.main()
