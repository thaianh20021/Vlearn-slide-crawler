"""Native downloader window. Run local checks with ``python gui.py --self-test``."""

import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_URL = (
    "https://vlearn.dev/course/k04-l34-p2-t4/reader"
    "?day=D05&part=m-91260eab-sec-ad51869a-p-7f7b526a&page=1"
)
PROGRESS_MESSAGES = {
    "opening": "Đang mở trình duyệt…",
    "waiting": "Đang chờ PDF của bài học…",
    "Dang mo trang bai hoc.": "Đang mở trang bài học…",
    "Dang cho PDF tu trinh duyet.": "Đang chờ PDF từ trình duyệt…",
    "Dang luu PDF.": "Đang lưu PDF…",
    "Hay dang nhap, mo lai dung bai hoc, ngay va phan ban dau.":
        "Chờ đăng nhập. Mở lại đúng bài học, ngày và phần ban đầu.",
    (
        "Yeu cau tai PDF bi tu choi (HTTP 403); dang cho PDF tu trinh duyet. "
        "Giu dung bai hoc mo va kiem tra dang nhap."
    ): "Yêu cầu PDF bị từ chối (HTTP 403). Đang chờ PDF từ trình duyệt; giữ bài học mở và kiểm tra đăng nhập.",
}


def download_worker(events, cancel_event, url, output_dir, channel, timeout):
    """Own the entire browser lifetime; emit (kind, value) tuples, never Tk calls."""
    saved = None
    result = ("error", "Không thể tải PDF. Kiểm tra trình duyệt, kết nối rồi thử lại.")
    try:
        from browser_session import open_session
        from download import (
            DownloadCancelledError,
            DownloadDeniedError,
            download_slides,
        )

        try:
            if cancel_event.is_set():
                raise DownloadCancelledError()
            events.put(("progress", PROGRESS_MESSAGES["opening"]))
            with open_session(SCRIPT_DIR / ".profile", channel=channel) as context:
                if cancel_event.is_set():
                    raise DownloadCancelledError()
                page = context.new_page()

                def on_progress(message):
                    # Only known tokens reach the UI; never forward URLs or credentials.
                    text = PROGRESS_MESSAGES.get(message) if isinstance(message, str) else None
                    events.put(("progress", text or PROGRESS_MESSAGES["waiting"]))

                saved = Path(download_slides(
                    page, url, output_dir, timeout,
                    on_progress=on_progress, cancel_event=cancel_event,
                )).resolve()
            result = ("success", saved)
        except DownloadCancelledError:
            result = ("cancelled", "Đã hủy tải.")
        except DownloadDeniedError:
            result = (
                "error",
                "Truy cập PDF bị từ chối (HTTP 403). Đăng nhập bằng tài khoản có quyền xem rồi thử lại.",
            )
    except ModuleNotFoundError:
        result = ("error", "Thiếu thư viện hoặc tệp chương trình. Kiểm tra cài đặt Playwright.")
    except TimeoutError:
        result = ("error", "Hết thời gian chờ PDF. Kiểm tra đăng nhập hoặc tăng thời gian chờ.")
    except OSError:
        result = ("error", "Không thể đọc hoặc ghi tệp. Kiểm tra thư mục, quyền ghi và dung lượng.")
    except Exception as error:
        if cancel_event.is_set():
            result = ("cancelled", "Đã hủy tải.")
        elif "executable doesn't exist" in str(error).lower() or "distribution 'chrome' is not found" in str(error).lower():
            result = ("error", "Không tìm thấy trình duyệt. Kiểm tra cài đặt Chrome hoặc Chromium.")
        elif "closed" in str(error).lower():
            result = ("error", "Trình duyệt đã đóng trước khi tải xong. Nhấn Tải PDF để thử lại.")
    finally:
        # A browser cleanup failure must not hide an already saved PDF.
        events.put(("success", saved) if saved is not None else result)


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.closing = False
        self.after_id = None
        self.saved_path = None
        self.last_progress = None
        self.url = tk.StringVar(value=DEFAULT_URL)
        self.folder = tk.StringVar(value=str(SCRIPT_DIR / "downloads"))
        self.browser = tk.StringVar(value="chrome")
        self.timeout = tk.StringVar(value="300")
        self.status = tk.StringVar(value="Sẵn sàng")
        self.saved_label = tk.StringVar()

        root.title("VLearn | Tải PDF")
        root.geometry("820x640")
        root.minsize(760, 600)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", padding=(12, 6))

        body = ttk.Frame(root, padding=20)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(10, weight=1)
        ttk.Label(body, text="VLearn · Tải PDF", style="Title.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 18)
        )
        ttk.Label(body, text="Liên kết bài học").grid(row=1, column=0, sticky="w")
        self.url_entry = ttk.Entry(body, textvariable=self.url)
        self.url_entry.grid(row=2, column=0, sticky="ew", pady=(5, 12))
        ttk.Label(body, text="Thư mục lưu").grid(row=3, column=0, sticky="w")
        folder_row = ttk.Frame(body)
        folder_row.grid(row=4, column=0, sticky="ew", pady=(5, 12))
        folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder)
        self.folder_entry.grid(row=0, column=0, sticky="ew")
        self.browse_button = ttk.Button(folder_row, text="Chọn…", command=self.browse)
        self.browse_button.grid(row=0, column=1, padx=(8, 0))

        options = ttk.Frame(body)
        options.grid(row=5, column=0, sticky="w", pady=(0, 14))
        ttk.Label(options, text="Trình duyệt").grid(row=0, column=0, sticky="w")
        self.browser_combo = ttk.Combobox(
            options, textvariable=self.browser, values=("chrome", "chromium"),
            state="readonly", width=12,
        )
        self.browser_combo.grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Label(options, text="Thời gian chờ (giây)").grid(
            row=0, column=1, sticky="w", padx=(24, 0)
        )
        self.timeout_spin = ttk.Spinbox(
            options, textvariable=self.timeout, from_=1, to=86400, width=12,
        )
        self.timeout_spin.grid(row=1, column=1, sticky="w", padx=(24, 0), pady=(5, 0))

        actions = ttk.Frame(body)
        actions.grid(row=6, column=0, sticky="ew", pady=(0, 14))
        self.start_button = ttk.Button(actions, text="Tải PDF", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(
            actions, text="Hủy", command=self.cancel, state="disabled",
        )
        self.cancel_button.pack(side="left", padx=8)
        self.open_pdf_button = ttk.Button(
            actions, text="Mở PDF", command=self.open_pdf, state="disabled",
        )
        self.open_pdf_button.pack(side="right")
        self.open_folder_button = ttk.Button(
            actions, text="Mở thư mục", command=self.open_folder,
        )
        self.open_folder_button.pack(side="right", padx=8)
        self.status_label = ttk.Label(body, textvariable=self.status, wraplength=700)
        self.status_label.grid(row=7, column=0, sticky="ew")
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.grid(row=8, column=0, sticky="ew", pady=(8, 12))
        ttk.Label(body, text="Nhật ký").grid(row=9, column=0, sticky="w", pady=(0, 5))
        log_frame = ttk.Frame(body)
        log_frame.grid(row=10, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(
            log_frame, height=6, wrap="word", state="disabled",
            font=("Segoe UI", 10), relief="solid", borderwidth=1, padx=8, pady=8,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.path_label = ttk.Label(body, textvariable=self.saved_label, wraplength=700)
        self.path_label.grid(row=11, column=0, sticky="ew", pady=(8, 0))
        body.bind("<Configure>", lambda event: self._wrap(event.width))
        root.bind("<Return>", lambda event: self.start() if event.widget is not self.log else None)
        self.url_entry.focus_set()
        self.after_id = root.after(100, self.poll)

    def _wrap(self, width):
        for label in (self.status_label, self.path_label):
            label.configure(wraplength=max(100, width - 40))

    def report(self, message):
        self.status.set(message)
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def browse(self):
        selected = filedialog.askdirectory(parent=self.root, title="Chọn thư mục lưu")
        if selected:
            self.folder.set(selected)

    def set_busy(self, busy):
        for widget in (
            self.url_entry, self.folder_entry, self.browse_button,
            self.timeout_spin, self.start_button,
        ):
            widget.configure(state="disabled" if busy else "normal")
        self.browser_combo.configure(state="disabled" if busy else "readonly")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def start(self):
        if self.worker is not None or self.closing:
            return
        try:
            from download import validate_reader_url
            url = validate_reader_url(self.url.get().strip())
        except ImportError:
            self.report("Thiếu tệp chương trình hoặc thư viện. Kiểm tra cài đặt.")
            return
        except ValueError:
            self.report("Liên kết không hợp lệ. Cần URL reader của vlearn.dev có day và part.")
            return
        try:
            timeout = int(self.timeout.get())
            if not 1 <= timeout <= 86400:
                raise ValueError
        except ValueError:
            self.report("Thời gian chờ phải là số nguyên từ 1 đến 86400 giây.")
            return
        try:
            if not self.folder.get().strip():
                raise ValueError
            output_dir = Path(self.folder.get().strip()).expanduser().resolve()
            if output_dir.exists() and not output_dir.is_dir():
                raise ValueError
        except (ValueError, OSError, RuntimeError):
            self.report("Thư mục lưu không hợp lệ.")
            return
        channel = self.browser.get()
        if channel not in ("chrome", "chromium"):
            self.report("Chọn trình duyệt chrome hoặc chromium.")
            return
        self.saved_path = None
        self.saved_label.set("")
        self.open_pdf_button.configure(state="disabled")
        self.last_progress = None
        self.cancel_event.clear()
        self.set_busy(True)
        self.progress.start(12)
        self.report("Đang tải PDF. Chờ đăng nhập nếu trình duyệt yêu cầu.")
        self.worker = threading.Thread(
            target=download_worker,
            args=(self.events, self.cancel_event, url, output_dir, channel, timeout),
            daemon=True,
        )
        try:
            self.worker.start()
        except RuntimeError:
            self.worker = None
            self.progress.stop()
            self.set_busy(False)
            self.report("Không thể bắt đầu tác vụ. Đóng rồi mở lại ứng dụng.")

    def cancel(self):
        if self.worker is not None:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.report("Đang hủy, chờ trình duyệt kết thúc…")

    def poll(self):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        finished = self.worker is not None and not self.worker.is_alive()
        if finished:
            self.worker.join()
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                if not self.cancel_event.is_set() and value != self.last_progress:
                    self.last_progress = value
                    self.report(value)
            elif kind == "success":
                self.saved_path = Path(value)
                self.saved_label.set(str(self.saved_path))
                self.open_pdf_button.configure(state="normal")
                self.report("Đã tải xong. PDF đã lưu; trình duyệt tự đóng là bình thường.")
            elif kind in ("error", "cancelled"):
                self.report(value)
        if finished:
            self.worker = None
            self.progress.stop()
            self.set_busy(False)
        if self.closing and self.worker is None:
            self.destroy()
            return
        self.after_id = self.root.after(100, self.poll)

    def open_folder(self):
        try:
            path = Path(self.folder.get().strip()).expanduser().resolve()
            if not self.folder.get().strip() or not path.is_dir():
                raise OSError
            os.startfile(str(path))
        except (OSError, ValueError, RuntimeError):
            self.report("Không thể mở thư mục. Kiểm tra thư mục đã tồn tại.")

    def open_pdf(self):
        try:
            if self.saved_path is None or not self.saved_path.is_file():
                raise OSError
            os.startfile(str(self.saved_path))
        except OSError:
            self.report("Không thể mở PDF. Kiểm tra tệp và ứng dụng đọc PDF.")

    def close(self):
        self.closing = True
        if self.worker is not None:
            self.cancel()
        else:
            self.destroy()

    def destroy(self):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.root.destroy()


def self_test():
    """Offline worker contract check; no browser, network, or Tk window."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import patch

    class Cancelled(Exception):
        pass

    class Denied(Exception):
        pass

    @contextmanager
    def session(profile, channel):
        assert profile == SCRIPT_DIR / ".profile"
        assert channel == "chrome"
        yield SimpleNamespace(new_page=lambda: object())

    def download(page, url, output, timeout, *, on_progress, cancel_event):
        on_progress("https://private.example/?token=secret")
        on_progress("Dang luu PDF.")
        return output / "test.pdf"

    events = queue.Queue()
    cancel_event = threading.Event()
    modules = {
        "browser_session": SimpleNamespace(open_session=session),
        "download": SimpleNamespace(
            DownloadCancelledError=Cancelled, DownloadDeniedError=Denied,
            download_slides=download,
        ),
    }
    with patch.dict(sys.modules, modules):
        download_worker(events, cancel_event, DEFAULT_URL, SCRIPT_DIR, "chrome", 300)
        messages = []
        while not events.empty():
            messages.append(events.get_nowait())
        assert messages[-1] == ("success", SCRIPT_DIR / "test.pdf")
        assert "secret" not in str(messages)
        assert ("progress", PROGRESS_MESSAGES["Dang luu PDF."]) in messages
        cancel_event.set()
        download_worker(events, cancel_event, DEFAULT_URL, SCRIPT_DIR, "chrome", 300)
        assert events.get_nowait()[0] == "cancelled"
    print("GUI worker checks passed.")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
