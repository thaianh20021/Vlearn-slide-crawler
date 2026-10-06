"""Run without browser dependencies: python -B test_main.py."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

import main


class DownloadDeniedError(RuntimeError):
    pass


class MainTests(unittest.TestCase):
    def setUp(self):
        self.download = ModuleType("download")
        self.download.DownloadDeniedError = DownloadDeniedError
        self.download.validate_reader_url = MagicMock(return_value="validated-url")
        self.saved = Path("result") / "slides-2.pdf"
        self.download.download_slides = MagicMock(return_value=self.saved)
        self.browser = ModuleType("browser_session")
        self.browser.open_session = MagicMock()
        self.context = self.browser.open_session.return_value.__enter__.return_value
        self.events = MagicMock()
        self.events.attach_mock(self.download.validate_reader_url, "validate")
        self.events.attach_mock(self.browser.open_session, "launch")
        modules = patch.dict(sys.modules, {
            "download": self.download, "browser_session": self.browser,
        })
        modules.start()
        self.addCleanup(modules.stop)

    def run_cli(self, args):
        self.stdout, self.stderr = StringIO(), StringIO()
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return main.main(args)

    def test_defaults_order_and_saved_path(self):
        self.assertEqual(self.run_cli([" reader-url "]), 0)
        root = Path(main.__file__).resolve().parent
        self.download.validate_reader_url.assert_called_once_with("reader-url")
        self.assertEqual(self.events.mock_calls[0][0], "validate")
        self.assertEqual(self.events.mock_calls[1][0], "launch")
        self.browser.open_session.assert_called_once_with(root / ".profile", channel="chrome")
        self.context.new_page.assert_called_once_with()
        self.download.download_slides.assert_called_once_with(
            self.context.new_page.return_value, "validated-url",
            root / "downloads", timeout=180,
        )
        self.assertIn(str(self.saved.resolve()), self.stdout.getvalue())
        self.browser.open_session.return_value.__exit__.assert_called_once()

    def test_invalid_url_never_launches(self):
        self.download.validate_reader_url.side_effect = ValueError("SECRET")
        self.assertEqual(self.run_cli(["bad"]), 1)
        self.browser.open_session.assert_not_called()
        self.download.download_slides.assert_not_called()
        self.assertIn("URL reader khong hop le", self.stderr.getvalue())
        self.assertNotIn("SECRET", self.stderr.getvalue())

    def test_prompt_and_explicit_args(self):
        with patch("builtins.input", return_value="prompt-url") as prompt:
            self.assertEqual(self.run_cli([
                "--browser", "chromium", "--timeout", "7",
                "--output", "custom-output", "--profile", "custom-profile",
            ]), 0)
        prompt.assert_called_once()
        self.download.validate_reader_url.assert_called_once_with("prompt-url")
        self.browser.open_session.assert_called_once_with(
            Path("custom-profile").resolve(), channel="chromium",
        )
        self.download.download_slides.assert_called_once_with(
            self.context.new_page.return_value, "validated-url",
            Path("custom-output").resolve(), timeout=7,
        )

    def test_invalid_args_never_launch(self):
        for args in (
            ["--timeout", "0"], ["--timeout", "-1"],
            ["--timeout", "abc"], ["--timeout", "1.5"],
            ["--browser", "firefox"],
        ):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                self.run_cli(["reader-url", *args])
            self.assertEqual(error.exception.code, 2)
        self.download.validate_reader_url.assert_not_called()
        self.browser.open_session.assert_not_called()

    def test_safe_error_categories(self):
        cases = (
            (DownloadDeniedError("SECRET"), "HTTP 403", 1),
            (ModuleNotFoundError("SECRET"), "python -m pip install playwright", 1),
            (TimeoutError("SECRET"), "--timeout", 1),
            (OSError("SECRET"), "Khong the doc/ghi tep", 1),
            (RuntimeError("SECRET"), "Khong the tai PDF", 1),
            (KeyboardInterrupt("SECRET"), "Da huy", 130),
        )
        messages = set()
        for error, expected, code in cases:
            with self.subTest(error=type(error).__name__):
                self.download.download_slides.side_effect = error
                self.assertEqual(self.run_cli(["reader-url"]), code)
                message = self.stderr.getvalue()
                self.assertIn(expected, message)
                self.assertNotIn("SECRET", message + self.stdout.getvalue())
                self.assertNotIn("Traceback", message)
                self.assertNotIn("Da luu PDF:", self.stdout.getvalue())
                messages.add(message)
        self.assertEqual(len(messages), len(cases))
        self.assertEqual(
            self.browser.open_session.return_value.__exit__.call_count, len(cases),
        )

    def test_missing_exception_import_is_sanitized(self):
        del self.download.DownloadDeniedError
        self.assertEqual(self.run_cli(["reader-url"]), 1)
        self.browser.open_session.assert_not_called()
        self.assertIn("Khong the tai PDF", self.stderr.getvalue())
        self.assertNotIn("Traceback", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
