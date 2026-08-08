"""Stage 1: load narration, transcript, beats, and the footage library."""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path

from moviepy import AudioFileClip, concatenate_audioclips

from .config import PipelineConfig
from .models import Beat, ScriptSection


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
VOICE_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
SCRIPT_MARKER_PATTERN = re.compile(r"^\s*SCRIPT\s*:\s*", re.IGNORECASE | re.MULTILINE)
PAUSE_MARKER_PATTERN = re.compile(r"<#\s*\d+(?:[.,]\d+)?\s*#>")
SECTION_HEADER_PATTERN = re.compile(
    r"^\s*\[([^\]\r\n]+)\]\s*$",
    re.MULTILINE,
)


def clean_script_text(text: str) -> str:
    """Remove authoring markers that are not spoken narration."""
    cleaned = PAUSE_MARKER_PATTERN.sub("\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def normalize_beat_code(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def filename_beat_code(
    path: Path,
    known_codes: set[str] | None = None,
) -> str | None:
    """Return the Beat code encoded in a footage filename.

    Prefer exact CSV codes so B044 does not get confused with B0044 or H044.
    """
    stem = path.stem.upper()
    if known_codes:
        for code in sorted(known_codes, key=len, reverse=True):
            escaped = re.escape(normalize_beat_code(code))
            if re.search(rf"(?:^|[^A-Z0-9]){escaped}(?=[^A-Z0-9]|$)", stem):
                return normalize_beat_code(code)
    match = re.search(r"(?:^|[^A-Z0-9])([A-Z]+\d+)(?=[^A-Z0-9]|$)", stem)
    return match.group(1).upper() if match else None


def parse_script_sections(
    content: str,
) -> tuple[str, list[ScriptSection]]:
    """Remove SCRIPT/section metadata and return narration-only text.

    A header such as ``[HOOK]`` starts a section. The header is metadata and
    must never become a transcript token used by alignment or CLIP scoring.
    """
    marker = SCRIPT_MARKER_PATTERN.search(content)
    body = content[marker.end():] if marker else content
    headers = list(SECTION_HEADER_PATTERN.finditer(body))
    if not headers:
        narration = clean_script_text(body)
        if not narration:
            raise ValueError("script.txt không có nội dung lời thoại")
        return narration, [ScriptSection(index=1, name="", text=narration)]

    preamble = body[:headers[0].start()].strip()
    if preamble:
        raise ValueError(
            "Có lời thoại nằm trước Section header đầu tiên trong script.txt"
        )
    sections = []
    for index, header in enumerate(headers, start=1):
        end = headers[index].start() if index < len(headers) else len(body)
        name = header.group(1).strip()
        text = clean_script_text(body[header.end():end])
        if not name:
            raise ValueError(f"Section header trống tại vị trí {index}")
        if not text:
            raise ValueError(f"Section [{name}] không có lời thoại")
        sections.append(ScriptSection(index=index, name=name, text=text))
    narration = "\n\n".join(section.text for section in sections)
    return narration, sections


def load_script(
    filepath: Path,
    voice_files: list[Path],
) -> tuple[str, list[ScriptSection]]:
    if len(voice_files) != 1:
        raise ValueError(
            "Project phải có đúng 1 file Audio cho toàn bộ kịch bản; "
            f"hiện tìm thấy {len(voice_files)} file."
        )
    content = filepath.read_text(encoding="utf-8-sig")
    narration, sections = parse_script_sections(content)
    # Section headers in older scripts are treated as authoring metadata only.
    # The current product model exposes one complete script and one narration.
    return narration, [
        ScriptSection(index=1, name="FULL SCRIPT", text=narration)
    ]


def discover_srt_files(voice_files: list[Path]) -> list[Path | None]:
    """Match an optional SRT to every voice, preferring an exact basename."""
    result = []
    all_srt = {
        path.resolve()
        for directory in {path.parent for path in voice_files}
        for path in directory.glob("*.srt")
        if path.is_file()
    }
    for voice in voice_files:
        exact = voice.with_suffix(".srt").resolve()
        if exact in all_srt:
            result.append(exact)
            continue
        voice_match = re.match(r"^(\d+)", voice.stem)
        voice_number = int(voice_match.group(1)) if voice_match else None
        numeric_matches = []
        for path in all_srt:
            match = re.match(r"^(\d+)", path.stem)
            if match and int(match.group(1)) == voice_number:
                numeric_matches.append(path)
        if len(numeric_matches) > 1:
            raise ValueError(
                f"Có nhiều file SRT khớp với Voice số {voice_number}: "
                + ", ".join(sorted(path.name for path in numeric_matches))
            )
        if numeric_matches:
            print(
                f"Cảnh báo: SRT được khớp theo tiền tố số: "
                f"{voice.name} -> {numeric_matches[0].name}"
            )
            result.append(numeric_matches[0])
        else:
            result.append(None)
    return result


