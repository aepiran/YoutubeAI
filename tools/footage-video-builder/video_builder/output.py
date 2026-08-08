"""Stage 9: write timeline reports and export the final video."""

from __future__ import annotations

import csv
import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

import imageio_ffmpeg
from moviepy import ColorClip, CompositeVideoClip, vfx
from proglog import ProgressBarLogger

from .config import PipelineConfig
from .audio_mix import load_configured_music_rows, mix_audio_with_music
from .effects import make_video_clip, source_window, visual_interval
from .models import Beat, Candidate, SpeechSegment, WordTiming
from .optimization import REUSE_COOLDOWN_CUTS, REUSE_COOLDOWN_SECONDS
from .subprocess_utils import hidden_subprocess_kwargs


class _OutputProgressLogger(ProgressBarLogger):
    """Emit stable machine-readable video encoding progress."""

    def __init__(self) -> None:
        super().__init__()
        self._last_percent = -1

    def bars_callback(
        self,
        bar,
        attr,
        value,
        old_value=None,
    ) -> None:
        if bar != "t" or attr != "index":
            return
        total = self.bars.get(bar, {}).get("total")
        if not total:
            return
        percent = max(0, min(100, round(100 * value / total)))
        if percent != self._last_percent:
            self._last_percent = percent
            print(f"OUTPUT_PROGRESS: {percent}", flush=True)


def candidate_to_report(candidate: Candidate) -> dict:
    data = asdict(candidate)
    data["path"] = str(candidate.path)
    data.pop("feature", None)
    data.pop("frame_features", None)
    return data


def _source_beat_code(path: Path) -> str:
    match = re.match(r"([A-Za-z]+\d+)", path.stem)
    return match.group(1).upper() if match else path.stem


def _interval_overlap_ratio(
    first_start: float,
    first_end: float,
    second_start: float,
    second_end: float,
) -> float:
    overlap = max(
        0.0,
        min(first_end, second_end) - max(first_start, second_start),
    )
    return overlap / max(
        min(first_end - first_start, second_end - second_start),
        0.001,
    )


