"""Offline GUI checks with real Tk: python -B -m unittest test_gui -v."""

from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import gui

READER = "https://vlearn.dev/course/python-basics/reader?day=1&part=2"


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        worker_patch = patch.object(gui, "download_worker")
        self.worker = worker_patch.start()
        self.addCleanup(worker_patch.stop)
        self.release = threading.Event()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.callback_errors = []
        self.root.report_callback_exception = (
            lambda *error: self.callback_errors.append(error)
        )
        self.app = gui.DownloaderApp(self.root)
        self.app.url.set(READER)
        self.app.folder.set(self.directory.name)
        self.root.update()

    def destroy_root(self):
        self.release.set()
        if hasattr(self, "app") and self.app.worker is not None:
            self.app.cancel_event.set()
            self.app.worker.join(timeout=3)
            self.assertFalse(self.app.worker.is_alive(), "Mock worker did not exit")
        if self.root.winfo_exists():
            for callback in self.root.tk.splitlist(
                self.root.tk.call("after", "info")
            ):
                self.root.after_cancel(callback)
            self.root.destroy()
        self.assertEqual(self.callback_errors, [], "Tk callback raised an exception")

    def pump_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("GUI did not reach the expected state before the deadline")

    def log(self):
        return self.app.log.get("1.0", "end-1c")

    def assert_idle_and_open(self):
        self.assertEqual(self.root.winfo_exists(), 1)
        self.assertIsNone(self.app.worker)
        self.assertFalse(self.app.start_button.instate(["disabled"]))
        self.assertTrue(self.app.cancel_button.instate(["disabled"]))
        self.assertFalse(self.app.url_entry.instate(["disabled"]))
        self.assertEqual(str(self.app.browser_combo.cget("state")), "readonly")

    def finish_with(self, kind, value):
        def worker(events, cancel_event, *args):
            events.put(("progress", "Progress retained"))
            events.put((kind, value))

        self.worker.side_effect = worker
        self.app.start_button.invoke()
        self.pump_until(lambda: self.app.worker is None)
        self.assert_idle_and_open()

    def widgets(self, parent=None):
        for widget in (parent or self.root).winfo_children():
            yield widget
            yield from self.widgets(widget)

    def test_constructs_real_native_controls_and_keeps_root_alive(self):
        widgets = list(self.widgets())
        self.assertTrue(any(isinstance(widget, ttk.Entry) for widget in widgets))
        self.assertTrue(any(isinstance(widget, ttk.Button) for widget in widgets))
        self.assertTrue(any(isinstance(widget, tk.Text) for widget in widgets))
        self.assertEqual(self.root.winfo_exists(), 1)
        self.assertTrue(self.app.cancel_button.instate(["disabled"]))
        self.assertTrue(self.app.open_pdf_button.instate(["disabled"]))

    def test_invalid_urls_never_create_a_thread_or_worker(self):
        invalid = (
            "", " ", "not a url",
            READER.replace("https:", "http:"),
            READER.replace("vlearn.dev", "vlearn.dev.evil.test"),
            READER.replace("vlearn.dev", "user@vlearn.dev"),
            READER.replace("&part=2", ""),
            READER.replace("/reader", "/edit"),
        )
        with patch.object(gui.threading, "Thread") as thread:
            for url in invalid:
                with self.subTest(url=url):
                    self.app.url.set(url)
                    before = self.log()
                    self.app.start_button.invoke()
                    self.root.update()
                    thread.assert_not_called()
                    self.worker.assert_not_called()
                    self.assertNotEqual(before, self.log())
                    self.assert_idle_and_open()

    def test_invalid_options_never_launch_worker(self):
        cases = (
            ("timeout", "0"), ("timeout", "-1"), ("timeout", "1.5"),
            ("timeout", "abc"), ("timeout", "86401"),
            ("folder", ""), ("browser", "firefox"),
            ("folder", str(Path(gui.__file__).resolve())),
        )
        with patch.object(gui.threading, "Thread") as thread:
            for name, value in cases:
                with self.subTest(name=name, value=value):
                    variable = getattr(self.app, name)
                    previous = variable.get()
                    variable.set(value)
                    self.app.start_button.invoke()
                    variable.set(previous)
                    thread.assert_not_called()
                    self.worker.assert_not_called()
                    self.assert_idle_and_open()

    def test_success_keeps_window_progress_and_saved_path(self):
        saved = Path(self.directory.name) / "slides.pdf"
        self.app.url.set("  " + READER + "  ")
        self.finish_with("success", saved)
        self.assertIn("Progress retained", self.log())
        self.assertIn(self.app.status.get(), self.log())
        self.assertEqual(self.app.saved_path, saved)
        self.assertEqual(self.app.saved_label.get(), str(saved))
        self.assertFalse(self.app.open_pdf_button.instate(["disabled"]))
        args = self.worker.call_args.args
        self.assertIs(args[0], self.app.events)
        self.assertIs(args[1], self.app.cancel_event)
        self.assertEqual(args[2:], (READER, Path(self.directory.name), "chrome", 300))

    def test_error_keeps_window_and_progress_available_for_retry(self):
        self.finish_with("error", "Download failed")
        self.assertEqual(self.app.status.get(), "Download failed")
        self.assertIn("Progress retained", self.log())
        self.assertIn("Download failed", self.log())
        self.assertTrue(self.app.open_pdf_button.instate(["disabled"]))
        self.finish_with("success", Path(self.directory.name) / "retry.pdf")
        self.assertEqual(self.worker.call_count, 2)
        self.assertIn("Download failed", self.log())

    def test_new_job_preserves_history_but_clears_old_success(self):
        self.finish_with("success", Path(self.directory.name) / "first.pdf")
        history = self.log()
        self.finish_with("error", "Second attempt failed")
        self.assertTrue(self.log().startswith(history))
        self.assertIsNone(self.app.saved_path)
        self.assertEqual(self.app.saved_label.get(), "")
        self.assertTrue(self.app.open_pdf_button.instate(["disabled"]))

    def test_cancel_signals_the_running_worker_and_keeps_window_open(self):
        started = threading.Event()
        received = []

        def worker(events, cancel_event, *args):
            received.append(cancel_event)
            events.put(("progress", "Waiting for login"))
            started.set()
            if not cancel_event.wait(3):
                events.put(("error", "Cancellation was not delivered"))
                return
            events.put(("cancelled", "Cancelled"))

        self.worker.side_effect = worker
        self.app.start_button.invoke()
        self.assertTrue(started.wait(1))
        self.pump_until(lambda: "Waiting for login" in self.log())
        self.app.cancel_button.invoke()
        self.assertTrue(received[0].is_set())
        self.assertTrue(self.app.cancel_button.instate(["disabled"]))
        self.pump_until(lambda: self.app.worker is None)
        self.assertEqual(self.app.status.get(), "Cancelled")
        self.assertIn("Waiting for login", self.log())
        self.assert_idle_and_open()
        self.assertTrue(self.app.open_pdf_button.instate(["disabled"]))
        self.finish_with("success", Path(self.directory.name) / "after-cancel.pdf")
        self.assertFalse(self.app.cancel_event.is_set())

    def test_running_job_blocks_button_and_direct_duplicate_starts(self):
        started = threading.Event()

        def worker(events, cancel_event, *args):
            started.set()
            self.release.wait(3)
            events.put(("error", "Stopped"))

        self.worker.side_effect = worker
        self.app.start_button.invoke()
        self.assertTrue(started.wait(1))
        original = self.app.worker
        for widget in (
            self.app.start_button, self.app.url_entry, self.app.folder_entry,
            self.app.browse_button, self.app.timeout_spin, self.app.browser_combo,
        ):
            self.assertTrue(widget.instate(["disabled"]))
        self.assertFalse(self.app.cancel_button.instate(["disabled"]))
        self.app.start_button.invoke()
        self.app.start()
        self.root.update()
        self.assertIs(self.app.worker, original)
        self.worker.assert_called_once()
        self.release.set()
        self.pump_until(lambda: self.app.worker is None)
        self.assert_idle_and_open()

    def test_thread_start_failure_restores_idle_ui(self):
        with patch.object(
            gui.threading.Thread, "start", side_effect=RuntimeError("Cannot start")
        ):
            self.app.start_button.invoke()
        self.worker.assert_not_called()
        self.assert_idle_and_open()
        self.assertTrue(self.log().strip())


if __name__ == "__main__":
    unittest.main()
