from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import AppSettings, VideoBuilderSettings
from storyflow_studio.modules.tts import CancellationToken
from storyflow_studio.modules.video_builder import CapCutPackageExporter
from storyflow_studio.modules.video_builder.capcut_draft import create_capcut_draft
from storyflow_studio.modules.workspace import WorkspaceService


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class CapCutExportTests(unittest.TestCase):
    def test_exports_portable_editable_package_from_saved_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = WorkspaceService().create_project(
                Path(directory) / "workspace", "CapCut", "capcut", AppSettings()
            )
            source = project.path_for("footage_dir") / "H01_LOCAL.mp4"
            source.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
                ],
                check=True,
            )
            subprocess.run(
                [
                    shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:a", "libmp3lame", "-y", str(project.path_for("audio_file")),
                ],
                check=True,
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nTest\n", encoding="utf-8"
            )
            project.path_for("screen_subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nKey message\n", encoding="utf-8"
            )
            rows = tuple(
                {
                    "cut": index + 1,
                    "beat": "H01",
                    "timeline_start": float(index),
                    "timeline_end": float(index + 1),
                    "footage": "video/H01_LOCAL.mp4",
                    "source_start": float(index),
                }
                for index in range(2)
            )
            updates = []

            result = CapCutPackageExporter().export(
                project,
                AppSettings(
                    video_builder=VideoBuilderSettings(
                        resolution="720p", encoder_preset="ultrafast"
                    )
                ),
                rows,
                2.0,
                updates.append,
                CancellationToken(),
            )

            self.assertEqual(result.scene_count, 2)
            self.assertEqual(len(tuple((result.package_dir / "scenes").glob("*.mp4"))), 2)
            self.assertTrue((result.package_dir / "narration.wav").is_file())
            self.assertTrue((result.package_dir / "screen.srt").is_file())
            self.assertTrue((result.package_dir / "narration.srt").is_file())
            self.assertTrue((result.package_dir / "selected_scenes.csv").is_file())
            self.assertTrue((result.package_dir / "README_CAPCUT.txt").is_file())
            manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "storyflow.capcut-package")
            self.assertEqual(manifest["canvas"]["duration_seconds"], 2.0)
            self.assertEqual(len(manifest["tracks"]["video"]), 2)
            self.assertEqual(updates[-1].state, "completed")

    def test_creates_owned_capcut_draft_from_configured_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Morning Prayer", "morning-prayer", AppSettings()
            )
            source = project.path_for("footage_dir") / "H01_LOCAL.mp4"
            source.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
                ],
                check=True,
            )
            subprocess.run(
                [
                    shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "libmp3lame", "-y", str(project.path_for("audio_file")),
                ],
                check=True,
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8"
            )
            project.path_for("screen_subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nKey message\n", encoding="utf-8"
            )
            template = root / "template"
            template.mkdir()
            (template / "draft_content.json").write_text(
                json.dumps(
                    {
                        "version": 360000,
                        "name": "Template",
                        "duration": 1_000_000,
                        "fps": 30.0,
                        "path": str(template),
                        "canvas_config": {"width": 1920, "height": 1080},
                        "materials": {
                            "videos": [{"id": "VIDEO", "path": "old.mp4", "duration": 1_000_000}],
                            "audios": [{"id": "AUDIO", "path": "old.wav", "duration": 1_000_000}],
                            "texts": [],
                        },
                        "tracks": [
                            {
                                "id": "VT", "type": "video",
                                "segments": [{
                                    "id": "VS", "material_id": "VIDEO",
                                    "source_timerange": {"start": 0, "duration": 1_000_000},
                                    "target_timerange": {"start": 0, "duration": 1_000_000},
                                    "extra_material_refs": [],
                                }],
                            },
                            {
                                "id": "AT", "type": "audio",
                                "segments": [{
                                    "id": "AS", "material_id": "AUDIO",
                                    "source_timerange": {"start": 0, "duration": 1_000_000},
                                    "target_timerange": {"start": 0, "duration": 1_000_000},
                                    "extra_material_refs": [],
                                }],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (template / "draft_meta_info.json").write_text(
                json.dumps({"draft_id": "TEMPLATE", "draft_name": "Template"}),
                encoding="utf-8",
            )
            drafts = root / "drafts"
            result = CapCutPackageExporter().export(
                project,
                AppSettings(
                    video_builder=VideoBuilderSettings(
                        resolution="720p",
                        encoder_preset="ultrafast",
                        capcut_template_dir=str(template),
                        capcut_drafts_root=str(drafts),
                    )
                ),
                ({
                    "cut": 1,
                    "beat": "H01",
                    "timeline_start": 0.0,
                    "timeline_end": 1.0,
                    "footage": "video/H01_LOCAL.mp4",
                    "source_start": 0.0,
                },),
                1.0,
                lambda _update: None,
                CancellationToken(),
                draft_name="Beautiful Morning Prayer",
            )

            self.assertEqual(result.draft_dir, drafts / "Beautiful Morning Prayer")
            self.assertTrue((result.draft_dir / "Resources" / "StoryFlowStudio" / "owner.json").is_file())
            content = json.loads(
                (result.draft_dir / "draft_content.json").read_text(encoding="utf-8")
            )
            self.assertEqual(content["name"], "Beautiful Morning Prayer")
            meta = json.loads(
                (result.draft_dir / "draft_meta_info.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(meta["draft_name"], "Beautiful Morning Prayer")
            self.assertIn("Resources/StoryFlowStudio/scenes", content["materials"]["videos"][0]["path"])
            manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["capcut_project_name"], "Beautiful Morning Prayer"
            )
            self.assertEqual(manifest["capcut_draft"]["path"], result.draft_dir.as_posix())


class CapCutDraftAdapterTests(unittest.TestCase):
    def test_template_owned_resources_are_replaced_when_creating_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            (package / "scenes").mkdir(parents=True)
            (package / "scenes" / "scene_001.mp4").write_bytes(b"new scene")
            (package / "narration.wav").write_bytes(b"narration")
            (package / "capcut_manifest.json").write_text(
                json.dumps(
                    {
                        "project": "Morning Prayer",
                        "canvas": {
                            "width": 1280,
                            "height": 720,
                            "fps": 30.0,
                            "duration_seconds": 1.0,
                        },
                        "tracks": {
                            "video": [
                                {
                                    "file": "scenes/scene_001.mp4",
                                    "duration": 1.0,
                                    "timeline_start": 0.0,
                                }
                            ],
                            "narration": "narration.wav",
                        },
                    }
                ),
                encoding="utf-8",
            )
            template = root / "template"
            stale_scene_dir = template / "Resources" / "StoryFlowStudio" / "scenes"
            stale_scene_dir.mkdir(parents=True)
            (stale_scene_dir / "stale.mp4").write_bytes(b"stale")
            (template / "draft_content.json").write_text(
                json.dumps(
                    {
                        "version": 360000,
                        "name": "Template",
                        "duration": 1_000_000,
                        "fps": 30.0,
                        "path": str(template),
                        "canvas_config": {"width": 1280, "height": 720},
                        "materials": {
                            "videos": [
                                {
                                    "id": "VIDEO",
                                    "path": "old.mp4",
                                    "duration": 1_000_000,
                                }
                            ],
                            "audios": [
                                {
                                    "id": "AUDIO",
                                    "path": "old.wav",
                                    "duration": 1_000_000,
                                }
                            ],
                            "texts": [],
                        },
                        "tracks": [
                            {
                                "id": "VT",
                                "type": "video",
                                "segments": [
                                    {
                                        "id": "VS",
                                        "material_id": "VIDEO",
                                        "source_timerange": {
                                            "start": 0,
                                            "duration": 1_000_000,
                                        },
                                        "target_timerange": {
                                            "start": 0,
                                            "duration": 1_000_000,
                                        },
                                        "extra_material_refs": [],
                                    }
                                ],
                            },
                            {
                                "id": "AT",
                                "type": "audio",
                                "segments": [
                                    {
                                        "id": "AS",
                                        "material_id": "AUDIO",
                                        "source_timerange": {
                                            "start": 0,
                                            "duration": 1_000_000,
                                        },
                                        "target_timerange": {
                                            "start": 0,
                                            "duration": 1_000_000,
                                        },
                                        "extra_material_refs": [],
                                    }
                                ],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (template / "draft_meta_info.json").write_text(
                json.dumps({"draft_id": "TEMPLATE", "draft_name": "Template"}),
                encoding="utf-8",
            )

            draft = create_capcut_draft(
                package,
                template,
                "Exported Draft",
                drafts_root=root / "drafts",
            )

            scene_dir = draft / "Resources" / "StoryFlowStudio" / "scenes"
            self.assertTrue((scene_dir / "scene_001.mp4").is_file())
            self.assertFalse((scene_dir / "stale.mp4").exists())


if __name__ == "__main__":
    unittest.main()
