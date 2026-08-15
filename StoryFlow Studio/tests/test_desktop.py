from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from storyflow_studio.core.settings import AppSettings, FootageSettings, SettingsStore
from storyflow_studio.core.version import version_badge
from storyflow_studio.desktop.main_window import MainWindow
from storyflow_studio.desktop.project_dialogs import ExportChoiceDialog, NewProjectDialog
from storyflow_studio.desktop.settings_dialog import (
    MIXKIT_CATALOG_URL,
    MIXKIT_LICENSE_NAME,
    MIXKIT_LICENSE_URL,
    SettingsDialog,
    TTS_MODEL_OPTIONS,
)
from storyflow_studio.modules.beat import BeatProgress, BeatWorkflowResult
from storyflow_studio.modules.music import MusicProgress, MusicWorkflowResult
from storyflow_studio.modules.footage import FootageProgress, FootageWorkflowResult
from storyflow_studio.modules.video_builder import (
    CapCutExportProgress,
    CapCutExportResult,
    TimelineAnalysisResult,
    TimelineReviewResult,
    VideoBuilderProgress,
    VideoRenderProgress,
    VideoRenderResult,
)
from storyflow_studio.modules.ai.service import AISnapshot, AuthStatus, ModelOption
from storyflow_studio.modules.tts import TTSProgress, TTSWorkflowResult, VoiceResult
from storyflow_studio.modules.workspace import WorkspaceService


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class FakeAIService:
    def snapshot(self) -> AISnapshot:
        return AISnapshot(
            AuthStatus(True, "Codex connected", "pro"),
            (ModelOption("gpt-test", "GPT Test", is_default=True),),
        )

    def login_chatgpt(self) -> AISnapshot:
        return self.snapshot()

    def run(self, prompt, workdir, settings) -> str:
        return "unused"


class FakeTTSWorkflowService:
    def run(self, project, settings, progress, cancellation):
        progress(TTSProgress("tts_script", "running", None, "Applying DNA"))
        project.path_for("tts_script").write_text("Test script\n", encoding="utf-8")
        progress(TTSProgress("tts_script", "completed", 100, "Created script_tts.txt"))
        progress(TTSProgress("voice", "running", 50, "Voice job processing", "job-ui"))
        project.path_for("audio_file").write_bytes(b"mp3")
        project.path_for("subtitle_file").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8"
        )
        progress(TTSProgress("voice", "completed", 100, "Voice outputs created", "job-ui"))
        return TTSWorkflowResult(
            project.path_for("tts_script"),
            VoiceResult(
                "job-ui",
                project.path_for("audio_file"),
                project.path_for("subtitle_file"),
            ),
        )


class FakeBeatWorkflowService:
    def __init__(self):
        self.replace_flags = []

    def run(
        self,
        project,
        settings,
        progress,
        cancellation,
        *,
        replace_existing=False,
    ):
        self.replace_flags.append(replace_existing)
        progress(BeatProgress("beat", "running", 25, "Applying Beat DNA"))
        output = project.path_for("beat_file")
        output.write_text(
            "ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh\n"
            "H01,Hope,sunrise,Golden sunrise,night\n",
            encoding="utf-8",
        )
        progress(BeatProgress("beat", "completed", 100, "Created footage.csv"))
        return BeatWorkflowResult(output, 1, 4.0)


class FakeMusicWorkflowService:
    def run(self, project, settings, progress, cancellation):
        progress(MusicProgress("music", "running", 50, "Rendering music cues"))
        cue_file = project.path_for("music_cue_file")
        audio_file = project.path_for("background_music_file")
        cue_file.write_text(
            "cue,start,end,track,prayer_section,crossfade_in_seconds,"
            "crossfade_out_seconds,gain_db,target_music_lufs,notes\n"
            "C01,00:00.000,00:04.000,bed.mp3,Hook,1,1,-18,-35,Soft\n",
            encoding="utf-8",
        )
        audio_file.write_bytes(b"music")
        progress(MusicProgress("music", "completed", 100, "Music outputs created"))
        return MusicWorkflowResult(cue_file, audio_file, 1, 4.0)


