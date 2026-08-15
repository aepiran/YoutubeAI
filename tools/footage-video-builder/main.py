"""UI and CLI entrypoint for the narration-led video pipeline."""

import os
import sys
from pathlib import Path

from video_builder.subprocess_utils import install_hidden_subprocess_patch


install_hidden_subprocess_patch()

import imageio_ffmpeg
import moviepy.config as moviepy_config


moviepy_config.FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()


def configure_utf8_stdio() -> None:
    """Keep Vietnamese runtime messages safe on Windows pipes and consoles."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def parse_capcut_body_music(values: list[str] | None) -> list[dict]:
    rows = []
    for value in values or []:
        parts = value.split("|")
        path_value = parts[0]
        repeat = False
        volume_db = -20.0
        for option in parts[1:]:
            if option == "repeat":
                repeat = True
            elif option.startswith("volume_db="):
                volume_db = float(option.split("=", 1)[1])
        if path_value:
            rows.append(
                {
                    "path": str(Path(path_value).resolve()),
                    "repeat": repeat,
                    "volume_db": volume_db,
                }
            )
    return rows


def run_cli(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    from video_builder import run_pipeline
    from video_builder.config import build_parser, config_from_args

    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    try:
        run_pipeline(
            config,
            skip_whisper=args.skip_whisper,
            analyze_only=args.analyze_only,
            force_analysis=args.force_analysis,
            render_only=args.render_only,
            render_sections=(
                set(args.render_section)
                if args.render_section
                else None
            ),
            export_scenes_only=args.export_scenes_only,
            scenes_output_dir=(
                None
                if not args.scenes_output_dir
                else Path(args.scenes_output_dir).resolve()
            ),
            export_capcut_package=args.export_capcut_package,
            capcut_output_dir=(
                None
                if not args.capcut_output_dir
                else Path(args.capcut_output_dir).resolve()
            ),
            capcut_sections=(
                set(args.capcut_section)
                if args.capcut_section
                else None
            ),
            capcut_reference_video=not args.no_capcut_reference_video,
            capcut_template_dir=(
                None
                if not args.capcut_template_dir
                else Path(args.capcut_template_dir).resolve()
            ),
            capcut_draft_name=args.capcut_draft_name,
            capcut_drafts_root=(
                None
                if not args.capcut_drafts_root
                else Path(args.capcut_drafts_root).resolve()
            ),
            capcut_register_draft=not args.no_capcut_register,
            capcut_replace_draft=args.replace_capcut_draft,
            capcut_hook_music=(
                None
                if not args.capcut_hook_music
                else Path(args.capcut_hook_music).resolve()
            ),
            capcut_hook_volume_db=args.capcut_hook_volume_db,
            capcut_body_music=parse_capcut_body_music(args.capcut_body_music),
            caption_max_lines=args.caption_max_lines,
            caption_max_characters_per_line=(
                args.caption_max_characters_per_line
            ),
            analyze_sections=(
                set(args.analyze_section)
                if args.analyze_section
                else None
            ),
        )
    except Exception as exc:
        if os.environ.get("FOOTAGE_BUILDER_UI_PROCESS") == "1":
            print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
            return 1
        raise
    return 0


def main() -> int:
    configure_utf8_stdio()
    argv = sys.argv[1:]
    if argv and argv[0] in {"--stock-footage-app", "--stock-worker"}:
        from stock_footage_app import main as stock_footage_main

        stock_argv = argv[1:] if argv[0] == "--stock-footage-app" else argv
        return stock_footage_main(stock_argv)
    if not argv or argv == ["--ui"]:
        try:
            from video_builder.ui.bootstrap import run_app
        except ImportError as exc:
            if exc.name and exc.name.startswith("PySide6"):
                print(
                    "PySide6 is required for the UI. "
                    "Install dependencies with: pip install -r requirements.txt",
                    file=sys.stderr,
                )
                return 1
            raise
        return run_app()
    cli_argv = [argument for argument in argv if argument != "--cli"]
    return run_cli(cli_argv)


if __name__ == "__main__":
    raise SystemExit(main())
