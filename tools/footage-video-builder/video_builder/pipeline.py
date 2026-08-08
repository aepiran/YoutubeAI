"""Pipeline orchestration; business logic lives in the stage modules."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from moviepy import concatenate_audioclips

from .config import PipelineConfig
from .duration_policy import extend_with_silent_outro
from .capcut_export import build_capcut_package, load_section_report
from .inputs import load_project_inputs, open_voice_timeline
from .low_memory_render import render_report_low_memory
from .optimization import select_global_timeline
from .output import (
    export_selected_scenes,
    load_render_plan,
    render_video,
    save_report,
)
from .quality_scoring import analyze_footage, build_score_matrix
from .script_overview import create_script_overview
from .section_processing import (
    build_section_segments,
    create_cached_section_timings,
    select_beats_for_sections,
)
from .source_coverage import analyze_source_coverage, print_source_coverage


def _stage_start(code: str) -> None:
    print(f"STAGE_START:{code}", flush=True)


def _stage_end(code: str) -> None:
    print(f"STAGE_END:{code}", flush=True)


def run_pipeline(
    config: PipelineConfig,
    *,
    skip_whisper: bool = False,
    analyze_only: bool = False,
    force_analysis: bool = False,
    render_only: bool = False,
    render_sections: set[int] | None = None,
    export_scenes_only: bool = False,
    scenes_output_dir: Path | None = None,
    export_capcut_package: bool = False,
    capcut_output_dir: Path | None = None,
    capcut_sections: set[int] | None = None,
    capcut_reference_video: bool = True,
    capcut_template_dir: Path | None = None,
    capcut_draft_name: str | None = None,
    capcut_drafts_root: Path | None = None,
    capcut_register_draft: bool = True,
    capcut_replace_draft: bool = False,
    capcut_hook_music: Path | None = None,
    capcut_hook_volume_db: float = -17.0,
    capcut_body_music: list[dict] | None = None,
    analyze_sections: set[int] | None = None,
) -> None:
    if export_capcut_package:
        build_capcut_package(
            config,
            capcut_output_dir or config.base_dir / "capcut_package",
            include_reference_video=capcut_reference_video,
            template_dir=capcut_template_dir,
            draft_name=capcut_draft_name,
            drafts_root=capcut_drafts_root,
            register_draft=capcut_register_draft,
            section_indexes=capcut_sections,
            replace_draft=capcut_replace_draft,
            hook_music=capcut_hook_music,
            hook_volume_db=capcut_hook_volume_db,
            body_music=capcut_body_music,
        )
        return
    if export_scenes_only:
        export_selected_scenes(
            config,
            scenes_output_dir or config.base_dir / "selected_scenes",
        )
        return
    _stage_start("INPUT")
    (
        script,
        script_sections,
        beats,
        voice_files,
        srt_files,
        video_files,
    ) = load_project_inputs(config)
    audio_clip, voice_source_clips, voice_timeline = open_voice_timeline(
        voice_files, srt_files
    )
    try:
        if analyze_sections:
            valid_indexes = {section.index for section in script_sections}
            invalid = sorted(analyze_sections - valid_indexes)
            if invalid:
                raise ValueError(
                    "Section không tồn tại: "
                    + ", ".join(map(str, invalid))
                )
        print(
            f"Đầu vào: 1 file Audio hoàn chỉnh, "
            f"{audio_clip.duration:.2f}s Audio, {len(beats)} Beat, "
            f"{len(video_files)} file Footage."
        )
        print(
            "Kịch bản hoàn chỉnh: toàn bộ nội dung được dựng trên một Timeline."
        )
        print(
            "Cấu hình thời lượng Cut: "
            f"{config.min_speech_seconds:.2f}s tối thiểu / "
            f"{config.target_speech_seconds:.2f}s mục tiêu / "
            f"{config.max_speech_seconds:.2f}s tối đa."
        )
        print("Timeline Voice:")
        for voice in voice_timeline:
            print(
                f"  {voice['name']}: {voice['start']:.2f}-"
                f"{voice['end']:.2f}s ({voice['duration']:.2f}s)"
            )
        _stage_end("INPUT")
        if force_analysis and not render_only:
            print("Force analysis: bo qua cache ket qua, phan tich lai tu dau.")
        if render_only:
            _stage_start("OUTPUT")
            render_plan_config = config
            temporary_report = None
            if render_sections:
                report = load_section_report(config, render_sections)
                temporary_report = (
                    config.cache_dir / "render_section_selection.json"
                )
                temporary_report.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                render_plan_config = replace(
                    config, report_file=temporary_report
                )
            else:
                report = json.loads(
                    config.report_file.read_text(encoding="utf-8-sig")
                )
            segments, _selected = load_render_plan(render_plan_config)
            render_audio = audio_clip
            combined_render_audio = None
            if render_sections:
                ordered_sections = sorted(render_sections)
                chosen_audio = [
                    voice_source_clips[index - 1]
                    for index in ordered_sections
                ]
                if len(chosen_audio) == 1:
                    render_audio = chosen_audio[0]
                else:
                    combined_render_audio = concatenate_audioclips(
                        chosen_audio
                    )
                    render_audio = combined_render_audio
                print(
                    "Chế độ Render Section: "
                    + ", ".join(map(str, ordered_sections))
                )
            print(
                f"Chế độ chỉ Render: đã nạp {len(segments)} Cut "
                f"từ {config.report_file}."
            )
            try:
                render_report_low_memory(
                    config, report, render_audio
                )
            finally:
                if combined_render_audio is not None:
                    combined_render_audio.close()
                if temporary_report is not None:
                    temporary_report.unlink(missing_ok=True)
            print(f"Video đã sẵn sàng: {config.output_file}")
            _stage_end("OUTPUT")
            return

        _stage_start("ALIGN")
        script_overview = create_script_overview(
            config,
            script,
            script_sections,
            beats,
            force_refresh=force_analysis,
        )
        analysis_sections = script_sections
        analysis_voices = voice_timeline
        analysis_beats = beats
        report_config = config
        analysis_scope = "project"
        if analyze_sections:
            analysis_sections = [
                section
                for section in script_sections
                if section.index in analyze_sections
            ]
            analysis_voices = [
                voice_timeline[index]
                for index, section in enumerate(script_sections)
                if section.index in analyze_sections
            ]
            analysis_beats = select_beats_for_sections(
                script_sections, beats, analyze_sections
            )
            preview_name = "_".join(
                f"{index:03d}" for index in sorted(analyze_sections)
            )
            preview_dir = config.cache_dir / "section_previews"
            report_config = replace(
                config,
                report_file=preview_dir / f"{preview_name}.json",
                report_csv_file=preview_dir / f"{preview_name}.csv",
            )
            analysis_scope = "section_preview"
            print(
                "Chế độ Preview Section: chỉ phân tích Section "
                + ", ".join(map(str, sorted(analyze_sections)))
                + "; report toàn dự án được giữ nguyên."
            )
        word_timings, section_rows = create_cached_section_timings(
            config,
            analysis_sections,
            analysis_voices,
            skip_whisper,
            force_sections=analyze_sections,
            force_refresh=force_analysis,
        )
        _stage_end("ALIGN")
        _stage_start("CUT")
        segments, _section_beats, beat_timings = build_section_segments(
            config,
            analysis_sections,
            analysis_voices,
            word_timings,
            analysis_beats,
            section_rows,
        )
        outro_seconds = 0.0
        if analysis_scope == "project":
            audio_duration = max(
                (float(item["end"]) for item in analysis_voices),
                default=0.0,
            )
            segments, outro_seconds = extend_with_silent_outro(
                config, segments, audio_duration
            )
            if outro_seconds > 0.0:
                print(
                    "DWG minimum duration: narration ngắn hơn "
                    f"{config.minimum_video_seconds / 60.0:g} phút; "
                    f"đã thêm {outro_seconds:.2f}s outro thiên nhiên."
                )
        alignment_report = {
            "schema_version": 1,
            "analysis_scope": analysis_scope,
            "audio_duration": round(
                max((float(item["end"]) for item in analysis_voices), default=0.0),
                3,
            ),
            "video_duration": round(
                max((segment.end for segment in segments), default=0.0),
                3,
            ),
            "beat_count": len(analysis_beats),
            "cut_count": len(segments),
            "beats": beat_timings,
            "cuts": [
                {
                    "beats": [beat.code for beat in segment.beats],
                    "timeline_start": round(segment.start, 3),
                    "timeline_end": round(segment.end, 3),
                    "duration": round(segment.duration, 3),
                    "section_index": segment.section_index,
                    "section_name": segment.section_name,
                }
                for segment in segments
            ],
        }
        alignment_path = report_config.cache_dir / "vfootage_alignment.json"
        alignment_path.parent.mkdir(parents=True, exist_ok=True)
        alignment_path.write_text(
            json.dumps(alignment_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            "Beat timing: đã lưu thời lượng từng Beat theo audio gốc "
            f"({alignment_path})."
        )
        print("Các Cut lời thoại trên Timeline:")
        for segment in segments:
            print(
                f"  {segment.beat_codes}: {segment.start:.2f}-"
                f"{segment.end:.2f}s ({segment.duration:.2f}s) "
                f"{segment.text}"
            )
        _stage_end("CUT")

        _stage_start("SHOT")
        candidates, rejected, model, processor, device = analyze_footage(
            config,
            video_files,
            force_refresh=force_analysis,
        )
        _stage_end("SHOT")
        source_coverage = analyze_source_coverage(segments, candidates)
        print_source_coverage(source_coverage)
        _stage_start("CLIP")
        score_matrix, score_components = build_score_matrix(
            config,
            segments,
            candidates,
            model,
            processor,
            device,
            script_overview,
        )
        _stage_end("CLIP")
        _stage_start("PLAN")
        selected, selected_scores, total_score = select_global_timeline(
            segments,
            candidates,
            score_matrix,
            score_components,
        )
        candidate_indexes = {
            id(candidate): index
            for index, candidate in enumerate(candidates)
        }
        selected_components = [
            {
                name: float(
                    matrix[segment_index, candidate_indexes[id(candidate)]]
                )
                for name, matrix in score_components.items()
            }
            for segment_index, candidate in enumerate(selected)
        ]
        _stage_end("PLAN")
        save_report(
            report_config,
            segments,
            selected,
            selected_scores,
            total_score,
            rejected,
            analysis_voices,
            word_timings,
            selected_components,
            sections=section_rows,
            script_overview=script_overview,
            analysis_scope=analysis_scope,
            source_coverage=source_coverage,
            beat_timings=beat_timings,
        )
        print("Timeline toàn cục đã chọn:")
        for segment, candidate, score in zip(
            segments, selected, selected_scores
        ):
            print(
                f"  {segment.beat_codes}: {candidate.path.name} "
                f"[{candidate.start:.2f}-{candidate.end:.2f}s], "
                f"score={score:.3f}"
            )
        if analyze_only:
            print("Chế độ chỉ phân tích: bỏ qua bước xuất Video.")
        else:
            _stage_start("LOOK")
            _stage_end("LOOK")
            _stage_start("AUDIO")
            print("Audio lời thoại: sẵn sàng")
            _stage_end("AUDIO")
            _stage_start("OUTPUT")
            render_video(config, segments, selected, audio_clip)
            print(f"Video đã sẵn sàng: {config.output_file}")
            _stage_end("OUTPUT")
    finally:
        if len(voice_source_clips) > 1:
            audio_clip.close()
        for voice_clip in voice_source_clips:
            voice_clip.close()
