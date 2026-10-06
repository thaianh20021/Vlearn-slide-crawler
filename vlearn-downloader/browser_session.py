from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, sync_playwright


@contextmanager
def open_session(
    profile: Path, channel: str = "chrome"
) -> Iterator[BrowserContext]:
    """Open a visible browser using a dedicated application profile."""
    if channel not in ("chrome", "chromium"):
        raise ValueError("Browser channel must be chrome or chromium")
    profile = profile.expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        options = {} if channel == "chromium" else {"channel": channel}
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile), headless=False, **options
        )
        try:
            yield context
        finally:
            context.close()
