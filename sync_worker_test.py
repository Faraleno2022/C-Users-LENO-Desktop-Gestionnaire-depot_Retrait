"""Cycle de vie du thread Qt, sans réseau ni base réelle."""
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from app.services import sync_worker


class SyncWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def process_until(self, predicate, timeout=4):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertTrue(predicate())

    def test_success_and_failure_release_thread_and_allow_next_sync(self):
        controller = sync_worker.AutoSyncController()
        successes, failures = [], []
        controller.tick_finished.connect(successes.append)
        controller.tick_failed.connect(failures.append)
        with patch.object(sync_worker.settings_service, "is_sync_configured", return_value=True), patch.object(
                sync_worker, "close_connection") as close, patch.object(sync_worker.sync_service, "sync_all",
                side_effect=[{"pushed": {}, "pulled": {}}, sync_worker.sync_service.SyncError("hors ligne")]):
            try:
                self.assertTrue(controller.trigger_now())
                self.assertFalse(controller.trigger_now())
                self.process_until(lambda: not controller.is_busy)
                self.assertIsNone(controller._thread)
                self.assertTrue(controller.trigger_now())
                self.process_until(lambda: not controller.is_busy)
                self.assertEqual(len(successes), 1)
                self.assertEqual(failures, ["hors ligne"])
                self.assertEqual(close.call_count, 2)
            finally:
                controller.stop()

    def test_slow_network_keeps_thread_alive_until_finished(self):
        started, release = threading.Event(), threading.Event()
        controller = sync_worker.AutoSyncController()
        def slow(**kwargs):
            started.set()
            release.wait(6)
            return {}
        with patch.object(sync_worker.settings_service, "is_sync_configured", return_value=True), patch.object(
                sync_worker, "close_connection"), patch.object(sync_worker.sync_service, "sync_all", side_effect=slow):
            try:
                controller.trigger_now()
                self.assertTrue(started.wait(2))
                self.assertFalse(controller.stop())
                self.assertTrue(controller._thread.isRunning())
                self.assertTrue(controller.is_busy)
                release.set()
                self.process_until(lambda: not controller.is_busy)
                self.assertTrue(controller.stop())
            finally:
                release.set()
                controller.stop()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
