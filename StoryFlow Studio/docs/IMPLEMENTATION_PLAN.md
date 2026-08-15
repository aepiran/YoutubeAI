# Implementation Plan

Mỗi phase phải được kiểm tra và chấp nhận trước khi bắt đầu phase tiếp theo.

## Phase 1 — Codex integration and ChatGPT configuration

**Status: Complete — 2026-08-14**

- Hoàn thiện application entry point tối thiểu bằng PySide6.
- Migrate Codex authentication và execution logic từ legacy Video Flow vào
  module `storyflow_studio.modules.ai`.
- Tạo AI service interface và fake implementation cho tests.
- Tìm Codex runtime từ PATH hoặc bundled runtime mà không phụ thuộc một đường
  dẫn cứng trên máy.
- Hiển thị `Authentication Status` từ `codex login status`.
- Thêm `Sign in with ChatGPT`; thao tác này chạy browser login flow của
  `codex login`.
- Không cung cấp hoặc đọc `OPENAI_API_KEY`.
- Tạo riêng phần `ChatGPT / AI Configuration` gồm model, reasoning effort khi
  backend hỗ trợ và default AI options.
- Lưu AI configuration không nhạy cảm ở application scope.
- Chuẩn bị `workspace-write` làm permission mặc định; workdir thật sẽ được cấp
  bởi Project module ở Phase 2.

Tiêu chí hoàn thành:

- App khởi động được và không phụ thuộc source của legacy UI.
- Nhận biết đúng trạng thái chưa đăng nhập/đã đăng nhập bằng ChatGPT.
- Có thể bắt đầu browser login flow từ app và refresh trạng thái sau đăng nhập.
- Model đã chọn được lưu và truyền đúng vào AI service.
- Fake AI service chạy qua Qt worker mà không cập nhật widget từ background
  thread.
- Không có OpenAI API key field, environment requirement hoặc plaintext secret.
- Chưa tích hợp TTS API.

Implementation:

- `storyflow_studio.modules.ai.service`: ChatGPT-only Codex adapter.
- `storyflow_studio.core.settings`: non-secret AI settings store.
- `storyflow_studio.desktop`: PySide6 shell, Codex status button và Settings.
- Unit tests và Qt offscreen smoke test.

Tài liệu tham chiếu chính thức:

