"""The 3-D replay recovers a known camera, ball flight, and players from one view."""

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from replay_fixtures import (
    CAMERA,
    FOCAL,
    HEIGHT,
    WIDTH,
    corners,
    doubles,
    flight,
    projection,
    write_run,
)
from vantage.coaching_server import WEB_ROOT
from vantage.config import CONFIG
from vantage.replay import (
    ReplayUnavailable,
    build_replay,
    camera_model,
    camera_view,
    demo_replay,
)


def position(replay, t):
    """The replay's ball position at time t, as the browser computes it."""
    g = replay["gravity_m_s2"]
    for piece in replay["ball"]:
        if piece["t0"] <= t <= piece["t1"]:
            tau = t - piece["t0"]
            p = np.array(piece["p0"]) + np.array(piece["v0"]) * tau
            p[2] -= 0.5 * g * tau * tau
            return p, piece["quality"]
    return None, None


class CameraTests(unittest.TestCase):
    def test_four_court_corners_recover_the_camera_that_saw_them(self):
        camera = camera_model(corners(projection()), WIDTH, HEIGHT, CONFIG)
        np.testing.assert_allclose(camera["center"], CAMERA, atol=0.02)
        self.assertAlmostEqual(camera["focal_px"], FOCAL, delta=5)
        self.assertTrue(camera["focal_estimated"])
        self.assertLess(camera["corner_error_px"], 0.5)
        view = camera_view(camera)
        np.testing.assert_allclose(view["position_m"], CAMERA, atol=0.02)
        self.assertAlmostEqual(
            view["vertical_fov_deg"], math.degrees(2 * math.atan(HEIGHT / 2 / FOCAL)), delta=0.2
        )
        # Looking down the court and slightly down at it, with the court's z axis up.
        self.assertGreater(view["forward"][1], 0.9)
        self.assertLess(view["forward"][2], 0)
        self.assertGreater(view["up"][2], 0.9)

    def test_overhead_court_falls_back_to_a_typical_lens(self):
        # Straight down at the court: perspective no longer constrains the focal length.
        p = projection(center=np.array([3.05, 6.7, 20.0]), target=(3.05, 6.71, 0.0))
        camera = camera_model(corners(p), WIDTH, HEIGHT, CONFIG)
        self.assertIsNotNone(camera)
        self.assertFalse(camera["focal_estimated"])


class ReplayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.run = Path(temp.name) / "run"

    def test_ball_flight_height_is_recovered_from_gravity(self):
        p0, v0 = (2.0, 2.0, 1.0), (0.5, 8.0, 4.0)
        rng = np.random.default_rng(7)

        def ball(t):
            if t > 0.9:
                return None
            return flight(p0, v0, t) + rng.normal(0, 0.004, 3)

        write_run(self.run, fps=60.0, frames=60, players=doubles, ball=ball)
        replay = build_replay(self.run)
        json.dumps(replay, allow_nan=False)
        for t in (0.1, 0.45, 0.8):
            estimate, quality = position(replay, t)
            self.assertEqual(quality, "fitted")
            # The ground projection alone would put the airborne ball metres too far away.
            np.testing.assert_allclose(estimate, flight(p0, v0, t), atol=0.25)
        self.assertGreater(replay["quality"]["ball_observations_used"], 0.9)

    def test_gaps_are_bridged_through_a_bounce_candidate(self):
        bounce_t, bounce = 0.65, np.array([3.0, 3.5, 0.0])
        incoming = np.array([0.0, -9.0, -1.0])
        start = bounce - incoming * bounce_t - 0.5 * np.array([0, 0, -9.81]) * bounce_t**2
        outgoing = np.array([0.2, -3.0, 4.5])

        def ball(t):
            if t <= 0.5:
                return flight(start, incoming, t)
            if 0.8 <= t <= 1.3:
                return flight(bounce, outgoing, t - bounce_t)
            return None

        events = [
            {
                "type": "bounce_candidate",
                "frame_index": 39,
                "time_s": bounce_t,
                "court": bounce[:2].tolist(),
                "call": "IN",
                "quality_flags": ["heuristic_bounce"],
            }
        ]
        write_run(self.run, fps=60.0, frames=84, players=doubles, ball=ball, events=events)
        replay = build_replay(self.run)
        qualities = [piece["quality"] for piece in replay["ball"]]
        self.assertIn("bridged", qualities)
        at_bounce, quality = position(replay, bounce_t)
        self.assertEqual(quality, "bridged")
        np.testing.assert_allclose(at_bounce, bounce, atol=0.05)
        for t in (0.25, 1.0):
            np.testing.assert_allclose(position(replay, t)[0], ball(t), atol=0.3)
        bounces = [e for e in replay["events"] if e["type"] == "bounce"]
        self.assertEqual(bounces[0]["court_m"], [3.0, 3.5])

    def test_players_keep_their_court_slots_and_spectators_are_left_out(self):
        def players(t):
            people = doubles(t)
            # ByteTrack loses the near-left player halfway and gives them a new ID.
            if t >= 1.0:
                people[0] = (7, *people[0][1:])
            return people

        write_run(self.run, fps=30.0, frames=60, players=players)
        replay = build_replay(self.run)
        labels = {p["label"]: p for p in replay["players"]}
        self.assertEqual(set(labels), {"Near left", "Near right", "Far left", "Far right"})
        rate = replay["player_rate_hz"]
        truth = {"Near left": 0, "Near right": 1, "Far right": 2, "Far left": 3}
        for label, index in truth.items():
            samples = labels[label]["samples"]
            self.assertTrue(all(samples), label)
            for i in (0, len(samples) // 2, len(samples) - 1):
                _, x, y = players(i / rate)[index]
                self.assertLess(math.dist(samples[i], (x, y)), 0.15, label)
            self.assertAlmostEqual(labels[label]["height_m"], 1.75, delta=0.05)
        self.assertEqual(replay["quality"]["player_count"], 4)

    def test_missing_or_mismatched_inputs_explain_what_to_do(self):
        write_run(self.run, fps=30.0, frames=10, players=doubles)
        (self.run / "tracks.jsonl").unlink()
        with self.assertRaisesRegex(ReplayUnavailable, "Analyze its video again"):
            build_replay(self.run)
        write_run(self.run, fps=30.0, frames=10, players=doubles)
        calibration = json.loads((self.run / "calibration.json").read_text())
        calibration["width"] = 1280
        (self.run / "calibration.json").write_text(json.dumps(calibration))
        with self.assertRaisesRegex(ReplayUnavailable, "calibration doesn't match"):
            build_replay(self.run)

    def test_a_run_without_ball_tracking_still_replays_the_players(self):
        write_run(self.run, fps=30.0, frames=30, players=doubles)
        replay = build_replay(self.run)
        self.assertEqual(replay["ball"], [])
        self.assertEqual(len(replay["players"]), 4)
        self.assertTrue(any("No ball flight" in w for w in replay["quality"]["warnings"]))


class DemoReplayTests(unittest.TestCase):
    def test_sample_game_replay_follows_its_rallies_and_is_labelled_synthetic(self):
        stats = json.loads((WEB_ROOT / "demo-stats.json").read_text())
        replay = demo_replay(stats)
        json.dumps(replay, allow_nan=False)
        self.assertTrue(replay["synthetic"])
        self.assertEqual(len(replay["rallies"]), len(stats["rallies"]))
        net = replay["court"]["net_y_m"]
        for player in replay["players"]:
            far = player["side"] == "far"
            self.assertTrue(all((s[1] > net) == far for s in player["samples"]), player["id"])
        times = [e["time_s"] for e in replay["events"]]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(p["t1"] > p["t0"] for p in replay["ball"]))
        # Every shot crosses the net: the ball is on the far side at one end of its flight.
        first = replay["ball"][0]
        self.assertNotEqual(first["p0"][1] > net, position(replay, first["t1"])[0][1] > net)


if __name__ == "__main__":
    unittest.main()
