# Phân tích thiết kế

## Mục tiêu

Mỗi dòng trong `script_beat.csv` đại diện cho một Beat cần footage. Công cụ phải:

1. Tìm đủ rộng trên Pexels mà không tải toàn bộ ứng viên.
2. Đánh giá nội dung hình ảnh sát `hinh_can_tim`, `y_chinh` và `tu_khoa`.
3. Loại hoặc hạ điểm nội dung nằm trong `tranh`.
4. Chỉ tải video tốt nhất sau khi hoàn thành tìm kiếm.
5. Cho phép nhiều Beat chạy đồng thời nhưng không làm model mất ổn định.

## Vì sao thay MiniLM bằng SigLIP 2

MiniLM chỉ so sánh văn bản. Kết quả video từ Pexels thường không có metadata
mô tả đủ chi tiết để phân biệt hai cảnh gần giống nhau. SigLIP 2 đọc trực tiếp
ảnh preview nên có thể so sánh:

- Bối cảnh và chủ thể thực tế trong khung hình.
- Mô tả hình cần tìm.
- Ý chính của Beat.
- Các khái niệm cần tránh.

Model mặc định:

```text
google/siglip2-base-patch16-224
```

## Cách xử lý từ khóa

Ví dụ:

```text
medieval castle aerial, stone fortress countryside, castle establishing shot
```

Được tách thành ba cụm từ khóa hoàn chỉnh. Hiện tại:

- Cụm đầu tiên được gửi tới Pexels làm truy vấn tìm kiếm.
- Tối đa bốn cụm đầu được ghép vào prompt chấm điểm.
- Dấu phẩy, dấu chấm phẩy, xuống dòng và `|` đều được xem là dấu phân cách.
- Không tách cụm thành từng từ đơn.

Đây là lựa chọn nhằm giữ truy vấn Pexels ngắn và tăng độ bao phủ. Nếu cụm đầu
không tốt, công cụ chuyển trang của cùng truy vấn; chưa tự chuyển sang cụm thứ
hai như một truy vấn API độc lập.

## Công thức điểm

```text
điểm cuối
  = tương đồng hình ảnh với nội dung cần tìm
  - 0,35 × tương đồng với nội dung cần tránh
  + thưởng kỹ thuật
```

Thưởng kỹ thuật tối đa khoảng 0,04:

- Độ phân giải: tối đa 0,025.
- Thời lượng vượt mức tối thiểu: tối đa 0,015.

Video bị loại trước khi chấm nếu:

- Không có file tải phù hợp.
- Thời lượng ngắn hơn `--min-duration`.

## Chiến lược phân trang

- Tìm từ trang 1 đến `--max-pages`.
- Mỗi trang lấy tối đa `--per-page` ứng viên.
- Chấm toàn bộ ảnh preview hợp lệ của trang.
- Nếu ứng viên tốt nhất đạt `--min-score`, dừng ngay.
- Nếu chưa đạt, giữ ứng viên tốt nhất toàn cục rồi chuyển trang.
- Hết trang tối đa vẫn tải ứng viên tốt nhất đã tìm được.

Mặc định:

| Tham số | Giá trị |
|---|---:|
| `max-pages` | 5 |
| `per-page` | 80 |
| `min-score` | 0,24 |
| `min-duration` | 5 giây |
| `workers` | 2 |

## Đa luồng

Đơn vị xử lý song song là Beat:

- Mỗi worker có `requests.Session` riêng để tìm và tải.
- Hai Beat có thể gọi API hoặc tải video đồng thời.
- SigLIP 2 dùng chung một model.
- Phần suy luận model được bảo vệ bằng `Lock` để tránh hai thread truy cập model
  cùng lúc.

Vì vậy đa luồng tăng tốc mạng và tải file nhưng không nhân đôi model trong RAM
hoặc VRAM.

## Giới hạn và rủi ro

- Điểm SigLIP là điểm tương đối, không phải xác suất tuyệt đối.
- Ảnh preview không thể đại diện hoàn hảo cho toàn bộ chuyển động trong video.
- Tăng `max-pages` và `workers` làm tiêu thụ hạn mức API nhanh hơn.
- Pexels giới hạn `per_page` tối đa 80.
- Link tải có thể hết hiệu lực; chạy lại Beat sẽ nhận link mới.