- [Codex authentication](https://learn.chatgpt.com/docs/auth)

## Phase 2 — Workspace, Project and remaining configuration

**Status: Complete — 2026-08-14**

- Tạo Settings model cho Workspace & Role, TTS và Beat DNA.
- Hoàn thiện Settings dialog PySide6 với bốn nhóm cấu hình.
- Lưu non-secret settings và bảo vệ TTS API key bằng System Keychain.
- Tạo `New Project`, `Open Project` và danh sách Recent Projects.
- Project mới luôn là thư mục con của Workspace Root.
- Dùng project đang mở làm Codex workdir với `workspace-write`.
- Main window chỉ hiển thị project hiện tại, workflow và progress.

Tiêu chí hoàn thành:

- Tạo và mở lại Project đúng theo `PROJECT_MODEL.md`.
- Project path không thể thoát khỏi Workspace Root.
- Codex không được dùng Workspace Root làm workdir.
- API key không xuất hiện dạng plaintext trong project hoặc application config.
- Chưa gọi TTS API.

Implementation:

- `storyflow_studio.modules.workspace`: tạo, mở, validate và discover trạng
  thái StoryFlow Project.
- `.storyflow/project.json`: snapshot canonical paths tại thời điểm tạo project.
- `storyflow_studio.core.settings`: schema cấu hình application cho AI,
  Workspace & Role, TTS và Beat DNA.
- `storyflow_studio.core.secrets`: lưu TTS API key trong System Keychain qua
  `keyring`; key không được serialize vào JSON.
- `storyflow_studio.desktop`: New/Open/Recent Projects, project overview và
  Settings dialog bốn nhóm.
- Unit tests cho path boundary, no-overwrite, manifest validation, output
  discovery, secret isolation và Qt desktop smoke flow.

## Phase 3 — TTS DNA and single-job Voice pipeline

**Status: Complete — 2026-08-14**

- Đọc `script.txt` và TTS DNA đã cấu hình.
- Áp dụng DNA qua Codex trong project workdir.
- Validate rằng Codex chỉ thay whitespace/line breaks, không thay nội dung.
- Ghi atomically thành `script_tts.txt`.
- Tách API client, balance, polling, retry, timeout, cancel và download khỏi
  legacy `tts.py`.
- Không migrate giao diện CustomTkinter.
- Không chia segment và không chạy parallel job.
- Một TTS Script tạo đúng một API job, một MP3 và một SRT.
- Console và từng stage nhận progress qua queued Qt signals.
- Output chỉ được publish sau khi cả MP3 và SRT hợp lệ.

Implementation:

- `storyflow_studio.modules.tts.service.TTSDNAService`: prompt, fidelity
  validation và Codex adapter.
- `VoiceApiClient`: HTTP contract tương thích legacy Voice API.
- `SingleJobVoiceService`: balance, generate, poll, retry, timeout, cancel và
  atomic output download.
- `TTSWorkflowService`: điều phối DNA → `script_tts.txt` → MP3/SRT.
- Desktop action `Run TTS Pipeline`, `Stop TTS`, Activity Console và stage
  progress.

## Phase 4 — TTS workflow screen

**Status: Merged into Phase 3 — 2026-08-14**

- Nhận Raw Script qua canonical `script.txt` của project.
- Output path được resolve từ Workspace và Settings.
- Không hiển thị output picker hoặc API configuration trên main screen.
- Chỉ hoàn thành khi cả MP3 và SRT hợp lệ.

## Phase 5 — TTS DNA

**Status: Merged into Phase 3 — 2026-08-14**

- Nhận Raw Script và áp dụng TTS DNA qua AI module.
- Validate rồi ghi atomically thành `script_tts.txt`.
- Theo quyết định Phase 3 mới, gọi Voice API ngay sau khi fidelity validation
  thành công; không dừng ở review screen.

## Phase 6 — Beat DNA (Product Phase 4)

**Status: Complete — 2026-08-14**

- Chỉ chạy khi MP3 và SRT sẵn sàng.
- Tạo canonical `footage.csv` tương thích với Footage Video Builder.
- Kiểm tra coverage, timing và required columns.

Implementation:

- `storyflow_studio.modules.beat.service.BeatDNAService`: gửi TTS Script,
  Beat DNA và SRT cue timing cho Codex trong project workdir.
- Codex trả structured JSON có contiguous cue ranges; ứng dụng không cho AI
  ghi file trực tiếp.
- `BeatWorkflowService`: kiểm tra TTS Script/SRT coverage, tham chiếu MP3
  duration bằng `ffprobe` khi có, kiểm tra mọi SRT cue được dùng đúng một lần
  và ghi atomically thành `footage.csv`.
- CSV chỉ có năm cột canonical `ma_beat`, `y_chinh`, `tu_khoa`,
  `hinh_can_tim`, `tranh`, tương thích Footage Video Builder.
- Desktop action `Generate Beat CSV`, Activity Console, stage progress và
  cancellation dùng Qt worker an toàn.
- Output hiện có chuyển desktop action sang `Generate Again`; người dùng xác
  nhận trước khi tạo lại đồng bộ `footage.csv` và `.storyflow/beat_timing.json`.
  Nếu publish thất bại, service tự khôi phục cả hai artifact cũ. Footage và
  Video Timeline downstream không bị xóa tự động và cần được kiểm tra/chạy lại.

## Background Music workflow

**Status: Complete — 2026-08-15**

- DNA mặc định: `dna/background_music.md`.
- Settings chỉ có Music Library Folder, DNA override, thông tin Mixkit Stock
  Music Free License và browser actions mở License/Catalog. Output là hai
  canonical project paths `audio/cue_music.csv` và `audio/background_music.mp3`,
  không cho cấu hình.
- `Import Downloaded Music…` cho người dùng duyệt các file đã tải; service kiểm
  tra audio metadata, chống trùng SHA-256, copy atomically và cập nhật
  `music_library.json` với nguồn/license Mixkit. Không scrape hoặc mass-download.
- Dùng `script_tts.txt` làm semantic context và SRT làm timeline chuẩn.
- Chỉ chọn track có thật trong Music Library được cấu hình.
- Codex trả structured cue plan; app validate và ghi atomically thành
  `audio/cue_music.csv` trước khi render, không trực tiếp ghi hoặc giả lập MP3.
- Renderer sẽ validate cue coverage, track path, duration, gain và fades trước
  khi publish `audio/cue_music.csv` và đúng một file music-only
  `audio/background_music.mp3`.
- Desktop card `Background Music` có Generate action, progress, cue count,
  cancellation và Activity Console. FFmpeg render theo overlap/crossfade của cue
  sheet legacy; output được publish atomically sau khi render thành công.
- Checkbox `Use Background Music` là opt-in và mặc định tắt. Khi tắt, card ở
  trạng thái Disabled, action bị khóa và service từ chối chạy trực tiếp.

## Phase 7 — Footage integrations

### Phase 7A — Footage Finder

**Status: Implemented — needs real-project validation — 2026-08-15**

- Đọc canonical `footage.csv` theo từng Beat.
- Tìm video ngang từ official Pexels Video API và Pixabay Video API.
- Cấu hình provider/API key, search breadth, clip count, duration, resolution,
  Pixabay cap và Dry Run trong `Settings → Footage Finder`.
- API key lưu bằng System Keychain; search cache không chứa secret.
- Ranking nhẹ dựa trên resolution, duration và popularity metadata; chưa
  migrate PyTorch/Transformers scorer của tool cũ.
- Chống trùng theo provider/video ID, hỗ trợ resume, atomic download và
  incremental manifest.
- Output cố định trong project: `video/*.mp4`, `selected-footage.json` và
  `selected-footage.csv`; search cache nằm trong `.storyflow/cache/stock-search`.
- Manifest lưu source URL/contributor cho attribution và audit.
- Desktop card có action `Search`, progress, cancel, console và số clip.

#### Phần chưa hoàn thành và cần cải tiến

**P0 — Cần làm trước khi coi Finder đạt production parity**

- Chưa chạy end-to-end bằng API key thật với project dài; tests hiện dùng fake
  provider và fake download response.
- Ranking mới chỉ dùng metadata (resolution, duration, popularity), chưa đánh
  giá mức độ khớp hình ảnh với `ý_chính`, `hình_cần_tìm` và nội dung cần
  `tránh`. Vì vậy clip đúng kỹ thuật vẫn có thể sai ngữ cảnh.
- Chưa có bước preview/review để người dùng giữ, loại hoặc tìm lại riêng một
  Beat trước khi tải toàn bộ.
- Chưa probe/validate stream MP4 sau download bằng `ffprobe`; hiện mới kiểm tra
  HTTP response và file không rỗng.
- Retry/backoff cho timeout, lỗi mạng và rate limit chưa đủ sâu; lỗi một Beat
  hiện làm toàn stage kết thúc ở trạng thái failed dù các clip đã tải vẫn được
  giữ để resume.

**P1 — Cải thiện chất lượng và vận hành**

- Bổ sung semantic/Visual AI scorer theo dạng adapter tùy chọn, không ép cài
  PyTorch/Transformers cho bản desktop cơ bản.
- Sinh/expand query từ `ý_chính`, `từ_khóa`, `hình_cần_tìm` và `tránh`; hỗ trợ
  synonym, fallback query và giới hạn query phù hợp từng provider.
- Thêm action `Retry Missing`, `Replace Clip` và trạng thái đủ/thiếu clip theo
  từng Beat trên giao diện.
- Làm rõ số request/quota còn lại, cache hit, clip đã resume và nguyên nhân bị
  loại trong Activity Console.
- Kiểm tra dung lượng ổ đĩa, giới hạn kích thước download và dọn file tạm khi
  ứng dụng bị đóng bất thường.
- Dry Run cần thay thế/cập nhật plan cũ thay vì có khả năng tích lũy nhiều bản
  ghi `planned` khi chạy lặp lại.
- Cần kiểm thử thêm cache expiry, invalid API key, HTTP 429, corrupt manifest,
  corrupt MP4, cancellation giữa download và resume sau crash.

**P2 — Chưa thuộc Footage Finder hiện tại**

- Chưa tạo thumbnail/contact sheet hoặc giao diện xem video trong app.
- Chưa tạo final credit/attribution output; manifest mới chỉ lưu dữ liệu nguồn.
- Chưa map clip vào SRT timing, chưa trim/crop/normalize và chưa dựng timeline.
- Chưa chạy Footage Video Builder dưới bất kỳ hình thức nào.

Điều kiện đóng Phase 7A: chạy thành công ít nhất một project thật với từng
provider được bật, kiểm tra thủ công chất lượng clip và attribution, xác nhận
resume sau lỗi mạng, và không còn lỗi P0 ảnh hưởng đến dữ liệu project.

### Phase 7B — Footage Video Builder

**Status: Phase 7B3 implemented — real-project validation required — 2026-08-15**

- Beat DNA lưu thêm `.storyflow/beat_timing.json` gồm validated cue ownership,
  continuous Beat timing và SHA-256 của Script/SRT/CSV. Video Builder không
  chạy Whisper, Codex hoặc Beat alignment lần thứ hai.
- Settings có tab `Video Builder`: resolution, FPS, workers, Cut profile,
  transition, minimum duration và encoder preset. Các field render/worker được
  chuẩn bị cho milestone sau; Phase 7B1 chỉ dùng Cut profile.
- `storyflow_studio.modules.video_builder.VideoBuilderService` tạo draft
  timeline từ Beat timing và footage inventory/manifest của Footage Finder.
- Timeline lưu project-relative footage path, input fingerprint, warning và
  trạng thái `finder_assignment_draft`.
- Canonical output: `.storyflow/video-builder/timeline.json` và
  `video_timeline.csv`.
- Desktop có card `06 · Video Builder`, action `Analyze`, progress, cancel,
  console và metric Cut/Warning. Sáu workflow card được chia thành hai hàng,
  mỗi hàng ba card.
- Timeline đã có đổi action thành `Analyze Again`; re-analysis cần xác nhận và
  tự khôi phục JSON/CSV cũ nếu lần ghi mới thất bại.
- Missing footage và source duration chưa verify trở thành review warning;
  service không tạo nguồn giả và chưa tuyên bố render-ready.
- Phase 7B2A nâng timeline lên schema 2, thêm technical compatibility score
  dựa trên duration verification, resolution và orientation metadata.
- Desktop có `Review` hiển thị từng Cut, source window, technical score,
  warning và missing Beat; `Retry Missing` quay lại Footage Finder mà không xóa
  clip đã tải.
- Review fingerprint Script/SRT/Beat timing/Beat CSV, footage manifest,
  inventory và Video Builder settings để cảnh báo timeline `stale` và yêu cầu
  `Analyze Again` trước Render.
- Phase 7B2B dùng FFmpeg scene detector adapter với safe fallback, chia source
  thành scene windows và tối ưu toàn chuỗi Cut bằng beam search có reuse/
  overlap/transition penalty.
- Optional semantic adapter hỗ trợ `openai/clip-vit-base-patch32` và
  `google/siglip2-base-patch16-224`. Runtime `torch`, `transformers`, `Pillow`
  nằm trong extra `visual`, không ép vào desktop core; local-cache-only bật
  mặc định.
- Timeline Review hiển thị Scene/Technical/Semantic score, mở clip bằng media
  player hệ thống và `Replace Clip` chỉ nhận source trong Project video folder.
  Manual override ghi atomically vào JSON/CSV và được đánh dấu cần semantic
  review lại.

Phần đã triển khai và validation còn lại:

- Validation còn lại của 7B2B: chạy model thật trên project dài, đo RAM/thời
  gian/cache hit và điều chỉnh score weights trước khi tuyên bố production-ready.
- Phase 7B3 implemented: low-memory FFmpeg render từng Cut, normalize
  resolution/FPS, concat, narration/background-music mix, disk-space check,
  progress/cancel, atomic `output/final_video.mp4`, `output/attribution.csv` và
  media validation bằng ffprobe.
- Desktop có `Render`/`Render Again`; timeline đã Analyze được render trực tiếp
  kể cả khi input fingerprint thay đổi, không tự chạy Analyze Again. Missing
  footage vẫn bị chặn và warning khác phải được người dùng xác nhận. Render
  Again giữ final MP4 cũ cho đến khi output mới vượt validation.
- Validation còn lại của 7B3: project dài thực tế, Windows packaging, crash
  recovery giữa Cut và transition/cinematic effects. Renderer hiện dùng hard
  cut để giữ narration timing chính xác; `transition_seconds` chưa được áp dụng.
- Phase 7B4 implemented: portable CapCut Package từ saved timeline, không chạy
  lại Analyze/Render. Export gồm normalized editable scenes, narration, SRT,
  optional background music/reference MP4, timing manifest, CSV và hướng dẫn
  import; publish atomically vào `output/capcut_package`. Direct draft database
  registration chưa bật vì phụ thuộc CapCut version/template và cần validation
  riêng trên macOS/Windows.
- Card 06 gom Final MP4 và CapCut vào một action `Export`; dialog cho chọn
  `Render Video` hoặc `Export CapCut Draft` để tránh làm chật card.

Phân tích đầy đủ và quyết định migration được lưu tại
[`VIDEO_BUILDER_INTEGRATION_ANALYSIS.md`](VIDEO_BUILDER_INTEGRATION_ANALYSIS.md).
Tool legacy tiếp tục hoạt động độc lập cho đến khi adapter mới đạt parity.

## Phase 8 — End-to-end hardening

- Resume/retry theo stage.
- Project locking để tránh job xung đột.
- Recovery, logs, tests và packaging desktop.
- Chỉ xóa legacy source sau khi migration được xác nhận đầy đủ.

## Quyết định đã khóa

- Tên sản phẩm: StoryFlow Studio.
- Desktop UI: PySide6.
- Python package: `storyflow_studio`.
- Một Workspace Root chứa nhiều project.
- Mỗi project là một thư mục con độc lập trong Workspace Root.
- Codex workdir là project đang mở, không phải toàn bộ Workspace Root.
- Settings nằm ngoài workflow chính.
- Codex dùng ChatGPT login, không dùng OpenAI API key.
- Một Voice request tạo một `narration.mp3` và một `narration.srt`.
- Default output nằm trong thư mục `audio` của project.
- Default folders và filenames có thể cấu hình.
- Legacy sources được migrate từng module, không chuyển hàng loạt.
