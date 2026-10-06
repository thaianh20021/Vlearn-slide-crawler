# VLearn slide downloader

Tải PDF gốc của bộ slide hiện tại bằng Python, Playwright và giao diện tkinter. Chỉ tải nội dung tài khoản có quyền truy cập; không quét toàn khóa học, không ghép ảnh, không vượt đăng nhập hoặc lỗi 403.

## Dùng giao diện

1. Nhấp đúp `launch.cmd`, hoặc chạy `.\run.ps1` không kèm URL.
2. Dán liên kết trang reader VLearn, chọn thư mục lưu PDF.
3. Bấm **Tải PDF**. Đăng nhập trong cửa sổ trình duyệt được mở nếu được yêu cầu, rồi mở bộ slide cần tải.
4. Theo dõi trạng thái và nhật ký; bấm **Hủy** để dừng tải. Khi hoàn tất, bấm **Mở PDF** hoặc **Mở thư mục**.

**Trình duyệt tự đóng sau khi tải xong là bình thường, không phải ứng dụng bị crash.** Cửa sổ ứng dụng vẫn mở, kết quả vẫn hiển thị để mở PDF hoặc tiếp tục tải.

GUI mặc định chờ 300 giây; có thể đổi **Thời gian chờ (giây)** trước khi tải. Kết quả giữ trong cửa sổ hiện tại đến lần tải tiếp theo; PDF đã lưu vẫn nằm trên đĩa.

Cần Python có tkinter và Google Chrome. `run.ps1` tạo `.venv`, cài thư viện còn thiếu; có thể dùng Python đi kèm Codex nếu máy chưa có Python phù hợp. Lần đầu cần mạng để cài thư viện. Chỉ định Python khi tạo môi trường lần đầu:

```powershell
.\run.ps1 -Python 'C:\path\to\python.exe'
```

Nếu Python thiếu tkinter, dùng bản Python có tkinter; `pip install tkinter` không phải cách cài. `-Python` không thay thế `.venv` đã tồn tại.

## Dùng dòng lệnh

Truyền URL cho `run.ps1` vẫn chạy CLI:

```powershell
.\run.ps1 'reader URL'
.\run.ps1 'reader URL' --output '.\downloads' --timeout 300
```

Sau khi đã tạo môi trường, có thể chạy trực tiếp:

```powershell
.\.venv\Scripts\python.exe gui.py
.\.venv\Scripts\python.exe main.py 'reader URL'
```

CLI nhận `--output` (mặc định `downloads` cạnh chương trình), `--profile` (mặc định `.profile`), `--timeout` (mặc định 180 giây), `--browser chrome|chromium` (mặc định Chrome). `main.py` không kèm URL sẽ hỏi URL trong terminal.

Nếu dùng Chromium thay Chrome:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\run.ps1 'reader URL' --browser chromium
```

Nếu Windows chặn script, chỉ chạy lệnh sau khi đã kiểm tra và tin cậy script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

`Bypass` chỉ áp dụng cho tiến trình này, không đổi execution policy toàn máy.

## Đăng nhập và riêng tư

Ứng dụng dùng lại **profile riêng hiện có** trong `.profile`; phiên hết hạn cần đăng nhập lại. Không dùng phiên Chrome đang mở hoặc phiên Codex, không trỏ `--profile` vào profile Chrome thường dùng.

Profile chứa cookie và thông tin phiên: không chia sẻ, không đưa vào Git, không đóng gói vào ZIP hay bản phát hành. Khi đóng gói, loại cả `.profile/`, `.venv/`, `downloads/`, `__pycache__/` và tệp tạm `*.part`; `.gitignore` không tự loại chúng khỏi ZIP tạo thủ công. Profile tùy chỉnh cũng phải được loại trừ.

## Xử lý lỗi

- **403 / liên kết hết hạn:** mở lại reader, kiểm tra đăng nhập và quyền truy cập, thử lại bằng URL reader; không có cơ chế vượt 403.
- **Hết thời gian chờ:** đăng nhập và mở slide sớm hơn; CLI có thể tăng `--timeout 300`.
- **Không tìm thấy Chrome:** cài Chrome hoặc dùng Chromium theo lệnh phía trên.
- **Không ghi được PDF:** kiểm tra thư mục, quyền ghi và dung lượng đĩa.

## Kiểm chứng

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe gui.py --self-test
```

Smoke test trình duyệt dùng reader/PDF giả lập, không thay thế kiểm thử đăng nhập thật. Theo kết quả đã được luồng chính xác minh, hai PDF hiện có trong `downloads` đều có **43 trang, 24.074.501 byte mỗi tệp**. Đợt cập nhật tài liệu này không thực hiện kiểm thử đăng nhập hoặc tải trực tiếp mới.
