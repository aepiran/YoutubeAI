# Thiết kế chia giai đoạn phân tích Footage Video Builder

Mục tiêu của thiết kế này là không chạy toàn bộ pipeline trong một lần duy nhất. Mỗi giai đoạn có nhiệm vụ riêng, có cache riêng, có output rõ ràng, và có thể chạy lại độc lập. Như vậy khi lỗi xảy ra, mình biết lỗi nằm ở input, timing, footage, matching, preview hay export.

## Nguyên tắc chính

- Không phân tích lại toàn bộ nếu chỉ thay đổi một phần nhỏ.
- Ưu tiên dùng cache ở mọi giai đoạn.
- Tách rõ bước “phân tích” và bước “xuất kết quả”.
- Footage local/kho tổng nên được xử lý giống một nguồn online đã có metadata.
- Project chỉ lấy footage đã phân tích để dùng; không nên phải phân tích lại cùng một footage nhiều lần.

## Luồng tổng thể

```text
Kiểm tra dữ liệu
→ Phân tích timing
→ Phân tích footage local / kho footage
→ Ghép footage với beat
→ Preview & sửa thủ công
→ Export / Render
```

## Giai đoạn 1: Kiểm tra dữ liệu

Mục tiêu: xác nhận dữ liệu đầu vào đã đủ và hợp lệ trước khi chạy AI hoặc xử lý nặng.

Kiểm tra:

- `script.txt`
- `script_beat.csv`
- voice/audio
- cue sheet nhạc nếu có
- thư mục footage của project
- kho footage tổng nếu đang bật
- beat nào thiếu keyword, thiếu desired visual, thiếu footage hint

Output đề xuất:

- report input hợp lệ/chưa hợp lệ
- danh sách lỗi cần sửa
- chưa chạy model vision
- chưa phân tích footage

Nút UI đề xuất:

```text
Kiểm tra dữ liệu
```

## Giai đoạn 2: Phân tích timing

Mục tiêu: xác định thời lượng và vị trí timeline của từng section/beat.

Xử lý:

- align voice với script
- chia section
- tính start/end từng beat
- tính tổng duration
- thêm outro nếu project cần đạt minimum video minutes

Output hiện có/liên quan:

- `.cache/vfootage_alignment.json`
- `.cache/sections/...`
- beat timing
- cut timing

Nút UI đề xuất:

```text
Phân tích timing
```

Cache của giai đoạn này chỉ nên bị invalid khi:

- đổi script
- đổi voice
- đổi section/beat timing rule
- bật/tắt hoặc đổi cấu hình Whisper liên quan timing

Nếu chỉ thay footage, đổi model vision, đổi nhạc nền, hoặc export lại CapCut thì không cần chạy lại timing.

## Giai đoạn 3: Phân tích footage local / kho footage

Mục tiêu: phân tích các video footage có sẵn, tạo metadata và embedding để dùng lại.

Xử lý:

- quét scene
- tạo candidate
- kiểm tra chất lượng hình ảnh:
  - quá tối
  - quá sáng
  - mờ
  - rung
  - ít motion
  - mostly black
- tạo embedding vision-language
- lưu cache phân tích
- lưu metadata tái sử dụng

Output hiện có/liên quan:

- `.cache/footage_analysis/...`

Output nên có thêm cho kho footage tổng:

- `footage_id`
- provider: `pexels`, `pixabay`, `local`
- provider video id nếu có
- source url nếu có
- file hash
- duration
- resolution
- fps
- tags/keywords
- prompt/query đã dùng để tải
- license/source metadata
- analysis profile đã dùng
- embedding/cache path

Nút UI đề xuất:

```text
Phân tích footage
Phân tích kho footage
```

Lưu ý quan trọng:

Hiện cache footage đang phụ thuộc nhiều vào đường dẫn file. Nếu cùng một footage được chuyển từ project sang kho tổng, đường dẫn thay đổi có thể làm cache bị miss. Về lâu dài nên chuyển cache key sang:

```text
provider + provider_video_id
```

hoặc fallback:

```text
file hash
```

Như vậy một footage chỉ cần phân tích một lần, dù được dùng ở nhiều project.

## Giai đoạn 4: Ghép beat với footage

Mục tiêu: chọn footage phù hợp nhất cho từng beat đã có timing.

Input:

- beat timing từ giai đoạn 2
- candidate footage đã phân tích từ giai đoạn 3
- metadata từ `script_beat.csv`

Scoring:

- desired visual
- main idea
- keywords
- narration context
- quality score
- beat identity
- avoid prompts
- fallback penalty nếu phải dùng footage không thật sự khớp

Output hiện có/liên quan:

- `.cache/vfootage_timeline.json`
- `.cache/vfootage_timeline.csv`

Nút UI đề xuất:

```text
Ghép footage
```

Giai đoạn này nên chạy nhanh hơn nhiều nếu footage đã có cache. Khi chỉ sửa keyword/desired visual trong beat CSV, có thể chỉ cần chạy lại giai đoạn này, không cần phân tích lại footage.

## Giai đoạn 5: Preview và sửa thủ công

Mục tiêu: kiểm tra kết quả trước khi render/export.

Xử lý:

- xem beat nào thiếu footage
- xem beat nào dùng fallback
- xem beat nào điểm thấp
- thay footage cho từng beat
- khóa footage đã chọn
- tìm footage bổ sung nếu local chưa đủ
- ghép lại riêng các beat chưa đạt

Output:

- timeline report đã chỉnh
- lock file cho các lựa chọn thủ công
- danh sách beat cần tìm thêm footage
- danh sách footage mới tải từ Pexels/Pixabay

