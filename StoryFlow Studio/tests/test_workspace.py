from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import AppSettings, BeatSettings, TTSSettings
from storyflow_studio.modules.workspace import ProjectError, WorkspaceService


class WorkspaceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WorkspaceService()

    def test_create_project_snapshots_paths_and_never_stores_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            settings = AppSettings(
                tts=TTSSettings(
                    api_key="must-not-enter-project",
                    script_filename="voice_script.txt",
                    output_folder="voice",
                    audio_filename="story.mp3",
                    subtitle_filename="story.srt",
                ),
                beat=BeatSettings(output_filename="shots.csv"),
            )

            project = self.service.create_project(
                workspace, "My First Story", "my-first-story", settings
            )

            self.assertEqual(project.root.parent, workspace.resolve())
            self.assertTrue(project.path_for("audio_dir").is_dir())
            self.assertTrue((project.root / ".storyflow" / "logs").is_dir())
            self.assertTrue((project.root / ".storyflow" / "cache").is_dir())
            self.assertEqual(project.path_for("tts_script").name, "voice_script.txt")
            self.assertEqual(project.path_for("audio_file"), project.root / "voice/story.mp3")
            self.assertEqual(
                project.path_for("music_cue_file"),
                project.root / "audio/cue_music.csv",
            )
            self.assertEqual(
                project.path_for("background_music_file"),
                project.root / "audio/background_music.mp3",
            )
            self.assertTrue((project.root / "audio").is_dir())
            self.assertEqual(
                project.path_for("capcut_package_dir"),
                project.root / "output/capcut_package",
            )
            manifest_text = project.manifest_path.read_text(encoding="utf-8")
            self.assertNotIn("must-not-enter-project", manifest_text)
            self.assertNotIn("api_key", manifest_text.lower())

    def test_create_rejects_existing_project_and_unsafe_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            self.service.create_project(workspace, "One", "one", AppSettings())

            with self.assertRaises(ProjectError):
                self.service.create_project(workspace, "Again", "one", AppSettings())
            with self.assertRaises(ProjectError):
                self.service.create_project(workspace, "Escape", "../escape", AppSettings())

    def test_open_rejects_manifest_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.service.create_project(
                directory, "Unsafe", "unsafe", AppSettings()
            )
            raw = json.loads(project.manifest_path.read_text(encoding="utf-8"))
            raw["paths"]["audio_dir"] = "../outside"
            project.manifest_path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaises(ProjectError):
                self.service.open_project(project.root)

    def test_open_discovers_completed_stages_from_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.service.create_project(
                directory, "Complete", "complete", AppSettings()
            )
            project.path_for("tts_script").write_text("script", encoding="utf-8")
            project.path_for("audio_file").write_bytes(b"mp3")
            project.path_for("subtitle_file").write_text("srt", encoding="utf-8")
            project.path_for("beat_file").write_text("beat", encoding="utf-8")

            reopened = self.service.open_project(project.root)

            self.assertEqual(
                reopened.manifest.stages,
                {
                    "tts_script": "completed",
                    "voice": "completed",
                    "beat": "completed",
                    "music": "pending",
                    "footage": "pending",
                    "video_plan": "pending",
                    "video_render": "pending",
                },
            )


if __name__ == "__main__":
    unittest.main()
