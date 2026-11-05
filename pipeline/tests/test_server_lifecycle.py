"""Server ownership holds during partial startup and failed cleanup."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vantage.coaching_server import CoachingServer, main


class ServerLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_partial_startup_releases_socket_workers_and_temporary_files(self):
        for boundary in ("PlaybackCache", "AnalysisJobs", "CoachService"):
            with self.subTest(boundary=boundary):
                server = CoachingServer.__new__(CoachingServer)
                with patch(
                    f"vantage.coaching_server.{boundary}",
                    side_effect=RuntimeError("startup failed"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "startup failed"):
                        server.__init__(("127.0.0.1", 0), self.root)
                self.assertEqual(server.socket.fileno(), -1)
                self.assertFalse(Path(server.playback_dir.name).exists())
                if hasattr(server, "jobs"):
                    server.jobs._worker.join(timeout=2)
                    self.assertFalse(server.jobs._worker.is_alive())
                # HTTPServer also closes itself on bind failures: repeated close is safe.
                server.server_close()

    def test_cleanup_failure_still_releases_remaining_resources(self):
        with patch("vantage.coaching_server.CoachService") as coach:
            coach.return_value.close.side_effect = RuntimeError("close failed")
            server = CoachingServer(("127.0.0.1", 0), self.root)
        with self.assertRaisesRegex(RuntimeError, "close failed"):
            server.server_close()
        server.jobs._worker.join(timeout=2)
        self.assertFalse(server.jobs._worker.is_alive())
        self.assertFalse(Path(server.playback_dir.name).exists())
        self.assertEqual(server.socket.fileno(), -1)
        server.server_close()
        coach.return_value.close.assert_called_once()

    def test_bind_failure_can_be_closed_repeatedly(self):
        server = CoachingServer.__new__(CoachingServer)
        with patch.object(CoachingServer, "server_bind", side_effect=OSError("bind failed")):
            with self.assertRaisesRegex(OSError, "bind failed"):
                server.__init__(("127.0.0.1", 0), self.root)
        self.assertEqual(server.socket.fileno(), -1)
        server.server_close()

    def test_browser_launch_failure_closes_server(self):
        with (
            patch("vantage.coaching_server.CoachingServer") as server,
            patch("vantage.coaching_server.webbrowser.open", side_effect=OSError("browser failed")),
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(OSError, "browser failed"):
                main(["--open", "--runs-dir", str(self.root)])
        server.return_value.server_close.assert_called_once()
        server.return_value.serve_forever.assert_not_called()