class FakeFootageWorkflowService:
    def run(self, project, settings, progress, cancellation):
        progress(FootageProgress("footage", "running", 40, "Searching Pexels"))
        output_dir = project.path_for("footage_dir")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "H01_PEXELS_101.mp4").write_bytes(b"video")
        manifest_file = project.path_for("footage_manifest")
        manifest_csv = project.path_for("footage_manifest_csv")
        manifest_file.write_text(
            '{"complete": true, "selections": []}\n', encoding="utf-8"
        )
        manifest_csv.write_text("beat_id,status\nH01,downloaded\n", encoding="utf-8")
        progress(FootageProgress("footage", "completed", 100, "Downloaded 1 clip"))
        return FootageWorkflowResult(
            output_dir, manifest_file, manifest_csv, 1, 0, 1
        )


class FakeVideoBuilderService:
    def __init__(self) -> None:
        self.replace_flags: list[bool] = []
        self.review_stale = False
        self.render_count = 0

    def analyze(
        self,
        project,
        settings,
        progress,
        cancellation,
        *,
        replace_existing=False,
    ):
        self.replace_flags.append(replace_existing)
        progress(
            VideoBuilderProgress(
                "video_plan", "running", 50, "Reusing validated Beat timing"
            )
        )
        timeline_file = project.path_for("video_timeline_file")
        timeline_csv = project.path_for("video_timeline_csv")
        timeline_file.parent.mkdir(parents=True, exist_ok=True)
        timeline_file.write_text(
            '{"timeline":[{"warnings":[]},{"warnings":["review"]}]}\n',
            encoding="utf-8",
        )
        timeline_csv.write_text("cut,beat\n1,H01\n2,H01\n", encoding="utf-8")
        progress(
            VideoBuilderProgress(
                "video_plan", "completed", 100, "Created 2 cuts · 1 warning"
            )
        )
        return TimelineAnalysisResult(timeline_file, timeline_csv, 2, 1, 8.0)

    def review(self, project, settings):
        return TimelineReviewResult(
            project.path_for("video_timeline_file"),
            ({"cut": 1, "warnings": []}, {"cut": 2, "warnings": []}),
            2,
            0,
            (),
            self.review_stale,
            "stale" if self.review_stale else "draft_ready",
        )

    def render(
        self,
        project,
        settings,
        progress,
        cancellation,
        *,
        replace_existing=False,
    ):
        self.render_count += 1
        progress(VideoRenderProgress("video_plan", "running", 75, "Muxing narration"))
        final_file = project.path_for("final_video_file")
        attribution_file = project.path_for("attribution_file")
        final_file.parent.mkdir(parents=True, exist_ok=True)
        final_file.write_bytes(b"final-video")
        attribution_file.write_text("footage,provider\nvideo/test.mp4,local\n")
        progress(VideoRenderProgress("video_plan", "completed", 100, "Created final_video.mp4"))
        return VideoRenderResult(final_file, attribution_file, 8.0, 11, 2)

    def export_capcut(
        self,
        project,
        settings,
        progress,
        cancellation,
        *,
        replace_existing=False,
    ):
        progress(CapCutExportProgress("video_plan", "running", 70, "Exporting scenes"))
        package = project.path_for("capcut_package_dir")
        package.mkdir(parents=True, exist_ok=True)
        manifest = package / "capcut_manifest.json"
        manifest.write_text('{"schema":"storyflow.capcut-package"}\n')
        progress(CapCutExportProgress("video_plan", "completed", 100, "Created capcut_package"))
        return CapCutExportResult(package, manifest, 2, 8.0)


class DesktopSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def wait_for_jobs(window: MainWindow) -> None:
        loop = QEventLoop()

        def check() -> None:
            if not window.jobs:
                loop.quit()
            else:
                QTimer.singleShot(10, check)

        QTimer.singleShot(10, check)
        QTimer.singleShot(2000, loop.quit)
        loop.exec()

    def test_header_has_codex_status_next_to_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                FakeAIService(),
                SettingsStore(Path(directory) / "settings.json", MemorySecretStore()),
            )
            self.wait_for_jobs(window)
            self.assertEqual(window.codex_button.text(), "● Codex")
            self.assertEqual(window.settings_button.accessibleName(), "Settings")
            self.assertEqual(window.run_tts_button.text(), "Start")
            self.assertEqual(window.run_beat_button.text(), "Generate")
            self.assertEqual(window.run_tts_button.objectName(), "StageActionButton")
            self.assertEqual(window.run_beat_button.objectName(), "StageActionButton")
            self.assertEqual(window.run_music_button.objectName(), "StageActionButton")
            self.assertEqual(window.run_footage_button.objectName(), "StageActionButton")
            self.assertEqual(
                window.run_video_builder_button.objectName(), "StageActionButton"
            )
            self.assertEqual(window.export_video_button.text(), "Export")
            self.assertEqual(
                window.export_video_button.accessibleName(),
                "Export Video Builder Output",
            )
            self.assertEqual(window.stage_grid.count(), 6)
            for row in range(2):
                for column in range(3):
                    self.assertIsNotNone(window.stage_grid.itemAtPosition(row, column))
            self.assertLessEqual(window.project_bar.maximumHeight(), 132)
            self.assertEqual(window.version_label.text(), version_badge())
            self.assertFalse(window.logo_label.pixmap().isNull())
            self.assertFalse(window.windowIcon().isNull())
            self.assertTrue(window.snapshot.auth.authenticated)
            self.assertIn("[CODEX] Codex connected", window.activity_console.toPlainText())
            window.close()

    def test_failed_stage_copies_full_error_and_enables_model_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_store = SettingsStore(
                Path(directory) / "settings.json", MemorySecretStore()
            )
            window = MainWindow(FakeAIService(), settings_store)
            self.wait_for_jobs(window)
            window.settings.video_builder.local_models_only = True
            message = (
                "Visual Model chưa có trong local cache.\n"
                "Model: openai/clip-vit-base-patch32\n"
                "Cho phép StoryFlow tải model từ Hugging Face để tiếp tục."
            )
            with patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                window._video_builder_failed(message)

            self.assertFalse(window.settings.video_builder.local_models_only)
            self.assertFalse(settings_store.load().video_builder.local_models_only)
            self.assertTrue(window._retry_video_analysis_after_model_download)
            detail = window.stage_details["video_plan"]
            window.show()
            self.app.processEvents()
            self.app.clipboard().clear()
            QTest.mouseClick(detail, Qt.MouseButton.LeftButton)
            self.assertEqual(self.app.clipboard().text(), message)
            self.assertEqual(detail.toolTip(), "Copied error log")
            window._retry_video_analysis_after_model_download = False
            window.close()

    def test_settings_dialog_has_music_configuration_and_download_links(self) -> None:
        dialog = SettingsDialog(AppSettings(), FakeAIService().snapshot())
        self.assertEqual(dialog.pages.count(), 7)
        self.assertEqual(dialog.navigation.count(), 7)
        self.assertEqual(
            tuple(
                dialog.navigation.item(index).text()
                for index in range(dialog.navigation.count())
            ),
            dialog.section_names,
        )
        dialog.navigation.setCurrentRow(2)
        self.assertEqual(dialog.pages.currentIndex(), 2)
        self.assertFalse(hasattr(dialog, "voice_name"))
        self.assertEqual(dialog.voice_model.count(), len(TTS_MODEL_OPTIONS))
        self.assertEqual(dialog.voice_model.itemData(0), "speech-2.8-hd")
        self.assertEqual(dialog.voice_model.itemData(9), "speech-01-turbo")
        self.assertIn("Background Music", dialog.section_names)
        self.assertIn("Footage Finder", dialog.section_names)
        self.assertIn("Video Builder", dialog.section_names)
        self.assertTrue(dialog.footage_use_pexels.isChecked())
        self.assertFalse(dialog.footage_use_pixabay.isChecked())
        self.assertEqual(dialog.builder_resolution.currentText(), "1080p")
        self.assertEqual(dialog.builder_min_cut.value(), 3.0)
        self.assertEqual(dialog.builder_target_cut.value(), 4.0)
        self.assertEqual(dialog.builder_max_cut.value(), 5.0)
        self.assertEqual(dialog.builder_minimum_minutes.value(), 0.0)
        self.assertFalse(hasattr(dialog, "music_output_filename"))
        self.assertFalse(dialog.enable_music.isChecked())
        self.assertEqual(
            dialog.music_import_button.accessibleName(),
            "Import Downloaded Music",
        )
        self.assertEqual(
            dialog.music_catalog_button.accessibleName(),
            "Open Mixkit Music Catalog",
        )
        self.assertEqual(MIXKIT_LICENSE_NAME, "Mixkit Stock Music Free License")
        with patch(
            "storyflow_studio.desktop.settings_dialog.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            dialog.music_license_button.click()
            self.assertEqual(open_url.call_args.args[0].toString(), MIXKIT_LICENSE_URL)
            dialog.music_catalog_button.click()
            self.assertEqual(open_url.call_args.args[0].toString(), MIXKIT_CATALOG_URL)
        dialog.close()

    def test_new_project_dialog_generates_folder_slug(self) -> None:
        dialog = NewProjectDialog("/tmp/projects")
        dialog.project_name.setText("Morning Prayer 001")
        self.assertEqual(dialog.folder_name.text(), "morning-prayer-001")
        dialog.close()

    def test_export_choice_dialog_returns_render_or_capcut(self) -> None:
        render_dialog = ExportChoiceDialog()
        render_dialog.render_button.click()
        self.assertEqual(render_dialog.choice(), "render")
        capcut_dialog = ExportChoiceDialog()
        capcut_dialog.capcut_button.click()
        self.assertEqual(capcut_dialog.choice(), "capcut")

    def test_recent_projects_live_in_more_menu_and_require_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = WorkspaceService()
            first = workspace.create_project(
                root / "workspace", "First Story", "first-story", AppSettings()
            )
            second = workspace.create_project(
                root / "workspace", "Second Story", "second-story", AppSettings()
            )
            window = MainWindow(
                FakeAIService(),
                SettingsStore(root / "settings.json", MemorySecretStore()),
            )
            self.wait_for_jobs(window)
            self.assertFalse(hasattr(window, "recent_projects"))
            self.assertEqual(window.project_more_button.text(), "•••")
            self.assertFalse(window.refresh_status_button.icon().isNull())
            self.assertIn("Refresh Status", window.refresh_status_button.toolTip())

            window.set_project(first)
            window.set_project(second)
            actions = window.switch_project_menu.actions()
            target = next(action for action in actions if action.text() == "first-story")
            current = next(action for action in actions if "Current" in action.text())
            self.assertTrue(target.isEnabled())
            self.assertFalse(current.isEnabled())
            with patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ) as question:
                target.trigger()
                self.app.processEvents()
            self.assertEqual(question.call_args.args[1], "Switch Project")
            self.assertEqual(window.current_project.root, first.root)
            window.close()

    def test_open_project_becomes_codex_workdir_and_recent_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings_store = SettingsStore(
                root / "settings.json", MemorySecretStore()
            )
            project = WorkspaceService().create_project(
                root / "workspace", "Story One", "story-one", AppSettings()
            )
            window = MainWindow(FakeAIService(), settings_store)
            self.assertTrue(window.open_folder_button.isEnabled())
            self.assertEqual(window.open_folder_button.text(), "Open Project…")
            self.assertEqual(window.project_status_badge.text(), "No project")
            window.set_project(project)

            self.assertEqual(window.current_ai_workdir(), project.root)
            self.assertEqual(window.project_title.text(), "Story One")
            self.assertTrue(window.open_folder_button.isEnabled())
            self.assertEqual(window.open_folder_button.text(), "Open Folder")
            self.assertTrue(window.refresh_status_button.isEnabled())
            self.assertTrue(window.copy_project_path_action.isEnabled())
            self.assertEqual(window.project_status_badge.text(), "Active")
            self.assertTrue(window.project_status_badge.property("active"))
            self.assertFalse(hasattr(window, "project_input_hint"))
            window.show()
            self.app.processEvents()
            self.app.clipboard().clear()
            QTest.mouseClick(window.project_path, Qt.MouseButton.LeftButton)
            self.assertEqual(self.app.clipboard().text(), str(project.root))
            self.app.clipboard().clear()
            window.copy_project_path_action.trigger()
            self.assertEqual(self.app.clipboard().text(), str(project.root))
            self.assertEqual(window.stage_labels["tts_script"].text(), "Waiting")
            self.assertIn("Add script.txt", window.stage_details["tts_script"].text())
            with patch(
                "storyflow_studio.desktop.main_window.QDesktopServices.openUrl",
                return_value=True,
            ) as open_url:
                window.open_project_folder()
                self.assertEqual(
                    open_url.call_args.args[0].toLocalFile(), str(project.root)
                )
            project.path_for("raw_script").write_text(
                "A test narration script.", encoding="utf-8"
            )
            window.refresh_project_status()
            self.assertEqual(window.stage_labels["tts_script"].text(), "Ready")
            self.assertIn("Ready from script.txt", window.stage_details["tts_script"].text())
            self.assertEqual(window.stage_metrics["tts_script"].text(), "4 words · 24 characters")

            window.start_stage("tts_script", "Applying TTS DNA…")
            self.assertEqual(window.stage_labels["tts_script"].text(), "Running")
            self.assertEqual(window.stage_progress["tts_script"].maximum(), 0)
            window.update_stage_progress("tts_script", 50, "Generating TTS script")
            self.assertEqual(window.stage_progress["tts_script"].value(), 50)
            window.complete_stage("tts_script", "Created script_tts.txt")
            self.assertEqual(window.stage_labels["tts_script"].text(), "Completed")
            self.assertEqual(window.stage_progress["tts_script"].value(), 100)
            self.assertIn("Created script_tts.txt", window.activity_console.toPlainText())
            self.assertEqual(
                settings_store.load().workspace.recent_projects[0], str(project.root)
            )
            self.wait_for_jobs(window)
            window.close()

    def test_tts_pipeline_updates_console_and_stage_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Voice Story", "voice-story", AppSettings()
            )
            project.path_for("raw_script").write_text("Test script", encoding="utf-8")
            window = MainWindow(
                FakeAIService(),
                SettingsStore(root / "settings.json", MemorySecretStore()),
                tts_workflow_service=FakeTTSWorkflowService(),
            )
            window.set_project(project)
            self.wait_for_jobs(window)
            self.assertTrue(window.run_tts_button.isEnabled())

            window.run_tts_pipeline()
            self.wait_for_jobs(window)

            self.assertEqual(window.stage_labels["tts_script"].text(), "Completed")
            self.assertEqual(window.stage_labels["voice"].text(), "Completed")
            self.assertIn("Voice outputs created", window.activity_console.toPlainText())
            self.assertEqual(window.stage_metrics["voice"].text(), "Audio · 00:01")
            self.assertFalse(window.cancel_tts_button.isEnabled())
            window.close()

    def test_beat_pipeline_updates_console_and_creates_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Beat Story", "beat-story", AppSettings()
            )
            project.path_for("tts_script").write_text("Test script", encoding="utf-8")
            project.path_for("audio_file").write_bytes(b"mp3")
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:04,000\nTest script\n",
                encoding="utf-8",
            )
            beat_service = FakeBeatWorkflowService()
            window = MainWindow(
                FakeAIService(),
                SettingsStore(root / "settings.json", MemorySecretStore()),
                beat_workflow_service=beat_service,
            )
            window.set_project(project)
            self.wait_for_jobs(window)
            self.assertTrue(window.run_beat_button.isEnabled())

            window.run_beat_pipeline()
            self.wait_for_jobs(window)

            self.assertEqual(window.stage_labels["beat"].text(), "Completed")
            self.assertTrue(project.path_for("beat_file").is_file())
            self.assertEqual(window.stage_metrics["beat"].text(), "1 beat")
            self.assertIn("Validated 1 beats", window.activity_console.toPlainText())
            self.assertTrue(window.run_beat_button.isEnabled())
            self.assertEqual(window.run_beat_button.text(), "Generate Again")
            self.assertEqual(beat_service.replace_flags, [False])

            with patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                window.run_beat_pipeline()
                self.wait_for_jobs(window)
            self.assertEqual(beat_service.replace_flags, [False, True])
            self.assertFalse(window.cancel_tts_button.isEnabled())
            window.close()

    def test_music_pipeline_updates_console_and_creates_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Music Story", "music-story", AppSettings()
            )
            project.path_for("tts_script").write_text(
                "Test script", encoding="utf-8"
            )
            project.path_for("audio_file").write_bytes(b"mp3")
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:04,000\nTest script\n",
                encoding="utf-8",
            )
            settings_store = SettingsStore(
                root / "settings.json", MemorySecretStore()
            )
            enabled_settings = AppSettings()
            enabled_settings.music.enabled = True
            settings_store.save(enabled_settings)
            window = MainWindow(
                FakeAIService(),
                settings_store,
                music_workflow_service=FakeMusicWorkflowService(),
            )
            window.set_project(project)
            self.wait_for_jobs(window)
            self.assertTrue(window.run_music_button.isEnabled())

            window.run_music_pipeline()
            self.wait_for_jobs(window)

            self.assertEqual(window.stage_labels["music"].text(), "Completed")
            self.assertTrue(project.path_for("music_cue_file").is_file())
            self.assertTrue(project.path_for("background_music_file").is_file())
            self.assertEqual(window.stage_metrics["music"].text(), "1 cue")
            self.assertIn(
                "Validated and rendered 1 cues",
                window.activity_console.toPlainText(),
            )
            self.assertFalse(window.cancel_tts_button.isEnabled())
            window.close()

    def test_footage_finder_updates_console_and_downloads_into_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Footage Story", "footage-story", AppSettings()
            )
            project.path_for("beat_file").write_text(
                "ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh\n"
                "H01,Hope,sunrise,Golden sunrise,logo\n",
                encoding="utf-8",
            )
            settings_store = SettingsStore(
                root / "settings.json", MemorySecretStore()
            )
            settings_store.save(
                AppSettings(
                    footage=FootageSettings(
                        use_pexels=True,
                        pexels_api_key="secret",
                        clips_per_beat=1,
                    )
                )
            )
            window = MainWindow(
                FakeAIService(),
                settings_store,
                footage_workflow_service=FakeFootageWorkflowService(),
            )
            window.set_project(project)
            self.wait_for_jobs(window)
            self.assertTrue(window.run_footage_button.isEnabled())

            window.run_footage_pipeline()
            self.wait_for_jobs(window)

            self.assertEqual(window.stage_labels["footage"].text(), "Completed")
            self.assertEqual(window.stage_metrics["footage"].text(), "1 clip")
            self.assertTrue(
                (project.path_for("footage_dir") / "H01_PEXELS_101.mp4").is_file()
            )
            self.assertIn("Searching Pexels", window.activity_console.toPlainText())
            self.assertFalse(window.run_footage_button.isEnabled())
            self.assertFalse(window.cancel_tts_button.isEnabled())
            window.close()

    def test_video_builder_analysis_reuses_previous_stage_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Video Story", "video-story", AppSettings()
            )
            for key, content in (
                ("tts_script", b"Test narration"),
                ("audio_file", b"audio"),
                ("subtitle_file", b"subtitle"),
                ("beat_file", b"beats"),
                ("beat_timing_file", b"timing"),
            ):
                path = project.path_for(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            builder_service = FakeVideoBuilderService()
            window = MainWindow(
                FakeAIService(),
                SettingsStore(root / "settings.json", MemorySecretStore()),
                video_builder_service=builder_service,
            )
            window.set_project(project)
            self.wait_for_jobs(window)
            self.assertTrue(window.run_video_builder_button.isEnabled())

            window.run_video_builder_analysis()
            self.wait_for_jobs(window)

            self.assertEqual(window.stage_labels["video_plan"].text(), "Completed")
            self.assertEqual(
                window.stage_metrics["video_plan"].text(), "2 cuts · 1 warning"
            )
            self.assertIn(
                "Reusing validated Beat timing",
                window.activity_console.toPlainText(),
            )
            self.assertTrue(window.run_video_builder_button.isEnabled())
            self.assertEqual(window.run_video_builder_button.text(), "Analyze Again")
            self.assertTrue(window.review_timeline_button.isEnabled())
            self.assertTrue(window.export_video_button.isEnabled())

            with patch(
                "storyflow_studio.desktop.main_window.ExportChoiceDialog"
            ) as dialog_type, patch.object(window, "run_video_render") as render_action:
                dialog_type.return_value.exec.return_value = True
                dialog_type.return_value.choice.return_value = "render"
                window.open_export_dialog()
                render_action.assert_called_once_with()
            with patch(
                "storyflow_studio.desktop.main_window.ExportChoiceDialog"
            ) as dialog_type, patch.object(window, "run_capcut_export") as capcut_action:
                dialog_type.return_value.exec.return_value = True
                dialog_type.return_value.choice.return_value = "capcut"
                window.open_export_dialog()
                capcut_action.assert_called_once_with()

            builder_service.review_stale = True
            window.run_video_render()
            self.wait_for_jobs(window)
            self.assertEqual(builder_service.render_count, 1)
            self.assertTrue(project.path_for("final_video_file").is_file())
            self.assertEqual(window.export_video_button.text(), "Export")
            self.assertIn("Muxing narration", window.activity_console.toPlainText())
            self.assertIn(
                "rendering the saved timeline without Analyze Again",
                window.activity_console.toPlainText(),
            )

            window.run_capcut_export()
            self.wait_for_jobs(window)
            self.assertTrue(project.path_for("capcut_package_dir").is_dir())
            self.assertEqual(window.export_video_button.text(), "Export")
            self.assertIn("CapCut Package:", window.activity_console.toPlainText())

            with patch(
                "storyflow_studio.desktop.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                window.run_video_builder_analysis()
                self.wait_for_jobs(window)
            self.assertEqual(builder_service.replace_flags, [False, True])
            window.close()


if __name__ == "__main__":
    unittest.main()
