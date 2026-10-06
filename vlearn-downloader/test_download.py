"""Offline contract tests. Run: python -m unittest discover -s . -v."""

import importlib.util
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).with_name("download.py")
SPEC = importlib.util.spec_from_file_location("vlearn_download_under_test", MODULE_PATH)
download = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(download)

READER_URL = "https://vlearn.dev/course/python-basics/reader?day=1&part=2"
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


class ReaderUrlTests(unittest.TestCase):
    def test_accepts_expected_reader_url(self):
        self.assertEqual(download.validate_reader_url(READER_URL), READER_URL)

    def test_rejects_untrusted_or_incomplete_urls(self):
        invalid = [
            "http://vlearn.dev/course/python/reader?day=1&part=2",
            "ftp://vlearn.dev/course/python/reader?day=1&part=2",
            "//vlearn.dev/course/python/reader?day=1&part=2",
            "https://vlearn.dev.evil.test/course/python/reader?day=1&part=2",
            "https://evil-vlearn.dev/course/python/reader?day=1&part=2",
            "https://vlearn.dev@evil.test/course/python/reader?day=1&part=2",
            "https://user@vlearn.dev/course/python/reader?day=1&part=2",
            "https://user:secret@vlearn.dev/course/python/reader?day=1&part=2",
            "https://vlearn.dev/course/python/reader",
            "https://vlearn.dev/course/python/reader?day=1",
            "https://vlearn.dev/course/python/reader?part=2",
            "https://vlearn.dev/course/python/reader?day=&part=2",
            "https://vlearn.dev/course/python/reader?day=1&part=",
            "https://vlearn.dev/reader?day=1&part=2",
            "https://vlearn.dev/course/python/edit?day=1&part=2",
            "https://vlearn.dev/course/../reader?day=1&part=2",
            "https://vlearn.dev/course/%2e%2e/reader?day=1&part=2",
            "https://vlearn.dev/course/%2e%2e%2fsecret/reader?day=1&part=2",
            "https://vlearn.dev/course/python\\..\\secret/reader?day=1&part=2",
            "",
        ]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                download.validate_reader_url(url)


class SlideUrlTests(unittest.TestCase):
    def test_accepts_slide_pdf_with_optional_query(self):
        for url in [
            "https://slides.vlearn.dev/slides/python/day-1.pdf",
            "https://slides.vlearn.dev/slides/python/day-1.pdf?token=example&v=2",
        ]:
            with self.subTest(url=url):
                self.assertIs(download.is_slide_pdf(url), True)

    def test_rejects_other_origins_paths_and_file_types(self):
        invalid = [
            "http://slides.vlearn.dev/slides/day-1.pdf",
            "ftp://slides.vlearn.dev/slides/day-1.pdf",
            "//slides.vlearn.dev/slides/day-1.pdf",
            "https://slides.vlearn.dev.evil.test/slides/day-1.pdf",
            "https://evil-slides.vlearn.dev/slides/day-1.pdf",
            "https://slides.vlearn.dev@evil.test/slides/day-1.pdf",
            "https://user@slides.vlearn.dev/slides/day-1.pdf",
            "https://vlearn.dev/slides/day-1.pdf",
            "https://slides.vlearn.dev/other/day-1.pdf",
            "https://slides.vlearn.dev/slides-evil/day-1.pdf",
            "https://slides.vlearn.dev/slides/day-1.pdf.exe",
            "https://slides.vlearn.dev/slides/day-1.html?file=day-1.pdf",
            "https://slides.vlearn.dev/slides/../secret.pdf",
            "https://slides.vlearn.dev/slides/%2e%2e/secret.pdf",
            "https://slides.vlearn.dev/slides/%2e%2e%2fsecret.pdf",
            "https://slides.vlearn.dev/slides/python\\..\\secret.pdf",
            "file:///slides/day-1.pdf",
            "javascript:alert(1)",
            "",
        ]
        for url in invalid:
            with self.subTest(url=url):
                self.assertIs(download.is_slide_pdf(url), False)


