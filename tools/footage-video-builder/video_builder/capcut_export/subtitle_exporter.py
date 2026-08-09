from __future__ import annotations

import re
from pathlib import Path

from .models import CaptionCue


_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")


def _clean_caption_text(words: list[str]) -> str:
    text = " ".join(word.strip() for word in words if word.strip())
    return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()


def wrap_caption_text(
    text: str,
    *,
    max_lines: int = 4,
    max_characters_per_line: int = 14,
) -> str:
    """Wrap at word boundaries without exceeding the character limit."""
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1")
    if max_characters_per_line < 1:
        raise ValueError("max_characters_per_line must be at least 1")
    words = text.split()
    if not words:
        return ""
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_characters_per_line:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        raise ValueError(
            f"Caption needs {len(lines)} lines but the configured layout only "
            f"supports {max_lines}"
        )
    return "\n".join(lines)


def _caption_chunks(
    text: str,
    max_lines: int,
    max_characters_per_line: int,
) -> list[str]:
    chunks: list[str] = []
    words: list[str] = []
    for word in text.split():
        candidate = _clean_caption_text([*words, word])
        try:
            wrap_caption_text(
                candidate,
                max_lines=max_lines,
                max_characters_per_line=max_characters_per_line,
            )
        except ValueError:
            if words:
                chunks.append(_clean_caption_text(words))
                words = [word]
            else:
                chunks.append(word)
        else:
            words.append(word)
    if words:
        chunks.append(_clean_caption_text(words))
    return chunks


def captions_from_word_timings(
    timings: list[dict],
    *,
    max_characters: int | None = None,
    max_duration: float = 3.5,
    max_gap: float = 0.75,
    max_lines: int = 4,
    max_characters_per_line: int = 14,
) -> list[CaptionCue]:
    if max_lines < 1 or max_characters_per_line < 1:
        raise ValueError("Caption line and character limits must be at least 1")
    cues: list[CaptionCue] = []
    words: list[str] = []
    cue_start = 0.0
    cue_end = 0.0
    previous_end = 0.0

    def flush() -> None:
        nonlocal words
        if not words:
            return
        cues.append(
            CaptionCue(
                index=len(cues) + 1,
                start=max(0.0, cue_start),
                end=max(cue_start + 0.08, cue_end),
                text=wrap_caption_text(
                    _clean_caption_text(words),
                    max_lines=max_lines,
                    max_characters_per_line=max_characters_per_line,
                ),
            )
        )
        words = []

    for item in timings:
        word = str(item.get("word", item.get("text", ""))).strip()
        if not word:
            continue
        start = float(item["start"])
        end = float(item["end"])
        candidate = _clean_caption_text([*words, word])
        try:
            wrap_caption_text(
                candidate,
                max_lines=max_lines,
                max_characters_per_line=max_characters_per_line,
            )
            exceeds_layout = False
        except ValueError:
            exceeds_layout = True
        should_split = bool(words) and (
            start - previous_end > max_gap
            or end - cue_start > max_duration
            or (max_characters is not None and len(candidate) > max_characters)
            or exceeds_layout
        )
        if should_split:
            flush()
        if not words:
            cue_start = start
        words.append(word)
        cue_end = end
        previous_end = end
        if _SENTENCE_END.search(word) and cue_end - cue_start >= 0.65:
            flush()
    flush()
    return cues


def captions_from_timeline(
    rows: list[dict],
    *,
    max_lines: int = 4,
    max_characters_per_line: int = 14,
) -> list[CaptionCue]:
    if max_lines < 1 or max_characters_per_line < 1:
        raise ValueError("Caption line and character limits must be at least 1")
    cues = []
    for row in rows:
        text = str(row.get("narration", "")).strip()
        if not text:
            continue
        start = float(row.get("timeline_start", 0.0))
        end = float(row.get("timeline_end", start))
        chunks = _caption_chunks(
            text,
            max_lines,
            max_characters_per_line,
        )
        total_words = sum(len(chunk.split()) for chunk in chunks)
        cursor = start
        for chunk_index, chunk in enumerate(chunks):
            chunk_words = len(chunk.split())
            chunk_end = (
                end
                if chunk_index == len(chunks) - 1
                else cursor + (end - start) * chunk_words / total_words
            )
            cues.append(
                CaptionCue(
                    index=len(cues) + 1,
                    start=max(0.0, cursor),
                    end=max(cursor + 0.08, chunk_end),
                    text=wrap_caption_text(
                        chunk,
                        max_lines=max_lines,
                        max_characters_per_line=max_characters_per_line,
                    ),
                )
            )
            cursor = chunk_end
    return cues


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},"
        f"{milliseconds:03d}"
    )


def write_srt(path: Path, cues: list[CaptionCue]) -> Path:
    if not cues:
        path.write_text("", encoding="utf-8")
        return path
    blocks = [
        (
            f"{index}\n"
            f"{_srt_timestamp(cue.start)} --> {_srt_timestamp(cue.end)}\n"
            f"{cue.text}"
        )
        for index, cue in enumerate(cues, start=1)
    ]
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def parse_srt(path: Path) -> list[CaptionCue]:
    timestamp = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )

    def seconds(parts: tuple[str, ...]) -> float:
        hours, minutes, whole_seconds, milliseconds = map(int, parts)
        return (
            hours * 3600
            + minutes * 60
            + whole_seconds
            + milliseconds / 1000
        )

    cues = []
    content = path.read_text(encoding="utf-8-sig")
    if not content.strip():
        return cues
    for block in re.split(r"\r?\n\s*\r?\n", content.strip()):
        lines = [line.strip() for line in block.splitlines()]
        if len(lines) < 3:
            continue
        match = timestamp.fullmatch(lines[1])
        if not match:
            continue
        cues.append(
            CaptionCue(
                index=len(cues) + 1,
                start=seconds(match.groups()[:4]),
                end=seconds(match.groups()[4:]),
                text="\n".join(lines[2:]).strip(),
            )
        )
    if not cues:
        raise ValueError(f"Không đọc được Caption hợp lệ từ {path}")
    return cues