Nút UI đề xuất:

```text
Xem timeline
Tìm bổ sung
Khóa lựa chọn
Ghép lại beat chưa đạt
```

Đây là giai đoạn rất quan trọng vì không phải lúc nào AI cũng chọn đúng cảm xúc hình ảnh. Với video cầu nguyện/Dawn With God, đôi khi footage đúng kỹ thuật nhưng sai “khí” của đoạn script.

## Giai đoạn 6: Export / Render

Mục tiêu: chỉ xuất kết quả từ report có sẵn, không phân tích lại.

Xử lý:

- render video final
- export CapCut package
- export scene clips
- export narration
- export subtitle/SRT
- export manifest
- export nhạc nền đã mix cue sheet
- tạo hoặc cập nhật draft CapCut nếu cần

Output:

- video render
- CapCut package
- background music hoàn chỉnh
- manifest
- timeline CSV/JSON

Nút UI đề xuất:

```text
Render video
Xuất CapCut
Xuất nhạc nền
Xuất tất cả
```

Giai đoạn này không nên tự động chạy lại phân tích. Nếu report chưa có hoặc thiếu dữ liệu thì báo lỗi rõ ràng và yêu cầu chạy lại giai đoạn phù hợp.

## Hai chế độ phân tích

Nên có hai profile để cân bằng tốc độ và chất lượng.

Lưu ý quan trọng: độ dài cut luôn phải theo cài đặt hiện tại của project:

- minimum cut seconds
- target cut seconds
- maximum cut seconds

Profile không được tự ý đổi cut một cách ngầm. Nếu có preset thay đổi cut, app phải hiển thị rõ và chỉ áp dụng khi người dùng chủ động chọn.

### Fast Draft

Dùng khi muốn dựng nháp nhanh.

Đề xuất:

- model: `CLIP ViT-B/32`
- scene scan thấp hơn
- CLIP frame thấp hơn
- giữ nguyên cut theo cài đặt project
- dùng cache tối đa

Mục tiêu:

- nhanh
- đủ tốt để xem bố cục
- phù hợp khi đang chỉnh script/beat

### Final Quality

Dùng khi chuẩn bị xuất bản.

Đề xuất:

- model tốt hơn nếu máy chịu được, ví dụ SigLIP 2
- scan footage kỹ hơn
- frame sampling cao hơn
- scoring đầy đủ
- kiểm tra fallback kỹ hơn

Mục tiêu:

- chất lượng chọn footage tốt hơn
- ít cảnh lệch cảm xúc
- phù hợp lần chạy cuối

## Resume / Start nên hiểu thế nào

### Resume

Resume là chế độ nên dùng mặc định.

Ý nghĩa:

- dùng cache hiện có
- chỉ xử lý phần thiếu hoặc phần đã thay đổi
- nhanh hơn
- phù hợp hầu hết trường hợp

Nên dùng khi:

- sửa beat CSV
- sửa nhạc
- export lại CapCut
- render lại
- thêm vài footage mới
- tiếp tục project đang làm dở

### Start

Start là phân tích lại từ đầu.

Ý nghĩa:

- bỏ qua cache
- chạy lại toàn bộ phân tích
- rất chậm

Chỉ nên dùng khi:

- đổi model vision
- đổi profile phân tích quan trọng
- nghi cache sai/hỏng
- muốn kiểm tra lại toàn bộ từ đầu

## Kho footage tổng

Kho footage tổng chỉ nên đóng vai trò như một nguồn footage local đã được index, gần giống Pexels/Pixabay nhưng nằm trên máy.

Luồng đề xuất:

```text
Project tải footage mới từ Pexels/Pixabay
→ dùng trong project
→ sau khi project xong, bổ sung footage về kho tổng
→ kho tổng kiểm tra trùng
→ footage mới được lưu metadata/cache
→ project sau query kho tổng trước
→ thiếu mới gọi online
```

Khi đưa footage từ project về kho tổng:

- nếu đã tồn tại theo provider id hoặc hash thì bỏ qua
- nếu trùng file nhưng thiếu metadata thì bổ sung metadata
- nếu file lỗi hoặc quá thấp chất lượng thì đưa vào trạng thái rejected
- nếu tốt thì thêm vào searchable index

Mục tiêu cuối cùng:

```text
Query local footage ≈ Query online footage
```

Nghĩa là app không cần quan tâm footage đến từ đâu. Nó chỉ cần hỏi:

```text
Tìm cảnh phù hợp với beat này
```

Nguồn trả về có thể là:

- kho footage tổng
- project footage
- Pexels
- Pixabay

Nhưng data format nên thống nhất.

## Đề xuất triển khai theo thứ tự

1. Tách UI/command cho từng giai đoạn.
2. Thêm Fast Draft / Final Quality profile.
3. Làm rõ Resume / Start trên UI.
4. Chuẩn hóa metadata footage.
5. Cache footage theo provider id hoặc file hash.
6. Thêm chức năng bổ sung footage từ project về kho tổng.
7. Thêm chức năng warm cache cho kho footage.
8. Cho query local footage trước, thiếu mới gọi online.

## Kết luận

Không nên xem “phân tích” là một nút lớn duy nhất. Nên xem nó là một chuỗi giai đoạn nhỏ, mỗi giai đoạn có thể kiểm tra, cache, chạy lại và debug riêng.

Thiết kế đúng sẽ giúp:

- chạy nhanh hơn
- ít lỗi hơn
- dễ biết lỗi nằm ở đâu
- tái sử dụng footage tốt hơn
- giảm gọi online
- xây được kho footage ngày càng mạnh theo thời gian
