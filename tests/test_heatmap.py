from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from heatmap import landing_density, render_landing_heatmap
from records import BounceEvent
from tests.helpers import settings


def bounce(index, x, y):
    return BounceEvent(index, index/30, (100, 100), (x, y), 'IN', .9, ['heuristic_bounce'])


class HeatmapTests(unittest.TestCase):
    def setUp(self):
        self.cfg = settings()

    def test_duplicate_frame_counts_once_but_repeat_landings_count_twice(self):
        a = bounce(1, 3, 4)
        one, _, _ = landing_density([a], self.cfg)
        two, included, meta = landing_density([a, a, bounce(30, 3, 4)], self.cfg)
        self.assertEqual(len(included), 2)
        self.assertEqual(meta['duplicate_frames_removed'], 1)
        np.testing.assert_allclose(two, 2*one)

    def test_near_left_origin_is_bottom_left_and_far_end_is_top(self):
        near, _, _ = landing_density([bounce(1, 0, 0)], self.cfg)
        far, _, _ = landing_density([bounce(1, 6.1, 13.41)], self.cfg)
        ny, nx = np.unravel_index(near.argmax(), near.shape)
        fy, fx = np.unravel_index(far.argmax(), far.shape)
        scale = self.cfg['heatmap']['pixels_per_m']
        self.assertEqual(nx, round(2*scale))
        self.assertEqual(ny, round((13.41+2)*scale))
        self.assertEqual(fy, round(2*scale))
        self.assertEqual(fx, round((6.1+2)*scale))
        self.assertGreater(ny, fy)

    def test_outside_points_stay_outside_and_invalid_points_are_excluded(self):
        density, included, meta = landing_density([
            bounce(1, -1, 5), bounce(2, -3, 5), bounce(3, float('nan'), 5),
            bounce(4, 3, float('inf'))], self.cfg)
        self.assertEqual(len(included), 1)
        self.assertEqual(meta['excluded_candidates'], 3)
        _, x = np.unravel_index(density.argmax(), density.shape)
        self.assertEqual(x, 60)  # -1 m remains outside; it is not clamped to x=0.

    def test_empty_density_has_no_invented_hotspot_and_png_is_valid(self):
        density, _, _ = landing_density([], self.cfg)
        self.assertEqual(float(density.max()), 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'empty.png'
            meta = render_landing_heatmap(path, [], 0, self.cfg)
            self.assertEqual(meta['included_candidates'], 0)
            image = cv2.imread(str(path))
            self.assertIsNotNone(image)
            self.assertGreater(image.shape[0], 1000)

    def test_counts_and_margin_edges_match_image_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            points = [bounce(1, 0, 0), bounce(2, 6.1, 13.41),
                      bounce(3, -2, 0), bounce(4, 8.1, 15.41)]
            meta = render_landing_heatmap(Path(directory)/'map.png', points, .2133, self.cfg)
            self.assertEqual(meta['inside_candidates'], 2)
            self.assertEqual(meta['outside_candidates'], 2)
            self.assertEqual(meta['included_candidates'], 4)
            self.assertEqual(meta['ball_observation_coverage'], .2133)

    def test_invalid_smoothing_is_rejected(self):
        self.cfg['heatmap']['sigma_m'] = 0
        with self.assertRaises(ValueError):
            landing_density([], self.cfg)
