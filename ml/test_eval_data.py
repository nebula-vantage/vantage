import http.client
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import cv2
import eval_data
import numpy as np
from labeling import load_labels


class FakeResponse(io.BytesIO):
    def __init__(self, data, status, headers):
        super().__init__(data)
        self.status, self.headers = status, headers


def range_server(blob, requests):
    """open_url stand-in that serves byte ranges of blob and records each request."""

    def open_url(url, *, headers=None, opener=None, timeout=120):
        start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
        requests.append((start, end))
        return FakeResponse(
            blob[start : end + 1], 206, {"Content-Range": f"bytes {start}-{end}/{len(blob)}"}
        )

    return open_url


def write_video(path, frames, size=(64, 48), fps=30):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for _ in range(frames):
        writer.write(np.zeros((size[1], size[0], 3), np.uint8))
    writer.release()


class DownloadTests(unittest.TestCase):
    def serve(self, body, length):
        return lambda url, **kwargs: FakeResponse(body, 200, {"Content-Length": str(length)})

    @mock.patch.object(eval_data.time, "sleep")
    def test_cut_off_body_is_retried_and_never_kept(self, _sleep):
        serve = mock.Mock(side_effect=self.serve(b"frame,x\n1,2", 100))
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(eval_data, "open_url", serve):
            path = Path(temp) / "labels.csv"
            with self.assertRaises(OSError):
                eval_data.download("https://example.test/labels.csv", path, attempts=2)
            self.assertFalse(path.exists())
        self.assertEqual(serve.call_count, 2)

    def test_size_pin_rejects_a_changed_upload_and_repairs_a_short_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            with mock.patch.object(eval_data, "open_url", self.serve(b"0123456789", 10)):
                with self.assertRaises(ValueError):
                    eval_data.download("https://example.test/v.mp4", path, size=12)
                path.write_bytes(b"01234")  # left by an older, cut-off run
                eval_data.download("https://example.test/v.mp4", path, size=10)
            self.assertEqual(path.read_bytes(), b"0123456789")

    def test_download_many_passes_size_pins(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(eval_data, "open_url", self.serve(b"0123456789", 10)),
        ):
            with self.assertRaises(ValueError):
                eval_data.download_many([("https://example.test/a", Path(temp) / "a", 11)])

    def test_link_video_replaces_a_clip_left_from_an_older_download(self):
        with tempfile.TemporaryDirectory() as temp:
            download, clip = Path(temp) / "download.mp4", Path(temp) / "clips" / "c.mp4"
            download.write_bytes(b"01234")
            eval_data.link_video(download, clip)
            download.unlink()
            download.write_bytes(b"0123456789")  # re-downloaded: a new file, not the linked one
            eval_data.link_video(download, clip)
            self.assertEqual(clip.read_bytes(), b"0123456789")


