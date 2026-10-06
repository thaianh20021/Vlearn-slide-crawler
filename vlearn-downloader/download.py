"""Download only PDFs observed in the user's authorized reader session.

Run checks with ``python -m doctest download.py``.

>>> is_slide_pdf("https://slides.vlearn.dev/slides/course/hash.pdf?sig=secret")
True
>>> is_slide_pdf("https://slides.vlearn.dev.evil/slides/hash.pdf")
False
>>> is_slide_pdf("https://user@slides.vlearn.dev/slides/hash.pdf")
False
>>> safe_filename("https://vlearn.dev/course/python/reader?day=2&part=1")
'python-day-2-part-1.pdf'
>>> _valid_pdf(b"%PDF-1.7\\nbody\\n%%EOF\\n")
True
>>> _valid_pdf(b"%PDF-1.7\\ntruncated")
False
>>> from threading import Event
>>> cancelled = Event()
>>> cancelled.set()
>>> try:
...     download_slides(None, "https://vlearn.dev/course/python/reader?day=2&part=1",
...                     Path("."), cancel_event=cancelled)
... except DownloadCancelledError as error:
...     print(error)
Da huy tai PDF.
"""

import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import parse_qs, unquote, urlsplit


class DownloadDeniedError(RuntimeError):
    """The authorized request was denied and no browser PDF completed."""

class DownloadCancelledError(RuntimeError):
    """The caller cancelled before a PDF was published."""


def _url(url, host):
    try:
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise ValueError
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or "\\" in url
            or parsed.fragment
        ):
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise ValueError("Invalid authorized URL.") from None


def validate_reader_url(url: str) -> str:
    parsed = _url(url, "vlearn.dev")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not re.fullmatch(r"/course/[A-Za-z0-9_-]+/reader/?", parsed.path):
        raise ValueError("Expected a vlearn.dev course reader URL.")
    if any(len(query.get(key, [])) != 1 or not query[key][0].strip()
           for key in ("day", "part")):
        raise ValueError("Reader URL requires one nonempty day and part.")
    return url


def is_slide_pdf(url: str) -> bool:
    try:
        parsed = _url(url, "slides.vlearn.dev")
        path = unquote(parsed.path)
        return (
            path.startswith("/slides/")
            and path.lower().endswith(".pdf")
            and "\\" not in path
            and all(segment not in ("", ".", "..") for segment in path.split("/")[1:])
            and not any(ord(c) < 32 for c in path)
        )
    except ValueError:
        return False


def safe_filename(url: str) -> str:
    parsed = urlsplit(validate_reader_url(url))
    query = parse_qs(parsed.query)

    def clean(value):
        return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_")[:64] or "slides"

    return (
        f"{clean(parsed.path.split('/')[2])}"
        f"-day-{clean(query['day'][0])}-part-{clean(query['part'][0])}.pdf"
    )


def _valid_pdf(data):
    return isinstance(data, bytes) and data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:]


