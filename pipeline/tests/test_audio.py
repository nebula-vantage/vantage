import unittest

import numpy as np

from vantage.audio import hit_onsets
from helpers import AUDIO_RATE as RATE, add_pop, noise, settings


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()

    def test_pops_are_found_at_their_times(self):
        signal = noise(5)
        times = [0.5, 1.4, 2.25, 4.0]
        for t in times:
            add_pop(signal, t)
        onsets = hit_onsets(signal, RATE, self.cfg)
        self.assertEqual(len(onsets), len(times))
        for found, expected in zip(onsets, times):
            self.assertAlmostEqual(found, expected, delta=0.01)

    def test_steady_noise_and_slow_swell_are_not_hits(self):
        signal = noise(5) * np.linspace(0.2, 5, 5 * RATE).astype(np.float32)
        self.assertEqual(hit_onsets(signal, RATE, self.cfg), [])

    def test_echo_counts_once(self):
        signal = noise(2)
        add_pop(signal, 1.0)
        add_pop(signal, 1.08, amplitude=0.4)
        self.assertEqual(len(hit_onsets(signal, RATE, self.cfg)), 1)

    def test_too_short_is_empty(self):
        self.assertEqual(hit_onsets(np.zeros(10, np.float32), RATE, self.cfg), [])


if __name__ == "__main__":
    unittest.main()
