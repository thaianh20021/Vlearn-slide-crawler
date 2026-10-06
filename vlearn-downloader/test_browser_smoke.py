"""Offline Chrome smoke: python -B -m unittest test_browser_smoke -v."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from download import download_slides, safe_filename

try:
    from playwright.sync_api import APIRequestContext, Error, sync_playwright
except ImportError:
    sync_playwright = None


READER = "https://vlearn.dev/course/course/reader?day=1&part=2"
SLIDE = "https://slides.vlearn.dev/slides/course/smoke.pdf"


def pdf_fixture():
    data = b"%PDF-1.4\n"
    offsets = []
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] >>",
    ]
    for index, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 4\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return data + (
        f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()


@unittest.skipIf(sync_playwright is None, "Playwright is not installed.")
class BrowserSmokeTests(unittest.TestCase):
    def test_real_requestfinished_saves_original_pdf(self):
        pdf = pdf_fixture()
        served = []
        finished = []
        blocked = []

        def intercept(route):
            request = route.request
            if request.method == "GET" and request.url == READER:
                served.append(request.url)
                route.fulfill(
                    status=200,
                    content_type="text/html",
                    body=f"""<!doctype html><title>Offline reader</title>
<script>
fetch("{SLIDE}").then(response => response.arrayBuffer());
</script>""",
                )
            elif request.method == "GET" and request.url == SLIDE:
                served.append(request.url)
                route.fulfill(
                    status=200,
                    content_type="application/pdf",
                    headers={"Access-Control-Allow-Origin": "https://vlearn.dev"},
                    body=pdf,
                )
            else:
                blocked.append(request.url)
                route.abort()

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    channel="chrome",
                    headless=True,
                    args=["--disable-background-networking"],
                )
            except Error as error:
                message = str(error).lower()
                if "executable doesn't exist" in message or (
                    "chrome" in message and "not found" in message
                ):
                    self.skipTest("Google Chrome is unavailable; install Chrome.")
                raise
            try:
                context = browser.new_context(service_workers="block")
                context.route("**/*", intercept)
                page = context.new_page()
                page.on("requestfinished", lambda request: finished.append(request.url))
                # Context routes do not intercept APIRequestContext network requests.
                with patch.object(
                    APIRequestContext,
                    "get",
                    side_effect=AssertionError("Direct HTTP fallback is forbidden."),
                ) as direct_get, tempfile.TemporaryDirectory() as directory:
                    output = Path(directory)
                    saved = download_slides(page, READER, output, timeout=10)
                    self.assertEqual(saved, output / safe_filename(READER))
                    self.assertEqual(saved.read_bytes(), pdf)
                    self.assertEqual(list(output.iterdir()), [saved])
                    self.assertEqual(served, [READER, SLIDE])
                    self.assertIn(SLIDE, finished)
                    direct_get.assert_not_called()
                    result = page.evaluate(
                        """async () => {
                            try {
                                await fetch("/offline-unmatched");
                                return "unexpected success";
                            } catch {
                                return "blocked";
                            }
                        }"""
                    )
                    self.assertEqual(result, "blocked")
                    self.assertIn("https://vlearn.dev/offline-unmatched", blocked)
                self.assertFalse(output.exists())
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
