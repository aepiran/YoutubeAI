from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

from .alignment import (
    align_beats_to_script,
    create_word_timings,
    script_tokens,
)
from .config import PipelineConfig
from .models import Beat, ScriptSection, SpeechSegment, WordTiming
from .segmentation import group_beats_by_duration


SECTION_CACHE_VERSION = 1


def _slug(section: ScriptSection) -> str:
    name = re.sub(
        r"[^A-Za-z0-9_-]+", "-", section.name
    ).strip("-")
    return f"{section.index:03d}_{name or 'UNTITLED'}"


def _file_signature(path: Path | None) -> dict | None:
    if path is None:
        return None
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _fingerprint(
    config: PipelineConfig,
    section: ScriptSection,
    voice: dict,
    skip_whisper: bool,
) -> tuple[str, dict]:
    signature = {
        "version": SECTION_CACHE_VERSION,
        "section_index": section.index,
        "section_name": section.name,
        "script": section.text,
        "audio": _file_signature(voice["path"]),
        "srt": _file_signature(voice.get("srt_path")),
        "skip_whisper": skip_whisper,
        "whisper_model": config.whisper_model,
    }
    encoded = json.dumps(
        signature, ensure_ascii=False, sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), signature


def _cache_path(
    config: PipelineConfig,
    section: ScriptSection,
) -> Path:
    return config.cache_dir / "sections" / _slug(section) / "alignment.json"