def save_report(
    config: PipelineConfig,
    segments: list[SpeechSegment],
    selected: list[Candidate],
    scores: list[float],
    total_score: float,
    rejected: list[Candidate],
    voice_timeline: list[dict],
    word_timings: list[WordTiming] | None = None,
    selected_components: list[dict[str, float]] | None = None,
    *,
    sections: list[dict] | None = None,
    script_overview: dict | None = None,
    analysis_scope: str = "project",
    source_coverage: list[dict] | None = None,
    beat_timings: list[dict] | None = None,
) -> None:
    rows = []
    total_duration = segments[-1].end
    selected_components = selected_components or [
        {} for _ in selected
    ]
    coverage_by_beat = {
        str(item.get("beat", "")).upper(): item
        for item in (source_coverage or [])
    }
    for segment_index, (segment, candidate, score, components) in enumerate(
        zip(segments, selected, scores, selected_components)
    ):
        visual_start, visual_end = visual_interval(
            config, segment, segment_index, len(segments), total_duration
        )
        source_start, source_end = source_window(
            candidate, visual_end - visual_start
        )
        is_cross_beat = components.get("cross_beat_fallback", 0) >= 0.5
        is_forced_low_semantic = (
            components.get("forced_low_semantic", 0) >= 0.5
        )
        source_code = _source_beat_code(candidate.path)
        warnings = []
        previous_reuse = None
        cooldown_met = False
        for previous_index in range(len(rows) - 1, -1, -1):
            previous = rows[previous_index]
            if Path(previous["footage"]) != candidate.path:
                continue
            overlap_ratio = _interval_overlap_ratio(
                source_start,
                source_end,
                float(previous["source_start"]),
                float(previous["source_end"]),
            )
            if overlap_ratio >= 0.20:
                previous_reuse = (
                    previous_index,
                    previous,
                    overlap_ratio,
                )
                break
        if is_cross_beat:
            warnings.append(
                f"Mượn footage {source_code} cho {segment.beat_codes}."
            )
            shortages = []
            for beat in segment.beats:
                coverage = coverage_by_beat.get(beat.code.upper(), {})
                missing = max(
                    0.0,
                    float(coverage.get("required_seconds", 0))
                    - float(coverage.get("available_unique_seconds", 0)),
                )
                if missing > 0.05:
                    shortages.append(f"{beat.code} thiếu {missing:.2f}s")
            if shortages:
                warnings.append(
                    "Nguồn đúng Beat không đủ: "
                    + ", ".join(shortages)
                    + "."
                )
        if is_forced_low_semantic:
            warnings.append(
                "Không có fallback đạt ngưỡng semantic; "
                "đã dùng phương án tốt nhất hiện có."
            )
        if previous_reuse is not None:
            previous_index, previous, overlap_ratio = previous_reuse
            cut_gap = segment_index - previous_index
            time_gap = max(
                0.0,
                segment.start - float(previous["timeline_end"]),
            )
            cooldown_met = (
                cut_gap >= REUSE_COOLDOWN_CUTS
                and time_gap >= REUSE_COOLDOWN_SECONDS
            )
            if cooldown_met:
                warnings.append(
                    f"Tái sử dụng vùng nguồn {source_code} "
                    f"(overlap {overlap_ratio:.0%}) sau "
                    f"{cut_gap} Cut/{time_gap:.1f}s."
                )
            else:
                warnings.append(
                    f"Buộc tái sử dụng vùng nguồn {source_code} "
                    f"trước cooldown "
                    f"({cut_gap} Cut/{time_gap:.1f}s, "
                    f"overlap {overlap_ratio:.0%})."
                )
        if visual_end - visual_start > candidate.duration + 0.05:
            warnings.append(
                "Thời lượng cần dài hơn Candidate đã phân tích; "
                "cửa sổ nguồn đã được mở rộng khi render."
            )
        if is_forced_low_semantic:
            allocation_status = "forced_low_semantic"
        elif previous_reuse is not None:
            allocation_status = (
                "reused_after_cooldown"
                if cooldown_met
                else "forced_early_reuse"
            )
        elif is_cross_beat:
            allocation_status = "borrowed_cross_beat"
        else:
            allocation_status = "matching_unused_region"
        segment_voices = [
            voice["name"]
            for voice in voice_timeline
            if voice["start"] < segment.end and voice["end"] > segment.start
        ]
        rows.append(
            {
                "beats": [beat.code for beat in segment.beats],
                "voices": segment_voices,
                "narration": segment.text,
                "timeline_start": round(segment.start, 3),
                "timeline_end": round(segment.end, 3),
                "duration": round(segment.duration, 3),
                "section_index": segment.section_index,
                "section_name": segment.section_name,
                "visual_start": round(visual_start, 3),
                "visual_end": round(visual_end, 3),
                "footage": str(candidate.path),
                "candidate_id": candidate.candidate_id,
                "scene_index": candidate.scene_index,
                "candidate_start": round(candidate.start, 6),
                "candidate_end": round(candidate.end, 6),
                "source_duration": round(candidate.source_duration, 6),
                "source_start": round(source_start, 3),
                "source_end": round(source_end, 3),
                "relevance_score": round(score, 6),
                "semantic_scores": {
                    key: round(float(value), 6)
                    for key, value in components.items()
                },
                "allocation_status": allocation_status,
                "selection_warnings": warnings,
                "selection_reason": (
                    "cross_beat_fallback"
                    if is_cross_beat
                    else "matching_beat"
                    if components.get("beat_identity_score", 0) >= 0.5
                    else "semantic_match"
                ),
                "quality": {
                    "brightness": round(candidate.brightness, 6),
                    "black_fraction": round(candidate.black_fraction, 6),
                    "edge_energy": round(candidate.edge_energy, 6),
                    "motion": round(candidate.motion, 6),
                    "shake": round(candidate.shake, 6),
                    "quality_score": round(candidate.quality_score, 6),
                },
            }
        )
    report = {
        "schema_version": 5,
        "analysis_scope": analysis_scope,
        "inputs": {
            "audio": [str(item["path"]) for item in voice_timeline],
            "voice_timeline": [
                {
                    "name": item["name"],
                    "start": round(item["start"], 3),
                    "end": round(item["end"], 3),
                    "duration": round(item["duration"], 3),
                    "srt": (
                        str(item["srt_path"])
                        if item.get("srt_path") is not None
                        else None
                    ),
                }
                for item in voice_timeline
            ],
            "script": str(config.script_file),
            "beats": str(config.beats_file),
            "videos": str(config.videos_dir),
            "output": str(config.output_file),
            "resolution": list(config.resolution),
            "vision_model": config.clip_model,
        },
        "word_timings": [
            {
                "word": item.word,
                "start": round(item.start, 6),
                "end": round(item.end, 6),
            }
            for item in (word_timings or [])
        ],
        "sections": sections or [],
        "beat_timings": beat_timings or [],
        "script_overview": script_overview or {},
        "source_coverage": source_coverage or [],
        "total_optimization_score": round(total_score, 6),
        "timeline": rows,
        "rejected_candidates": [
            candidate_to_report(candidate) for candidate in rejected
        ],
    }
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    config.report_file.parent.mkdir(parents=True, exist_ok=True)
    config.report_csv_file.parent.mkdir(parents=True, exist_ok=True)
    config.report_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Đã lưu Report phân tích: {config.report_file}")

    csv_columns = [
        "section_index", "section_name", "beats", "voices", "narration",
        "timeline_start", "timeline_end",
        "duration", "visual_start", "visual_end", "footage", "footage_path",
        "source_start", "source_end", "relevance_score", "quality_score",
        "brightness", "black_fraction", "edge_energy", "motion", "shake",
        "overview_score", "desired_visual_score", "main_idea_score", "keyword_score",
        "narration_score", "avoid_score", "beat_identity_score",
        "semantic_fit_score", "cross_beat_fallback", "fallback_eligible",
        "forced_low_semantic", "allocation_status", "selection_warnings",
        "selection_reason",
    ]
    with config.report_csv_file.open(
        "w", encoding="utf-8-sig", newline=""
    ) as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=csv_columns)
        writer.writeheader()
        for row in rows:
            footage_path = Path(row["footage"])
            writer.writerow(
                {
                    "section_index": row["section_index"],
                    "section_name": row["section_name"],
                    "beats": "+".join(row["beats"]),
                    "voices": "+".join(row["voices"]),
                    "narration": row["narration"],
                    "timeline_start": row["timeline_start"],
                    "timeline_end": row["timeline_end"],
                    "duration": row["duration"],
                    "visual_start": row["visual_start"],
                    "visual_end": row["visual_end"],
                    "footage": footage_path.name,
                    "footage_path": str(footage_path),
                    "source_start": row["source_start"],
                    "source_end": row["source_end"],
                    "relevance_score": row["relevance_score"],
                    "quality_score": row["quality"]["quality_score"],
                    "brightness": row["quality"]["brightness"],
                    "black_fraction": row["quality"]["black_fraction"],
                    "edge_energy": row["quality"]["edge_energy"],
                    "motion": row["quality"]["motion"],
                    "shake": row["quality"]["shake"],
                    "desired_visual_score": row["semantic_scores"].get(
                        "desired_visual_score", 0
                    ),
                    "overview_score": row["semantic_scores"].get(
                        "overview_score", 0
                    ),
                    "main_idea_score": row["semantic_scores"].get(
                        "main_idea_score", 0
                    ),
                    "keyword_score": row["semantic_scores"].get(
                        "keyword_score", 0
                    ),
                    "narration_score": row["semantic_scores"].get(
                        "narration_score", 0
                    ),
                    "avoid_score": row["semantic_scores"].get(
                        "avoid_score", 0
                    ),
                    "beat_identity_score": row["semantic_scores"].get(
                        "beat_identity_score", 0
                    ),
                    "semantic_fit_score": row["semantic_scores"].get(
                        "semantic_fit_score", 0
                    ),
                    "cross_beat_fallback": row["semantic_scores"].get(
                        "cross_beat_fallback", 0
                    ),
                    "fallback_eligible": row["semantic_scores"].get(
                        "fallback_eligible", 0
                    ),
                    "forced_low_semantic": row["semantic_scores"].get(
                        "forced_low_semantic", 0
                    ),
                    "allocation_status": row["allocation_status"],
                    "selection_warnings": " | ".join(
                        row["selection_warnings"]
                    ),
                    "selection_reason": row["selection_reason"],
                }
            )
    print(f"Đã lưu Timeline CSV: {config.report_csv_file}")


