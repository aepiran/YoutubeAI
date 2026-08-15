# Workspace and Project Model

## Khái niệm

### Workspace Root

Workspace Root là thư mục cha dùng để chứa tất cả StoryFlow projects. Đây là
một thiết lập cấp application và được chọn trong Settings.

Ví dụ:

```text
/Users/name/StoryFlow Projects/
```

### Project

Project là một thư mục con trực tiếp trong Workspace Root. Mỗi project chứa
toàn bộ input, output và trạng thái của đúng một workflow sản xuất video.

```text
StoryFlow Projects/
└── morning-prayer-001/
    ├── script.txt
    ├── script_tts.txt
    ├── footage.csv
    ├── video_timeline.csv
    ├── video/
    ├── output/
    │   ├── final_video.mp4
    │   ├── attribution.csv
    │   └── capcut_package/
    ├── audio/
    │   ├── narration.mp3
    │   └── narration.srt
    └── .storyflow/
        ├── project.json
        ├── beat_timing.json
        ├── video-builder/
        ├── logs/
        └── cache/
```

## New Project workflow

```text
Launch StoryFlow Studio
        -> New Project
        -> nhập Project Name
        -> tạo/kiểm tra Folder Name
        -> xác nhận Workspace Root
        -> Create Project
        -> mở project workflow
```

Dialog `New Project` gồm:

- `Project Name`: tên hiển thị.
- `Folder Name`: slug được sinh tự động nhưng có thể sửa.
- `Workspace Root`: lấy mặc định từ Settings và có thể đổi trước khi tạo.
- Preview đường dẫn project đầy đủ.

Quy tắc tạo project:

- Folder Name không chứa path separator hoặc `..`.
- Project path sau khi resolve phải nằm trực tiếp trong Workspace Root.
- Không ghi đè thư mục đã tồn tại.
- Nếu thư mục đã là StoryFlow project, đề nghị `Open Project` thay vì tạo lại.
- Tạo `.storyflow/project.json` trước khi đánh dấu project sẵn sàng.
- Không lưu credential trong project manifest.

## Project manifest

`.storyflow/project.json` tối thiểu chứa:

```json
{
  "schema_version": 1,
  "project_id": "uuid",
  "name": "Morning Prayer 001",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "paths": {
    "raw_script": "script.txt",
    "tts_script": "script_tts.txt",
    "audio_dir": "audio",
    "audio_file": "narration.mp3",
    "subtitle_file": "narration.srt",
    "beat_file": "footage.csv",
    "beat_timing_file": ".storyflow/beat_timing.json",
    "footage_dir": "video",
    "video_timeline_file": ".storyflow/video-builder/timeline.json",
    "video_timeline_csv": "video_timeline.csv",
    "final_video_file": "output/final_video.mp4",
    "attribution_file": "output/attribution.csv",
    "capcut_package_dir": "output/capcut_package"
  },
  "stages": {
    "tts_script": "pending",
    "voice": "pending",
    "beat": "pending",
    "footage": "pending",
    "video_plan": "pending",
    "video_render": "pending"
  }
}
```

Tên file mặc định đến từ Settings tại thời điểm tạo project và được snapshot
vào manifest. Thay đổi Settings sau này không âm thầm đổi đường dẫn của project
đã tồn tại; người dùng phải xác nhận migration riêng.

## Open Project

Một thư mục được coi là StoryFlow project khi có:

```text
.storyflow/project.json
```

Khi mở project:

- Validate manifest schema và project paths.
- Không cho relative path thoát ra ngoài project directory.
- Discover MP3, SRT và Beat output hiện có.
- Khôi phục stage status từ trạng thái file thực tế.
- Đưa project hợp lệ vào Recent Projects.

## Permission boundary

Project directory đang mở là Codex workdir. `workspace-write` cho phép Codex
đọc/ghi đầy đủ bên trong project nhưng không tự động cấp quyền cho các project
khác cùng Workspace Root hoặc các thư mục ngoài Workspace Root.

TTS API được gọi trực tiếp bởi Voice provider của application, không phụ thuộc
vào Codex sandbox.
