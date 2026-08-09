# Hướng dẫn sử dụng

## 1. Chuẩn bị Project

```text
E:\NE\scripts\0000\
├── script.txt
├── script_beat.csv
├── voices\
│   └── narration.mp3
└── video\
    ├── H01_castle_aerial.mp4
    ├── H02_stone_wall.mp4
    └── ...
```

Không đặt nhiều file audio trong `voices`.

## 2. Kịch bản

Tối giản:

```text
SCRIPT:
Toàn bộ lời thoại của video...
```

Marker `SCRIPT:` có thể bỏ. Nếu dùng dữ liệu cũ có các header trong ngoặc vuông,
parser sẽ loại header và gộp nội dung thành một kịch bản.

## 3. Beat CSV

```csv
ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh
H01,Castle ownership,"medieval castle aerial, stone fortress","A real medieval castle in Western Europe","fantasy castle, cartoon, watermark"
```

Không cần cột chia đoạn.

## 4. Footage

Tên khuyến nghị:

```text
H01_medieval_castle_aerial_01.mp4
H01_medieval_castle_gate_02.mp4
```

Với Beat có nhiều Cut, nên có từ hai file khác nhau trở lên. Mỗi cảnh lý tưởng
liên tục khoảng 5–7 giây, hoặc dài hơn Cut dài nhất của Beat.

## 5. Phân tích

Trong giao diện:

1. Mở Project.
2. Kiểm tra bốn nguồn đã sẵn sàng.
3. Nhấn **Phân tích kịch bản**.
4. Chờ hoàn thành Stage INPUT đến PLAN.
5. Duyệt bảng Timeline.

CLI:

```powershell
python main.py --cli `
  --base-dir "E:\NE\scripts\0000" `
  --analyze-only
```

## 6. Duyệt cảnh báo

Click ô màu ở cột **Kiểm tra** hoặc ô footage được tô màu.

Cửa sổ chi tiết cho biết:

- Lỗi.
- Cách xử lý.
- Tổng số giây cần.
- Số giây hiện có và còn thiếu.
- Số file nên tìm thêm.
- Mô tả hình phù hợp.
- Từ khóa có thể sao chép.

Sau khi bổ sung footage đúng mã Beat, phân tích lại toàn bộ Timeline.

## 7. Render

Trong giao diện nhấn **Render Video**.

CLI:

```powershell
python main.py --cli `
  --base-dir "E:\NE\scripts\0000" `
  --render-only `
  --output "E:\NE\scripts\0000\video_output.mp4"
```

Không xóa hoặc cắt audio để sửa lỗi hình ảnh. Hãy thay footage.

## 8. Xuất CapCut

Trong giao diện nhấn **Xuất CapCut**.

CLI:

```powershell
python main.py --cli `
  --base-dir "E:\NE\scripts\0000" `
  --export-capcut-package `
  --caption-max-lines 4 `
  --caption-max-characters-per-line 14 `
  --capcut-output-dir "E:\NE\scripts\0000\capcut_package"
```

Trong **Cấu hình > CapCut > Caption layout**, đặt số dòng tối đa và số ký tự tối
đa trên mỗi dòng. Builder chỉ ngắt tại khoảng trắng và không cắt giữa từ.
Caption vượt tổng sức chứa sẽ được tách thành cue kế tiếp theo tỷ lệ thời lượng,
không cắt bỏ chữ. Mặc định là `4 dòng × 4 từ`.

Template đang chọn trong Settings luôn được ưu tiên khi Replace Draft. Photo
overlay của template giữ nguyên vị trí và kích thước, đồng thời kéo tới hết
timeline. Khi narration ngắn hơn mốc `Video tối thiểu`, Builder lặp phần nhạc
cuối để phủ đúng toàn bộ outro.

`narration.wav` được đặt tại đầu Timeline và giữ toàn bộ lời thoại.

## 9. Tùy chỉnh Cut

```powershell
python main.py --cli `
  --base-dir "E:\NE\scripts\0000" `
  --analyze-only `
  --min-cut-seconds 3 `
  --target-cut-seconds 5 `
  --max-cut-seconds 7
```

## 10. Xử lý lỗi

### Project có nhiều audio

Giữ đúng một file trong `voices`.

### Beat thiếu nguồn

- Sao chép từ khóa từ cửa sổ cảnh báo.
- Tìm thêm video đúng mã Beat.
- Đảm bảo tổng số giây độc lập đạt yêu cầu.

### Cảnh bị lặp hoặc nhảy ngược

- Thay bằng file khác cùng Beat.
- Hoặc chọn nguồn có nhiều khoảng hình ảnh chưa dùng.

### Footage ngắn

Tìm cảnh dài hơn. Không tăng audio, không cắt audio và không cho video lặp từ
đầu.

### Model chưa có

Kết nối Internet trong lần đầu hoặc bật tự tải model trong Cấu hình.
