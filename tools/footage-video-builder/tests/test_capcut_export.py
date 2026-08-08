from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from video_builder.capcut_export.subtitle_exporter import (
    captions_from_timeline,
    captions_from_word_timings,
    parse_srt,
    write_srt,
)
from video_builder.capcut_export.media_exporter import export_capcut_scenes
from video_builder.capcut_export.package_builder import (
    _export_background_music,
    load_section_report,
)
from video_builder.capcut_export.draft_adapter import _register_draft
from video_builder.capcut_export.draft_adapter import (
    _replace_captions,
    _stretch_template_tracks,
)
from video_builder.config import default_config


class CapCutSubtitleTests(unittest.TestCase):
    def test_word_timings_split_on_sentence_and_keep_timing(self) -> None:
        timings = [
            {"word": "Hello", "start": 0.1, "end": 0.4},
            {"word": "world.", "start": 0.42, "end": 0.9},
            {"word": "Next", "start": 1.1, "end": 1.4},
            {"word": "caption", "start": 1.42, "end": 1.9},
        ]

        cues = captions_from_word_timings(timings)

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, "Hello world.")
        self.assertEqual(cues[0].start, 0.1)
        self.assertEqual(cues[0].end, 0.9)
        self.assertEqual(cues[1].text, "Next caption")

    def test_timeline_fallback_supports_old_analysis_reports(self) -> None:
        rows = [
            {
                "timeline_start": 0.0,
                "timeline_end": 2.25,
                "narration": "Fallback caption.",
            }
        ]

        cues = captions_from_timeline(rows)

        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].text, "Fallback caption.")
        self.assertEqual(cues[0].end, 2.25)

    def test_srt_is_utf8_and_uses_comma_timestamps(self) -> None:
        cues = captions_from_timeline(
            [
                {
                    "timeline_start": 1.234,
                    "timeline_end": 3.456,
                    "narration": "Phụ đề tiếng Việt.",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = write_srt(Path(temporary) / "captions.srt", cues)
            content = path.read_text(encoding="utf-8")

        self.assertIn("00:00:01,234 --> 00:00:03,456", content)
        self.assertIn("Phụ đề tiếng Việt.", content)

    def test_written_srt_can_be_read_by_draft_adapter(self) -> None:
        source = captions_from_timeline(
            [
                {
                    "timeline_start": 0.25,
                    "timeline_end": 1.75,
                    "narration": "Editable CapCut caption.",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = write_srt(Path(temporary) / "captions.srt", source)
            loaded = parse_srt(path)

        self.assertEqual(loaded, source)

    def test_empty_captions_are_written_as_empty_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = write_srt(Path(temporary) / "captions.srt", [])

            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            self.assertEqual(parse_srt(path), [])


class CapCutTemplateFallbackTests(unittest.TestCase):
    def test_template_without_caption_track_skips_caption_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            captions = write_srt(
                Path(temporary) / "captions.srt",
                captions_from_timeline(
                    [
                        {
                            "timeline_start": 0.0,
                            "timeline_end": 1.0,
                            "narration": "Caption exists.",
                        }
                    ]
                ),
            )
            content = {
                "tracks": [{"type": "video", "segments": []}],
                "materials": {},
            }

            _replace_captions(content, captions)

            self.assertEqual(content["tracks"], [{"type": "video", "segments": []}])

    def test_template_without_effect_track_skips_effect_stretch(self) -> None:
        content = {"tracks": [{"type": "video", "segments": []}]}

        _stretch_template_tracks(content, 2_000_000)

        self.assertEqual(content, {"tracks": [{"type": "video", "segments": []}]})


class CapCutMediaExportTests(unittest.TestCase):
    def test_background_music_plan_uses_hook_and_body_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hook = root / "hook.mp3"
            body_a = root / "body_a.mp3"
            body_b = root / "body_b.mp3"
            for path in (hook, body_a, body_b):
                path.write_bytes(b"audio")
            report = {
                "sections": [
                    {
                        "name": "Hook",
                        "timeline_start": 0.0,
                        "timeline_end": 3.0,
                    }
                ],
                "timeline": [
                    {"timeline_start": 0.0, "timeline_end": 3.0},
                    {"timeline_start": 3.0, "timeline_end": 10.0},
                ],
            }

            with patch(
                "video_builder.capcut_export.package_builder._audio_duration",
                side_effect=lambda path: {
                    hook.resolve(): 2.0,
                    body_a.resolve(): 4.0,
                    body_b.resolve(): 5.0,
                }[path.resolve()],
            ):
                rows = _export_background_music(
                    root / "package",
                    report,
                    hook_music=hook,
                    body_music=[
                        {"path": str(body_a), "repeat": False},
                        {"path": str(body_b), "repeat": True},
                    ],
                )

            self.assertEqual(
                [
                    (row["role"], row["timeline_start"], row["duration"])
                    for row in rows
                ],
                [
                    ("hook", 0.0, 2.0),
                    ("body", 2.0, 4.0),
                    ("body", 6.0, 4.0),
                ],
            )
            self.assertTrue((root / "package" / rows[0]["file"]).is_file())
            self.assertTrue(math.isclose(rows[0]["volume"], 10 ** (-17 / 20)))
            self.assertTrue(math.isclose(rows[1]["volume"], 10 ** (-20 / 20)))

    def test_body_music_repeats_after_hook_music_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hook = root / "hook.mp3"
            body = root / "body.mp3"
            hook.write_bytes(b"audio")
            body.write_bytes(b"audio")
            report = {
                "sections": [
                    {
                        "name": "Main",
                        "timeline_start": 0.0,
                        "timeline_end": 10.0,
                    }
                ],
                "timeline": [
                    {"timeline_start": 0.0, "timeline_end": 2.0},
                    {"timeline_start": 2.0, "timeline_end": 10.0},
                ],
            }

            with patch(
                "video_builder.capcut_export.package_builder._audio_duration",
                side_effect=lambda path: {
                    hook.resolve(): 2.0,
                    body.resolve(): 3.0,
                }[path.resolve()],
            ):
                rows = _export_background_music(
                    root / "package",
                    report,
                    hook_music=hook,
                    body_music=[{"path": str(body), "repeat": True}],
                )

            self.assertEqual(
                [
                    (row["role"], row["timeline_start"], row["duration"])
                    for row in rows
                ],
                [
                    ("hook", 0.0, 2.0),
                    ("body", 2.0, 3.0),
                    ("body", 5.0, 3.0),
                    ("body", 8.0, 2.0),
                ],
            )

    def test_replacing_draft_updates_registry_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft = root / "ProjectDraft"
            draft.mkdir()
            registry_path = root / "root_meta_info.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "draft_ids": 1,
                        "all_draft_store": [{
                            "draft_id": "existing-id",
                            "draft_name": "ProjectDraft",
                            "draft_fold_path": str(draft).replace("\\", "/"),
                        }],
                    }
                ),
                encoding="utf-8",
            )
            meta = {
                "draft_id": "existing-id",
                "draft_name": "ProjectDraft",
                "tm_draft_create": 1,
                "tm_draft_modified": 2,
            }

            _register_draft(
                registry_path,
                "existing-id",
                meta,
                draft,
                10,
                20,
                replace_existing=True,
            )

            registry = json.loads(
                registry_path.read_text(encoding="utf-8")
            )
            self.assertEqual(len(registry["all_draft_store"]), 1)
            self.assertEqual(registry["draft_ids"], 1)

    def test_selected_preview_reports_are_merged_and_rebased(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = default_config(root)
            preview_dir = config.cache_dir / "section_previews"
            preview_dir.mkdir(parents=True)
            for index, start, duration in (
                (1, 0.0, 2.0),
                (3, 7.0, 3.0),
            ):
                audio = root / f"{index:03d}.mp3"
                audio.write_bytes(b"audio")
                report = {
                    "analysis_scope": "section_preview",
                    "inputs": {
                        "audio": [str(audio)],
                        "voice_timeline": [],
                    },
                    "sections": [{
                        "index": index,
                        "name": f"S{index}",
                        "audio": str(audio),
                        "srt": None,
                        "duration": duration,
                        "timeline_start": start,
                        "timeline_end": start + duration,
                    }],
                    "timeline": [{
                        "section_index": index,
                        "timeline_start": start,
                        "timeline_end": start + duration,
                        "visual_start": start,
                        "visual_end": start + duration,
                    }],
                    "word_timings": [{
                        "word": f"section{index}",
                        "start": start,
                        "end": start + 0.5,
                    }],
                }
                (preview_dir / f"{index:03d}.json").write_text(
                    json.dumps(report), encoding="utf-8"
                )

            merged = load_section_report(config, {1, 3})

            self.assertEqual(
                [
                    row["timeline_start"]
                    for row in merged["timeline"]
                ],
                [0.0, 2.0],
            )
            self.assertEqual(
                [row["timeline_start"] for row in merged["sections"]],
                [0.0, 2.0],
            )
            self.assertEqual(
                [row["start"] for row in merged["word_timings"]],
                [0.0, 2.0],
            )

    def test_scene_export_removes_renderer_crossfade_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "H01_source.mp4"
            source.write_bytes(b"fixture")
            output_dir = root / "scenes"
            row = {
                "beats": ["H01"],
                "footage": str(source),
                "timeline_start": 5.0,
                "timeline_end": 8.0,
                "visual_start": 4.82,
                "visual_end": 8.18,
                "source_start": 10.0,
                "source_end": 13.36,
            }
            config = SimpleNamespace(
                resolution=(1920, 1080),
                output_fps=30,
                encoder_preset="veryfast",
            )

            with patch(
                "video_builder.capcut_export.media_exporter."
                "imageio_ffmpeg.get_ffmpeg_exe",
                return_value="ffmpeg",
            ), patch(
                "video_builder.capcut_export.media_exporter.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stderr=""),
            ) as run:
                manifest = export_capcut_scenes(
                    config, [row], output_dir
                )

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-ss") + 1], "10.180000")
            self.assertEqual(command[command.index("-t") + 1], "3.000000")
            self.assertIn(
                "scale=1920:1080:force_original_aspect_ratio=increase",
                command[command.index("-vf") + 1],
            )
            self.assertIn(
                "tpad=stop_mode=clone:stop_duration=3.000000",
                command[command.index("-vf") + 1],
            )
            self.assertTrue(manifest.is_file())


if __name__ == "__main__":
    unittest.main()
