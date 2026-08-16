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
optional CLIP/SigLIP adapter. Final MP4 rendering, portable CapCut Package và
template-based editable CapCut Draft đã được tích hợp; Source legacy vẫn được
giữ nguyên.

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

### Windows

Lần đầu tiên, mở PowerShell hoặc nhấp đúp `setup-windows.bat`:

```powershell
cd "StoryFlow Studio"
.\setup-windows.bat
```

Script ưu tiên Python 3.12, 3.11 hoặc 3.10 từ Python Launcher, tạo `.venv` và cài
StoryFlow Studio cùng dependencies. Sau đó khởi chạy bằng:

```powershell
.\run.bat
```

`run.bat` và `run.ps1` luôn xác định thư mục ứng dụng từ chính vị trí của script,
vì vậy có thể chạy từ File Explorer hoặc từ một working directory khác. Nếu môi
trường thiếu dependency, launcher dừng với hướng dẫn chạy lại setup thay vì dùng
nhầm Python toàn hệ thống.

### Build file EXE trên Windows

Sau khi hoàn thành `setup-windows.bat`, chạy:

```powershell
.\build-windows.bat -Clean -StopRunningApp
```

Builder tự cài PyInstaller vào `.venv` nếu chưa có, chạy toàn bộ test, đóng gói
assets và kèm `ffmpeg.exe`/`ffprobe.exe`. Kết quả chính:

```text
dist\windows\StoryFlowStudio\StoryFlowStudio.exe
release\StoryFlowStudio-<version>-windows-<architecture>.zip
```

Đây là bản `onedir`: khi phân phối cần gửi toàn bộ thư mục `StoryFlowStudio` hoặc
file ZIP, không chỉ gửi riêng EXE. File `openai-codex-cli-bin` và các runtime khác
nằm trong thư mục `_internal`; gửi riêng `StoryFlowStudio.exe` sẽ làm chức năng kết
nối Codex báo thiếu dependency. Dạng này ổn định và khởi động nhanh hơn one-file đối
với PySide6, Torch và Transformers. Builder cũng kiểm tra Codex CLI trước khi tạo
file ZIP. Các tùy chọn build:

```powershell
.\build-windows.bat -SkipTests
.\build-windows.bat -Clean -NoArchive
```

Nếu bản trong `dist` đang mở, builder sẽ dừng trước khi xóa và hiển thị PID đang
khóa thư mục. Đóng ứng dụng thủ công hoặc thêm `-StopRunningApp` để chỉ dừng đúng
`StoryFlowStudio.exe` đang chạy từ thư mục build. Thao tác xóa được thử lại vài
lần để Windows và antivirus có thời gian nhả DLL.

Nếu chưa đăng nhập, bấm nút `○ Codex` trên header hoặc mở Settings rồi chọn
`Sign in with ChatGPT`. Browser sẽ mở luồng đăng nhập Codex. StoryFlow Studio
không yêu cầu `OPENAI_API_KEY`.

## Bắt đầu một project

1. Mở `Settings` và cấu hình `Workspace & Role`, `TTS` và `Beat DNA`.
2. Chọn `New Project`; project luôn được tạo trực tiếp bên trong Workspace Root.
3. Hoặc chọn `Open Project…` để mở thư mục có `.storyflow/project.json`.
4. Project đang mở trở thành Codex workdir với quyền `workspace-write`.

Hộp thoại `New Project` cho phép nhập tên, mô tả, folder name và Workspace Root.
Mô tả tối đa 2.000 ký tự, được lưu vào `.storyflow/project.json` để giữ mục tiêu,
đối tượng và định hướng nội dung của project.

TTS API key được lưu bằng System Keychain, không nằm trong `settings.json` hoặc
project manifest. `Recent Projects` và project mở gần nhất được lưu ở application
settings. Voice API chỉ được gọi từ background worker sau khi TTS DNA output đã
qua fidelity validation.

## Workflow thủ công và Auto

