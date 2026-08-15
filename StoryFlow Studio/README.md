# StoryFlow Studio

StoryFlow Studio là desktop application điều phối toàn bộ quy trình sản xuất:

```text
Script -> TTS DNA -> Voice MP3/SRT -> Beat DNA -> Footage -> Video Timeline
```

Đây là project chính mới. Các tool hiện có trong repository được xem là legacy
sources để migrate dần vào đây dưới dạng module độc lập. Không import trực tiếp
giao diện cũ vào ứng dụng mới.

## Nguyên tắc kiến trúc

- Một desktop shell PySide6 duy nhất.
- Mỗi capability là một module có service interface riêng.
- UI không gọi trực tiếp HTTP API, Codex SDK hoặc tool legacy.
- Workspace Root là nơi chứa nhiều project độc lập.
- Mỗi project là ranh giới dữ liệu và quyền thực thi của một workflow.
- Settings tách khỏi màn hình workflow.
- Provider có thể thay thế mà không cần viết lại UI.
- Migration theo từng phase; không di chuyển hàng loạt source chưa kiểm chứng.

## Cấu trúc

```text
StoryFlow Studio/
├── docs/
│   ├── ARCHITECTURE.md
│   └── IMPLEMENTATION_PLAN.md
├── src/storyflow_studio/
│   ├── core/
│   ├── desktop/
│   └── modules/
│       ├── ai/
│       ├── workspace/
│       ├── tts/
│       ├── beat/
│       ├── footage/
│       └── video_builder/
└── tests/
```

## Trạng thái

Product Phase 1–4, Footage Finder và Video Builder Phase 7B3 đã triển khai:
PySide6 application
shell, Codex ChatGPT authentication, Workspace/Project management, TTS DNA,
single-job Voice API pipeline, Beat DNA, Background Music và tìm/tải stock
footage. Video Builder tạo/review timeline; semantic Visual AI đã có dưới dạng
optional CLIP/SigLIP adapter. Final MP4 rendering và portable CapCut Package đã
được tích hợp bằng FFmpeg low-memory pipeline; Source legacy vẫn được giữ nguyên.

## Cài đặt và chạy

Yêu cầu Python 3.10 trở lên.

Các dependency Visual Model đã nằm trong `requirements.txt`. Cài đầy đủ bằng:

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

Desktop vẫn mặc định chạy `Technical Only`; chọn CLIP/SigLIP trong Settings
khi muốn chạy semantic scoring. Ở lần chạy đầu, app sẽ hỏi quyền tải model từ
Hugging Face rồi lưu vào cache của project; các lần sau có thể bật
`Use local model cache only` để chạy offline.

```bash
cd "StoryFlow Studio"
python3 -m venv .venv
.venv/bin/python -m pip install -e .
./run.sh
```

Sau lần cài đặt đầu tiên, chỉ cần chạy `./run.sh`. Script tự tìm đúng thư mục
ứng dụng và sử dụng Python trong `.venv`, kể cả khi được gọi từ thư mục khác.

Nếu chưa đăng nhập, bấm nút `○ Codex` trên header hoặc mở Settings rồi chọn
`Sign in with ChatGPT`. Browser sẽ mở luồng đăng nhập Codex. StoryFlow Studio
không yêu cầu `OPENAI_API_KEY`.

## Bắt đầu một project

1. Mở `Settings` và cấu hình `Workspace & Role`, `TTS` và `Beat DNA`.
2. Chọn `New Project`; project luôn được tạo trực tiếp bên trong Workspace Root.
3. Hoặc chọn `Open Project…` để mở thư mục có `.storyflow/project.json`.
4. Project đang mở trở thành Codex workdir với quyền `workspace-write`.

TTS API key được lưu bằng System Keychain, không nằm trong `settings.json` hoặc
project manifest. `Recent Projects` và project mở gần nhất được lưu ở application
settings. Voice API chỉ được gọi từ background worker sau khi TTS DNA output đã
qua fidelity validation.

## Chạy TTS Pipeline

1. Đăng nhập Codex bằng ChatGPT.
2. Trong `Settings → TTS & Voice`, chọn TTS DNA File và nhập API Base URL,
   API Key, Voice ID, Voice Model cùng thông số giọng.
