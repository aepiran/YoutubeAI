from __future__ import annotations

import re
from pathlib import Path

from .models import CaptionCue


_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")


def _clean_caption_text(words: list[str]) -> str:
    text = " ".join(word.strip() for word in words if word.strip())
    return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()


def captions_from_word_timings(
    timings: list[dict],
    *,
    max_characters: int = 46,
    max_duration: float = 3.5,
    max_gap: float = 0.75,
) -> list[CaptionCue]:
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
                text=_clean_caption_text(words),
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
        should_split = bool(words) and (
            start - previous_end > max_gap
            or end - cue_start > max_duration
            or len(candidate) > max_characters
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


def captions_from_timeline(rows: list[dict]) -> list[CaptionCue]:
    cues = []
    for row in rows:
        text = str(row.get("narration", "")).strip()
        if not text:
            continue
        start = float(row.get("timeline_start", 0.0))
        end = float(row.get("timeline_end", start))
        cues.append(
            CaptionCue(
                index=len(cues) + 1,
                start=max(0.0, start),
                end=max(start + 0.08, end),
                text=text,
            )
        )
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
                text=" ".join(lines[2:]).strip(),
            )
        )
    if not cues:
        raise ValueError(f"Không đọc được Caption hợp lệ từ {path}")
    return cues
