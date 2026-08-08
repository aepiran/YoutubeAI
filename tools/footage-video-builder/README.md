# Footage Video Builder

Ứng dụng dựng một Timeline footage hoàn chỉnh từ:

- Một file kịch bản.
- Đúng một file audio lời thoại.
- Một danh sách Beat trong `footage.csv`.
- Kho video footage đã gắn mã Beat.

Ứng dụng phân tích audio, chia Cut, chấm footage bằng model thị giác, tối ưu
toàn Timeline, cảnh báo nguồn yếu/lặp cảnh và xuất MP4 hoặc Draft CapCut.

## Mô hình dữ liệu cuối cùng

```text
project/
├── script.txt
├── footage.csv
├── voice/ (hoặc voices/)
│   └── narration.mp3
├── video/
│   ├── H01_*.mp4
│   ├── H02_*.mp4
│   └── ...
└── .cache/
```

Quy tắc bắt buộc:

- `voice/` hoặc `voices/` có đúng một file audio; cũng có thể đặt một file
  audio đánh số ngay tại thư mục project.
- Audio không bị cắt, tua ngược hoặc ghép lặp.
- `script.txt` là toàn bộ lời thoại.
- `footage.csv` không cần cột chia đoạn.
- Mỗi footage nên bắt đầu bằng mã Beat, ví dụ `H31_cave_search.mp4`.

## Khởi động

```powershell
cd D:\yt-src\TOOL-YOUTUBE
.\.venv\Scripts\Activate.ps1
pip install -r .\footage-video-builder\requirements.txt
python .\footage-video-builder\main.py
```

Hoặc CLI:

```powershell
python .\footage-video-builder\main.py --cli `
  --base-dir "E:\NE\scripts\0000" `
  --analyze-only
```

Render từ report:

```powershell
python .\footage-video-builder\main.py --cli `
  --base-dir "E:\NE\scripts\0000" `
  --render-only
```

## Quy trình giao diện

1. Chuẩn bị dữ liệu.
2. Phân tích kịch bản và footage.
3. Duyệt Timeline theo Beat.
4. Sửa Beat có cảnh báo.
5. Render MP4 hoặc xuất CapCut.

Sau khi phân tích, nút **Tìm footage bổ sung** tạo
`.cache/footage_download_plan.csv` và mở Stock Footage Finder. Mỗi Beat chỉ
tải tối đa một file trong một lượt. Quay lại Builder và phân tích lại để hệ
thống tận dụng nhiều vùng hình trong file mới trước khi đề xuất lượt tiếp theo.

Ô cảnh báo màu có thể click để xem:

- Lỗi cụ thể.
- Cách xử lý.
- Tổng footage cần và số giây còn thiếu.
- Độ dài liên tục nên tìm.
- Hình ảnh, từ khóa và nội dung cần tránh.
- Nút sao chép từ khóa tìm footage.

## Profile Cut mặc định

| Loại | Thời lượng |
|---|---:|
| Tối thiểu | 3 giây |
| Mục tiêu | 5 giây |
| Tối đa | 7 giây |

Hệ thống ưu tiên Cut trong khoảng 3–5 giây. Chỉ tiến gần 7 giây khi nội dung
lời thoại hoặc cảnh nguồn thực sự cần.

Một file footage dài có thể cấp nhiều Cut nếu các khoảng nguồn không chồng
lấn. Vùng hình đã dùng không được lặp trong 18 Cut hoặc 90 giây khi vẫn còn
phương án an toàn khác.

## Audio

Audio nguồn là trục thời gian chính:

- Timeline hình ảnh được dựng theo toàn bộ thời lượng audio.
- Render thông thường gắn nguyên audio vào video.
- Render tiết kiệm RAM không dùng `-shortest`.
- CapCut dùng một file `narration.wav` đặt tại `00:00:00`.
- Không tạo các audio nhỏ cho từng Cut.

Profile DWG tự động dùng thư viện `BASE/audio/music` và file
`DWG_25min_music_cue_sheet.csv`. Gain dB, điểm vào/ra và crossfade trong CSV
được áp dụng thống nhất khi render MP4 và xuất CapCut. Các cue chồng nhau được
đặt trên nhiều audio track trong Draft CapCut; fade được bake vào asset WAV.

Có thể ghi đè bằng `--music-dir` và `--music-cue-sheet`, hoặc tắt hoàn toàn bằng
`--no-background-music`. Tùy chọn Hook/Body music cũ vẫn được ưu tiên nếu người
dùng khai báo rõ khi xuất CapCut.

### Thời lượng tối thiểu DWG

`Cấu hình > Video > Video tối thiểu` mặc định là 25 phút. Khi narration ngắn
hơn, Builder thêm các Cut `DWG OUTRO` không lời tới đúng mốc tối thiểu. Các Cut
này dùng Beat kết thúc để chấm footage và được tính vào source coverage, nên
nút `Tìm footage bổ sung` có thể yêu cầu downloader lấy thêm footage nếu kho
hiện tại thiếu. Nhạc nền tiếp tục tới hết timeline; narration không bị kéo chậm
hoặc lặp. Audio bằng hoặc dài hơn mốc cấu hình được giữ nguyên. Chọn `Tắt` hoặc
dùng `--minimum-video-minutes 0` để vô hiệu hóa.

## Tài liệu

- [Phân tích thiết kế](docs/ANALYSIS.md)
- [Kiến trúc và sơ đồ hoạt động](docs/ARCHITECTURE.md)
- [Triển khai](docs/DEPLOYMENT.md)
- [Hướng dẫn sử dụng](docs/USAGE.md)
- [Prompt tạo footage.csv](prompt-packages/SCRIPT_TO_FOOTAGE_CSV.md)

## Kiểm thử

```powershell
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s .\footage-video-builder\tests -v
```
