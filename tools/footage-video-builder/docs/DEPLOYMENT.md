# Triển khai

## Yêu cầu

- Windows 10/11.
- Python tương thích với các phiên bản trong `requirements.txt`.
- FFmpeg được cung cấp qua `imageio-ffmpeg`.
- RAM tối thiểu khuyến nghị 16 GB cho Project lớn.
- GPU CUDA là tùy chọn.
- Internet trong lần đầu tải model/Whisper.

## Cài đặt môi trường

```powershell
cd D:\yt-src\TOOL-YOUTUBE
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r .\footage-video-builder\requirements.txt
```

## Chạy ứng dụng

```powershell
python .\footage-video-builder\main.py
```

Chạy CLI:

```powershell
python .\footage-video-builder\main.py --cli --help
```

## Model

Các lựa chọn:

```text
openai/clip-vit-base-patch32
google/siglip2-base-patch16-224
```

Cache:

```text
footage-video-builder/.cache/huggingface/hub
```

Whisper cache:

```text
project/.cache/
```

## Build ứng dụng

PyInstaller đã nằm trong requirements. Trước khi build:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s .\footage-video-builder\tests -v
```

PyInstaller không hỗ trợ cross-build. Hãy dùng script trên đúng hệ điều hành:

```powershell
# Windows
.\build-scripts\build_windows.ps1 -Version 1.0.0 -InstallDependencies -Clean
```

```bash
# macOS
chmod +x build-scripts/build_macos.sh
./build-scripts/build_macos.sh --version 1.0.0 --install-dependencies --clean
```

Xem toàn bộ tùy chọn và vị trí file đầu ra tại
[`build-scripts/README.md`](../build-scripts/README.md).

Không đóng gói:

- Project người dùng.
- `.cache`.
- Model lớn nếu muốn bản portable nhẹ.
- API key hoặc thông tin CapCut cá nhân.

## CapCut

Để tạo Draft trực tiếp cần:

- Một Draft template tương thích.
- Đường dẫn CapCut Drafts.
- Quyền ghi vào thư mục Draft.

Nên thử trước với `--no-capcut-register` hoặc một bản sao template.

## Kiểm tra sau triển khai

```powershell
python .\footage-video-builder\main.py --cli --help
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s .\footage-video-builder\tests -v
```

Checklist:

- Giao diện mở được.
- Project một audio được nhận diện.
- Project nhiều audio bị chặn.
- Phân tích tạo report.
- Render audio đủ thời lượng.
- Click cảnh báo mở chi tiết.
- CapCut có một narration.
