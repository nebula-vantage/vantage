import base64
import unittest

import numpy as np

from make_hit_fixtures import build_fixture, swift_config, synthetic_pcm


class MakeHitFixturesTests(unittest.TestCase):
    def test_synthetic_recording_exercises_each_rule(self):
        fixture = build_fixture(synthetic_pcm(16000), 16000, "synthetic")
        # Clean hits count; the echo (0.88), the second of a close pair (2.35), the faint pop
        # (1.30) and the 200 Hz hum (1.0) don't; a two-hop rise counts once, at its peak (1.955).
        self.assertEqual(fixture["onsets"], [0.3, 0.8, 1.7, 1.955, 2.2, 2.7])
        self.assertEqual(fixture["hop"], 80)
        self.assertEqual(fixture["summary"], {"seconds": 3.0, "hops": 600, "onsets": 6})

    def test_samples_round_trip_as_little_endian_int16(self):
        pcm = np.array([0, 1, -1, 32767, -32768], np.int16)
        fixture = build_fixture(pcm, 16000, "tiny")
        decoded = np.frombuffer(base64.b64decode(fixture["pcm_s16le_base64"]), "<i2")
        np.testing.assert_array_equal(decoded, pcm)
        self.assertEqual(fixture["levels"], [])  # shorter than one hop
        self.assertEqual(fixture["onsets"], [])

    def test_config_uses_swift_property_names(self):
        config = swift_config()
        self.assertEqual(config["riseDecibels"], 11.0)
        self.assertEqual(len(config), 6)


if __name__ == "__main__":
    unittest.main()