def export_selected_scenes(
    config: PipelineConfig,
    output_dir: Path,
) -> Path:
    if not config.report_file.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy Report phân tích: {config.report_file}. "
            "Hãy chạy Phân tích trước khi xuất Scene."
        )
    report = json.loads(config.report_file.read_text(encoding="utf-8-sig"))
    rows = report.get("timeline")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Report phân tích không hợp lệ: {config.report_file}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for index, row in enumerate(rows, start=1):
        source = Path(str(row["footage"]))
        if not source.is_file():
            raise FileNotFoundError(
                f"Footage đã chọn không còn tồn tại: {source}"
            )
        beat_value = row.get("beats", [])
        beat_codes = (
            [str(code) for code in beat_value]
            if isinstance(beat_value, list)
            else str(beat_value).split("+")
        )
        beat_label = "+".join(beat_codes) or f"CUT{index:03d}"
        safe_source = re.sub(r"[^A-Za-z0-9_-]+", "-", source.stem).strip("-")
        filename = f"{index:03d}_{beat_label}_{safe_source}.mp4"
        destination = output_dir / filename
        source_start = float(row["source_start"])
        source_end = float(row["source_end"])
        duration = source_end - source_start
        if duration <= 0:
            raise ValueError(
                f"Dòng Timeline {index} có khoảng nguồn không hợp lệ"
            )
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-ss", f"{source_start:.6f}",
            "-i", str(source),
            "-t", f"{duration:.6f}",
            "-map", "0:v:0",
            "-an",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(destination),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            **hidden_subprocess_kwargs(),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Không thể xuất Scene {index}: "
                f"{completed.stderr.strip() or 'FFmpeg thất bại'}"
            )
        quality = row.get("quality", {})
        manifest_rows.append(
            {
                "order": index,
                "beats": beat_label,
                "scene_file": filename,
                "source_file": source.name,
                "source_path": str(source),
                "scene_index": row.get("scene_index", 0),
                "timeline_start": row.get("timeline_start", 0),
                "timeline_end": row.get("timeline_end", 0),
                "timeline_duration": row.get("duration", duration),
                "source_start": source_start,
                "source_end": source_end,
                "export_duration": round(duration, 6),
                "relevance_score": row.get("relevance_score", 0),
                "quality_score": quality.get("quality_score", 0),
            }
        )
        print(
            f"Xuất Scene [{index}/{len(rows)}]: "
            f"{beat_label} -> {filename}"
        )

    manifest_path = output_dir / "selected_scenes.csv"
    with manifest_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(manifest_rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"Các Scene đã chọn đã sẵn sàng: {output_dir}")
    print(f"Scene manifest: {manifest_path}")
    return output_dir


