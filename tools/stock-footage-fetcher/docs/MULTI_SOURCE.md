# Tìm footage đa nguồn Pexels + Pixabay

`multi_source.py` đọc `script_beat.csv`, tìm ứng viên từ hai API, chấm preview bằng
SigLIP 2, chống trùng trên toàn project, tải video được chọn và tạo manifest.

## Cấu trúc project

```text
project/
├── script.txt
├── script_beat.csv
├── selected-footage.json
├── selected-script_beat.csv
├── video/
│   ├── H01_PEXELS_123.mp4
│   └── H01_PIXABAY_456.mp4
└── .cache/
    └── stock-search/
```

## API key

Thêm hai key vào `stock-footage-fetcher/.env`:

```env
PEXELS_API_KEY=your_pexels_key
PIXABAY_API_KEY=your_pixabay_key
```

Không đưa `.env` vào Git.

## Chạy thử không tải video

```powershell
cd D:\yt-src\TOOL-YOUTUBE\stock-footage-fetcher
..\.venv\Scripts\python.exe .\multi_source.py `
  --project-dir "E:\NE\scripts\dawn-001" `
  --dry-run
```

Kết quả lựa chọn được ghi vào `selected-footage.json` và
`selected-script_beat.csv` với trạng thái `planned`.

## Tìm và tải tự động

```powershell
cd D:\yt-src\TOOL-YOUTUBE\stock-footage-fetcher
..\.venv\Scripts\python.exe .\multi_source.py `
  --project-dir "E:\NE\scripts\dawn-001"
```

Mặc định:

- Tìm tối đa 2 truy vấn cho mỗi Beat.
- Tìm 1 trang mỗi truy vấn và mỗi nguồn.
- Lấy tối đa 40 kết quả mỗi trang.
- Cân bằng nguồn/truy vấn và chỉ chấm tối đa 24 thumbnail mỗi Beat.
- Chỉ nhận video ngang tối thiểu 1920×1080 và dài ít nhất 8 giây.
- Tải 2 video cho mỗi Beat để Footage Video Builder có lựa chọn.
- Cache kết quả API trong ít nhất 24 giờ.
- Giới hạn tối đa 20 video Pixabay trong một project.
- Resume các file đã tải thành công.

## Chỉ dùng một nguồn

```powershell
..\.venv\Scripts\python.exe .\multi_source.py `
  --project-dir "E:\NE\scripts\dawn-001" `
  --providers pexels
```

Hoặc:

```powershell
..\.venv\Scripts\python.exe .\multi_source.py `
  --project-dir "E:\NE\scripts\dawn-001" `
  --providers pixabay
```

## Chế độ tiết kiệm API và dung lượng

```powershell
..\.venv\Scripts\python.exe .\multi_source.py `
  --project-dir "E:\NE\scripts\dawn-001" `
  --max-queries 1 `
  --per-page 30 `
  --clips-per-beat 1
```

## Tìm sâu cho các Beat khó

Nên tạo một CSV chỉ chứa các Beat còn yếu rồi chạy:

```powershell
..\.venv\Scripts\python.exe .\multi_source.py `
  --project-dir "E:\NE\scripts\dawn-001" `
  --csv "E:\NE\scripts\dawn-001\weak-beats.csv" `
  --max-queries 3 `
  --max-pages 2 `
  --clips-per-beat 2
```

Không nên chạy tìm sâu cho toàn bộ 60–90 Beat vì sẽ lãng phí quota.

## Tham số quan trọng

| Tham số | Mặc định | Ý nghĩa |
|---|---:|---|
| `--providers` | `pexels,pixabay` | Nguồn tìm kiếm |
| `--max-queries` | 2 | Số truy vấn thay thế mỗi Beat |
| `--max-pages` | 1 | Số trang mỗi truy vấn và mỗi nguồn |
| `--per-page` | 40 | Số kết quả API mỗi trang |
| `--clips-per-beat` | 2 | Số source video tải cho mỗi Beat |
| `--candidate-pool` | 24 | Số ứng viên tối đa đưa vào SigLIP mỗi Beat |
| `--min-score` | 0.18 | Ngưỡng phù hợp tối thiểu |
| `--min-duration` | 8 | Thời lượng video nguồn tối thiểu |
| `--min-width` | 1920 | Chiều rộng tối thiểu |
| `--min-height` | 1080 | Chiều cao tối thiểu |
| `--shortlist` | 6 | Số thumbnail dùng để chống gần-trùng |
| `--max-pixabay-downloads` | 20 | Giới hạn video Pixabay trong project |
| `--workers` | 2 | Số Beat xử lý đồng thời |
| `--dry-run` | tắt | Chọn nhưng không tải |
| `--force` | tắt | Bỏ manifest cũ và chọn lại |

## Manifest và resume

`selected-footage.json` lưu:

- Beat và thứ hạng lựa chọn.
- Nguồn, ID, contributor và URL trang stock.
- Truy vấn đã tìm.
- Điểm semantic và điểm cuối.
- Độ phân giải, thời lượng và perceptual hash.
- Tên file, trạng thái tải và lỗi.

Khi chạy lại, chương trình chỉ resume những record có trạng thái `downloaded` và
file thật vẫn tồn tại. Record `planned` hoặc `failed` sẽ được tìm lại.

## Lưu ý API và giấy phép

- Pexels API: https://www.pexels.com/api/documentation/
- Pexels License: https://www.pexels.com/legal-pages/license/
- Pixabay API: https://pixabay.com/api/docs/
- Pixabay Content License: https://pixabay.com/service/license-summary/

Pixabay yêu cầu cache kết quả API trong 24 giờ và không cho phép systematic mass
downloads. Công cụ chỉ tải ứng viên cuối cùng và mặc định giới hạn số file Pixabay.
Manifest nên được giữ lại cùng project để làm hồ sơ nguồn và tránh tải trùng.

## Gói prompt

Dùng `PRAYER_SCRIPT_TO_FOOTAGE_CSV.md` để chuyển kịch bản Dawn With God thành CSV.
Prompt dùng dấu `|` để phân cách các truy vấn hoàn chỉnh và chia Beat theo khoảng
20–40 giây lời đọc.
