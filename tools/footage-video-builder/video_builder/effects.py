"""Stage 7: transitions, motion animation, crop, and color grade."""

from __future__ import annotations

import numpy as np
from moviepy import VideoFileClip, vfx

from .config import PipelineConfig
from .models import Candidate, SpeechSegment

try:
    import cv2
except ImportError:
    cv2 = None


_CINEMATIC_FRAME_CACHE = {}


def source_window(
    candidate: Candidate, requested_duration: float
) -> tuple[float, float]:
    center = (candidate.start + candidate.end) / 2
    start = center - requested_duration / 2
    start = min(
        max(0.0, start),
        max(0.0, candidate.source_duration - requested_duration),
    )
    return start, min(candidate.source_duration, start + requested_duration)


def visual_interval(
    config: PipelineConfig,
    segment: SpeechSegment,
    segment_index: int,
    segment_count: int,
    total_duration: float,
) -> tuple[float, float]:
    if not config.enable_cinematic_effects or config.transition_seconds <= 0:
        return segment.start, segment.end
    half_transition = config.transition_seconds / 2
    start = segment.start - (half_transition if segment_index > 0 else 0.0)
    end = segment.end + (
        half_transition if segment_index < segment_count - 1 else 0.0
    )
    return max(0.0, start), min(total_duration, end)


def cinematic_grade_frame(config: PipelineConfig, frame):
    height, width = frame.shape[:2]
    cache_key = (
        width,
        height,
        config.color_contrast,
        config.color_brightness_offset,
        config.vignette_strength,
    )
    cached = _CINEMATIC_FRAME_CACHE.get(cache_key)
    if cached is None:
        values = np.arange(256, dtype=np.float32)
        lut = np.uint8(
            np.clip(
                (values - 128.0) * config.color_contrast
                + 128.0
                + config.color_brightness_offset,
                0,
                255,
            )
        )
        y, x = np.ogrid[-1.0:1.0:height * 1j, -1.0:1.0:width * 1j]
        radius = np.sqrt(x * x + y * y)
        vignette = 1.0 - config.vignette_strength * np.clip(
            radius, 0.0, 1.0
        ) ** 1.7
        vignette_rgb = np.repeat(
            np.uint8(np.clip(vignette * 255.0, 0, 255))[:, :, None],
            3,
            axis=2,
        )
        color_matrix = np.array(
            [
                [1.025, 0.000, -0.008],
                [0.000, 0.995, 0.000],
                [-0.008, 0.005, 0.985],
            ],
            dtype=np.float32,
        )
        cached = (lut, vignette_rgb, color_matrix)
        _CINEMATIC_FRAME_CACHE[cache_key] = cached
    lut, vignette_rgb, color_matrix = cached
    if cv2 is not None:
        graded = cv2.LUT(frame, lut)
        graded = cv2.transform(graded, color_matrix)
        return cv2.multiply(graded, vignette_rgb, scale=1.0 / 255.0)
    graded = np.einsum(
        "ijk,lk->ijl",
        lut[frame].astype(np.float32),
        color_matrix,
        optimize=True,
    )
    graded *= vignette_rgb.astype(np.float32) / 255.0
    return np.uint8(np.clip(graded, 0, 255))


def make_video_clip(
    config: PipelineConfig, candidate: Candidate, duration: float
):
    source = VideoFileClip(str(candidate.path), audio=False)
    start, end = source_window(candidate, duration)
    if end - start + 1e-3 >= duration:
        clip = source.subclipped(start, start + duration)
    else:
        # Rewinding a short source creates a visible jump on every loop. Keep
        # the final frame instead; normally optimization filters these sources
        # out, so this is only a defensive fallback for a very small library.
        clip = source.subclipped(start, end).with_effects(
            [vfx.Freeze(t="end", total_duration=duration)]
        )
    target_width, target_height = config.resolution
    scale = max(target_width / clip.w, target_height / clip.h)
    clip = clip.resized(scale * config.fill_overscan)
    clip = clip.cropped(
        x_center=clip.w / 2,
        y_center=clip.h / 2,
        width=target_width,
        height=target_height,
    )
    if config.enable_cinematic_effects:
        clip = clip.image_transform(
            lambda frame: cinematic_grade_frame(config, frame)
        )
    return clip.with_duration(duration).without_audio(), source, start
