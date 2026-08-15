from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, replace
from pathlib import Path


WORKDIR = Path(__file__).resolve().parent.parent
VISION_MODELS = {
    "CLIP ViT-B/32": "openai/clip-vit-base-patch32",
    "SigLIP 2 Base": "google/siglip2-base-patch16-224",
}


@dataclass(frozen=True)
class PipelineConfig:
    """All paths and tuning values needed by the pipeline."""

    workdir: Path
    base_dir: Path
    voices_dir: Path
    script_file: Path
    beats_file: Path
    videos_dir: Path
    output_file: Path
    cache_dir: Path
    whisper_cache_file: Path
    report_file: Path
    report_csv_file: Path
    whisper_model_dir: Path
    clip_cache_dir: Path
    selected_voice_files: tuple[Path, ...] | None = None
    music_dir: Path | None = None
    music_cue_sheet: Path | None = None
    enable_background_music: bool = True
    minimum_video_seconds: float = 1500.0

    min_speech_seconds: float = 3.0
    target_speech_seconds: float = 4.0
    max_speech_seconds: float = 5.0
    scene_scan_fps: float = 3.0
    scene_min_seconds: float = 1.0
    scene_adaptive_threshold: float = 3.0
    scene_min_content_value: float = 15.0
    scene_histogram_threshold: float = 0.34
    scene_pixel_threshold: float = 0.16
    candidate_min_seconds: float = 3.0
    candidate_max_seconds: float = 5.36
    candidate_target_seconds: float = 4.36
    candidate_step_seconds: float = 4.5
    clip_frame_fps: float = 5.0
    clip_batch_size: int = 16
    min_brightness: float = 0.055
    max_brightness: float = 0.94
    max_black_fraction: float = 0.78
    min_edge_energy: float = 40.0
    min_motion: float = 0.001
    max_shake: float = 0.035
    whisper_model: str = "base.en"
    clip_model: str = "openai/clip-vit-base-patch32"
    auto_download_clip: bool = True
    resolution: tuple[int, int] = (1920, 1080)
    output_fps: int = 30
    encoder_preset: str = "veryfast"
    encoder_threads: int = 8
    analysis_workers: int = min(4, max(1, os.cpu_count() or 1))
    enable_cinematic_effects: bool = True
    transition_seconds: float = 0.36
    color_contrast: float = 1.06
    color_brightness_offset: float = -3.0
    vignette_strength: float = 0.0
    fill_overscan: float = 1.005
    score_overview_weight: float = 0.12
    score_desired_visual_weight: float = 0.30
    score_main_idea_weight: float = 0.18
    score_keywords_weight: float = 0.13
    score_narration_weight: float = 0.09
    score_quality_weight: float = 0.09
    score_beat_identity_weight: float = 0.09
    score_avoid_penalty: float = 0.25
    avoid_reject_threshold: float = 0.30
    avoid_reject_margin: float = 0.02
    cross_beat_fallback_penalty: float = 0.18
    fallback_semantic_min: float = 0.22
    fallback_semantic_margin: float = 0.055
    forced_fallback_penalty: float = 0.28


def default_config(workdir: Path = WORKDIR) -> PipelineConfig:
    base_dir = workdir / "vfootage"
    cache_dir = workdir / ".cache"
    return PipelineConfig(
        workdir=workdir,
        base_dir=base_dir,
        voices_dir=base_dir / "voice",
        script_file=base_dir / "script.txt",
        beats_file=base_dir / "script_beat.csv",
        videos_dir=base_dir / "footage",
        output_file=workdir / "video_vfootage.mp4",
        cache_dir=cache_dir,
        whisper_cache_file=cache_dir / "whisper_words_vfootage.json",
        report_file=cache_dir / "vfootage_timeline.json",
        report_csv_file=cache_dir / "vfootage_timeline.csv",
        whisper_model_dir=cache_dir / "whisper",
        clip_cache_dir=cache_dir / "huggingface" / "hub",
        music_dir=_discover_dwg_music_dir(base_dir, workdir),
        music_cue_sheet=_discover_dwg_cue_sheet(base_dir, workdir),
    )


