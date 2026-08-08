# Triển khai

## Yêu cầu

- Windows 10/11.
- Python 3.11 trở lên.
- Internet để gọi Pexels và tải model trong lần đầu.
- API key Pexels.
- RAM tối thiểu khuyến nghị: 8 GB.
- GPU CUDA là tùy chọn; CPU vẫn chạy được.

## Cài đặt

Từ thư mục monorepo:

```powershell
cd D:\yt-src\TOOL-YOUTUBE
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r .\download-pexels\requirements.txt
```

## Cấu hình API key

Tạo file:

```text
download-pexels/.env
```

Nội dung:

```env
PEXELS_API_KEY=PEXELS_KEY_THAT_CUA_BAN
```

Không:

- Đặt key trong `main.py`.
- Truyền chuỗi minh họa như `API_KEY_CUA_BAN`.
- Commit `.env`.

`.env` đã được `.gitignore` loại khỏi Git.

## Model và cache

Model mặc định:

```text
google/siglip2-base-patch16-224
```

Cache mặc định được dùng chung với Footage Video Builder:

```text
footage-video-builder/.cache/huggingface/hub
```

Có thể ghi đè:

```powershell
python main.py `
  --project-dir "E:\NE\scripts\0000" `
  --model-cache-dir "D:\AI-CACHE\huggingface"
```

## Endpoint và giới hạn

Endpoint:

```text
https://api.pexels.com/v1/videos/search
```

Tham số gửi:

```text
query, orientation, size, page, per_page
```

Không dùng URL website:

```text
https://www.pexels.com/search/videos/
```

Tài liệu chính thức:

- <https://www.pexels.com/api/documentation/>
- <https://help.pexels.com/hc/en-us/articles/900006470063-What-steps-can-I-take-to-avoid-hitting-the-rate-limit>

## Kiểm thử triển khai

```powershell
cd D:\yt-src\TOOL-YOUTUBE\download-pexels
python -m unittest test_main -v
python main.py --help
```

## Khuyến nghị vận hành

- Bắt đầu với `--workers 2`.
- Dùng `--max-pages 5` hoặc `10`.
- Không dùng đồng thời `workers=8`, `max-pages=50` cho Project lớn nếu API key
  chưa được nâng hạn mức.
- Theo dõi lỗi 429 và giảm số trang/worker nếu cần.