3. Giữ `Require subtitle output` được bật.
4. Mở project, đặt kịch bản vào `script.txt`, rồi chọn `Refresh Status`.
5. Khi Step 1 hiện `Ready`, chọn `Run TTS Pipeline`.

Pipeline sẽ tạo lần lượt:

```text
script_tts.txt
audio/narration.mp3
audio/narration.srt
```

Activity Console hiển thị Codex, job ID, polling, download và lỗi.
`Stop Active Job` gửi cancel đến pipeline đang hoạt động. Mặc định StoryFlow
không ghi đè MP3/SRT đã có; bật `Overwrite` trong Settings nếu muốn chạy lại.

## Chạy Beat DNA

1. Hoàn thành TTS Pipeline để project có `script_tts.txt`, narration MP3 và SRT.
2. Trong `Settings → Beat DNA`, chọn DNA File.
3. Khi Step 3 hiện `Ready`, chọn `Generate Beat CSV`.

Codex dùng TTS Script để hiểu toàn bộ nội dung và dùng từng SRT cue làm mốc
timing. StoryFlow chỉ publish `footage.csv` sau khi mọi cue được phủ đúng một
lần, mã Beat liên tục và đủ năm cột mà Footage Video Builder yêu cầu. File đã
có sẽ đổi action thành `Generate Again`. Sau khi xác nhận, StoryFlow tạo lại
đồng bộ `footage.csv` và `.storyflow/beat_timing.json`; nếu ghi file mới lỗi,
hai artifact cũ được tự động khôi phục. Footage và Video Timeline downstream
được giữ nguyên nhưng có thể cần chạy lại để khớp Beat mới.

Cùng lúc đó app lưu `.storyflow/beat_timing.json`. Artifact này giữ cue range,
continuous timing và fingerprint của TTS Script/SRT/CSV để Video Builder dùng
lại mà không chạy Whisper hoặc căn Beat lần thứ hai.

## Background Music DNA

DNA mặc định cho bước tạo một file nhạc nền nằm tại
[`dna/background_music.md`](dna/background_music.md). DNA dùng TTS Script làm
ngữ cảnh, SRT làm timeline và chỉ chọn track từ Music Library được cung cấp.
Output gồm timeline có thể kiểm tra/chỉnh sửa `audio/cue_music.csv` và
một file music-only `audio/background_music.mp3`. Structured cue plan được
validate rồi chuyển thành CSV trước khi renderer ghép nhạc.

Đầu tiên bật `Use Background Music` trong `Settings → Background Music`; mặc
định tùy chọn này tắt. Khi chưa bật, card hiển thị `Disabled` và workflow bỏ qua
bước nhạc nền.

Trên card `Background Music`, nhấn `Generate` sau khi đã có `script_tts.txt`,
Narration MP3/SRT và Music Library. App áp dụng DNA bằng Codex, kiểm tra schema
legacy 10 cột, cue `C01…`, timestamp `MM:SS.mmm`, crossfade overlap, gain/LUFS,
sau đó render MP3 bằng FFmpeg. Nếu một trong hai output đã tồn tại, app không tự
ghi đè; xóa cả hai file trước khi tạo lại.

Trong `Settings → Background Music`, chỉ cấu hình Music Library Folder và DNA
tùy chọn. Output không phải cấu hình: app luôn ghi `audio/cue_music.csv` và
`<project>/audio/background_music.mp3`. Tab này có nút mở trang license, catalog và
`Import Downloaded Music…` để đưa các track đã tải vào thư viện:

