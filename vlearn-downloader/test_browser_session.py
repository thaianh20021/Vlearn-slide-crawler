import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_session import open_session


class BrowserSessionTests(unittest.TestCase):
    def test_lifecycle(self):
        for channel in ("chrome", "chromium"):
            for fail in (False, True):
                with self.subTest(channel=channel, fail=fail):
                    with tempfile.TemporaryDirectory() as root:
                        with patch("browser_session.sync_playwright") as start:
                            manager = start.return_value
                            launch = (
                                manager.__enter__.return_value.chromium
                                .launch_persistent_context
                            )
                            profile = Path(root) / "new" / "profile"
                            failure = RuntimeError("body failure")

                            def exercise():
                                with open_session(profile, channel) as context:
                                    self.assertTrue(profile.is_dir())
                                    self.assertIs(context, launch.return_value)
                                    launch.return_value.close.assert_not_called()
                                    if fail:
                                        raise failure

                            if fail:
                                with self.assertRaises(RuntimeError) as caught:
                                    exercise()
                                self.assertIs(caught.exception, failure)
                            else:
                                exercise()

                            options = {
                                "user_data_dir": str(profile.resolve()),
                                "headless": False,
                            }
                            if channel == "chrome":
                                options["channel"] = "chrome"
                            launch.assert_called_once_with(**options)
                            launch.return_value.close.assert_called_once_with()
                            manager.__exit__.assert_called_once()

    def test_launch_failure(self):
        for channel in ("chrome", "chromium"):
            with self.subTest(channel=channel):
                with tempfile.TemporaryDirectory() as root:
                    with patch("browser_session.sync_playwright") as start:
                        manager = start.return_value
                        launch = (
                            manager.__enter__.return_value.chromium
                            .launch_persistent_context
                        )
                        failure = RuntimeError("launch failure")
                        launch.side_effect = failure
                        with self.assertRaises(RuntimeError) as caught:
                            with open_session(Path(root) / "profile", channel):
                                self.fail("Session yielded after launch failed")
                        self.assertIs(caught.exception, failure)
                        launch.return_value.close.assert_not_called()
                        manager.__exit__.assert_called_once()

    def test_default_channel(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("browser_session.sync_playwright") as start:
                with open_session(Path(root)):
                    pass
                launch = (
                    start.return_value.__enter__.return_value.chromium
                    .launch_persistent_context
                )
                self.assertEqual(launch.call_args.kwargs["channel"], "chrome")

    def test_invalid_channel_rejected_before_side_effects(self):
        for channel in ("", " ", "firefox", "Chrome", None):
            with self.subTest(channel=channel):
                with tempfile.TemporaryDirectory() as root:
                    profile = Path(root) / "profile"
                    with patch("browser_session.sync_playwright") as start:
                        with self.assertRaises(ValueError):
                            with open_session(profile, channel):
                                self.fail("Invalid channel accepted")
                        start.assert_not_called()
                        self.assertFalse(profile.exists())


if __name__ == "__main__":
    unittest.main()