class RemoteZipTests(unittest.TestCase):
    def test_reads_members_through_ranges_without_fetching_everything(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("big.bin", bytes(range(256)) * 40000)  # ~10 MB, never read
            archive.writestr("Dataset/game1/Label.csv", "file name,visibility\n0000.jpg,1\n")
        blob, requests = buffer.getvalue(), []
        with mock.patch.object(eval_data, "open_url", range_server(blob, requests)):
            archive = eval_data.remote_zip("https://example.test/data.zip")
            self.assertEqual(
                archive.read("Dataset/game1/Label.csv"), b"file name,visibility\n0000.jpg,1\n"
            )
        fetched = sum(end - start + 1 for start, end in requests)
        self.assertLess(fetched, len(blob) - 1_000_000, "should not download the unread member")

    @mock.patch.object(eval_data.time, "sleep")
    def test_a_whole_file_answer_is_never_read_as_a_range(self, _sleep):
        def open_url(url, *, headers=None, opener=None, timeout=120):
            if headers["Range"] == "bytes=0-0":
                return FakeResponse(b"P", 206, {"Content-Range": "bytes 0-0/1000"})
            return FakeResponse(b"<html>sign in</html>", 200, {})

        with mock.patch.object(eval_data, "open_url", open_url):
            remote = eval_data.RemoteFile("https://example.test/data.zip")
            with self.assertRaises(OSError):
                remote.read(10)

    @mock.patch.object(eval_data.time, "sleep")
    def test_wrong_or_cut_off_ranges_are_retried(self, _sleep):
        blob = bytes(range(256)) * 4
        answers = iter(["wrong offset", "cut off", "good"])

        def open_url(url, *, headers=None, opener=None, timeout=120):
            start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
            if start == end == 0:
                return FakeResponse(blob[:1], 206, {"Content-Range": f"bytes 0-0/{len(blob)}"})
            answer = next(answers)
            if answer == "wrong offset":
                # Right length, wrong bytes: only the Content-Range check can catch it.
                return FakeResponse(
                    blob[1:] + b"x", 206, {"Content-Range": f"bytes 1-{len(blob)}/{len(blob)}"}
                )
            response = FakeResponse(
                blob[start : end + 1], 206, {"Content-Range": f"bytes {start}-{end}/{len(blob)}"}
            )
            if answer == "cut off":
                response.read = mock.Mock(side_effect=http.client.IncompleteRead(b"partial"))
            return response

        with mock.patch.object(eval_data, "open_url", open_url):
            remote = eval_data.RemoteFile("https://example.test/data.bin")
            self.assertEqual(remote.read(len(blob)), blob)

    def test_extract_refuses_unsafe_names(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../escape.txt", "x")
        with tempfile.TemporaryDirectory() as temp, zipfile.ZipFile(buffer) as archive:
            with self.assertRaises(ValueError):
                eval_data.extract(archive, ["../escape.txt"], temp)

    @mock.patch.object(eval_data.time, "sleep")
    def test_range_must_match_requested_end_and_original_archive_size(self, _sleep):
        for header in ("bytes 0-8/10", "bytes 0-9/11", "bytes 0-9/*"):
            with self.subTest(header=header):
                responses = [FakeResponse(b"x", 206, {"Content-Range": "bytes 0-0/10"})]
                responses += [
                    FakeResponse(b"0123456789", 206, {"Content-Range": header}) for _ in range(4)
                ]
                with mock.patch.object(eval_data, "open_url", side_effect=responses) as network:
                    with eval_data.RemoteFile("https://example.test/archive") as remote:
                        with self.assertRaises(OSError):
                            remote.read(10)
                        self.assertEqual(remote.tell(), 0)
                self.assertEqual(network.call_count, 5)

    def test_probe_rejects_malformed_or_empty_archive_ranges(self):
        for header in ("bytes 1-1/10", "bytes 0-9/10", "bytes 0-0/0", "bytes 0-0/*", "invalid"):
            with self.subTest(header=header):
                with mock.patch.object(
                    eval_data,
                    "open_url",
                    return_value=FakeResponse(b"x", 206, {"Content-Range": header}),
                ):
                    with self.assertRaises(OSError):
                        eval_data.RemoteFile("https://example.test/archive")

    @mock.patch.object(eval_data.time, "sleep")
    def test_oversized_range_responses_are_bounded_and_rejected(self, _sleep):
        probe = FakeResponse(b"x", 206, {"Content-Range": "bytes 0-0/10"})
        responses = [
            FakeResponse(b"x" * 1000, 206, {"Content-Range": "bytes 0-9/10"}) for _ in range(4)
        ]
        for response in responses:
            response.read = mock.Mock(wraps=response.read)
        with mock.patch.object(eval_data, "open_url", side_effect=[probe, *responses]):
            with eval_data.RemoteFile("https://example.test/archive") as remote:
                with self.assertRaises(OSError):
                    remote.read(10)
        for response in responses:
            response.read.assert_called_once_with(11)

    def test_seeks_validate_arguments_without_moving_on_error(self):
        with mock.patch.object(eval_data, "open_url", range_server(b"0123456789", [])):
            with eval_data.RemoteFile("https://example.test/archive") as remote:
                self.assertEqual(remote.seek(3), 3)
                for offset, whence, error in (
                    (-1, io.SEEK_SET, ValueError),
                    (-4, io.SEEK_CUR, ValueError),
                    (0, 9, ValueError),
                    (1.5, io.SEEK_SET, TypeError),
                ):
                    with self.subTest(offset=offset, whence=whence), self.assertRaises(error):
                        remote.seek(offset, whence)
                    self.assertEqual(remote.tell(), 3)
                self.assertEqual(remote.seek(-2, io.SEEK_END), 8)
                self.assertEqual(remote.read(2), b"89")
                self.assertEqual(remote.seek(20), 20)
                self.assertEqual(remote.read(1), b"")

    def test_zero_length_reads_and_closed_operations_do_not_fetch(self):
        requests = []
        with mock.patch.object(eval_data, "open_url", range_server(b"0123456789", requests)):
            remote = eval_data.RemoteFile("https://example.test/archive")
            self.assertEqual(remote.readinto(bytearray()), 0)
            self.assertEqual(remote.tell(), 0)
            remote.close()
            for operation in (
                remote.tell,
                remote.readable,
                remote.seekable,
                lambda: remote.seek(0),
                lambda: remote.readinto(bytearray(1)),
            ):
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    operation()
        self.assertEqual(requests, [(0, 0)])


class WriteClipTests(unittest.TestCase):
    def test_points_become_schema_1_labels_with_extras(self):
        with tempfile.TemporaryDirectory(dir=eval_data.ROOT / "ml") as temp:
            root = Path(temp)
            video = root / "clips" / "c.mp4"
            video.parent.mkdir()
            write_video(video, 10)
            record = eval_data.write_clip(
                root,
                "c",
                video,
                {
                    0: (32, 24),
                    3: None,
                    6: {
                        "ball": (10, 20),
                        "visibility": "occluded",
                        "event": "bounce",
                        "interpolated": None,
                    },
                },
            )
            labels = load_labels(root / "labels" / "c.json")
        half = eval_data.BALL_BOX_FRACTION * 64 / 2
        self.assertEqual(
            labels[0]["ball"],
            [round(32 - half, 1), round(24 - half, 1), round(32 + half, 1), round(24 + half, 1)],
        )
        self.assertEqual(labels[3], {"time_s": 0.1, "ball": None, "origin": "absent"})
        self.assertEqual((labels[6]["visibility"], labels[6]["event"]), ("occluded", "bounce"))
        self.assertNotIn("interpolated", labels[6], "None extras are dropped")
        self.assertEqual(
            {k: record[k] for k in ("frames", "labeled", "visible", "events")},
            {"frames": 10, "labeled": 3, "visible": 2, "events": 1},
        )

    def test_paths_stay_inside_the_checkout_when_ml_external_is_a_symlink(self):
        with tempfile.TemporaryDirectory() as checkout, tempfile.TemporaryDirectory() as shared:
            checkout = Path(checkout).resolve()
            (checkout / "ml").mkdir()
            os.symlink(shared, checkout / "ml" / "external")
            root = checkout / "ml" / "external" / "eval" / "src"
            (root / "clips").mkdir(parents=True)
            write_video(root / "clips" / "c.mp4", 3)
            with mock.patch.object(eval_data, "ROOT", checkout):
                record = eval_data.write_clip(root, "c", root / "clips" / "c.mp4", {0: (1, 1)})
        self.assertEqual(record["video"], "ml/external/eval/src/clips/c.mp4")

    def test_labels_past_the_video_end_are_an_error(self):
        with tempfile.TemporaryDirectory(dir=eval_data.ROOT / "ml") as temp:
            video = Path(temp) / "c.mp4"
            write_video(video, 5)
            with self.assertRaises(ValueError):
                eval_data.write_clip(temp, "c", video, {5: (1, 1)})


class EncodeFramesTests(unittest.TestCase):
    def test_decoded_frame_i_is_image_i(self):
        with tempfile.TemporaryDirectory() as temp:
            images = []
            for i in range(12):
                path = Path(temp) / f"{i}.png"
                cv2.imwrite(str(path), np.full((48, 64, 3), i * 20, np.uint8))
                images.append(path)
            video = eval_data.encode_frames(images, 30, Path(temp) / "out.mp4")
            fps, frames, size = eval_data.video_info(video)
            capture = cv2.VideoCapture(str(video))
            brightness = [capture.read()[1].mean() for _ in range(frames)]
            capture.release()
        self.assertEqual((round(fps), frames, size), (30, 12, (64, 48)))
        for i, value in enumerate(brightness):
            self.assertAlmostEqual(value, i * 20, delta=3)


class OperatingPointTests(unittest.TestCase):
    def test_weak_balls_are_dropped_but_players_kept(self):
        from evaluate_external import drop_weak_balls

        frames = [
            {
                "detections": [
                    {"classID": 32, "confidence": 0.15, "box": [0, 0, 1, 1]},
                    {"classID": 32, "confidence": 0.25, "box": [5, 5, 6, 6]},
                    {"classID": 0, "confidence": 0.12, "box": [0, 0, 9, 9]},
                ]
            }
        ]
        kept = drop_weak_balls(frames, 0.20)[0]["detections"]
        self.assertEqual([(d["classID"], d["confidence"]) for d in kept], [(32, 0.25), (0, 0.12)])

    def test_operating_point_comes_from_the_model_card(self):
        from evaluate_external import card_ball_confidence

        self.assertEqual(
            card_ball_confidence(eval_data.ROOT / "ml" / "models" / "pickleball-v1.pt"), 0.2
        )
        self.assertIsNone(card_ball_confidence(Path("yolo26n.pt")))


if __name__ == "__main__":
    unittest.main()
