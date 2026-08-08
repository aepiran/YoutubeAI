"""Minimum-duration policy for DWG videos."""

from __future__ import annotations

import math

from .config import PipelineConfig
from .models import SpeechSegment


def extend_with_silent_outro(
    config: PipelineConfig,
    segments: list[SpeechSegment],
    audio_duration: float,
) -> tuple[list[SpeechSegment], float]:
    """Append nature-only cuts when narration is shorter than the DWG minimum."""
    minimum = max(0.0, float(config.minimum_video_seconds))
    current_end = max(
        float(audio_duration),
        max((segment.end for segment in segments), default=0.0),
    )
    missing = max(0.0, minimum - current_end)
    if missing <= 0.01 or not segments:
        return segments, 0.0

    closing_beat = segments[-1].beats
    target = max(1.0, float(config.target_speech_seconds))
    maximum = max(target, float(config.max_speech_seconds))
    cut_count = max(1, math.ceil(missing / maximum))
    cut_duration = missing / cut_count
    if cut_duration > maximum + 1e-6:
        cut_count = math.ceil(missing / maximum)
        cut_duration = missing / cut_count

    extended = list(segments)
    cursor = current_end
    for _ in range(cut_count):
        end = min(minimum, cursor + cut_duration)
        extended.append(
            SpeechSegment(
                index=len(extended),
                beats=closing_beat,
                text=(
                    "Peaceful closing nature scene after the prayer; "
                    "no narration, no indoor scene, no dramatic action."
                ),
                start=cursor,
                end=end,
                section_index=0,
                section_name="DWG OUTRO",
            )
        )
        cursor = end
    return extended, missing