def _load_cached_timings(
    path: Path,
    fingerprint: str,
) -> list[WordTiming] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("fingerprint") != fingerprint:
            return None
        return [
            WordTiming(
                str(item["word"]),
                float(item["start"]),
                float(item["end"]),
            )
            for item in payload["word_timings"]
        ]
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _save_cached_timings(
    path: Path,
    *,
    fingerprint: str,
    signature: dict,
    timings: list[WordTiming],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SECTION_CACHE_VERSION,
        "fingerprint": fingerprint,
        "signature": signature,
        "word_timings": [
            {
                "word": item.word,
                "start": round(item.start, 6),
                "end": round(item.end, 6),
            }
            for item in timings
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_cached_section_timings(
    config: PipelineConfig,
    sections: list[ScriptSection],
    voice_timeline: list[dict],
    skip_whisper: bool,
    force_sections: set[int] | None = None,
    force_refresh: bool = False,
) -> tuple[list[WordTiming], list[dict]]:
    force_sections = force_sections or set()
    local_by_index: dict[int, list[WordTiming]] = {}
    metadata: dict[int, dict] = {}
    misses = []

    for section, voice in zip(sections, voice_timeline):
        fingerprint, signature = _fingerprint(
            config, section, voice, skip_whisper
        )
        path = _cache_path(config, section)
        cached = (
            None
            if force_refresh or section.index in force_sections
            else _load_cached_timings(path, fingerprint)
        )
        metadata[section.index] = {
            "index": section.index,
            "name": section.name,
            "audio": str(voice["path"]),
            "srt": (
                str(voice["srt_path"])
                if voice.get("srt_path") is not None
                else None
            ),
            "duration": round(float(voice["duration"]), 6),
            "timeline_start": round(float(voice["start"]), 6),
            "timeline_end": round(float(voice["end"]), 6),
            "fingerprint": fingerprint,
            "cache_file": str(path),
            "timing_status": "cached" if cached is not None else "analyzed",
        }
        if cached is not None:
            local_by_index[section.index] = cached
            print(
                f"Section cache [{section.index}/{len(sections)}] "
                f"{section.name}: dùng lại Alignment."
            )
        else:
            misses.append((section, voice, path, fingerprint, signature))

    if misses:
        pending_sections = []
        pending_voices = []
        cursor = 0.0
        for section, voice, *_ in misses:
            duration = float(voice["duration"])
            pending_sections.append(section)
            pending_voices.append(
                {
                    **voice,
                    "start": cursor,
                    "end": cursor + duration,
                }
            )
            cursor += duration
        pending_cache = (
            config.cache_dir / "sections" / "pending_whisper_words.json"
        )
        pending_config = replace(
            config,
            whisper_cache_file=pending_cache,
        )
        pending_timings = create_word_timings(
            pending_config,
            pending_sections,
            pending_voices,
            skip_whisper,
        )
        word_cursor = 0
        for (
            section,
            voice,
            path,
            fingerprint,
            signature,
        ), pending_voice in zip(misses, pending_voices):
            word_count = len(script_tokens(section.text))
            section_timings = pending_timings[
                word_cursor:word_cursor + word_count
            ]
            offset = float(pending_voice["start"])
            local = [
                WordTiming(
                    item.word,
                    max(0.0, item.start - offset),
                    max(0.0, item.end - offset),
                )
                for item in section_timings
            ]
            word_cursor += word_count
            local_by_index[section.index] = local
            _save_cached_timings(
                path,
                fingerprint=fingerprint,
                signature=signature,
                timings=local,
            )
            print(
                f"Section cache [{section.index}/{len(sections)}] "
                f"{section.name}: đã cập nhật."
            )

    global_timings = []
    section_rows = []
    for section, voice in zip(sections, voice_timeline):
        offset = float(voice["start"])
        local = local_by_index[section.index]
        global_timings.extend(
            WordTiming(
                item.word,
                item.start + offset,
                item.end + offset,
            )
            for item in local
        )
        row = metadata[section.index]
        row["word_count"] = len(local)
        section_rows.append(row)
    return global_timings, section_rows


def _normalize_section_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _explicit_section_index(
    beat: Beat,
    sections: list[ScriptSection],
) -> int:
    if len(sections) == 1:
        return sections[0].index
    key = _normalize_section_key(beat.section)
    for section in sections:
        if key in {
            str(section.index),
            f"{section.index:02d}",
            _normalize_section_key(section.name),
        }:
            return section.index
    raise ValueError(
        f"Beat {beat.code} tham chiếu Section không tồn tại: "
        f"{beat.section!r}"
    )


def select_beats_for_sections(
    sections: list[ScriptSection],
    beats: list[Beat],
    selected_indexes: set[int],
) -> list[Beat]:
    """Select explicitly mapped Beats without validating unrelated Sections."""
    mapped = map_beats_for_preview(sections, beats)
    selected = [
        beat
        for section_index in sorted(selected_indexes)
        for beat in mapped.get(section_index, [])
    ]
    if not selected:
        labels = ", ".join(map(str, sorted(selected_indexes)))
        raise ValueError(
            f"Không thể phân bổ Beat cho Section {labels}. "
            "Hãy kiểm tra cột section trong script_beat.csv."
        )
    return selected


def map_beats_for_preview(
    sections: list[ScriptSection],
    beats: list[Beat],
) -> dict[int, list[Beat]]:
    """Map Beats for UI/preview without requiring every Section to be ready."""
    mapped = {section.index: [] for section in sections}
    if len(sections) == 1:
        mapped[sections[0].index] = list(beats)
        return mapped
    has_explicit_mapping = any(beat.section.strip() for beat in beats)
    if has_explicit_mapping:
        for beat in beats:
            if not beat.section.strip():
                continue
            mapped[_explicit_section_index(beat, sections)].append(beat)
        return mapped

    synthetic_timings = []
    section_ranges = []
    cursor = 0
    for section in sections:
        words = script_tokens(section.text)
        start = cursor
        synthetic_timings.extend(
            WordTiming(word, float(cursor + index), float(cursor + index + 1))
            for index, word in enumerate(words)
        )
        cursor += len(words)
        section_ranges.append((section.index, start, cursor))
    global_ranges = align_beats_to_script(synthetic_timings, beats)
    for beat, (beat_start, beat_end) in zip(beats, global_ranges):
        best_section = max(
            section_ranges,
            key=lambda item: max(
                0,
                min(beat_end, item[2]) - max(beat_start, item[1]),
            ),
        )
        mapped[best_section[0]].append(beat)
    return mapped


def assign_beats_to_sections(
    sections: list[ScriptSection],
    word_timings: list[WordTiming],
    beats: list[Beat],
) -> dict[int, list[Beat]]:
    if len(sections) == 1:
        return {sections[0].index: list(beats)}
    explicit = [bool(beat.section.strip()) for beat in beats]
    if any(explicit) and not all(explicit):
        raise ValueError(
            "Cột section trong script_beat.csv phải được điền cho toàn bộ Beat "
            "hoặc để trống toàn bộ."
        )
    assigned = {section.index: [] for section in sections}
    if all(explicit):
        for beat in beats:
            assigned[_explicit_section_index(beat, sections)].append(beat)
    else:
        global_ranges = align_beats_to_script(word_timings, beats)
        section_ranges = []
        cursor = 0
        for section in sections:
            count = len(script_tokens(section.text))
            section_ranges.append((section.index, cursor, cursor + count))
            cursor += count
        for beat, (beat_start, beat_end) in zip(beats, global_ranges):
            best_section = max(
                section_ranges,
                key=lambda item: max(
                    0,
                    min(beat_end, item[2]) - max(beat_start, item[1]),
                ),
            )
            assigned[best_section[0]].append(beat)
    missing = [
        section.name or str(section.index)
        for section in sections
        if not assigned[section.index]
    ]
    if missing:
        raise ValueError(
            "Các Section chưa có Beat: "
            + ", ".join(missing)
            + ". Hãy bổ sung cột section trong script_beat.csv."
        )
    return assigned


def build_section_segments(
    config: PipelineConfig,
    sections: list[ScriptSection],
    voice_timeline: list[dict],
    word_timings: list[WordTiming],
    beats: list[Beat],
    section_rows: list[dict],
) -> tuple[list[SpeechSegment], dict[int, list[Beat]], list[dict]]:
    assigned = assign_beats_to_sections(sections, word_timings, beats)
    segments = []
    beat_timings = []
    word_cursor = 0
    segment_index = 0
    section_row_map = {row["index"]: row for row in section_rows}
    for section, voice in zip(sections, voice_timeline):
        word_count = len(script_tokens(section.text))
        offset = float(voice["start"])
        local_timings = [
            WordTiming(
                item.word,
                item.start - offset,
                item.end - offset,
            )
            for item in word_timings[word_cursor:word_cursor + word_count]
        ]
        word_cursor += word_count
        section_beats = assigned[section.index]
        local_ranges = align_beats_to_script(
            local_timings, section_beats
        )
        for beat, (start_word, end_word) in zip(section_beats, local_ranges):
            start = float(local_timings[start_word].start + offset)
            end = float(
                local_timings[end_word - 1].end + offset
                if end_word > start_word
                else local_timings[start_word].start + offset
            )
            beat_timings.append(
                {
                    "beat": beat.code,
                    "section_index": section.index,
                    "section_name": section.name,
                    "timeline_start": round(start, 3),
                    "timeline_end": round(end, 3),
                    "duration": round(max(0.0, end - start), 3),
                    "word_start": start_word,
                    "word_end": end_word,
                }
            )
        local_segments = group_beats_by_duration(
            config,
            local_timings,
            section_beats,
            local_ranges,
            float(voice["duration"]),
        )
        for local_segment in local_segments:
            segments.append(
                SpeechSegment(
                    index=segment_index,
                    beats=local_segment.beats,
                    text=local_segment.text,
                    start=local_segment.start + offset,
                    end=local_segment.end + offset,
                    section_index=section.index,
                    section_name=section.name,
                )
            )
            segment_index += 1
        row = section_row_map[section.index]
        row["beats"] = [beat.code for beat in section_beats]
        row["beat_count"] = len(section_beats)
        row["cut_count"] = len(local_segments)
        row["status"] = "analyzed"
    return segments, assigned, beat_timings