def _discover_dwg_music_dir(base_dir: Path, workdir: Path) -> Path | None:
    candidates: list[Path] = []
    for root in (base_dir, *base_dir.parents, workdir, *workdir.parents):
        candidate = root / "BASE" / "audio" / "music"
        if candidate not in candidates:
            candidates.append(candidate)
    return next((path.resolve() for path in candidates if path.is_dir()), None)


def _discover_dwg_cue_sheet(base_dir: Path, workdir: Path) -> Path | None:
    music_dir = _discover_dwg_music_dir(base_dir, workdir)
    if music_dir is None:
        return None
    cue_sheet = music_dir / "DWG_25min_music_cue_sheet.csv"
    return cue_sheet.resolve() if cue_sheet.is_file() else None


def _preferred_project_dir(base_dir: Path, *names: str) -> Path:
    return next(
        (base_dir / name for name in names if (base_dir / name).is_dir()),
        base_dir / names[0],
    )


def build_parser(config: PipelineConfig | None = None) -> argparse.ArgumentParser:
    config = config or default_config()
    parser = argparse.ArgumentParser(
        description="Dựng Timeline theo lời thoại từ Beat CSV và kho Footage."
    )
    parser.add_argument(
        "--analyze-only", action="store_true",
        help="Phân tích và lưu Report lựa chọn, không xuất Video.",
    )
    parser.add_argument(
        "--force-analysis",
        action="store_true",
        help="Bo qua cache ket qua va phan tich lai tu dau.",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Render từ Report đã lưu mà không chạy lại phân tích.",
    )
    parser.add_argument(
        "--render-section",
        action="append",
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--export-scenes-only",
        action="store_true",
        help="Xuất các Scene đã chọn mà không chạy lại phân tích.",
    )
    parser.add_argument(
        "--scenes-output-dir",
        help="Thư mục chứa các Scene đã chọn và CSV manifest.",
    )
    parser.add_argument(
        "--export-capcut-package",
        action="store_true",
        help=(
            "Xuất từng Scene, narration, SRT, manifest và MP4 tham chiếu "
            "để dựng tiếp trong CapCut."
        ),
    )
    parser.add_argument(
        "--capcut-output-dir",
        help="Thư mục chứa gói dựng CapCut.",
    )
    parser.add_argument(
        "--capcut-section",
        action="append",
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-capcut-reference-video",
        action="store_true",
        help="Không render reference.mp4 khi xuất gói CapCut.",
    )
    parser.add_argument(
        "--capcut-template-dir",
        help=(
            "Template Draft CapCut. Khi có giá trị này, ứng dụng clone "
            "template và tạo Draft mới từ gói đã xuất."
        ),
    )
    parser.add_argument(
        "--capcut-draft-name",
        help="Tên Draft mới hiển thị trong CapCut.",
    )
    parser.add_argument(
        "--capcut-drafts-root",
        help="Thư mục Draft đích; mặc định là thư mục cha của template.",
    )
    parser.add_argument(
        "--no-capcut-register",
        action="store_true",
        help=(
            "Tạo thư mục Draft nhưng không đăng ký vào root_meta_info.json "
            "của CapCut."
        ),
    )
    parser.add_argument(
        "--replace-capcut-draft",
        action="store_true",
        help=(
            "Thay thế Draft CapCut đã tạo trước đó cho project, "
            "không tạo thêm Draft mới."
        ),
    )
    parser.add_argument(
        "--capcut-hook-music",
        help="File nhac nen danh rieng cho Hook.",
    )
    parser.add_argument(
        "--capcut-hook-volume-db",
        type=float,
        default=-17.0,
        help="Volume nhac Hook tinh bang dB.",
    )
    parser.add_argument(
        "--capcut-body-music",
        action="append",
        help=(
            "File nhac nen sau Hook. Them '|repeat' vao cuoi de lap tu bai nay "
            "den het video."
        ),
    )
    parser.add_argument(
        "--skip-whisper", action="store_true",
        help=(
            "Bỏ qua Whisper; dùng Timing SRT nếu có, nếu không sẽ ước tính "
            "từ kịch bản."
        ),
    )
    parser.add_argument(
        "--analyze-section",
        action="append",
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--analysis-workers", type=int, default=config.analysis_workers,
        help=(
            "Số thread Worker dùng để decode Footage/phân tích Scene "
            f"(mặc định: {config.analysis_workers})."
        ),
    )
    parser.add_argument(
        "--voice-files", nargs=1,
        help="Đúng một file Audio chứa toàn bộ lời thoại của kịch bản.",
    )
    parser.add_argument(
        "--base-dir",
        help=(
            "Thư mục Project chứa Voice, kịch bản, Beat và Video. Các đối số "
            "đầu vào cụ thể sẽ ghi đè đường dẫn suy ra từ thư mục này."
        ),
    )
    parser.add_argument("--script", help="File transcript.")
    parser.add_argument("--beats", help="File Beat CSV.")
    parser.add_argument("--footage-dir", help="Thư mục chứa Footage nguồn.")
    parser.add_argument(
        "--music-dir",
        help="Thư mục nhạc nền DWG; mặc định tự tìm BASE/audio/music.",
    )
    parser.add_argument(
        "--music-cue-sheet",
        help="CSV chia cue nhạc; mặc định DWG_25min_music_cue_sheet.csv.",
    )
    parser.add_argument(
        "--no-background-music",
        action="store_true",
        help="Không trộn nhạc nền vào MP4 và không thêm nhạc vào gói CapCut.",
    )
    parser.add_argument(
        "--minimum-video-minutes",
        type=float,
        default=config.minimum_video_seconds / 60.0,
        help=(
            "Thời lượng video tối thiểu. Nếu narration ngắn hơn, thêm outro "
            "thiên nhiên và kéo nhạc; 0 để tắt (mặc định: 25 phút)."
        ),
    )
    parser.add_argument(
        "--caption-max-lines",
        type=int,
        default=4,
        help="Số dòng tối đa cho mỗi caption CapCut (mặc định: 4).",
    )
    parser.add_argument(
        "--caption-max-characters-per-line",
        "--caption-max-words-per-line",
        dest="caption_max_characters_per_line",
        type=int,
        default=14,
        help=(
            "Số ký tự tối đa trên mỗi dòng caption CapCut; ngắt tại khoảng "
            "trắng (mặc định: 14)."
        ),
    )
    parser.add_argument("--output", help="Đường dẫn MP4 đầu ra.")
    parser.add_argument(
        "--resolution", choices=("1080p", "720p"), default="1080p",
        help="Resolution đầu ra (mặc định: 1080p).",
    )
    parser.add_argument(
        "--vision-model",
        choices=tuple(VISION_MODELS.values()),
        default=config.clip_model,
        help="Model Vision-Language dùng để chấm Semantic Footage.",
    )
    parser.add_argument(
        "--min-cut-seconds", type=float, default=config.min_speech_seconds,
        help=f"Minimum narration cut duration (default: {config.min_speech_seconds}).",
    )
    parser.add_argument(
        "--target-cut-seconds", type=float, default=config.target_speech_seconds,
        help=f"Preferred narration cut duration (default: {config.target_speech_seconds}).",
    )
    parser.add_argument(
        "--max-cut-seconds", type=float, default=config.max_speech_seconds,
        help=f"Maximum narration cut duration (default: {config.max_speech_seconds}).",
    )
    parser.add_argument(
        "--no-model-download",
        action="store_true",
        help="Không tự động tải model khi Cache local bị thiếu.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> PipelineConfig:
    config = default_config()
    if args.base_dir:
        base_dir = Path(args.base_dir).resolve()
        cache_dir = base_dir / ".cache"
        music_dir = _discover_dwg_music_dir(base_dir, config.workdir)
        config = replace(
            config,
            base_dir=base_dir,
            voices_dir=_preferred_project_dir(
                base_dir, "audio", "voice", "voices"
            ),
            script_file=base_dir / "script.txt",
            beats_file=base_dir / "script_beat.csv",
            videos_dir=_preferred_project_dir(base_dir, "video", "footage"),
            output_file=base_dir / "video_output.mp4",
            cache_dir=cache_dir,
            whisper_cache_file=cache_dir / "whisper_words_vfootage.json",
            report_file=cache_dir / "vfootage_timeline.json",
            report_csv_file=cache_dir / "vfootage_timeline.csv",
            music_dir=music_dir,
            music_cue_sheet=(
                music_dir / "DWG_25min_music_cue_sheet.csv"
                if music_dir is not None
                and (music_dir / "DWG_25min_music_cue_sheet.csv").is_file()
                else None
            ),
        )

    if args.min_cut_seconds <= 0:
        raise ValueError("--min-cut-seconds must be greater than 0")
    if not (
        args.min_cut_seconds <= args.target_cut_seconds <= args.max_cut_seconds
    ):
        raise ValueError(
            "Thời lượng Cut phải thỏa mãn: min <= target <= max"
        )
    if args.analysis_workers < 1:
        raise ValueError("--analysis-workers must be at least 1")
    if args.caption_max_lines < 1:
        raise ValueError("--caption-max-lines must be at least 1")
    if args.caption_max_characters_per_line < 1:
        raise ValueError(
            "--caption-max-characters-per-line must be at least 1"
        )
    modes = (
        bool(args.analyze_only),
        bool(getattr(args, "render_only", False)),
        bool(getattr(args, "export_scenes_only", False)),
        bool(getattr(args, "export_capcut_package", False)),
    )
    if sum(modes) > 1:
        raise ValueError(
            "--analyze-only, --render-only, --export-scenes-only and "
            "--export-capcut-package "
            "cannot be combined"
        )
    if args.render_section and not args.render_only:
        raise ValueError("--render-section chỉ dùng cùng --render-only")
    if args.capcut_section and not args.export_capcut_package:
        raise ValueError(
            "--capcut-section chỉ dùng cùng --export-capcut-package"
        )

    updates = {
        "selected_voice_files": (
            tuple(Path(item).resolve() for item in args.voice_files)
            if args.voice_files else None
        ),
        "resolution": (1920, 1080) if args.resolution == "1080p" else (1280, 720),
        "min_speech_seconds": args.min_cut_seconds,
        "target_speech_seconds": args.target_cut_seconds,
        "max_speech_seconds": args.max_cut_seconds,
        "candidate_min_seconds": args.min_cut_seconds,
        "candidate_target_seconds": (
            args.target_cut_seconds + config.transition_seconds
        ),
        "candidate_max_seconds": (
            args.max_cut_seconds + config.transition_seconds
        ),
        "analysis_workers": args.analysis_workers,
        "clip_model": args.vision_model,
        "auto_download_clip": not getattr(args, "no_model_download", False),
        "enable_background_music": not getattr(
            args, "no_background_music", False
        ),
        "minimum_video_seconds": max(
            0.0, float(getattr(args, "minimum_video_minutes", 25.0)) * 60.0
        ),
    }
    path_options = {
        "script_file": args.script,
        "beats_file": args.beats,
        "videos_dir": args.footage_dir,
        "output_file": args.output,
        "music_dir": getattr(args, "music_dir", None),
        "music_cue_sheet": getattr(args, "music_cue_sheet", None),
    }
    updates.update(
        {
            field: Path(value).resolve()
            for field, value in path_options.items()
            if value
        }
    )
    if getattr(args, "music_dir", None) and not getattr(
        args, "music_cue_sheet", None
    ):
        candidate = Path(args.music_dir).resolve() / "DWG_25min_music_cue_sheet.csv"
        updates["music_cue_sheet"] = candidate if candidate.is_file() else None
    return replace(config, **updates)
