# Architecture

## Desktop shell

`storyflow_studio.desktop` chịu trách nhiệm hiển thị workflow, Settings,
progress và error. Desktop shell chỉ gọi service interfaces từ core/modules.

## Core

`storyflow_studio.core` chứa các thành phần dùng chung:

- Application configuration.
- Workspace Root, Project state và canonical project paths.
- Pipeline stages và status transitions.
- Event/progress contracts.
- Validation và error types.
- Secure secret-storage abstraction.

Core không phụ thuộc vào widget UI hoặc một AI/TTS provider cụ thể.

## Modules

### AI

Adapter cho Codex sử dụng ChatGPT login, model selection và Role/Instructions.
Module này không sử dụng `OPENAI_API_KEY`.

Phase 1 dùng Codex SDK account API để đọc session, lấy model catalog động và
khởi tạo browser-based ChatGPT login. UI chỉ giao tiếp qua `AIService`; các thao
tác Codex chạy trên Qt worker thread.

### Workspace

Quản lý Workspace Root, project folder, canonical filenames, output discovery
và project state. Codex được đọc/ghi đầy đủ trong project đang mở qua
`workspace-write`; Workspace Root không tự động trở thành Codex workdir.

### TTS

Bao gồm hai capability tách biệt bên trong cùng module:

1. Áp dụng TTS DNA để tạo `script_tts.txt`.
2. Gửi toàn bộ TTS Script lên Voice API bằng một job duy nhất để nhận một MP3
   và một SRT.

Voice provider được đặt sau interface để có thể tích hợp provider khác sau này.

Phase 3 triển khai một pipeline duy nhất: đọc Raw Script, áp dụng TTS DNA bằng
Codex, kiểm tra fidelity, ghi atomically `script_tts.txt`, rồi tạo đúng một
Voice API job. Job chỉ được đánh dấu hoàn tất khi một MP3 và một SRT đã được
validate và publish vào project. HTTP/polling chạy ngoài UI thread; progress đi
về desktop bằng queued Qt signals.

### Beat

Áp dụng Beat DNA lên `script_tts.txt`, sử dụng SRT làm timing và MP3 làm duration
tham chiếu, sau đó tạo `footage.csv`. Validated cue ownership được giữ thêm ở
`.storyflow/beat_timing.json` để downstream không phải chạy alignment lại.

### Footage

Footage Finder tìm/tải stock footage theo Beat và lưu attribution manifest.

### Video Builder

Phase 7B1 tạo draft timeline qua `VideoBuilderService`. Service tái sử dụng Beat
timing và Footage Finder inventory, ghi project-relative plan và structured
warning. Phase 7B2A bổ sung technical compatibility score, Timeline Review,
Retry Missing và fingerprint để nhận biết timeline stale. Phase 7B2B đặt FFmpeg
scene detection và CLIP/SigLIP sau optional adapter, rồi dùng beam optimizer để
chọn source window toàn timeline. Preview/Replace nằm ở desktop/service boundary;
render backend vẫn độc lập và desktop core không bắt buộc PyTorch/MoviePy.

Phase 7B3 dùng `FFmpegTimelineRenderer`: mỗi Cut được encode độc lập trong
`.storyflow/cache/video-builder`, concat ở mức stream rồi mux narration và file
background music đã render. Final MP4 chỉ được publish vào Project sau khi
ffprobe xác nhận video/audio, resolution và duration; attribution được xuất từ
Footage manifest cho đúng các source thực sự xuất hiện trên timeline.

Phase 7B4 dùng `CapCutPackageExporter` để chuyển saved timeline thành package
portable gồm các editable scene MP4, narration, captions, optional music và
timing manifest. Export độc lập với Final Render và không ghi vào dữ liệu nội
bộ của CapCut.

## Dependency direction

```text
desktop -> core interfaces <- modules
                         ^
                         |
                    provider adapters
```

Module không import UI. Module cũng không import trực tiếp module khác; pipeline
orchestrator trong core chịu trách nhiệm nối output của stage trước với input
của stage sau.

## Workspace and Project contract

Default paths đều có thể thay đổi trong Settings.

```text
workspace-root/
├── morning-prayer-001/
│   ├── script.txt
│   ├── script_tts.txt
│   ├── footage.csv
│   ├── audio/
│   │   ├── narration.mp3
│   │   └── narration.srt
│   └── .storyflow/
│       ├── project.json
│       ├── logs/
│       └── cache/
└── morning-prayer-002/
    └── ...
```

Credential không được lưu trong Workspace Root hoặc project.

Application settings không nhạy cảm được ghi atomically vào file JSON cấp ứng
dụng. TTS API key đi qua `SecretStore`; bản desktop mặc định dùng System
Keychain bằng package `keyring`. Settings JSON và project manifest không có
field API key.

Chi tiết vòng đời project được định nghĩa trong `PROJECT_MODEL.md`.
