# Kiến trúc và sơ đồ hoạt động

## Thành phần

| Thành phần | Trách nhiệm |
|---|---|
| `load_env_file` | Nạp API key từ `.env` |
| `load_rows` | Đọc và kiểm tra cấu trúc `script_beat.csv` |
| `search_query` | Lấy cụm từ khóa chính cho Pexels |
| `positive_prompt` | Tạo prompt chấm điểm từ CSV |
| `search_best_video` | Gọi API, phân trang và dừng sớm |
| `VisualScorer` | Tải preview và chấm bằng SigLIP 2 |
| `technical_bonus` | Chấm độ phân giải và thời lượng |
| `download_video` | Tải streaming vào file `.part`, sau đó đổi tên |
| `ThreadPoolExecutor` | Chạy nhiều Beat đồng thời |

## Luồng tổng thể

```mermaid
flowchart TD
    A[Khởi động CLI] --> B[Nạp .env]
    B --> C[Đọc tham số và Project]
    C --> D[Kiểm tra script_beat.csv]
    D --> E[Nạp SigLIP 2 một lần]
    E --> F[Hàng đợi Beat]
    F --> G1[Worker Beat 1]
    F --> G2[Worker Beat 2]
    G1 --> H[Tìm Pexels theo trang]
    G2 --> H
    H --> I[Tải ảnh preview]
    I --> J[Khóa model]
    J --> K[Chấm điểm hình ảnh]
    K --> L{Đạt min-score?}
    L -- Không --> M{Còn trang?}
    M -- Có --> H
    M -- Không --> N[Giữ ứng viên tốt nhất]
    L -- Có --> N
    N --> O[Tải MP4 vào video/]
    O --> P[Beat hoàn tất]
```

## Trình tự xử lý một Beat

```mermaid
sequenceDiagram
    participant W as Beat Worker
    participant P as Pexels API
    participant I as Preview CDN
    participant S as SigLIP 2
    participant D as Video CDN

    W->>P: GET /v1/videos/search?query=...&page=1
    P-->>W: Danh sách video
    loop Ứng viên hợp lệ
        W->>I: Tải ảnh preview
        I-->>W: JPEG
    end
    W->>S: Chấm positive/avoid
    S-->>W: Điểm từng video
    alt Đạt ngưỡng
        W->>D: Tải MP4 tốt nhất
    else Chưa đạt và còn trang
        W->>P: GET trang kế tiếp
    end
    D-->>W: MP4
```

## Cấu trúc dữ liệu

Các cột CSV bắt buộc:

```text
ma_beat,tu_khoa,hinh_can_tim,tranh
```

`y_chinh` không bắt buộc ở bước kiểm tra CSV nhưng được dùng để tăng chất lượng
prompt nếu có.

Tên file đầu ra:

```text
<MA_BEAT>_PEXELS_<VIDEO_ID>.mp4
```

Ví dụ:

```text
H31_PEXELS_27255641.mp4
```

File được ghi trước dưới đuôi `.part`. Chỉ khi tải thành công file mới được đổi
thành `.mp4`, tránh để lại video hỏng mang tên hoàn chỉnh.

