# Hướng dẫn sử dụng

## 1. Chuẩn bị Project

```text
E:\NE\scripts\0000\
├── footage.csv
└── video\
```

Ví dụ CSV:

```csv
ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh
H01,Castle ownership,"medieval castle aerial, stone fortress countryside","Real medieval stone castle in Western Europe","fantasy castle, cartoon, watermark"
```

Các cụm trong `tu_khoa` được phân cách bằng dấu phẩy.

## 2. Chạy mặc định

```powershell
cd D:\yt-src\TOOL-YOUTUBE\download-pexels
python main.py --project-dir "E:\NE\scripts\0000"
```

Mặc định:

- 2 Beat đồng thời.
- 5 trang mỗi Beat.
- 80 video mỗi trang.
- Dừng khi điểm đạt 0,24.
- Video phải dài ít nhất 5 giây.

## 3. Tìm sâu hơn

```powershell
python main.py `
  --project-dir "E:\NE\scripts\0000" `
  --max-pages 10 `
  --workers 2
```

## 4. Chạy tuần tự

```powershell
python main.py `
  --project-dir "E:\NE\scripts\0000" `
  --workers 1
```

## 5. Điều chỉnh chất lượng

Khắt khe hơn:

```powershell
python main.py `
  --project-dir "E:\NE\scripts\0000" `
  --min-score 0.28 `
  --min-duration 7
```

Tìm rộng hơn:

```powershell
python main.py `
  --project-dir "E:\NE\scripts\0000" `
  --min-score 0.20 `
  --max-pages 15
```

## 6. Ghi đè CSV hoặc thư mục đầu ra

```powershell
python main.py `
  --project-dir "E:\NE\scripts\0000" `
  --csv "E:\shotlists\custom.csv" `
  --output-dir "E:\downloads\pexels"
```

`--csv` và `--output-dir` được ưu tiên hơn đường dẫn suy ra từ
`--project-dir`.

## Tham số

| Tham số | Mặc định | Ý nghĩa |
|---|---:|---|
| `--project-dir` | Không | Project chứa `footage.csv` và `video/` |
| `--csv` | `download-pexels/footage.csv` | Ghi đè CSV |
| `--output-dir` | `download-pexels/video` | Ghi đè nơi tải |
| `--workers` | 2 | Beat chạy đồng thời, từ 1–8 |
| `--max-pages` | 5 | Số trang tối đa, từ 1–50 |
| `--per-page` | 80 | Video mỗi trang, từ 1–80 |
| `--min-score` | 0,24 | Ngưỡng dừng sớm |
| `--min-duration` | 5 | Thời lượng video tối thiểu |
| `--model` | SigLIP 2 Base | Model chấm ảnh |
| `--model-cache-dir` | Cache dùng chung | Thư mục model |

## Xử lý lỗi

### 400 Bad Request

Đảm bảo chương trình đang dùng:

```text
query=<từ khóa>
```

Không dùng `q`, `locale`, `frame_rate` hoặc `resolution_name` với endpoint hiện
tại.

### 401 Unauthorized

- Kiểm tra `.env`.
- Không truyền `--api-key API_KEY_CUA_BAN`.
- Không có khoảng trắng hoặc dấu `*` trong key.

### 429 Too Many Requests

- Giảm `--max-pages`.
- Giảm `--workers`.
- Chờ hạn mức API reset.

### Không có video đạt yêu cầu

- Giảm `--min-score`.
- Giảm `--min-duration`.
- Đưa cụm từ khóa quan trọng nhất lên đầu cột `tu_khoa`.
- Tăng `--max-pages`.

