# Kiến trúc và sơ đồ hoạt động

## Kiến trúc module

| Module | Trách nhiệm |
|---|---|
| `inputs.py` | Nạp một audio, script, Beat và footage |
| `alignment.py` | Căn từ trong script với audio |
| `segmentation.py` | Chia lời thoại thành Cut |
| `scene_candidates.py` | Phát hiện scene và tạo cửa sổ ứng viên |
| `quality_scoring.py` | Lọc kỹ thuật và chấm model thị giác |
| `source_coverage.py` | Đo nguồn footage theo Beat |
| `optimization.py` | Tối ưu lựa chọn toàn Timeline |
| `effects.py` | Scale, transition, color và giữ khung cuối |
| `output.py` | Report, render và xuất scene |
| `low_memory_render.py` | Render từng scene rồi mux nguyên audio |
| `capcut_export/` | Gói scene, narration, caption và Draft CapCut |
| `ui/main_window.py` | Workflow, bảng Beat và cảnh báo tương tác |

## Pipeline chín Stage

```mermaid
flowchart LR
    A[INPUT] --> B[ALIGN]
    B --> C[CUT]
    C --> D[SHOT]
    D --> E[CLIP]
    E --> F[PLAN]
    F --> G[LOOK]
    G --> H[AUDIO]
    H --> I[OUTPUT]
```

| Stage | Chức năng |
|---|---|
| INPUT | Audio, transcript, Beat và kho footage |
| ALIGN | Căn lời thoại với audio |
| CUT | Chia lời theo Min/Target/Max |
| SHOT | Phát hiện scene và Candidate |
| CLIP | Lọc chất lượng và chấm nội dung |
| PLAN | Tối ưu toàn bộ Timeline |
| LOOK | Transition, animation và color |
| AUDIO | Gắn nguyên audio lời thoại |
| OUTPUT | Xuất MP4, report hoặc CapCut |

## Luồng phân tích

```mermaid
flowchart TD
    P[Project] --> V[Đúng 1 Audio]
    P --> S[script.txt]
    P --> B[footage.csv]
    P --> F[video/]
    V --> A[Căn word timing]
    S --> A
    A --> C[Cut 3-5-7 giây]
    B --> C
    F --> D[Candidate footage]
    D --> Q[Lọc chất lượng]
    C --> M[Ma trận semantic]
    Q --> M
    M --> O[Beam search toàn Timeline]
    O --> H[Kiểm tra độ phủ và bất thường]
    H --> R[vfootage_timeline.json]
```

## Luồng render không cắt audio

```mermaid
sequenceDiagram
    participant R as Report
    participant F as Footage Renderer
    participant A as Audio gốc
    participant X as FFmpeg
    participant O as MP4

    R->>F: Danh sách Cut hình ảnh
    F->>X: Render/concat video scene
    A->>X: Mux toàn bộ narration
    Note over X: Không dùng -shortest
    X->>O: Video có thời lượng theo audio
```

## Dữ liệu report

Report chính:

```text
project/.cache/vfootage_timeline.json
```

Chứa:

- Thông tin đầu vào.
- Word timing.
- Timeline Cut.
- Footage và khoảng nguồn.
- Điểm semantic/chất lượng.
- Cảnh báo nguồn.
- Tổng điểm tối ưu.

## CapCut

Gói CapCut:

```text
capcut_package/
├── scenes/
├── narration.wav
├── captions.srt
├── capcut_manifest.json
└── README_CAPCUT.txt
```

Audio trong Draft là `narration.wav` duy nhất, bắt đầu tại `00:00:00`.

