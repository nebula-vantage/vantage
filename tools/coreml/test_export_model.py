"""Exercise export publication without running expensive model conversion."""

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import export_model


class ExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.weights = self.root / "weights.pt"
        self.weights.write_bytes(b"original checkpoint")
        self.output = self.root / "published"
        self.args = ["--weights", str(self.weights), "--output", str(self.output)]
        self.enterContext(patch.dict(os.environ, {"YOLO_CONFIG_DIR": str(self.root / "config")}))

    def test_invalid_confidence_never_creates_output(self):
        for value in ("nan", "inf", "-0.1", "1.1"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    export_model.main([*self.args, "--ball-confidence", value])
                self.assertFalse(self.output.exists())

    def test_failed_export_cleans_staging_and_allows_retry(self):
        def fail(args, work_dir):
            (work_dir / "partial.mlpackage").mkdir()
            raise RuntimeError("conversion failed")

        with patch.object(export_model, "export_model", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "conversion failed"):
                export_model.main(self.args)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.iterdir()), [self.weights])

        def succeed(args, work_dir):
            (work_dir / "manifest.json").write_text("{}")
            return args.output / "VantageDetector.mlpackage"

        with (
            patch.object(export_model, "export_model", side_effect=succeed),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            export_model.main(self.args)
        self.assertTrue((self.output / "manifest.json").is_file())

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        marker = self.output / "keep"
        marker.write_bytes(b"existing export")
        with patch.object(export_model, "export_model") as convert:
            with self.assertRaises(FileExistsError):
                export_model.main(self.args)
        convert.assert_not_called()
        self.assertEqual(marker.read_bytes(), b"existing export")

    def test_manifest_identifies_copied_weights_and_final_package(self):
        weights = self.weights

        class FakeYOLO:
            names = {0: "ball"}

            def __init__(self, checkpoint):
                self.checkpoint = Path(checkpoint)

            def export(self, **options):
                weights.write_bytes(b"replacement checkpoint")
                package = self.checkpoint.with_suffix(".mlpackage")
                package.mkdir()
                return package

        class FakeModel:
            def __init__(self, package, **options):
                self.user_defined_metadata = {}

            def save(self, destination):
                path = Path(destination)
                path.mkdir()
                (path / "metadata.json").write_text(json.dumps(self.user_defined_metadata))

            def get_spec(self):
                return SimpleNamespace(
                    description=SimpleNamespace(input=["image"], output=["boxes"])
                )

        modules = {
            "ultralytics": SimpleNamespace(YOLO=FakeYOLO, __version__="test"),
            "coremltools": SimpleNamespace(
                models=SimpleNamespace(MLModel=FakeModel), __version__="test"
            ),
            "torch": SimpleNamespace(__version__="test"),
        }
        with patch.dict("sys.modules", modules), contextlib.redirect_stdout(io.StringIO()):
            export_model.main([*self.args, "--ball-confidence", "0.2"])
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(
            manifest["source_sha256"], hashlib.sha256(b"original checkpoint").hexdigest()
        )
        package = Path(manifest["package"])
        self.assertEqual(package, (self.output / "VantageDetector.mlpackage").resolve())
        self.assertTrue(package.is_dir())
        self.assertEqual(
            json.loads((package / "metadata.json").read_text())["vantage_ball_confidence"], "0.2"
        )
        self.assertEqual((self.output / "VantageDetector.pt").read_bytes(), b"original checkpoint")
        self.assertEqual(list(self.root.glob(".coreml-export-*")), [])