class FilenameTests(unittest.TestCase):
    def test_filename_is_safe_and_identifies_course_and_day(self):
        name = download.safe_filename(READER_URL)
        self.assertIsInstance(name, str)
        self.assertEqual(Path(name).name, name)
        self.assertFalse(re.search(r'[<>:"/\\|?*\x00-\x1f]', name))
        self.assertFalse(name.endswith((" ", ".")))
        self.assertIn("python-basics", name.lower())
        self.assertIn("1", name)
        self.assertTrue(name.lower().endswith(".pdf"))
        self.assertEqual(download.safe_filename(READER_URL), name)

    def test_distinct_days_have_distinct_names(self):
        self.assertNotEqual(
            download.safe_filename(READER_URL),
            download.safe_filename(READER_URL.replace("day=1", "day=2")),
        )

    def test_untrusted_day_and_part_cannot_escape_filename(self):
        url = (
            "https://vlearn.dev/course/CON/reader"
            "?day=..%2F..%2Fsecret&part=%5C%00%3A%2A%3F"
        )
        name = download.safe_filename(url)
        self.assertEqual(Path(name).name, name)
        self.assertFalse(re.search(r'[<>:"/\\|?*\x00-\x1f]', name))
        self.assertNotIn("..", name)
        self.assertTrue(name.endswith(".pdf"))


class SavePdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / "slides.pdf"

    def test_saves_bytes_and_returns_path_without_temporary_residue(self):
        result = download.save_pdf(PDF, self.destination)
        self.assertIsInstance(result, Path)
        self.assertEqual(result, self.destination)
        self.assertEqual(result.read_bytes(), PDF)
        self.assertEqual(list(self.root.iterdir()), [result])

    def test_existing_file_is_never_clobbered(self):
        sentinel = b"existing user content"
        self.destination.write_bytes(sentinel)
        first = download.save_pdf(PDF, self.destination)
        second = download.save_pdf(PDF, self.destination)
        self.assertEqual(self.destination.read_bytes(), sentinel)
        self.assertEqual(len({self.destination, first, second}), 3)
        for path in (first, second):
            self.assertEqual(path.parent, self.root)
            self.assertEqual(path.read_bytes(), PDF)
        self.assertEqual(set(self.root.iterdir()), {self.destination, first, second})

    def test_invalid_content_leaves_no_output(self):
        invalid = [
            b"",
            b"<html>Login required</html>",
            b"not a PDF\n%%EOF\n",
            b"%PDF-1.7\ntruncated",
            b"prefix%PDF-1.7\n%%EOF\n",
            b"%PDF-1.7\n%%EOF\n" + b"x" * 8192,
        ]
        for data in invalid:
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                download.save_pdf(data, self.destination)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_content_preserves_existing_file(self):
        self.destination.write_bytes(b"keep me")
        with self.assertRaises(ValueError):
            download.save_pdf(b"%PDF-1.7\nmissing EOF", self.destination)
        self.assertEqual(self.destination.read_bytes(), b"keep me")
        self.assertEqual(list(self.root.iterdir()), [self.destination])

    def test_publication_failure_cleans_temporary_file(self):
        def fail_publish(source, destination):
            self.assertEqual(Path(source).read_bytes(), PDF)
            self.assertFalse(Path(destination).exists())
            raise OSError("simulated publication failure")

        with patch.object(download.os, "link", side_effect=fail_publish):
            with self.assertRaisesRegex(OSError, "simulated publication failure"):
                download.save_pdf(PDF, self.destination)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_sync_failure_never_publishes_partial_file(self):
        with patch.object(download.os, "fsync", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                download.save_pdf(PDF, self.destination)
        self.assertEqual(list(self.root.iterdir()), [])


class DownloaderTests(unittest.TestCase):
    """Mock the page boundary; never create a browser or make HTTP requests."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = Mock()
        self.page.url = READER_URL
        self.listeners = {}
        self.page.on.side_effect = self.listeners.__setitem__
        self.slide_url = "https://slides.vlearn.dev/slides/python-basics/day-1.pdf?sig=example"

    def response(self, *, url=None, status=200, data=PDF, headers=None):
        return Mock(
            url=url or self.slide_url,
            status=status,
            headers=headers or {},
            body=Mock(return_value=data),
        )

    def emit(self, response):
        self.listeners["response"](response)
        self.listeners["requestfinished"](Mock(response=Mock(return_value=response)))

    def assert_listeners_removed(self):
        self.assertEqual(self.page.remove_listener.call_count, 2)
        for event, handler in self.listeners.items():
            self.page.remove_listener.assert_any_call(event, handler)

    def test_cancelled_before_navigation_has_no_browser_or_file_side_effects(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(download.DownloadCancelledError):
            download.download_slides(
                self.page, READER_URL, self.root, timeout=1, cancel_event=cancelled
            )
        self.page.goto.assert_not_called()
        self.page.wait_for_timeout.assert_not_called()
        self.page.context.request.get.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])
        for event, handler in self.listeners.items():
            self.page.remove_listener.assert_any_call(event, handler)

    def test_cancellation_during_wait_discards_even_a_completed_response(self):
        cancelled = threading.Event()
        clock = [0.0]

        def cancel_during_wait(milliseconds):
            clock[0] += milliseconds / 1000
            self.emit(self.response())
            cancelled.set()

        self.page.wait_for_timeout.side_effect = cancel_during_wait
        with patch.object(download.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(download.DownloadCancelledError):
                download.download_slides(
                    self.page, READER_URL, self.root, timeout=1,
                    cancel_event=cancelled,
                )
        self.page.wait_for_timeout.assert_called_once()
        self.page.context.request.get.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])
        self.assert_listeners_removed()

    def test_cancellation_after_partial_response_preserves_existing_output(self):
        cancelled = threading.Event()
        existing = self.root / download.safe_filename(READER_URL)
        existing.write_bytes(b"existing user content")
        partial = self.response(
            status=206, data=PDF[:12], headers={"content-range": "bytes 0-11/500"}
        )
        self.page.goto.side_effect = lambda *a, **kw: self.emit(partial)
        forbidden = self.response(status=403)
        self.page.context.request.get.return_value = forbidden
        clock = [0.0]

        def cancel_during_wait(milliseconds):
            clock[0] += milliseconds / 1000
            cancelled.set()

        self.page.wait_for_timeout.side_effect = cancel_during_wait
        with patch.object(download.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(download.DownloadCancelledError):
                download.download_slides(
                    self.page, READER_URL, self.root, timeout=1,
                    cancel_event=cancelled,
                )
        self.assertEqual(existing.read_bytes(), b"existing user content")
        self.assertEqual(list(self.root.iterdir()), [existing])
        forbidden.dispose.assert_called_once_with()
        self.assert_listeners_removed()

    def test_progress_callback_reports_status_without_signed_url(self):
        progress = Mock()
        self.slide_url = (
            "https://slides.vlearn.dev/slides/python-basics/day-1.pdf"
            "?sig=private-signature-sentinel&token=private-token-sentinel"
        )
        self.page.goto.side_effect = lambda *a, **kw: self.emit(self.response())
        result = download.download_slides(
            self.page, READER_URL, self.root, timeout=1, on_progress=progress
        )
        self.assertEqual(result.read_bytes(), PDF)
        self.assertTrue(progress.called)
        for call in progress.call_args_list:
            self.assertEqual(len(call.args), 1)
            self.assertEqual(call.kwargs, {})
            self.assertIsInstance(call.args[0], str)
            self.assertTrue(call.args[0].strip())
        reported = repr(progress.call_args_list)
        for secret in (self.slide_url, "private-signature-sentinel", "private-token-sentinel"):
            self.assertNotIn(secret, reported)
        self.assert_listeners_removed()

    def test_progress_callback_does_not_leak_fallback_exception_url(self):
        progress = Mock()
        partial = self.response(
            status=206, data=PDF[:12], headers={"content-range": "bytes 0-11/500"}
        )
        self.page.goto.side_effect = lambda *a, **kw: self.emit(partial)
        self.page.context.request.get.side_effect = RuntimeError(
            f"Request failed: {self.slide_url}"
        )
        clock = [0.0]
        self.page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, 2.0)
        with patch.object(download.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                download.download_slides(
                    self.page, READER_URL, self.root, timeout=1, on_progress=progress
                )
        self.assertTrue(progress.called)
        self.assertNotIn(self.slide_url, repr(progress.call_args_list))
        self.assertNotIn("sig=example", repr(progress.call_args_list))
        self.assertEqual(list(self.root.iterdir()), [])
        self.assert_listeners_removed()

    def test_observed_pdf_saved_without_extra_request(self):
        response = self.response()
        self.page.goto.side_effect = lambda *a, **kw: self.emit(response)
        result = download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(result.read_bytes(), PDF)
        self.assertEqual(result.name, download.safe_filename(READER_URL))
        self.assertEqual(self.page.goto.call_args.args[0], READER_URL)
        self.page.context.request.get.assert_not_called()
        self.assert_listeners_removed()

    def test_unrelated_and_invalid_responses_ignored(self):
        rejected = [
            self.response(url="https://evil.test/slides/secret.pdf"),
            self.response(status=403),
            self.response(data=b"<html>login required</html>"),
        ]

        def navigate(*args, **kwargs):
            for response in rejected:
                self.emit(response)
            self.emit(self.response())

        self.page.goto.side_effect = navigate
        result = download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(result.read_bytes(), PDF)
        rejected[0].body.assert_not_called()
        rejected[1].body.assert_not_called()
        self.page.context.request.get.assert_not_called()
        self.assert_listeners_removed()

    def test_partial_pdf_retried_only_at_observed_url_without_redirects(self):
        partial = self.response(
            status=206, data=PDF[:12], headers={"content-range": "bytes 0-11/500"}
        )
        self.page.goto.side_effect = lambda *a, **kw: self.emit(partial)
        full = self.response()
        self.page.context.request.get.return_value = full
        result = download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(result.read_bytes(), PDF)
        self.page.context.request.get.assert_called_once()
        request = self.page.context.request.get.call_args
        self.assertEqual(request.args, (self.slide_url,))
        self.assertEqual(request.kwargs["max_redirects"], 0)
        self.assertEqual(request.kwargs["headers"]["Origin"], "https://vlearn.dev")
        full.dispose.assert_called_once_with()
        self.assert_listeners_removed()

    def test_partial_pdf_and_forbidden_fallback_never_saved(self):
        # Even marker-bearing bytes are incomplete when Content-Range says so.
        partial = self.response(
            status=206,
            headers={"content-range": f"bytes 0-{len(PDF) - 1}/{len(PDF) + 100}"},
        )
        self.page.goto.side_effect = lambda *a, **kw: self.emit(partial)
        forbidden = self.response(status=403)
        self.page.context.request.get.return_value = forbidden
        clock = [0.0]
        self.page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, 2.0)
        with patch.object(download.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(download.DownloadDeniedError, "403"):
                download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(list(self.root.iterdir()), [])
        self.page.context.request.get.assert_called_once()
        forbidden.body.assert_not_called()
        forbidden.dispose.assert_called_once_with()
        self.assert_listeners_removed()

    def test_browser_full_pdf_after_forbidden_fallback_still_saves(self):
        partial = self.response(
            status=206, data=PDF[:12], headers={"content-range": "bytes 0-11/500"}
        )
        self.page.goto.side_effect = lambda *a, **kw: self.emit(partial)
        forbidden = self.response(status=403)
        self.page.context.request.get.return_value = forbidden
        full = self.response()
        clock = [0.0]

        def browser_progress(milliseconds):
            clock[0] += milliseconds / 1000
            self.emit(full)

        self.page.wait_for_timeout.side_effect = browser_progress
        with patch.object(download.time, "monotonic", side_effect=lambda: clock[0]):
            result = download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(result.read_bytes(), PDF)
        self.assertEqual(list(self.root.iterdir()), [result])
        self.page.context.request.get.assert_called_once()
        forbidden.body.assert_not_called()
        forbidden.dispose.assert_called_once_with()
        self.assert_listeners_removed()

    def test_unrelated_course_pdf_is_ignored(self):
        rejected = self.response(
            url="https://slides.vlearn.dev/slides/other-course/day-1.pdf",
            data=PDF + b"wrong course",
        )

        def navigate(*args, **kwargs):
            self.emit(rejected)
            self.emit(self.response())

        self.page.goto.side_effect = navigate
        result = download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(result.read_bytes(), PDF)
        rejected.body.assert_not_called()
        self.assert_listeners_removed()

    def test_fallback_cannot_substitute_another_deck(self):
        partial = self.response(
            status=206, data=PDF[:12], headers={"content-range": "bytes 0-11/500"}
        )
        self.page.goto.side_effect = lambda *a, **kw: self.emit(partial)
        other_deck = self.response(
            url="https://slides.vlearn.dev/slides/python-basics/other-deck.pdf"
        )
        self.page.context.request.get.return_value = other_deck
        clock = [0.0]
        self.page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, 2.0)
        with patch.object(download.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(list(self.root.iterdir()), [])
        other_deck.body.assert_not_called()
        other_deck.dispose.assert_called_once_with()
        self.assert_listeners_removed()

    def test_other_reader_day_or_part_response_is_ignored(self):
        rejected = [
            self.response(data=PDF + b"wrong day"),
            self.response(data=PDF + b"wrong part"),
        ]

        def navigate(*args, **kwargs):
            self.page.url = READER_URL.replace("day=1", "day=9")
            self.emit(rejected[0])
            self.page.url = READER_URL.replace("part=2", "part=9")
            self.emit(rejected[1])
            self.page.url = READER_URL
            self.emit(self.response())

        self.page.goto.side_effect = navigate
        result = download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(result.read_bytes(), PDF)
        for response in rejected:
            response.body.assert_not_called()
        self.assert_listeners_removed()

    def test_complete_206_body_requires_no_retry(self):
        response = self.response(
            status=206, headers={"content-range": f"bytes 0-{len(PDF) - 1}/{len(PDF)}"}
        )
        self.page.goto.side_effect = lambda *a, **kw: self.emit(response)
        result = download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(result.read_bytes(), PDF)
        self.page.context.request.get.assert_not_called()
        self.assert_listeners_removed()

    def test_timeout_removes_listeners_without_output(self):
        with patch.object(download.time, "monotonic", side_effect=[0, 0, 2]):
            with self.assertRaises(TimeoutError):
                download.download_slides(self.page, READER_URL, self.root, timeout=1)
        self.assertEqual(list(self.root.iterdir()), [])
        self.page.context.request.get.assert_not_called()
        self.assert_listeners_removed()

    def test_invalid_reader_rejected_before_browser_access(self):
        with self.assertRaises(ValueError):
            download.download_slides(self.page, "https://evil.test/", self.root)
        self.assertEqual(self.page.mock_calls, [])

    def test_invalid_timeout_rejected_before_browser_access(self):
        for timeout in [0, -1, True, float("nan"), float("inf"), "1"]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                download.download_slides(self.page, READER_URL, self.root, timeout)
        self.assertEqual(self.page.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
