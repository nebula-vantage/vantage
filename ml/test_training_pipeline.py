import json
from pathlib import Path
import tempfile
import unittest

import yaml

from build_dataset import external_samples, split_for, video_samples, yolo_line
import os
from unittest import mock

import fetch_roboflow
from fetch_roboflow import license_problem, parse_id
from labeling import save_labels
from vantage_classes import canonical_map, vantage_class


class ClassTests(unittest.TestCase):
    def test_coco_and_fine_tuned_names_map_to_canonical_ids(self):
        self.assertEqual(canonical_map({0: "person", 1: "bicycle", 32: "sports ball", 38: "tennis racket"}),
                         {0: 0, 32: 32, 38: 38})
        self.assertEqual(canonical_map({0: "player", 1: "ball", 2: "paddle"}), {0: 0, 1: 32, 2: 38})
        self.assertEqual(vantage_class(" Pickleball "), "ball")
        self.assertIsNone(vantage_class("net"))


class LicenseTests(unittest.TestCase):
    def test_policy(self):
        for ok in ("CC BY 4.0", "Public Domain", "MIT", "CC0 1.0", "Apache 2.0", "CC BY-SA 4.0"):
            self.assertIsNone(license_problem(ok), ok)
        for bad in ("CC BY-NC 4.0", "CC BY-NC-SA 4.0", "CC BY-ND 4.0", "", None, "Private"):
            self.assertIsNotNone(license_problem(bad), bad)

    def test_api_key_from_environment_then_private_file(self):
        with tempfile.TemporaryDirectory() as folder:
            key_file = Path(folder) / "roboflow_api_key"
            with mock.patch.object(fetch_roboflow, "KEY_FILE", key_file), \
                    mock.patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(fetch_roboflow.api_key())
                key_file.write_text("file-key\n")
                self.assertEqual(fetch_roboflow.api_key(), "file-key")
                with mock.patch.dict(os.environ, {"ROBOFLOW_API_KEY": "env-key"}):
                    self.assertEqual(fetch_roboflow.api_key(), "env-key")

    def test_parse_id(self):
        self.assertEqual(parse_id("acme/pickle-ball/3"), ("acme", "pickle-ball", 3))
        with self.assertRaises(ValueError):
            parse_id("acme/pickle-ball")


class DatasetTests(unittest.TestCase):
    def test_yolo_line_normalizes_and_clips(self):
        self.assertEqual(yolo_line("ball", [90, 40, 110, 60], 200, 100), "1 0.500000 0.500000 0.100000 0.200000")
        self.assertEqual(yolo_line("player", [-10, 0, 10, 100], 200, 100), "0 0.025000 0.500000 0.050000 1.000000")
        self.assertIsNone(yolo_line("ball", [250, 10, 260, 20], 200, 100), "entirely outside")

    def test_split_is_deterministic_and_roughly_proportional(self):
        self.assertEqual(split_for("clip:3", .15), split_for("clip:3", .15))
        val = sum(split_for(f"clip:{i}", .15) == "val" for i in range(2000))
        self.assertTrue(200 < val < 400, val)

    def test_video_samples_exclude_holdout_and_group_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            labels = {i: {"time_s": i / 30, "ball": None if i % 2 else [1, 1, 5, 5], "origin": "manual"}
                      for i in range(0, 120, 5)}
            for name in ("train-clip", "holdout-clip"):
                save_labels(Path(folder) / f"{name}.json", labels, video=f"assets/{name}.mov",
                            video_size=(640, 360), detections=None)
            samples = video_samples(folder, {"holdout-clip"}, 0.5)
            self.assertEqual({s[2] for s in samples}, {"labels/train-clip"})
            self.assertEqual(len(samples), 24)
            by_block = {}
            for split, key, source, video, frame, ball in samples:
                by_block.setdefault(int(frame / 30 // 2), set()).add(split)
            self.assertTrue(all(len(splits) == 1 for splits in by_block.values()), "a 2 s block never straddles splits")

    def test_external_samples_map_classes_and_splits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "ws__proj__v1"
            for split in ("train", "valid"):
                (root / split / "images").mkdir(parents=True)
                (root / split / "labels").mkdir(parents=True)
                (root / split / "images" / "a.jpg").write_bytes(b"x")
                (root / split / "labels" / "a.txt").write_text("0 0.5 0.5 0.01 0.01\n1 0.2 0.2 0.1 0.3\n2 0 0 0 0 0 0\n")
            (root / "data.yaml").write_text(yaml.safe_dump({"names": ["Pickleball", "net"]}))
            samples = external_samples(folder, [{"dir": "ws__proj__v1", "classes": {"Pickleball": "ball"}}])
            self.assertEqual([(s[0], s[4]) for s in samples],
                             [("train", [("ball", [0.5, 0.5, 0.01, 0.01])]), ("val", [("ball", [0.5, 0.5, 0.01, 0.01])])])
            self.assertEqual(samples[0][5], {"ball"})
            with self.assertRaises(SystemExit):
                external_samples(folder, [{"dir": "ws__proj__v1", "classes": {"Pickleball": "pickle"}}])

    def test_external_caps_and_only_with_ball(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "ds"
            (root / "train" / "images").mkdir(parents=True)
            (root / "train" / "labels").mkdir(parents=True)
            for i in range(10):
                (root / "train" / "images" / f"{i}.jpg").write_bytes(b"x")
                (root / "train" / "labels" / f"{i}.txt").write_text("0 0.5 0.5 0.01 0.01\n" if i % 2 else "")
            (root / "data.yaml").write_text(yaml.safe_dump({"names": ["ball"]}))
            entry = {"dir": "ds", "classes": {"ball": "ball"}}
            self.assertEqual(len(external_samples(folder, [entry])), 10)
            only = external_samples(folder, [{**entry, "only_with_ball": True}])
            self.assertEqual(sorted(s[1] for s in only), [f"ds__train__{i}" for i in (1, 3, 5, 7, 9)])
            capped = external_samples(folder, [{**entry, "max_train": 3}])
            self.assertEqual(len(capped), 3)
            self.assertEqual(capped, external_samples(folder, [{**entry, "max_train": 3}]), "deterministic")


if __name__ == "__main__":
    unittest.main()
