# Phân tích thiết kế

## Bài toán

Một audio lời thoại hoàn chỉnh cần được phủ bởi footage phù hợp với nội dung
từng Beat. Kết quả phải:

- Không cắt audio.
- Không lặp hoặc tua ngược footage gây giật.
- Ưu tiên Cut gần 5 giây.
- Dùng đúng footage của Beat khi có thể.
- Cảnh báo rõ khi nguồn không đủ.
- Có thể duyệt và sửa trước khi render.

## Đầu vào

### Kịch bản

`script.txt` chứa toàn bộ lời thoại. Marker `SCRIPT:` là tùy chọn. Header cũ
trong ngoặc vuông vẫn được loại khỏi nội dung phân tích để tương thích dữ liệu
cũ, nhưng không tạo nhiều Timeline hoặc nhiều audio.

### Audio

Project có đúng một file thuộc một trong các định dạng:

```text
.mp3 .wav .m4a .aac .flac .ogg
```

SRT có cùng tên là tùy chọn. Nếu không có SRT:

- Whisper tạo word timing; hoặc
- `--skip-whisper` ước tính timing từ kịch bản.

### Beat CSV

Cột bắt buộc:

```text
ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh
```

Ý nghĩa:

| Cột | Mục đích |
|---|---|
| `ma_beat` | Mã duy nhất như `H01`, `H31` |
| `y_chinh` | Nội dung Beat phải truyền đạt |
| `tu_khoa` | Khái niệm hỗ trợ chấm semantic |
| `hinh_can_tim` | Mô tả trực tiếp hình ảnh mong muốn |
| `tranh` | Nội dung không được xuất hiện |

### Footage

Tên file nên bắt đầu bằng mã Beat:

```text
H31_man_searching_cave.mp4
```

Đúng mã Beat là điều kiện nhận diện nguồn, nhưng chưa đủ để đảm bảo được chọn.
Footage vẫn phải đạt chất lượng, thời lượng, semantic và không gây lặp.

## Chia Cut

Profile mặc định là `3 / 5 / 7` giây:

- Từ 3 đến 5 giây: vùng ưu tiên.
- Trên 5 đến 7 giây: vùng dự phòng.
- Ngoài giới hạn chỉ dùng khi cấu trúc lời thoại không cho phép cắt hợp lý.

## Chấm điểm

Điểm lựa chọn gồm:

| Thành phần | Trọng số |
|---|---:|
| Hình cần tìm | 0,30 |
| Ý chính | 0,18 |
| Từ khóa | 0,13 |
| Tổng quan kịch bản | 0,12 |
| Nội dung narration | 0,09 |
| Chất lượng kỹ thuật | 0,09 |
| Đúng mã Beat | 0,09 |

Hình phạt:

| Loại | Giá trị |
|---|---:|
| Nội dung cần tránh | `0,25 × avoid_score` |
| Dùng footage Beat khác | 0,18 |
| Lặp cùng cửa sổ nguồn | đến 1,25 |
| Candidate cùng file bị overlap | phạt theo tỷ lệ overlap |
| Footage ngắn hơn Cut | 2,0 cộng tỷ lệ thiếu |

Footage Beat khác còn phải vượt cổng `semantic_fit`. Điểm này chỉ dùng
`hình cần tìm`, `ý chính`, `từ khóa` và `narration`; chất lượng kỹ thuật hoặc
tổng quan chung không thể tự biến một cảnh sai nội dung thành fallback hợp lệ.
Nếu không có fallback nào đạt ngưỡng, hệ thống chỉ giữ một phương án khẩn cấp,
phạt mạnh và ghi cảnh báo.

Ngưỡng cảnh báo điểm phù hợp:

- Từ 0,285: bình thường.
- 0,260–0,284: cảnh báo.
- Dưới 0,260: nghiêm trọng.

## Tối ưu Timeline

Hệ thống dùng beam search để phân bổ vùng nguồn:

- So sánh nhiều phương án trên toàn Timeline.
- Ưu tiên các vùng chưa dùng của footage đúng mã Beat.
- Cho phép nhiều Cut liên tiếp lấy các vùng không overlap trong cùng file.
- Coi các Candidate overlap từ 20% là cùng một visual region.
- Chỉ mượn footage Beat khác khi đoạn đó vượt ngưỡng semantic.
- Cooldown một visual region tối thiểu 12 Cut và 45 giây.
- Phạt riêng nguồn fallback bị quay lại dày đặc.
- Ưu tiên Candidate đã được phân tích đủ dài cho Cut thực tế.

Khi không có lựa chọn đủ nguồn, hệ thống vẫn giữ phương án render được nhưng
ghi rõ `forced_low_semantic`, `forced_early_reuse` hoặc việc phải mở rộng cửa
sổ nguồn trong Report.

## Phân tích độ phủ nguồn

Với mỗi Beat, hệ thống tính:

- Tổng số giây hình ảnh cần phủ.
- Số giây footage độc lập đang có.
- Số Cut.
- Số file nguồn.
- Cảnh liên tục dài nhất.
- Số file nên bổ sung.

Nguồn được xem là có dự phòng tốt khi đạt khoảng 125% nhu cầu.

Ví dụ:

```text
Beat cần 16 giây
Hiện có 9 giây độc lập
Thiếu tối thiểu 7 giây
Khuyến nghị khoảng 11 giây mới để đạt 25% dự phòng
```

## Cảnh báo giao diện

Màu:

- Xanh: đạt.
- Vàng: cần xem lại.
- Đỏ: bất thường hoặc thiếu nguồn.

Click ô màu để mở chi tiết. Không dùng hover cho nội dung lỗi.

Các lỗi được nhận diện:

- Footage thiếu thời lượng.
- Lặp khung hoặc quay lại đoạn nguồn cũ.
- Nhảy ngược thời gian.
- Timeline hở hoặc chồng.
- Điểm phù hợp/chất lượng thấp.
- Rung hoặc vùng đen cao.
- Thiếu file.
- Dùng nguồn từ Beat khác.
- Fallback không đạt ngưỡng semantic.
- Tái sử dụng visual region trước cooldown.
- Candidate ngắn hơn thời lượng render thực tế.
- Không đủ số giây hoặc số file.
