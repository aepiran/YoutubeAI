"""Stage 3: split aligned narration into word-safe 3–5 second visual cuts."""

from __future__ import annotations

import math
import re

import numpy as np

from .config import PipelineConfig
from .models import Beat, SpeechSegment, WordTiming


def cut_duration_cost(
    duration: float,
    minimum: float,
    target: float,
    maximum: float,
) -> float:
    """Prefer the min-to-target range and treat max as a safety ceiling."""
    if duration <= target:
        span = max(target - minimum, 0.5)
        return 0.65 * ((target - duration) / span) ** 2
    span = max(maximum - target, 0.5)
    return 1.60 * ((duration - target) / span) ** 2


def group_beats_by_duration(
    config: PipelineConfig,
    word_timings: list[WordTiming],
    beats: list[Beat],
    beat_word_ranges: list[tuple[int, int]],
    total_duration: float,
) -> list[SpeechSegment]:
    word_count = len(word_timings)
    boundary_times = np.zeros(word_count + 1, dtype=float)
    boundary_times[0] = 0.0
    for index in range(1, word_count):
        boundary_times[index] = word_timings[index].start
    boundary_times[word_count] = total_duration
    semantic_boundaries = {word_end for _, word_end in beat_word_ranges[:-1]}

    def solve(min_seconds: float, max_seconds: float):
        costs = np.full(word_count + 1, np.inf)
        previous = np.full(word_count + 1, -1, dtype=int)
        costs[0] = 0.0
        for end_word in range(1, word_count + 1):
            end_time = boundary_times[end_word]
            first_start = int(
                np.searchsorted(
                    boundary_times,
                    end_time - max_seconds,
                    side="left",
                )
            )
            last_start = int(
                np.searchsorted(
                    boundary_times,
                    end_time - min_seconds,
                    side="right",
                )
            )
            for start_word in range(
                first_start,
                min(end_word, last_start),
            ):
                if not math.isfinite(costs[start_word]):
                    continue
                duration = end_time - boundary_times[start_word]
                if duration < min_seconds or duration > max_seconds:
                    continue
                token = word_timings[end_word - 1].word
                sentence_end = bool(re.search(r"[.!?][\"']?$", token))
                short_pause = bool(re.search(r"[,;:][\"']?$", token))
                punctuation_bonus = (
                    0.60 if sentence_end else (0.25 if short_pause else 0.0)
                )
                semantic_bonus = 0.40 if end_word in semantic_boundaries else 0.0
                split_penalty = (
                    0.28
                    if end_word != word_count and end_word not in semantic_boundaries
                    else 0.0
                )
                cost = (
                    costs[start_word]
                    + cut_duration_cost(
                        duration,
                        min_seconds,
                        config.target_speech_seconds,
                        max_seconds,
                    )
                    - punctuation_bonus
                    - semantic_bonus
                    + split_penalty
                )
                if cost < costs[end_word]:
                    costs[end_word] = cost
                    previous[end_word] = start_word
        if not math.isfinite(costs[-1]):
            return None
        groups = []
        cursor = word_count
        while cursor > 0:
            start = int(previous[cursor])
            groups.append((start, cursor))
            cursor = start
        return list(reversed(groups))

    groups = solve(config.min_speech_seconds, config.max_speech_seconds)
    if groups is None:
        largest_boundary_gap = float(np.max(np.diff(boundary_times)))
        relaxed_min = min(config.min_speech_seconds, 1.5)
        relaxed_max = max(
            config.max_speech_seconds,
            4.5,
            largest_boundary_gap + 0.25,
        )
        print(
            "Cảnh báo: cấu hình thời lượng Cut không khả thi; "
            f"cho phép khoảng {relaxed_min:.2f}-{relaxed_max:.2f}s "
            "để xử lý từ hoặc khoảng nghỉ dài."
        )
        groups = solve(relaxed_min, relaxed_max)
    if groups is None:
        raise RuntimeError(
            "Không thể nhóm Semantic Beat thành các Cut lời thoại phù hợp"
        )

    segments = []
    for index, (start_word, end_word) in enumerate(groups):
        related_beats = tuple(
            beat
            for beat, (beat_start, beat_end) in zip(beats, beat_word_ranges)
            if beat_start < end_word and beat_end > start_word
        )
        if not related_beats:
            raise RuntimeError(
                f"Không có Visual Beat trùng với các từ "
                f"{start_word}:{end_word}"
            )
        segments.append(
            SpeechSegment(
                index=index,
                beats=related_beats,
                text=" ".join(
                    item.word for item in word_timings[start_word:end_word]
                ),
                start=float(boundary_times[start_word]),
                end=float(boundary_times[end_word]),
            )
        )
    # A very long pause or unsplittable timing gap can force the word-safe
    # solver above its maximum. Keep the narration untouched, but introduce
    # extra visual boundaries so no rendered shot exceeds the configured cap.
    visual_segments = []
    for segment in segments:
        part_count = max(
            1,
            int(math.ceil(segment.duration / config.max_speech_seconds)),
        )
        part_duration = segment.duration / part_count
        for part_index in range(part_count):
            start = segment.start + part_index * part_duration
            end = (
                segment.end
                if part_index == part_count - 1
                else segment.start + (part_index + 1) * part_duration
            )
            visual_segments.append(
                SpeechSegment(
                    index=len(visual_segments),
                    beats=segment.beats,
                    text=segment.text,
                    start=start,
                    end=end,
                )
            )
    return visual_segments
