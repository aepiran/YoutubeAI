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
    wrap_caption_text,
    write_srt,
)
from video_builder.capcut_export.media_exporter import export_capcut_scenes
from video_builder.capcut_export.models import CaptionCue
from video_builder.capcut_export.package_builder import (
    _export_background_music,
    _validate_report_matches_current_audio,
    _write_package_manifest,
    build_capcut_package,
    load_section_report,
)
from video_builder.capcut_export.draft_adapter import _register_draft
from video_builder.capcut_export.draft_adapter import (
    _recover_interrupted_draft,
    _replace_captions,
    _replace_video_track,
    _set_caption_text,
    _stretch_template_tracks,
)
from video_builder.config import default_config


class CapCutSubtitleTests(unittest.TestCase):
    def test_caption_wraps_at_character_limit_without_splitting_words(self) -> None:
        wrapped = wrap_caption_text(
            "His mercy did not run out while you slept",
            max_lines=4,
            max_characters_per_line=14,
        )

        self.assertEqual(
            wrapped,
            "His mercy did\nnot run out\nwhile you\nslept",
        )
        self.assertTrue(
            all(len(line) <= 14 for line in wrapped.splitlines())
        )

    def test_word_timings_split_cue_when_layout_capacity_is_exceeded(self) -> None:
        timings = [
            {"word": word, "start": index * 0.1, "end": (index + 1) * 0.1}
            for index, word in enumerate("one two three four five six seven".split())
        ]

        cues = captions_from_word_timings(
            timings,
            max_characters=200,
            max_duration=20.0,
            max_lines=2,
            max_characters_per_line=11,
        )

        self.assertEqual([cue.text for cue in cues], [
            "one two\nthree four",
            "five six\nseven",
        ])

    def test_timeline_caption_splits_and_distributes_duration(self) -> None:
        cues = captions_from_timeline(
            [{
                "timeline_start": 0.0,
                "timeline_end": 8.0,
                "narration": "one two three four five six seven eight",
            }],
            max_lines=2,
            max_characters_per_line=11,
        )

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, "one two\nthree four")
        self.assertEqual(cues[0].end, 4.0)
        self.assertEqual(cues[1].start, 4.0)
        self.assertEqual(cues[1].end, 8.0)

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

        cues = captions_from_timeline(
            rows,
            max_characters_per_line=100,
        )

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
            ],
            max_characters_per_line=100,
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

    def test_srt_round_trip_preserves_caption_line_breaks(self) -> None:
        source = captions_from_timeline(
            [{
                "timeline_start": 0.0,
                "timeline_end": 2.0,
                "narration": "one two three four five",
            }],
            max_lines=3,
            max_characters_per_line=7,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = write_srt(Path(temporary) / "captions.srt", source)
            loaded = parse_srt(path)

        self.assertEqual(loaded, source)
        self.assertIn("\n", loaded[0].text)

    def test_empty_captions_are_written_as_empty_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = write_srt(Path(temporary) / "captions.srt", [])

            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            self.assertEqual(parse_srt(path), [])


class CapCutDraftRecoveryTests(unittest.TestCase):
    def test_interrupted_replacement_preserves_failed_draft_and_restores_backup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "DWG0808"
            backup = root / ".DWG0808.capcut_adapter_backup"
            target.mkdir()
            backup.mkdir()
            (target / "state.txt").write_text("failed", encoding="utf-8")
            (backup / "state.txt").write_text("old", encoding="utf-8")

            with patch("builtins.print"):
                recovery = _recover_interrupted_draft(target, backup)

            self.assertIsNotNone(recovery)
            self.assertEqual(
                (target / "state.txt").read_text(encoding="utf-8"),
                "old",
            )
            self.assertEqual(
                (recovery / "state.txt").read_text(encoding="utf-8"),
                "failed",
            )
            self.assertFalse(backup.exists())

    def test_pending_draft_install_reuses_completed_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "capcut_package"
            template = root / "template"
            drafts_root = root / "drafts"
            output.mkdir()
            template.mkdir()
            drafts_root.mkdir()
            (
                drafts_root / "DWG0808" / "Resources" / "CapCutAdapter"
            ).mkdir(parents=True)
            (output / "narration.wav").write_bytes(b"audio")
            (output / "capcut_manifest.json").write_text(
                json.dumps({
                    "canvas": {
                        "narration_duration": 2.0,
                    },
                    "tracks": {
                        "reference_video": None,
                        "captions": {
                            "max_lines": 4,
                            "max_characters_per_line": 14,
                        },
                    }
                }),
                encoding="utf-8",
            )
            pending = output / ".capcut_draft_install_pending.json"
            pending.write_text(
                json.dumps({
                    "draft_name": "DWG0808",
                    "template_dir": str(template),
                    "drafts_root": str(drafts_root),
                    "register": False,
                    "replace_existing": False,
                }),
                encoding="utf-8",
            )
            config = SimpleNamespace(base_dir=root / "project")
            report = {
                "inputs": {
                    "voice_timeline": [{"end": 2.0}],
                },
                "timeline": [{"timeline_end": 2.0}],
            }

            with (
                patch("builtins.print"),
                patch(
                    "video_builder.capcut_export.package_builder._load_report",
                    return_value=report,
                ),
                patch(
                    "video_builder.capcut_export.package_builder."
                    "_validate_report_matches_current_audio"
                ),
                patch(
                    "video_builder.capcut_export.package_builder.create_capcut_draft"
                ) as create_draft,
            ):
                package = build_capcut_package(
                    config,
                    output,
                    template_dir=template,
                )

            create_draft.assert_called_once_with(
                output,
                template.resolve(),
                "DWG0808",
                drafts_root=drafts_root.resolve(),
                register=False,
                replace_existing=True,
            )
            self.assertEqual(package.root, output)
            self.assertFalse(pending.exists())

    def test_pending_draft_install_ignores_package_without_duration_profile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "capcut_package"
            template = root / "template"
            output.mkdir()
            template.mkdir()
            (output / "narration.wav").write_bytes(b"audio")
            (output / "capcut_manifest.json").write_text(
                json.dumps({
                    "tracks": {
                        "reference_video": None,
                        "captions": {
                            "max_lines": 4,
                            "max_characters_per_line": 14,
                        },
                    }
                }),
                encoding="utf-8",
            )
            (output / ".capcut_draft_install_pending.json").write_text(
                json.dumps({
                    "draft_name": "DWG0808",
                    "template_dir": str(template),
                    "register": False,
                }),
                encoding="utf-8",
            )
            audio = root / "voice.mp3"
            audio.write_bytes(b"audio")
            config = SimpleNamespace(base_dir=root / "project")
            clip = SimpleNamespace(duration=2.0, close=lambda: None)
            report = {
                "inputs": {
                    "audio": [str(audio)],
                    "voice_timeline": [{"end": 2.0}],
                },
                "timeline": [{"timeline_end": 2.0}],
            }

            with (
                patch(
                    "video_builder.capcut_export.package_builder._load_report",
                    return_value=report,
                ),
                patch(
                    "video_builder.capcut_export.package_builder."
                    "_validate_report_matches_current_audio"
                ),
                patch(
                    "video_builder.capcut_export.package_builder."
                    "open_voice_timeline",
                    return_value=(clip, [clip], []),
                ),
                patch(
                    "video_builder.capcut_export.package_builder."
                    "export_capcut_scenes",
                    side_effect=RuntimeError("rebuild package"),
                ),
                patch(
                    "video_builder.capcut_export.package_builder."
                    "create_capcut_draft"
                ) as create_draft,
            ):
                with self.assertRaisesRegex(RuntimeError, "rebuild package"):
                    build_capcut_package(
                        config,
                        output,
                        template_dir=template,
                    )

            create_draft.assert_not_called()


class CapCutTemplateFallbackTests(unittest.TestCase):
    def test_video_replacement_preserves_materials_used_by_overlay_tracks(
        self,
    ) -> None:
        content = {
            "tracks": [
                {
                    "type": "video",
                    "segments": [{
                        "id": "main-segment",
                        "material_id": "main-video",
                        "extra_material_refs": [],
                    }],
                },
                {
                    "type": "video",
                    "segments": [{
                        "id": "overlay-segment",
                        "material_id": "photo-overlay",
                        "extra_material_refs": [],
                    }],
                },
            ],
            "materials": {
                "videos": [
                    {"id": "main-video", "type": "video"},
                    {"id": "photo-overlay", "type": "photo"},
                ],
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            scene = package / "scenes" / "001.mp4"
            scene.parent.mkdir()
            scene.write_bytes(b"scene")

            _replace_video_track(
                content,
                package,
                [{
                    "file": "scenes/001.mp4",
                    "timeline_start": 0.0,
                    "duration": 2.0,
                }],
            )

        material_ids = {
            material["id"] for material in content["materials"]["videos"]
        }
        self.assertIn("photo-overlay", material_ids)
        self.assertNotIn("main-video", material_ids)
        self.assertIn(
            content["tracks"][0]["segments"][0]["material_id"],
            material_ids,
        )

    def test_caption_text_updates_content_and_base_content(self) -> None:
        source = {
            "text": "Template",
            "styles": [{
                "range": [0, 8],
                "bold": True,
                "font": {"id": "custom", "path": "custom.ttf"},
            }],
        }
        base_source = {
            "text": "Template",
            "styles": [{
                "range": [0, 8],
                "font": {"id": "", "path": "fallback.ttf"},
            }],
        }
        material = {
            "content": json.dumps(source),
            "base_content": json.dumps(base_source),
            "recognize_text": "stale template text",
            "translate_original_text": "stale template text",
            "words": {
                "start_time": [0], "end_time": [10], "text": ["stale"]
            },
            "current_words": {
                "start_time": [0], "end_time": [10], "text": ["stale"]
            },
        }

        _set_caption_text(
            material,
            "ONE TWO\nTHREE",
            semantic_text="One two three",
            duration=1_200_000,
        )

        for field in ("content", "base_content"):
            payload = json.loads(material[field])
            self.assertEqual(payload["text"], "ONE TWO\nTHREE")
            self.assertEqual(payload["styles"][0]["range"], [0, 13])
            self.assertEqual(
                payload["styles"][0]["font"],
                {"id": "custom", "path": "custom.ttf"},
            )
        self.assertEqual(material["recognize_text"], "One two three")
        self.assertEqual(material["translate_original_text"], "One two three")
        self.assertEqual(
            material["words"]["text"],
            ["One", " ", "two", " ", "three"],
        )
        self.assertEqual(material["words"]["end_time"][-1], 1200)
        self.assertEqual(material["current_words"]["text"], [])

    def test_direct_text_material_template_replaces_captions(self) -> None:
        source = json.dumps({
            "text": "TEMPLATE",
            "styles": [{"range": [0, 8]}],
        })
        content = {
            "tracks": [{
                "type": "text",
                "segments": [{
                    "id": "segment-old",
                    "material_id": "text-old",
                    "extra_material_refs": ["animation-old"],
                    "target_timerange": {"start": 0, "duration": 1_000_000},
                    "clip": {"transform": {"x": 0.3, "y": 0.0}},
                }],
            }],
            "materials": {
                "texts": [{
                    "id": "text-old",
                    "content": source,
                    "base_content": source,
                }],
                "material_animations": [{
                    "id": "animation-old",
                    "animations": [],
                }],
                "text_templates": [],
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            captions = write_srt(
                Path(temporary) / "captions.srt",
                [
                    CaptionCue(
                        index=1,
                        start=0.0,
                        end=2.0,
                        text="One two\nThree four",
                    )
                ],
            )
            _replace_captions(content, captions)

        segment = content["tracks"][0]["segments"][0]
        self.assertNotEqual(segment["material_id"], "text-old")
        self.assertEqual(segment["clip"]["transform"]["x"], 0.3)
        self.assertEqual(len(content["materials"]["texts"]), 1)
        payload = json.loads(content["materials"]["texts"][0]["content"])
        self.assertEqual(payload["text"], "ONE TWO\nTHREE FOUR")

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

    def test_photo_overlay_keeps_geometry_and_matches_video_duration(self) -> None:
        content = {
            "tracks": [
                {"type": "video", "segments": []},
                {
                    "type": "video",
                    "segments": [{
                        "material_id": "photo-overlay",
                        "source_timerange": {"start": 0, "duration": 1_000_000},
                        "target_timerange": {"start": 0, "duration": 1_000_000},
                        "clip": {
                            "transform": {"x": -0.7, "y": -0.2},
                            "scale": {"x": 1.0, "y": 1.0},
                        },
                        "uniform_scale": {"on": True, "value": 1.0},
                    }],
                },
            ],
            "materials": {
                "videos": [{
                    "id": "photo-overlay",
                    "type": "photo",
                    "duration": 1_000_000,
                }],
            },
        }

        _stretch_template_tracks(content, 25_000_000)

        segment = content["tracks"][1]["segments"][0]
        self.assertEqual(segment["target_timerange"]["duration"], 25_000_000)
        self.assertEqual(segment["source_timerange"]["duration"], 25_000_000)
        self.assertEqual(segment["clip"]["transform"], {"x": -0.7, "y": -0.2})
        self.assertEqual(segment["uniform_scale"]["value"], 1.0)


class CapCutMediaExportTests(unittest.TestCase):
    def test_report_audio_mismatch_is_rejected_before_capcut_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_audio = root / "old.mp3"
            new_audio = root / "new.mp3"
            old_audio.write_bytes(b"old")
            new_audio.write_bytes(b"new")
            report = {
                "inputs": {
                    "audio": [str(old_audio)],
                    "voice_timeline": [{"end": 1500.0}],
                },
                "timeline": [{"timeline_end": 1500.0}],
            }
            config = SimpleNamespace()

            with patch(
                "video_builder.capcut_export.package_builder."
                "discover_voice_files",
                return_value=[new_audio],
            ):
                with self.assertRaisesRegex(ValueError, "khong khop Audio"):
                    _validate_report_matches_current_audio(config, report)

    def test_report_timeline_shorter_than_audio_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "voice.mp3"
            audio.write_bytes(b"audio")
            report = {
                "inputs": {
                    "audio": [str(audio)],
                    "voice_timeline": [{"end": 1680.0}],
                },
                "timeline": [{"timeline_end": 1500.0}],
            }
            clip = SimpleNamespace(duration=1680.0, close=lambda: None)
            config = SimpleNamespace()

            with (
                patch(
                    "video_builder.capcut_export.package_builder."
                    "discover_voice_files",
                    return_value=[audio],
                ),
                patch(
                    "video_builder.capcut_export.package_builder."
                    "open_voice_timeline",
                    return_value=(clip, [clip], []),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "chua phu het Audio"):
                    _validate_report_matches_current_audio(config, report)

    def test_manifest_duration_never_shorter_than_narration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "capcut_manifest.json"
            report = {
                "timeline": [{
                    "beats": ["B001"],
                    "timeline_start": 0.0,
                    "timeline_end": 1500.0,
                    "footage": "scene.mp4",
                    "narration": "Amen.",
                }],
            }
            scene_rows = [{
                "order": 1,
                "scene_file": "001_B001_scene.mp4",
                "duration": 1500.0,
                "source_start": 0.0,
                "source_end": 1500.0,
            }]
            config = SimpleNamespace(
                base_dir=root / "project",
                resolution=(1920, 1080),
                output_fps=30,
            )

            _write_package_manifest(
                manifest,
                config=config,
                report=report,
                scene_rows=scene_rows,
                audio_section_rows=[],
                background_music_rows=[],
                reference_video=None,
                captions_enabled=False,
                caption_max_lines=4,
                caption_max_characters_per_line=14,
                narration_duration=1680.0,
            )

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["canvas"]["duration"], 1680.0)
            self.assertEqual(payload["canvas"]["timeline_duration"], 1500.0)
            self.assertEqual(payload["canvas"]["narration_duration"], 1680.0)

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
