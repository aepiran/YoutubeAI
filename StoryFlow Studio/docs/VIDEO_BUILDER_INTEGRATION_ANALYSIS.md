# Video Builder Integration Analysis

## Mục tiêu

Tích hợp lõi `tools/footage-video-builder` vào StoryFlow Studio mà không nhúng
giao diện PySide6 cũ, không dựng lại dữ liệu mà các stage trước đã xác nhận và
không gọi Video Builder legacy như một ứng dụng độc lập.

Luồng sản phẩm đề xuất:

```text
Footage Finder
    -> Analyze Timeline
    -> Review / Retry Missing Footage
    -> Render Final Video
```

## Dữ liệu có thể tái sử dụng

| Video Builder cần | Canonical StoryFlow input |
|---|---|
| Nội dung narration | `script_tts.txt` |
| Một audio duy nhất | `audio/narration.mp3` |
| Timing | `audio/narration.srt` |
| Beat semantic | `footage.csv` |
| Beat timing | `.storyflow/beat_timing.json` |
| Footage theo Beat | `video/H01_*.mp4` |
| Metadata/source footage | `selected-footage.json` |
| Nhạc nền đã render | `audio/background_music.mp3` |

`Beat DNA` đã biết chính xác mỗi Beat sở hữu cue SRT nào. Vì vậy StoryFlow cần
lưu lại artifact timing ngay lúc tạo `footage.csv`; Video Builder không cần
chạy Whisper hoặc căn Beat với narration lần thứ hai.

Footage Finder đã gắn provider video vào từng Beat và lưu duration/source trong
manifest. Timeline analysis có thể dùng assignment này làm draft plan trước
khi bổ sung Visual AI scorer.

## Kiến trúc đích

```text
desktop -> VideoBuilderService -> analysis backend -> timeline artifacts
                             \-> render backend   -> final_video.mp4
```

API module:

```python
VideoBuilderService.analyze(project, settings, progress, cancellation)
VideoBuilderService.render(project, settings, progress, cancellation)
```

Analysis và render nặng nên chạy trong worker process riêng ở bản hoàn chỉnh.
UI chỉ nhận structured progress event; không parse câu log đã dịch.

## Canonical output

```text
.storyflow/video-builder/timeline.json
video_timeline.csv
.storyflow/cache/video-builder/
output/final_video.mp4
output/attribution.csv
```

Report phải lưu project-relative path để project vẫn dùng được sau khi di
chuyển. Final output phải được render vào temporary path, validate bằng
`ffprobe`, rồi mới publish atomically.

## Cấu hình

Tab `Settings -> Video Builder` gồm resolution, FPS, analysis workers,
Min/Target/Max Cut, encoder preset, transition và model thị giác. Output path
không cấu hình; nó thuộc Project contract.

Quyết định mặc định:

- Dùng SRT timing, chưa cài Whisper trong MVP.
- Cut profile `3 / 4 / 5` giây theo implementation legacy hiện tại.
- Không tự kéo video lên 25 phút; minimum duration mặc định tắt.
- Nhạc nền dùng trực tiếp `audio/background_music.mp3`, không đọc lại Music
  Library hoặc render cue sheet lần nữa.
- CapCut Export không thuộc MVP.

## Migration scope

### Phase 7B1 — Timeline Analysis

- Lưu Beat timing artifact từ Beat DNA.
- Tạo Video Builder settings và project paths.
- Tạo draft timeline từ validated SRT/Beat timing và footage inventory.
- Tính source coverage, cut count và warning count.
- Tạo JSON/CSV report và card `Analyze`.
- Cho phép `Analyze Again` với confirmation và rollback về plan cũ nếu lần
  phân tích mới thất bại.

Draft plan tái sử dụng assignment của Footage Finder. Chất lượng kỹ thuật và
semantic Visual AI chưa được chấm trong milestone này và phải được thể hiện rõ
trong report.

### Phase 7B2 — Visual Analysis and Review

