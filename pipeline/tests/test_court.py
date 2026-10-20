from pathlib import Path
import tempfile
import unittest

import numpy as np

from court import compute_homography, load_calibration, project, save_calibration
from tests.helpers import settings


class CourtTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()
        self.corners = [[20, 220], [300, 220], [280, 20], [40, 20]]

    def test_corner_mapping_and_inverse(self):
        h = compute_homography(self.corners, 320, 240, self.cfg)
        expected = [(0, 0), (6.10, 0), (6.10, 13.41), (0, 13.41)]
        np.testing.assert_allclose([project(p, h) for p in self.corners], expected, atol=1e-5)
        net = (3.05, 6.705)
        np.testing.assert_allclose(project(project(net, np.linalg.inv(h)), h), net, atol=1e-5)

    def test_invalid_corners(self):
        for corners in ([[0, 0]] * 4, [[0, 0], [319, 239], [319, 0], [0, 239]],
                        [[0, 0], [999, 0], [30, 30], [0, 30]]):
            with self.assertRaises(ValueError):
                compute_homography(corners, 320, 240, self.cfg)

    def test_cache_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            h = compute_homography(self.corners, 320, 240, self.cfg)
            save_calibration(path, h, self.corners, 320, 240)
            np.testing.assert_allclose(load_calibration(path, 320, 240, self.cfg), h)
            self.assertIsNone(load_calibration(path, 640, 480, self.cfg))
            np.save(path / 'homography.npy', np.eye(3))
            self.assertIsNone(load_calibration(path, 320, 240, self.cfg))
            (path / 'calibration.json').write_text('invalid')
            self.assertIsNone(load_calibration(path, 320, 240, self.cfg))

    def test_horizon_returns_none(self):
        self.assertIsNone(project((1, 0), np.array([[1, 0, 0], [0, 1, 0], [0, 1, 0]])))