Các nút trên từng Step dùng để chạy thủ công. Step 1 `TTS Script` có nút
`Generate` và `Import` file TTS text UTF-8; sau khi có `script_tts.txt`, Step 2
`Voice` cũng có nút `Generate` để tạo MP3/SRT. Nút `Import` ở Step 2 cho phép dùng
một file narration audio và file SRT có sẵn. App kiểm tra cấu trúc/timing SRT,
đối chiếu thời lượng và tự đổi định dạng audio bằng FFmpeg nếu khác định dạng đầu
ra của project.

Nút `Auto` nằm cạnh `Stop Active Job` trong Activity Console. Khi nhấn, app yêu
cầu chọn `Final MP4` hoặc `CapCut Draft`, rồi lần lượt chạy TTS Script → Voice →
Beat DNA → Background Music (nếu bật) → Footage → Video Analyze → Export. Các
bước đã hoàn thành được bỏ qua. Khi Auto đang chạy, các nút thủ công bị khóa;
`Stop Active Job` sẽ hủy bước hiện tại và dừng cả chuỗi Auto.

Cạnh nút `Auto`, `Total ~…` hiển thị thời gian còn lại ước tính của toàn workflow.
Trong mỗi card đang chạy, ETA nằm bên phải trên cùng hàng với trạng thái `Running`.
Ước tính cập nhật mỗi giây từ kích thước project và progress thực tế; dấu `~` cho
biết đây là dự báo, đặc biệt có thể dao động ở các bước dùng API hoặc tải mạng.

## Chạy TTS Script và Voice thủ công

1. Đăng nhập Codex bằng ChatGPT.
2. Trong `Settings → TTS & Voice`, chọn TTS DNA File và nhập API Base URL,
   API Key, Voice ID, Voice Model cùng thông số giọng.
3. Giữ `Require subtitle output` được bật.
4. Mở project, đặt kịch bản vào `script.txt`, rồi chọn `Refresh Status`.
5. Khi Step 1 hiện `Ready`, chọn `Generate` để tạo `script_tts.txt`.
6. Khi Step 2 hiện `Ready`, chọn `Generate` để tạo narration MP3 và SRT.

Pipeline sẽ tạo lần lượt:

```text
script_tts.txt
audio/narration.mp3
audio/narration.srt
audio/screen.srt
```

After Voice creates the audio and full narration timing, StoryFlow automatically
asks Codex to read `script_tts.txt` and `narration.srt`, then creates the complete
viewer-facing captions in `audio/screen.srt`. All narration content is preserved;
only exact spoken numerical expressions may be converted to visual notation,
including Bible references, money, years, dates, percentages and measurements.
No manual caption editing is required.
The full `narration.srt` is timing input only and is never displayed as CapCut
captions.

The built-in conversion rules live in
`src/storyflow_studio/assets/dna/screen_subtitles.md`. In
`Settings → TTS & Voice → Screen SRT DNA`, leave the field empty to use this
built-in DNA or choose a custom Markdown DNA file. The custom DNA is loaded for
both generated and imported narration workflows.

When running from this repository, blank DNA settings automatically prefer
`BASE/DNA_screen_subtitles.md` and `BASE/DNA_background_music.md`. Packaged
copies under `storyflow_studio/assets/dna` are the fallback included in the EXE.

Activity Console hiển thị Codex, job ID, polling, download và lỗi.
`Stop Active Job` gửi cancel đến pipeline đang hoạt động. Mặc định StoryFlow
không ghi đè MP3/SRT đã có; bật `Overwrite` trong Settings nếu muốn chạy lại.

## Chạy Beat DNA

1. Hoàn thành TTS Script và Voice để project có `script_tts.txt`, narration MP3 và SRT.
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
Codex đọc toàn bộ nội dung để chia các đoạn cảm xúc, chọn track phù hợp cho
từng đoạn, chấm confidence và đưa ra alternative. Output gồm timeline
`audio/cue_music.csv`, file music-only `audio/background_music.mp3`, phân tích
`.storyflow/music_analysis.json` và đề xuất tìm thêm nhạc tại
`audio/music_recommendations.json`.

