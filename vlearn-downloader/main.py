"""Download only the requested reader's slide PDF using a manual browser login."""

import argparse
from pathlib import Path
import sys


def positive_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Timeout phai la so nguyen duong.") from None
    if seconds <= 0:
        raise argparse.ArgumentTypeError("Timeout phai la so nguyen duong.")
    return seconds


def main(argv=None) -> int:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Tai PDF slide tu URL reader.")
    parser.add_argument("url", nargs="?", help="URL reader can tai")
    parser.add_argument("--output", type=Path, default=script_dir / "downloads")
    parser.add_argument("--profile", type=Path, default=script_dir / ".profile")
    parser.add_argument("--timeout", type=positive_seconds, default=180)
    parser.add_argument("--browser", choices=("chrome", "chromium"), default="chrome")
    try:
        args = parser.parse_args(argv)
        raw_url = args.url if args.url is not None else input("Nhap URL reader: ")

        from download import DownloadDeniedError, download_slides, validate_reader_url

        try:
            url = validate_reader_url(raw_url.strip())
        except ValueError:
            print("Loi: URL reader khong hop le.", file=sys.stderr)
            return 1

        from browser_session import open_session

        output_dir = args.output.expanduser().resolve()
        profile = args.profile.expanduser().resolve()
        print(
            "Hay tu dang nhap trong trinh duyet khi duoc yeu cau. "
            "Chi tai PDF slide cua URL da nhap.",
            flush=True,
        )
        with open_session(profile, channel=args.browser) as context:
            page = context.new_page()
            try:
                saved_path = download_slides(page, url, output_dir, timeout=args.timeout)
            except DownloadDeniedError:
                print(
                    "Loi: HTTP 403 - truy cap PDF bi tu choi. "
                    "Dang nhap va tai lai trang reader; "
                    "khong the vuot qua gioi han truy cap.",
                    file=sys.stderr,
                )
                return 1
        print(f"Da luu PDF: {Path(saved_path).resolve()}")
        return 0
    except KeyboardInterrupt:
        print("\nDa huy.", file=sys.stderr)
        return 130
    except EOFError:
        print("Loi: Chua nhap URL reader.", file=sys.stderr)
        return 1
    except ModuleNotFoundError:
        print(
            "Loi: Thieu thu vien. Cai Playwright: python -m pip install playwright. "
            "Kiem tra cac tep chuong trinh cung thu muc.",
            file=sys.stderr,
        )
        return 1
    except TimeoutError:
        print(
            "Loi: Het thoi gian cho dang nhap hoac slide. "
            "Thu lai va tang --timeout.",
            file=sys.stderr,
        )
        return 1
    except OSError:
        print(
            "Loi: Khong the doc/ghi tep. Kiem tra duong dan, "
            "quyen truy cap va dung luong dia.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            "Loi: Khong the tai PDF. Kiem tra dang nhap, ket noi, "
            "trinh duyet va quyen ghi thu muc; sau do thu lai.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