def load_render_plan(
    config: PipelineConfig,
) -> tuple[list[SpeechSegment], list[Candidate]]:
    if not config.report_file.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy Report phân tích: {config.report_file}. "
            "Hãy chạy Phân tích trước khi Render."
        )
    report = json.loads(config.report_file.read_text(encoding="utf-8-sig"))
    rows = report.get("timeline")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Report phân tích không hợp lệ: {config.report_file}")
    segments = []
    selected = []
    for index, row in enumerate(rows):
        beats = []
        for code in row.get("beats", []):
            match = re.search(r"(\d+)", str(code))
            beats.append(
                Beat(
                    number=int(match.group(1)) if match else index + 1,
                    code=str(code),
                    main_idea="",
                    keywords="",
                    desired_visual="",
                    avoid="",
                )
            )
        if not beats:
            raise ValueError(f"Dòng Timeline {index + 1} không có Beat")
        footage_path = Path(row["footage"])
        if not footage_path.is_file():
            raise FileNotFoundError(
                f"Footage đã chọn không còn tồn tại: {footage_path}"
            )
        segment = SpeechSegment(
            index=index,
            beats=tuple(beats),
            text=str(row["narration"]),
            start=float(row["timeline_start"]),
            end=float(row["timeline_end"]),
            section_index=int(row.get("section_index", 0)),
            section_name=str(row.get("section_name", "")),
        )
        quality = row.get("quality", {})
        candidate = Candidate(
            candidate_id=int(row.get("candidate_id", index)),
            path=footage_path,
            scene_index=int(row.get("scene_index", 0)),
            start=float(row.get("candidate_start", row["source_start"])),
            end=float(row.get("candidate_end", row["source_end"])),
            source_duration=float(
                row.get("source_duration", row["source_end"])
            ),
            brightness=float(quality.get("brightness", 0.0)),
            black_fraction=float(quality.get("black_fraction", 0.0)),
            edge_energy=float(quality.get("edge_energy", 0.0)),
            motion=float(quality.get("motion", 0.0)),
            shake=float(quality.get("shake", 0.0)),
            quality_score=float(quality.get("quality_score", 0.0)),
        )
        segments.append(segment)
        selected.append(candidate)
    return segments, selected