Đầu tiên bật `Use Background Music` trong `Settings → Background Music`; mặc
định tùy chọn này tắt. Khi chưa bật, card hiển thị `Disabled` và workflow bỏ qua
bước nhạc nền.

Trên card `Background Music`, nhấn `Generate` sau khi đã có `script_tts.txt`,
Narration MP3/SRT và Music Library. App áp dụng DNA bằng Codex, kiểm tra schema
legacy 10 cột, cue `C01…`, timestamp `MM:SS.mmm`, crossfade overlap, gain/LUFS,
sau đó render MP3 bằng FFmpeg. Khi thư viện chưa có track đủ phù hợp, app vẫn
dùng lựa chọn local an toàn nhất để render, đồng thời tạo search query cho
Mixkit/CapCut. Nút `Review` hiển thị timeline, mood, track đã chọn, confidence,
alternative, lý do và search query; các dòng cần bổ sung nhạc được tô vàng.
Từ Review có thể copy query, mở Mixkit, import nhạc thủ công hoặc chọn `Find &
Download`. Chức năng này dùng Query API công khai của ccMixter để tìm và tải tối
đa ba track phù hợp. App chỉ chấp nhận Public Domain hoặc Creative Commons
Attribution; NonCommercial và NoDerivatives bị loại. Artist, source URL, license
và attribution được lưu trong `music_library.json`, đồng thời app tạo
`audio/music_attribution.txt`. Sau khi tải xong, StoryFlow tự chạy `Generate
Again` để đánh giá thư viện mới và chỉ thay bộ output cũ sau khi kết quả mới đã
được validate và render thành công.

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

Mixkit chỉ dùng cho duyệt/tải thủ công. Tải tự động dùng ccMixter API theo
[Query API](https://ccmixter.org/query-api) và
[ccMixter Terms](https://ccmixter.org/terms). Track CC BY bắt buộc giữ credit;
hãy kiểm tra `audio/music_attribution.txt` trước khi xuất bản video.

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

Nếu kết quả Analyze có Beat thiếu footage, app tạo `footage_supplement.csv`
chứa đúng các dòng tìm kiếm cần bổ sung và hiển thị lựa chọn chạy Footage Finder.
Finder giữ nguyên clip/manifest hiện có và tải thêm phần còn thiếu. Khi hoàn tất,
app hỏi người dùng có tiếp tục Video Analyze hay không.

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

Khi workflow `Auto` hoàn tất Video Analyze mà không còn thiếu footage, app tự
chạy lựa chọn `Final MP4` hoặc `CapCut Draft` đã xác nhận lúc bật Auto.

## Xuất Draft CapCut

StoryFlow luôn tạo portable package tại `output/capcut_package`. Để tạo thêm một
Draft có thể mở và chỉnh sửa trực tiếp trong CapCut:

1. Tạo hoặc chọn một Draft template tương thích CapCut 9.1.0.
2. Trong `Settings → Video Builder → CapCut Draft`, chọn `Template Draft`.
3. Chọn `CapCut Drafts Root`; nếu để trống, app dùng thư mục cha của template.
4. Bật `Register generated Draft in CapCut` nếu muốn cập nhật registry của CapCut.
   Khi bật tùy chọn này phải đóng CapCut trước khi Export.
5. Mở `Export` trên Video Builder và chọn `Export CapCut Draft`.

Draft dùng tên project, chứa scene MP4, `narration.wav`, caption và optional
background music trong `Resources/StoryFlowStudio`. Export Again chỉ thay một
Draft có ownership marker của StoryFlow; Draft cùng tên do ứng dụng khác tạo sẽ
không bị ghi đè. Template schema khác `360000` bị từ chối để tránh làm hỏng Draft.

## Kiểm thử

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

## Project model

Khi mở ứng dụng, người dùng chọn `New Project` hoặc `Open Project`. Project mới
được tạo thành một thư mục con bên trong Workspace Root đã cấu hình.

Xem đặc tả tại [`docs/PROJECT_MODEL.md`](docs/PROJECT_MODEL.md).
