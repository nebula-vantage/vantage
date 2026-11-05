"""Dataset publication is complete, bounded in memory, and retryable after failure."""

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fetch_roboflow import download_dataset, parse_id


def archive_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return stream.getvalue()


class DatasetDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root / "dataset"
        self.entry = {"id": "workspace/project/1", "license": "CC BY 4.0"}
        self.archive = archive_bytes(
            {"train/images/frame.jpg": b"image", "data.yaml": b"names: [ball]"}
        )

    def test_streams_export_and_publishes_complete_provenance(self):
        class BoundedResponse(io.BytesIO):
            def read(self, size=-1):
                if not 0 < size <= 1024 * 1024:
                    raise AssertionError("Download must use bounded reads")
                return super().read(size)

        with patch(
            "fetch_roboflow.urllib.request.urlopen", return_value=BoundedResponse(self.archive)
        ):
            download_dataset("https://example.test/export", self.destination, self.entry)
        self.assertEqual((self.destination / "train/images/frame.jpg").read_bytes(), b"image")
        self.assertEqual(json.loads((self.destination / "SOURCE.json").read_text()), self.entry)
        self.assertEqual(list(self.root.iterdir()), [self.destination])

    def test_interrupted_download_is_cleaned_up_and_can_be_retried(self):
        class InterruptedResponse(io.BytesIO):
            reads = 0

            def read(self, size=-1):
                self.reads += 1
                if self.reads > 1:
                    raise OSError("connection lost")
                return super().read(10)

        with patch(
            "fetch_roboflow.urllib.request.urlopen", return_value=InterruptedResponse(self.archive)
        ):
            with self.assertRaisesRegex(OSError, "connection lost"):
                download_dataset("https://example.test/export", self.destination, self.entry)
        self.assertEqual(list(self.root.iterdir()), [])
        with patch("fetch_roboflow.urllib.request.urlopen", return_value=io.BytesIO(self.archive)):
            download_dataset("https://example.test/export", self.destination, self.entry)
        self.assertTrue((self.destination / "SOURCE.json").is_file())

    def test_failed_extraction_never_publishes_partial_dataset(self):
        def failed_extract(archive, destination):
            (destination / "partial.jpg").write_bytes(b"incomplete")
            raise zipfile.BadZipFile("bad CRC")

        with (
            patch("fetch_roboflow.urllib.request.urlopen", return_value=io.BytesIO(self.archive)),
            patch.object(zipfile.ZipFile, "extractall", failed_extract),
        ):
            with self.assertRaisesRegex(zipfile.BadZipFile, "bad CRC"):
                download_dataset("https://example.test/export", self.destination, self.entry)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unsafe_archive_members_are_rejected_before_publication(self):
        for name in (
            "../escape.txt",
            "/absolute.txt",
            "train/../../escape.txt",
            "train\\escape.txt",
        ):
            with self.subTest(name=name):
                raw = archive_bytes({"valid.txt": b"valid", name: b"unsafe"})
                with patch("fetch_roboflow.urllib.request.urlopen", return_value=io.BytesIO(raw)):
                    with self.assertRaisesRegex(ValueError, "Unsafe archive"):
                        download_dataset(
                            "https://example.test/export", self.destination, self.entry
                        )
                self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_dataset_is_preserved_without_downloading(self):
        self.destination.mkdir()
        marker = self.destination / "existing.txt"
        marker.write_bytes(b"keep")
        with patch("fetch_roboflow.urllib.request.urlopen") as network:
            with self.assertRaises(FileExistsError):
                download_dataset("https://example.test/export", self.destination, self.entry)
        network.assert_not_called()
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_dataset_id_cannot_change_url_or_destination_structure(self):
        for value in (
            "../project/1",
            "workspace/../1",
            "/project/1",
            "workspace/project?key=value/1",
            "workspace/a\\b/1",
            "workspace/project/١",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_id(value)