- Migrate scene detection, technical scoring, CLIP/SigLIP scoring và global
  optimization từ legacy core.
- Thêm Timeline Review, Replace Clip và Retry Missing.
- Nối source coverage thiếu về Footage Finder hiện tại.
- Fingerprint input để phát hiện report stale.

#### Phase 7B2A — Implemented

- Technical compatibility scoring từ duration verification và metadata
  resolution/orientation, không yêu cầu dependency ML.
- Timeline Review read-only theo từng Cut, warning và missing Beat.
- `Retry Missing` nối lại Footage Finder; input fingerprint phát hiện timeline
  stale sau khi Script, Beat, footage hoặc settings thay đổi.

#### Phase 7B2B — Implemented, needs real-model validation

- FFmpeg scene candidate adapter với safe fallback.
- Optional CLIP/SigLIP Hugging Face adapter; model được hỏi quyền tải ở lần đầu
  và lưu trong project cache. Local-only dành cho model đã tải sẵn.
- Beam-search global selection phạt source-window overlap/reuse và ưu tiên tổng
  hợp semantic/technical score.
- Timeline Review có Scene/Semantic columns, system-player Preview và atomic
  Replace Clip trong Project footage inventory.

### Phase 7B3 — Final Render

**Implemented — needs long-project validation.**

- Low-memory FFmpeg render từng normalized Cut và concat stream.
- Mix toàn bộ narration với `audio/background_music.mp3` khi Music được bật;
  không dùng `-shortest` và không cắt narration theo video rounding.
- Progress/cancel, disk-space check, temporary workspace, atomic publish và
  ffprobe validation cho resolution/video/audio/duration.
- Canonical outputs: `output/final_video.mp4` và `output/attribution.csv`.
- Render/Render Again trên desktop dùng trực tiếp saved timeline, kể cả khi
  fingerprint đã stale; app không tự Analyze Again. Missing footage vẫn bị
  chặn và warning cần xác nhận. Transition/cinematic effects vẫn pending để
  không làm sai narration timing trong low-memory pipeline.

### Phase 7B4 — Optional exports

**Portable CapCut Package implemented — direct draft registration pending.**

- Dùng trực tiếp saved timeline, không Analyze hoặc Render lại.
- FFmpeg xuất từng Cut thành scene MP4 đã trim/normalize, giữ đúng thứ tự và
  narration timing.
- Package cố định tại `output/capcut_package`, gồm `scenes/`, narration,
  captions SRT, optional background music/reference MP4,
  `selected_scenes.csv`, `capcut_manifest.json` và hướng dẫn import.
- Publish atomically; khi export lại, package cũ được giữ đến lúc package mới
  hoàn tất.
- Desktop dùng một nút `Export`, sau đó chọn `Render Video` hoặc
  `Export CapCut Draft` trong dialog.
- Chưa ghi trực tiếp vào CapCut draft registry/database vì schema phụ thuộc
  version và template; bước này cần fixture thật trên từng platform.

## Rủi ro cần xử lý

- Legacy report dùng absolute path; phải chuyển sang project-relative path.
- PyTorch/Transformers/OpenCV làm build lớn; nên là optional video runtime.
- Cancellation legacy chưa đi sâu vào scene scan/model scoring.
- Render-only ưu tiên saved timeline; stale fingerprint chỉ cảnh báo trong log.
  Renderer vẫn validate source footage, Cut continuity và narration coverage.
- Cache phải fingerprint script, SRT, Beat CSV, footage inventory, model và
  settings.
- Critical warning cần review/confirmation trước render.

## Điều kiện hoàn thành

- Timeline phủ liên tục toàn bộ narration và mọi Cut thuộc đúng Beat timing.
- Không có source window âm, vượt duration hoặc overlap trái chính sách.
- Project di chuyển vẫn đọc được timeline.
- Missing footage được báo theo Beat và có đường quay lại Finder.
- Final MP4 giữ nguyên toàn bộ narration, không bị `-shortest` cắt mất audio.
