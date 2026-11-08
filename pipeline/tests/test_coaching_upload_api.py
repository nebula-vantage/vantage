"""HTTP contract and local-only boundaries for browser video analysis jobs."""

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch

from helpers import sign_in
from vantage.coaching_server import CoachingServer


class CoachingUploadAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job_id = "b" * 32
        self.job = {
            "id": self.job_id,
            "name": "Court practice.mov",
            "status": "preparing",
            "stage": "Preparing video",
            "progress": None,
            "frames_done": 0,
            "total_frames": 0,
            "error": None,
        }
        self.jobs = Mock()
        self.jobs.config.return_value = {
            "analysis_available": True,
            "max_upload_bytes": 536_870_912,
            "max_duration_s": 1200,
        }
        self.jobs.get.side_effect = lambda identity: (
            dict(self.job) if identity == self.job_id else None
        )
        self.received = []

        def receive(name, stream, length):
            self.received.append((name, stream.read(length), length))
            return dict(self.job)

        self.jobs.create_upload.side_effect = receive
        self.preview = self.root / "preview.png"
        self.preview.write_bytes(b"\x89PNG\r\n\x1a\nlocal-preview")
        self.jobs.preview.side_effect = lambda identity: (
            self.preview if identity == self.job_id else None
        )
        self.jobs.start.return_value = {**self.job, "status": "queued", "stage": "Queued"}
        self.jobs.cancel.return_value = {**self.job, "status": "cancelled", "stage": "Cancelled"}
        factory = patch("vantage.coaching_server.AnalysisJobs", return_value=self.jobs)
        factory.start()
        self.addCleanup(factory.stop)
        self.server = CoachingServer(("127.0.0.1", 0), self.root / "runs")
        self.cookie = sign_in(self.server)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.jobs.close.assert_called_once()

    def request(self, method, path, body=None, headers=None):
        headers = {"Cookie": self.cookie, **(headers or {})}
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            data = (
                json.loads(raw)
                if "application/json" in response.getheader("Content-Type", "") and raw
                else raw
            )
            return response.status, data, dict(response.getheaders())
        finally:
            connection.close()

    def upload(self, body=b"\x00video\xff\r\nbytes", name="Court%20practice.mov", headers=None):
        return self.request(
            "POST",
            f"/api/analysis?name={name}",
            body,
            {"Content-Type": "application/octet-stream", **(headers or {})},
        )

    def test_upload_transfers_exact_bytes_and_decodes_display_filename(self):
        content = b"\x00\xffbinary\r\nvideo\x00"
        status, body, headers = self.upload(content)
        self.assertEqual(status, 202)
        self.assertEqual(body, self.job)
        self.assertEqual(self.received, [("Court practice.mov", content, len(content))])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_configuration_includes_analysis_limits_without_credentials(self):
        # Never run the real `codex login status` check from a test.
        with (
            patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "private-test-key", "VANTAGE_COACH_MODEL": "test-model"},
            ),
            patch(
                "vantage.coach_engines.configuration",
                return_value={"engines": [], "default": None},
            ),
        ):
            status, config, _ = self.request("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertTrue(config["analysis_available"])
        self.assertEqual(config["max_upload_bytes"], 536_870_912)
        self.assertEqual(config["max_duration_s"], 1200)
        self.assertTrue(config["ai_available"])
        self.assertNotIn("private-test-key", json.dumps(config))

    def test_poll_preview_start_and_cancel_preserve_job_contract(self):
        self.job.update(
            status="awaiting_calibration",
            stage="Mark court corners",
            preview_url=f"/api/analysis/{self.job_id}/preview",
            video={"width": 1280, "height": 720, "fps": 30, "frame_count": 300, "duration_s": 10},
        )
        status, body, _ = self.request("GET", f"/api/analysis/{self.job_id}")
        self.assertEqual((status, body), (200, self.job))
        status, body, headers = self.request("GET", self.job["preview_url"])
        self.assertEqual((status, body), (200, self.preview.read_bytes()))
        self.assertEqual(headers["Content-Type"], "image/png")
        status, body, headers = self.request("HEAD", self.job["preview_url"])
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(int(headers["Content-Length"]), self.preview.stat().st_size)
        corners = [[120, 620], [1160, 620], [1000, 90], [270, 90]]
        status, body, _ = self.request(
            "POST", f"/api/analysis/{self.job_id}/start", {"corners": corners, "synthetic": True}
        )
        self.assertEqual((status, body["status"]), (202, "queued"))
        self.jobs.start.assert_called_once_with(self.job_id, corners, True)
        self.jobs.start.reset_mock()
        self.request("POST", f"/api/analysis/{self.job_id}/start", {"corners": corners})
        self.jobs.start.assert_called_once_with(self.job_id, corners, False)
        status, body, _ = self.request("POST", f"/api/analysis/{self.job_id}/cancel", {})
        self.assertEqual((status, body["status"]), (200, "cancelled"))
        self.jobs.cancel.assert_called_once_with(self.job_id)
        self.job.update(
            status="completed", stage="Complete", progress=1, session_id="result-session"
        )
        self.assertEqual(
            self.request("GET", f"/api/analysis/{self.job_id}")[1]["session_id"], "result-session"
        )

    def test_unknown_jobs_and_non_allowlisted_paths_are_not_files(self):
        for path in (
            "/api/analysis/missing",
            "/api/analysis/missing/preview",
            f"/api/analysis/{self.job_id}/source.mp4",
            f"/api/analysis/{self.job_id}/preview/private.json",
            "/api/analysis/../preview",
            "/api/analysis/%2e%2e/preview",
            "/.uploads/private/source.mp4",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)
        for action in ("start", "cancel"):
            self.assertEqual(self.request("POST", f"/api/analysis/missing/{action}", {})[0], 404)
        self.assertEqual(self.request("POST", f"/api/analysis/{self.job_id}/erase", {})[0], 404)
        self.jobs.start.assert_not_called()
        self.jobs.cancel.assert_not_called()

    def test_upload_rejects_bad_type_length_and_unconfigured_analysis_before_reading(self):
        self.assertEqual(self.upload(headers={"Content-Type": "video/mp4"})[0], 415)
        for length in ("0", "-1", str(536_870_913)):
            with self.subTest(length=length):
                self.assertEqual(self.upload(b"", headers={"Content-Length": length})[0], 413)
        self.assertEqual(self.upload(b"", headers={"Content-Length": "invalid"})[0], 400)
        self.jobs.config.return_value["analysis_available"] = False
        self.jobs.config.return_value["analysis_error"] = (
            "Install the bundled pickleball model to analyze videos."
        )
        status, body, _ = self.upload()
        self.assertEqual(status, 503)
        self.assertIn("bundled pickleball model", body["error"])
        self.jobs.create_upload.assert_not_called()

    def test_job_requests_reject_bad_json_types_and_surface_validation(self):
        target = f"/api/analysis/{self.job_id}/start"
        self.assertEqual(
            self.request("POST", target, b"{broken", {"Content-Type": "application/json"})[0], 400
        )
        self.assertEqual(
            self.request("POST", target, [], {"Content-Type": "application/json"})[0], 400
        )
        self.assertEqual(
            self.request("POST", target, b"{}", {"Content-Type": "text/plain"})[0], 415
        )
        self.jobs.start.side_effect = ValueError("Choose four non-crossing court corners.")
        status, body, _ = self.request("POST", target, {"corners": [[0, 0]]})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "Choose four non-crossing court corners.")
        self.jobs.create_upload.side_effect = ValueError(
            "Choose an MP4, MOV, M4V, WebM or AVI video."
        )
        self.assertEqual(self.upload(name="notes.txt")[0], 400)

    def test_cross_origin_and_rebinding_cannot_upload_start_or_cancel(self):
        for headers in (
            {"Origin": "https://attacker.example"},
            {"Origin": "null"},
            {"Host": "attacker.example"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.upload(headers=headers)[0], 403)
                for action in ("start", "cancel"):
                    self.assertEqual(
                        self.request("POST", f"/api/analysis/{self.job_id}/{action}", {}, headers)[
                            0
                        ],
                        403,
                    )
        self.jobs.create_upload.assert_not_called()
        self.jobs.start.assert_not_called()
        self.jobs.cancel.assert_not_called()
        self.assertEqual(
            self.upload(headers={"Origin": f"http://localhost:{self.server.server_port}"})[0], 202
        )

    def test_unexpected_errors_do_not_expose_paths_or_exception_bodies(self):
        for error, expected_status in (
            (OSError("/private/secret/disk"), 400),
            (RuntimeError("/private/secret/model"), 500),
        ):
            with self.subTest(error=type(error).__name__):
                self.jobs.create_upload.side_effect = error
                status, body, _ = self.upload()
                self.assertEqual(status, expected_status)
                self.assertNotIn("/private", json.dumps(body))
                self.assertLess(len(body["error"]), 200)
        self.jobs.start.side_effect = RuntimeError("/private/model/weights.pt")
        status, body, _ = self.request("POST", f"/api/analysis/{self.job_id}/start", {})
        self.assertEqual(status, 500)
        self.assertNotIn("/private", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