def save_pdf(data: bytes, destination: Path) -> Path:
    if not _valid_pdf(data):
        raise ValueError("Response is not a complete PDF.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pdf-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        index = 0
        while True:
            candidate = destination if index == 0 else destination.with_name(
                f"{destination.stem}-{index}{destination.suffix}"
            )
            try:
                # Publish a complete file atomically without replacing an existing name.
                os.link(temporary, candidate)
                return candidate
            except FileExistsError:
                index += 1
    finally:
        os.unlink(temporary)


def _complete_body(response):
    data = response.body()
    if response.status == 206:
        match = re.fullmatch(
            r"bytes 0-(\d+)/(\d+)", response.headers.get("content-range", "").strip()
        )
        if not match or int(match[1]) + 1 != int(match[2]) or len(data) != int(match[2]):
            return None
    return data if _valid_pdf(data) else None


def download_slides(page, url: str, output_dir: Path, timeout: int = 180, *,
                    on_progress=None, cancel_event=None) -> Path:
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

    validate_reader_url(url)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be a positive number of seconds.")

    def check_active():
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError("Da huy tai PDF.")
        if page.is_closed() is True:
            raise RuntimeError("Browser session closed or became unavailable.")

    def progress(message, instruction=None):
        if on_progress is not None:
            on_progress(message)
        elif instruction is not None:
            print(instruction, file=sys.stderr)

    def save(data):
        check_active()
        progress("Dang luu PDF.")
        check_active()
        return save_pdf(data, destination)

    check_active()
    destination = Path(output_dir) / safe_filename(url)
    deadline = time.monotonic() + timeout
    ready = []
    observed = []
    attempted = set()
    expected = urlsplit(url)
    expected_query = parse_qs(expected.query)
    course_prefix = f"/slides/{expected.path.split('/')[2]}/"
    instructed = False
    fallback_denied = False

    def requested_reader():
        try:
            current = urlsplit(validate_reader_url(page.url))
            query = parse_qs(current.query)
            return current.path.rstrip("/") == expected.path.rstrip("/") and all(
                query[key] == expected_query[key] for key in ("day", "part")
            )
        except ValueError:
            return False

    def allowed_asset(asset_url):
        return is_slide_pdf(asset_url) and unquote(urlsplit(asset_url).path).startswith(course_prefix)

    def on_response(response):
        if requested_reader() and allowed_asset(response.url) and 200 <= response.status < 300:
            if response.status == 206 and response.url not in attempted:
                observed.append(response.url)

    def on_finished(request):
        try:
            response = request.response()
        except Exception:
            return
        if response and requested_reader() and allowed_asset(response.url) and 200 <= response.status < 300:
            ready.append(response)

    page.on("response", on_response)
    page.on("requestfinished", on_finished)
    try:
        progress("Dang mo trang bai hoc.")
        check_active()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=max(1, min(15000, (deadline - time.monotonic()) * 1000)))
        except PlaywrightTimeoutError:
            # Navigation can time out while a login or the reader remains usable.
            pass
        except PlaywrightError:
            check_active()
            raise RuntimeError("Reader navigation failed. Check connectivity and open the requested reader, then retry.") from None
        check_active()
        progress("Dang cho PDF tu trinh duyet.")
        while time.monotonic() < deadline:
            check_active()
            if not requested_reader():
                ready.clear()
                observed.clear()
                if not instructed:
                    progress(
                        "Hay dang nhap, mo lai dung bai hoc, ngay va phan ban dau.",
                        "After login, reopen the original requested reader URL with the same course, day and part.",
                    )
                    instructed = True
            while ready and time.monotonic() < deadline:
                check_active()
                response = ready.pop(0)
                try:
                    data = _complete_body(response)
                except Exception:
                    continue
                if data is not None and requested_reader():
                    return save(data)
            if observed and requested_reader() and time.monotonic() < deadline:
                check_active()
                signed_url = observed.pop(0)
                if signed_url in attempted:
                    continue
                attempted.add(signed_url)
                response = None
                data = None
                denied = False
                try:
                    response = page.context.request.get(
                        signed_url,
                        headers={"Referer": "https://vlearn.dev/", "Origin": "https://vlearn.dev"},
                        timeout=max(1, min(30000, (deadline - time.monotonic()) * 1000)),
                        max_redirects=0,
                    )
                    denied = response.status == 403
                    if response.url == signed_url and allowed_asset(response.url) and 200 <= response.status < 300:
                        data = _complete_body(response)
                except Exception:
                    pass
                finally:
                    if response is not None:
                        try:
                            response.dispose()
                        except Exception:
                            pass
                check_active()
                if denied:
                    if not fallback_denied:
                        progress(
                            "Yeu cau tai PDF bi tu choi (HTTP 403); dang cho PDF tu trinh duyet. "
                            "Giu dung bai hoc mo va kiem tra dang nhap.",
                            "Full slide request denied (HTTP 403); waiting for the browser PDF. "
                            "Keep the requested reader open and confirm you are logged in.",
                        )
                    fallback_denied = True
                if data is not None and requested_reader():
                    return save(data)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    page.wait_for_timeout(min(200, remaining * 1000))
                except Exception:
                    check_active()
                    raise RuntimeError("Browser session closed or became unavailable.") from None
        check_active()
        if fallback_denied:
            raise DownloadDeniedError(
                "Slide download denied (HTTP 403); no complete browser PDF arrived. Log in, "
                "reopen the requested reader, confirm access, then retry. "
                "Partial-range assembly is not supported."
            )
        raise TimeoutError(
            "No complete authorized slide PDF received before timeout. Log in, reopen the "
            "original reader URL with the same course, day and part, then retry."
        )
    except PlaywrightError:
        check_active()
        raise RuntimeError("Browser session closed or became unavailable.") from None
    finally:
        for event, handler in (("response", on_response), ("requestfinished", on_finished)):
            try:
                page.remove_listener(event, handler)
            except PlaywrightError:
                pass