- License: Mixkit Stock Music Free License
- License URL: [mixkit.co/license/#musicFree](https://mixkit.co/license/#musicFree)
- Catalog URL: [mixkit.co/free-stock-music](https://mixkit.co/free-stock-music/)

Nhạc được tải thủ công bằng browser. Sau đó chọn `Import Downloaded Music…`,
duyệt các file trong Downloads; StoryFlow kiểm tra audio metadata, chống trùng
bằng SHA-256, copy atomically vào Music Library Folder và cập nhật
`music_library.json` kèm nguồn/license Mixkit. StoryFlow không scrape hoặc tải
hàng loạt catalog.

## Tìm Stock Footage

1. Chạy Beat DNA để project có `footage.csv`.
2. Mở `Settings → Footage Finder`, bật Pexels và/hoặc Pixabay, sau đó
   nhập API key. Key được lưu trong System Keychain, không ghi vào
   `settings.json` hay project.
3. Chọn số query/Beat, số trang, số clip/Beat và bộ lọc duration,
   resolution. Có thể bật `Dry Run` để chỉ lập selection plan.
4. Trên card `Footage Finder`, nhấn `Search`.

Finder dùng từ khóa trong từng Beat, xếp hạng candidate theo metadata,
loại clip trùng, hỗ trợ resume và tải trực tiếp vào project:

```text
video/*.mp4
selected-footage.json
selected-footage.csv
.storyflow/cache/stock-search/*.json
```

Manifest giữ provider, contributor và source page để attribution/audit. Cache
tìm kiếm được giữ tối thiểu 24 giờ theo yêu cầu Pixabay; app cũng có
giới hạn số clip Pixabay mỗi lần chạy. Các API contract tham chiếu
[Pexels API](https://www.pexels.com/api/documentation/) và
[Pixabay API](https://pixabay.com/api/docs/).

Phase này không ghép footage, không dựng timeline và không gọi Video
Builder. Bước dựng video sẽ là phase riêng sau khi Finder được test
với project thật.

> **Trạng thái hiện tại:** Finder đã được triển khai và có automated tests,
> nhưng chưa được xác nhận end-to-end bằng API key/project thật. Semantic visual
> scoring, preview/replace theo từng Beat, MP4 validation, retry/backoff đầy đủ
> và final attribution output vẫn cần cải tiến. Danh sách ưu tiên chi tiết nằm
> trong [Implementation Plan](docs/IMPLEMENTATION_PLAN.md#phần-chưa-hoàn-thành-và-cần-cải-tiến).

## Analyze Video Timeline

1. Hoàn thành Voice và Beat DNA để có `.storyflow/beat_timing.json`.
2. Tìm footage hoặc tự đặt footage có prefix Beat vào `video/`.
3. Mở `Settings → Video Builder` và chọn Cut profile.
4. Nhấn `Analyze` trên card `06 · Video Builder`.

Sau lần đầu, action đổi thành `Analyze Again`. App hỏi xác nhận rồi thay
timeline JSON/CSV. Nếu lần phân tích mới lỗi hoặc không ghi đủ hai artifact,
timeline trước đó được tự động khôi phục.

Phase 7B tái sử dụng SRT timing, Beat cue ownership và Footage Finder
assignment để tạo:

```text
.storyflow/video-builder/timeline.json
video_timeline.csv
```

Đây là draft timeline có input fingerprint, project-relative footage path và
warning cho Beat thiếu nguồn, source bị dùng lại hoặc duration chưa được
`ffprobe` xác nhận. Chọn `Review` để xem từng Cut, scene window, technical/
semantic score, preview hoặc replace clip; `Retry Missing` quay lại Footage
Finder. CLIP/SigLIP được chọn trong Settings và dùng cache local mặc định.
Sau khi Review, chọn `Render`; app tạo `output/final_video.mp4` và
`output/attribution.csv`. `Render Again` giữ output cũ đến khi bản mới qua
ffprobe validation. Timeline stale/missing footage bị chặn; warning khác cần
xác nhận. Renderer hiện dùng hard cut, chưa áp dụng transition/cinematic
effects. Chi tiết thiết kế nằm tại
[`docs/VIDEO_BUILDER_INTEGRATION_ANALYSIS.md`](docs/VIDEO_BUILDER_INTEGRATION_ANALYSIS.md).

## Kiểm thử

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

## Project model

Khi mở ứng dụng, người dùng chọn `New Project` hoặc `Open Project`. Project mới
được tạo thành một thư mục con bên trong Workspace Root đã cấu hình.

Xem đặc tả tại [`docs/PROJECT_MODEL.md`](docs/PROJECT_MODEL.md).