def load_beats(filepath: Path) -> list[Beat]:
    required = {"ma_beat", "y_chinh", "tu_khoa", "hinh_can_tim", "tranh"}
    if not filepath.exists():
        raise FileNotFoundError(f"Không tìm thấy Beat CSV: {filepath}")

    beats = []
    seen = set()
    with filepath.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{filepath.name} thiếu các cột: {', '.join(sorted(missing))}"
            )
        for row_index, row in enumerate(reader, start=2):
            code = (row["ma_beat"] or "").strip()
            match = re.search(r"(\d+)", code)
            if not match:
                raise ValueError(
                    f"ma_beat không hợp lệ tại dòng CSV {row_index}: {code!r}"
                )
            number = int(match.group(1))
            if number in seen:
                raise ValueError(
                    f"Trùng Beat số {number} trong {filepath.name}"
                )
            beat = Beat(
                number=number,
                code=code,
                main_idea=(row["y_chinh"] or "").strip(),
                keywords=(row["tu_khoa"] or "").strip(),
                desired_visual=(row["hinh_can_tim"] or "").strip(),
                avoid=(row["tranh"] or "").strip(),
                section=(row.get("section") or "").strip(),
            )
            if not beat.main_idea or not beat.desired_visual:
                raise ValueError(f"{code} phải có y_chinh và hinh_can_tim")
            beats.append(beat)
            seen.add(number)
    if not beats:
        raise ValueError(f"Không tìm thấy Beat trong {filepath.name}")
    return beats


def list_video_files(directory: Path) -> list[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Không tìm thấy thư mục Footage: {directory}")
    return sorted(
        (
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ),
        key=lambda path: [
            int(part) if part.isdigit() else part
            for part in re.split(r"(\d+)", str(path).lower())
        ],
    )


def voice_sort_key(path: Path) -> tuple[float, str]:
    match = re.match(r"^(\d+)", path.stem)
    number = int(match.group(1)) if match else math.inf
    return number, path.name.lower()


def numbered_voice_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    files = []
    ignored = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in VOICE_EXTENSIONS:
            continue
        if not re.match(r"^\d+", path.stem):
            ignored.append(path.name)
            continue
        files.append(path)
    if ignored:
        print(
            f"Cảnh báo: bỏ qua file Voice không có tiền tố số trong "
            f"{directory}: {', '.join(sorted(ignored))}"
        )
    return sorted(files, key=voice_sort_key)


def discover_voice_files(config: PipelineConfig) -> list[Path]:
    if config.selected_voice_files:
        missing = [path for path in config.selected_voice_files if not path.is_file()]
        invalid = [
            path
            for path in config.selected_voice_files
            if path.suffix.lower() not in VOICE_EXTENSIONS
        ]
        if missing:
            raise FileNotFoundError(f"Không tìm thấy file Voice: {missing[0]}")
        if invalid:
            raise ValueError(f"Định dạng Voice không được hỗ trợ: {invalid[0]}")
        if len(config.selected_voice_files) != 1:
            raise ValueError(
                "Chỉ được chọn đúng 1 file Audio cho toàn bộ kịch bản."
            )
        return list(config.selected_voice_files)

    folder_voices = sorted(
        (
            path
            for path in config.voices_dir.iterdir()
            if path.is_file() and path.suffix.lower() in VOICE_EXTENSIONS
        ),
        key=voice_sort_key,
    ) if config.voices_dir.is_dir() else []
    if folder_voices:
        if len(folder_voices) != 1:
            raise ValueError(
                f"Thư mục {config.voices_dir} phải có đúng 1 file Audio; "
                f"hiện có {len(folder_voices)} file."
            )
        root_voices = numbered_voice_files(config.base_dir)
        if root_voices:
            print(
                f"Nguồn Voice: dùng {config.voices_dir}; bỏ qua "
                f"{len(root_voices)} file Audio có đánh số trong {config.base_dir}."
            )
        return folder_voices
    root_voices = numbered_voice_files(config.base_dir)
    if root_voices:
        if len(root_voices) != 1:
            raise ValueError(
                f"Project phải có đúng 1 file Audio; hiện tìm thấy "
                f"{len(root_voices)} file tại {config.base_dir}."
            )
        return root_voices
    raise FileNotFoundError(
        f"Không tìm thấy file Audio trong {config.voices_dir} hoặc "
        f"{config.base_dir}. Project cần đúng 1 file như narration.mp3."
    )


def open_voice_timeline(
    voice_files: list[Path],
    srt_files: list[Path | None] | None = None,
):
    source_clips = []
    timeline = []
    cursor = 0.0
    try:
        for voice_index, path in enumerate(voice_files):
            clip = AudioFileClip(str(path))
            source_clips.append(clip)
            end = cursor + float(clip.duration)
            timeline.append(
                {
                    "path": path,
                    "name": path.name,
                    "start": cursor,
                    "end": end,
                    "duration": float(clip.duration),
                    "srt_path": (
                        srt_files[voice_index]
                        if srt_files is not None else None
                    ),
                }
            )
            cursor = end
    except Exception:
        for clip in source_clips:
            clip.close()
        raise
    combined = (
        source_clips[0]
        if len(source_clips) == 1
        else concatenate_audioclips(source_clips)
    )
    return combined, source_clips, timeline


def load_project_inputs(config: PipelineConfig):
    validate_inputs(config)
    beats = load_beats(config.beats_file)
    voice_files = discover_voice_files(config)
    script, script_sections = load_script(config.script_file, voice_files)
    srt_files = discover_srt_files(voice_files)
    video_files = list_video_files(config.videos_dir)
    if not video_files:
        raise FileNotFoundError(
            f"Không tìm thấy Footage trong {config.videos_dir}"
        )
    return (
        script,
        script_sections,
        beats,
        voice_files,
        srt_files,
        video_files,
    )


def validate_inputs(config: PipelineConfig) -> None:
    for filepath in (config.script_file, config.beats_file):
        if not filepath.exists():
            raise FileNotFoundError(
                f"Không tìm thấy dữ liệu đầu vào bắt buộc: {filepath}"
            )
    config.output_file.parent.mkdir(parents=True, exist_ok=True)