def select_render_sections(
    segments: list[SpeechSegment],
    selected: list[Candidate],
    voice_timeline: list[dict],
    section_indexes: set[int],
) -> tuple[list[SpeechSegment], list[Candidate], list[int]]:
    """Filter and rebase selected Sections into one continuous timeline."""
    available = {
        segment.section_index
        for segment in segments
        if segment.section_index > 0
    }
    invalid = sorted(section_indexes - available)
    if invalid:
        raise ValueError(
            "Section chưa có trong Report phân tích: "
            + ", ".join(map(str, invalid))
        )
    ordered = sorted(section_indexes)
    rebuilt_segments = []
    rebuilt_candidates = []
    cursor = 0.0
    for section_index in ordered:
        voice = voice_timeline[section_index - 1]
        source_start = float(voice["start"])
        duration = float(voice["duration"])
        for segment, candidate in zip(segments, selected):
            if segment.section_index != section_index:
                continue
            rebuilt_segments.append(
                SpeechSegment(
                    index=len(rebuilt_segments),
                    beats=segment.beats,
                    text=segment.text,
                    start=segment.start - source_start + cursor,
                    end=segment.end - source_start + cursor,
                    section_index=segment.section_index,
                    section_name=segment.section_name,
                )
            )
            rebuilt_candidates.append(candidate)
        cursor += duration
    return rebuilt_segments, rebuilt_candidates, ordered


def render_video(
    config: PipelineConfig,
    segments: list[SpeechSegment],
    selected: list[Candidate],
    audio_clip,
) -> None:
    footage_clips = []
    source_clips = []
    overlay_clips = []
    music_clips = []
    render_audio = audio_clip
    try:
        total_duration = max(
            float(audio_clip.duration),
            max((segment.end for segment in segments), default=0.0),
        )
        music_rows = load_configured_music_rows(config, total_duration)
        if music_rows or total_duration > float(audio_clip.duration) + 0.001:
            render_audio, music_clips = mix_audio_with_music(
                audio_clip, music_rows, duration=total_duration
            )
            print(
                f"Nhạc nền DWG: {len(music_rows)} cue từ "
                f"{config.music_cue_sheet.name}."
            )
        for segment_index, (segment, candidate) in enumerate(
            zip(segments, selected)
        ):
            visual_start, visual_end = visual_interval(
                config,
                segment,
                segment_index,
                len(segments),
                total_duration,
            )
            visual_duration = visual_end - visual_start
            clip, source, source_start = make_video_clip(
                config, candidate, visual_duration
            )
            if (
                config.enable_cinematic_effects
                and segment_index > 0
                and config.transition_seconds > 0
            ):
                clip = clip.with_effects(
                    [
                        vfx.CrossFadeIn(
                            min(config.transition_seconds, visual_duration / 2)
                        )
                    ]
                )
            clip = clip.with_start(visual_start).with_position(
                ("center", "center")
            )
            footage_clips.append(clip)
            source_clips.append(source)
            print(
                f"  {segment.beat_codes} {segment.start:.2f}-{segment.end:.2f}s "
                f"<- {candidate.path.name} @ {source_start:.2f}s "
                f"(visual {visual_start:.2f}-{visual_end:.2f}s)"
            )
        background = ColorClip(
            size=config.resolution,
            color=(0, 0, 0),
            duration=total_duration,
        )
        overlay_clips.append(background)
        video_track = CompositeVideoClip(
            [background, *footage_clips], size=config.resolution
        ).with_duration(total_duration)
        print("Audio lời thoại: sẵn sàng (đã tắt SFX).")
        final_video = video_track.with_audio(render_audio)
        try:
            print(f"Đang xuất {config.output_file.name}...")
            final_video.write_videofile(
                str(config.output_file),
                fps=config.output_fps,
                codec="libx264",
                audio_codec="aac",
                bitrate="8000k",
                preset=config.encoder_preset,
                threads=config.encoder_threads,
                logger=_OutputProgressLogger(),
            )
            print("OUTPUT_PROGRESS: 100", flush=True)
        finally:
            final_video.close()
            video_track.close()
    finally:
        for clip in footage_clips:
            clip.close()
        for clip in overlay_clips:
            clip.close()
        for clip in source_clips:
            clip.close()
        if render_audio is not audio_clip:
            render_audio.close()
        for clip in music_clips:
            clip.close()
