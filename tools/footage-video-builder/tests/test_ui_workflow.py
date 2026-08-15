from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem

from video_builder.config import default_config
from video_builder.ui.settings_dialog import BuilderUiSettings, SettingsDialog
from video_builder.ui.main_window import (
    ANALYSIS_STAGE_MODES,
    MainWindow,
    build_timeline_health_tooltip,
    completion_popup_content,
    footage_search_keywords,
    format_stage_duration,
    inspect_timeline_health,
    preferred_capcut_template,
    preferred_project_voice,
)

REFRESH_START_ENABLED = MainWindow._refresh_start_enabled


class PreferredVoiceTests(unittest.TestCase):
    def test_project_voice_prefers_audio_001_mp3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "audio"
            legacy = root / "voice"
            audio.mkdir()
            legacy.mkdir()
            preferred = audio / "001.mp3"
            preferred.write_bytes(b"audio")
            (legacy / "001.mp3").write_bytes(b"legacy")

            self.assertEqual(preferred_project_voice(root), preferred.resolve())

    def test_current_capcut_template_wins_over_stale_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "DWG_Template"
            stale = root / "DWG_Master_Template"
            selected.mkdir()
            stale.mkdir()

            result = preferred_capcut_template(
                str(selected), {"template": str(stale)}
            )

            self.assertEqual(result, selected)


class TimelineHealthTests(unittest.TestCase):
    def test_reverse_source_time_tooltip_explains_visual_fix(self) -> None:
        tooltip = build_timeline_health_tooltip(
            ["Footage ở Cut kế tiếp bị nhảy ngược thời gian"]
        )

        self.assertIn("footage khác cùng mã Beat", tooltip)
        self.assertIn("sau điểm kết thúc của Cut trước", tooltip)
        self.assertIn("audio không bị cắt", tooltip)

    def test_each_warning_has_its_own_resolution(self) -> None:
        tooltip = build_timeline_health_tooltip(
            [
                "Footage thiếu 2.00s; phải giữ/kéo khung cuối",
                "Điểm phù hợp rất thấp (0.210)",
            ],
            "H31",
        )

        self.assertIn("BEAT H31", tooltip)
        self.assertEqual(tooltip.count("Cách xử lý:"), 2)
        self.assertIn("footage đủ dài", tooltip)
        self.assertIn("đúng mã Beat", tooltip)

    def test_tooltip_explains_required_duration_and_visual(self) -> None:
        tooltip = build_timeline_health_tooltip(
            ["Nguồn: Thiếu 4.00s footage độc lập"],
            "H31",
            coverage={
                "required_seconds": 16.0,
                "available_unique_seconds": 12.0,
                "file_count": 1,
                "recommended_additional_files": 2,
                "longest_required_seconds": 5.8,
            },
            beat_details={
                "desired_visual": "A researcher searching a dark cave",
                "main_idea": "The search for evidence",
                "keywords": "researcher, cave, flashlight",
                "avoid": "cartoon",
            },
        )

        self.assertIn("Thiếu tối thiểu: 4.00s", tooltip)
        self.assertIn("5.80–7.00s", tooltip)
        self.assertIn("ít nhất 2 file", tooltip)
        self.assertIn("researcher, cave, flashlight", tooltip)
        self.assertIn("Cần tránh: cartoon", tooltip)

    def test_search_keywords_are_copy_ready(self) -> None:
        self.assertEqual(
            footage_search_keywords(
                {
                    "keywords": "researcher, cave, flashlight",
                    "desired_visual": "A dark cave search",
                }
            ),
            "researcher, cave, flashlight",
        )
        self.assertEqual(
            footage_search_keywords(
                {"keywords": "", "desired_visual": "A dark cave search"}
            ),
            "A dark cave search",
        )

    def test_short_low_quality_repeated_footage_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            footage = Path(temporary) / "source.mp4"
            footage.write_bytes(b"fixture")
            common = {
                "footage": str(footage),
                "source_duration": 10.0,
                "quality": {
                    "quality_score": 0.75,
                    "shake": 0.01,
                    "black_fraction": 0.1,
                },
                "relevance_score": 0.32,
                "selection_reason": "matching_beat",
            }
            timeline = [
                {
                    **common,
                    "timeline_start": 0.0,
                    "timeline_end": 3.0,
                    "visual_start": 0.0,
                    "visual_end": 3.0,
                    "source_start": 0.0,
                    "source_end": 3.0,
                },
                {
                    **common,
                    "timeline_start": 3.0,
                    "timeline_end": 6.0,
                    "visual_start": 3.0,
                    "visual_end": 6.0,
                    "source_start": 0.0,
                    "source_end": 1.0,
                    "quality": {
                        "quality_score": 0.45,
                        "shake": 0.03,
                        "black_fraction": 0.1,
                    },
                    "relevance_score": 0.25,
                },
            ]

            health = inspect_timeline_health(timeline)

        self.assertEqual(health[0]["severity"], "ok")
        self.assertEqual(health[1]["severity"], "critical")
        self.assertTrue(
            any("thiếu" in warning.lower() for warning in health[1]["warnings"])
        )
        self.assertTrue(
            any("lặp" in warning.lower() for warning in health[1]["warnings"])
        )

    def test_healthy_cut_has_no_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            footage = Path(temporary) / "source.mp4"
            footage.write_bytes(b"fixture")
            health = inspect_timeline_health(
                [
                    {
                        "footage": str(footage),
                        "timeline_start": 0.0,
                        "timeline_end": 3.0,
                        "visual_start": 0.0,
                        "visual_end": 3.0,
                        "source_start": 2.0,
                        "source_end": 5.0,
                        "source_duration": 10.0,
                        "quality": {
                            "quality_score": 0.75,
                            "shake": 0.01,
                            "black_fraction": 0.1,
                        },
                        "relevance_score": 0.32,
                        "selection_reason": "matching_beat",
                    }
                ]
            )

        self.assertEqual(health, [{"severity": "ok", "warnings": []}])


class WorkflowUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        patches = [
            patch.object(MainWindow, "_restore_settings"),
            patch.object(MainWindow, "_refresh_project_summary"),
            patch.object(MainWindow, "_load_project_stage_state"),
            patch.object(MainWindow, "_refresh_beat_table"),
            patch.object(MainWindow, "_refresh_start_enabled"),
        ]
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        for item in patches:
            item.start()
        self.window = MainWindow()
        self.addCleanup(self.window.close)

    def test_ui_exposes_one_complete_script_workflow(self) -> None:
        arguments = self.window._build_cli_arguments("analyze")

        self.assertFalse(hasattr(self.window, "section_table"))
        self.assertFalse(hasattr(self.window, "analyze_section_btn"))
        self.assertNotIn("--analyze-section", arguments)
        self.assertIn("--analyze-only", arguments)
        self.assertNotIn("--force-analysis", arguments)
        self.assertEqual(
            self.window.start_btn.text(),
            "◆  Phân tích kịch bản",
        )
        self.assertFalse(hasattr(self.window, "workflow_scope_label"))
        self.assertFalse(hasattr(self.window, "selection_summary_label"))
        self.assertEqual(
            self.window.find_footage_btn.text(),
            "Tìm footage",
        )
        self.assertEqual(
            self.window.find_footage_btn.accessibleName(),
            "Tìm footage",
        )
        self.assertFalse(self.window.find_footage_btn.icon().isNull())
        self.assertEqual(
            (
                arguments[arguments.index("--min-cut-seconds") + 1],
                arguments[arguments.index("--target-cut-seconds") + 1],
                arguments[arguments.index("--max-cut-seconds") + 1],
            ),
            ("3.0", "4.0", "5.0"),
        )

    def test_find_footage_is_independent_from_supplement_state(self) -> None:
        self.window._running = False
        with patch.object(self.window, "_are_inputs_ready", return_value=False):
            REFRESH_START_ENABLED(self.window)

        self.assertTrue(self.window.find_footage_btn.isEnabled())
        self.assertFalse(self.window.supplement_btn.isEnabled())

        self.window._set_running_ui_state(True)

        self.assertTrue(self.window.find_footage_btn.isEnabled())
        self.assertFalse(self.window.supplement_btn.isEnabled())

    def test_find_footage_opens_standalone_finder_without_analysis(self) -> None:
        self.window.project_edit.clear()
        with patch(
            "video_builder.ui.main_window.QProcess.startDetached",
            return_value=(True, 1234),
        ) as start_detached:
            self.window.find_footage_btn.click()

        start_detached.assert_called_once()
        arguments = start_detached.call_args.args[1]
        self.assertNotIn("--project", arguments)

    def test_packaged_find_footage_uses_embedded_app_mode(self) -> None:
        self.window.project_edit.setText("D:/projects/prayer")
        with (
            patch(
                "video_builder.ui.main_window.sys.frozen",
                True,
                create=True,
            ),
            patch(
                "video_builder.ui.main_window.sys.executable",
                "D:/apps/FootageVideoBuilder/FootageVideoBuilder.exe",
            ),
            patch(
                "video_builder.ui.main_window.QProcess.startDetached",
                return_value=(True, 1234),
            ) as start_detached,
        ):
            self.window.find_footage_btn.click()

        program, arguments, working_directory = start_detached.call_args.args
        self.assertEqual(
            program,
            "D:/apps/FootageVideoBuilder/FootageVideoBuilder.exe",
        )
        self.assertEqual(
            arguments,
            ["--stock-footage-app", "--project", "D:\\projects\\prayer"],
        )
        self.assertEqual(
            Path(working_directory),
            Path("D:/apps/FootageVideoBuilder"),
        )

    def test_full_reanalysis_is_explicit_and_forces_cache_refresh(self) -> None:
        arguments = self.window._build_cli_arguments("analyze_force")

        self.assertIn("--analyze-only", arguments)
        self.assertIn("--force-analysis", arguments)

    def test_analysis_stage_modes_use_stage_argument(self) -> None:
        expected = {
            "stage_input": "input",
            "stage_timing": "timing",
            "stage_footage": "footage",
            "stage_match": "match",
        }

        for mode, stage in expected.items():
            with self.subTest(mode=mode):
                arguments = self.window._build_cli_arguments(mode)
                self.assertIn("--analysis-stage", arguments)
                self.assertEqual(
                    arguments[arguments.index("--analysis-stage") + 1],
                    stage,
                )
                self.assertNotIn("--analyze-only", arguments)

    def test_analysis_stage_checkboxes_expose_four_stages(self) -> None:
        labels = [
            checkbox.text()
            for checkbox in self.window.analysis_stage_checks.values()
        ]

        self.assertEqual(len(labels), 4)
        self.assertTrue(any("1." in label for label in labels))
        self.assertTrue(any("4." in label for label in labels))

    def test_completed_analysis_stage_checkbox_is_green_and_checked(self) -> None:
        self.window._set_stage_status(0, "done")
        checkbox = self.window.analysis_stage_checks["stage_input"]

        self.assertTrue(checkbox.isChecked())
        self.assertIn("#86efac", checkbox.styleSheet())

    def test_analysis_stage_checkbox_click_starts_stage(self) -> None:
        with patch.object(self.window, "_start_build") as start_build:
            self.window.analysis_stage_checks["stage_timing"].click()

        start_build.assert_called_once_with("stage_timing")

    def test_stage_completion_popup_content(self) -> None:
        for mode in ANALYSIS_STAGE_MODES:
            with self.subTest(mode=mode):
                title, message = completion_popup_content(mode)
                self.assertIn("Giai", title)
                self.assertIn("xong", message)

    def test_full_reanalysis_requires_confirmation(self) -> None:
        with (
            patch.object(self.window, "_start_build") as start_build,
            patch(
                "video_builder.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ),
        ):
            self.window._confirm_full_reanalysis()
            start_build.assert_not_called()

        with (
            patch.object(self.window, "_start_build") as start_build,
            patch(
                "video_builder.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            self.window._confirm_full_reanalysis()
            start_build.assert_called_once_with("analyze_force")

    def test_analysis_prompt_uses_resume_start_cancel_labels(self) -> None:
        class FakeMessageBox:
            ButtonRole = QMessageBox.ButtonRole
            click_label = "Start"
            last = None

            def __init__(self, _parent=None) -> None:
                self.buttons = {}
                self.default_button = None
                FakeMessageBox.last = self

            def setWindowTitle(self, title: str) -> None:
                self.title = title

            def setText(self, text: str) -> None:
                self.text = text

            def setInformativeText(self, text: str) -> None:
                self.informative_text = text

            def addButton(self, label: str, _role) -> str:
                self.buttons[label] = label
                return label

            def setDefaultButton(self, button: str) -> None:
                self.default_button = button

            def exec(self) -> None:
                return None

            def clickedButton(self) -> str:
                return self.buttons[self.click_label]

            @staticmethod
            def warning(*_args, **_kwargs) -> None:
                return None

        with (
            patch("video_builder.ui.main_window.QMessageBox", FakeMessageBox),
            patch.object(self.window, "_start_build") as start_build,
        ):
            self.window._prompt_analysis_action()

        self.assertEqual(
            list(FakeMessageBox.last.buttons),
            ["Resume", "Start", "Cancel"],
        )
        self.assertEqual(FakeMessageBox.last.default_button, "Resume")
        start_build.assert_called_once_with("analyze_force")

    def test_technical_details_are_open_by_default(self) -> None:
        self.assertFalse(self.window.stage_table.isHidden())
        self.assertFalse(self.window.log_view.isHidden())

    def test_stage_table_exposes_elapsed_time_and_eta(self) -> None:
        self.assertEqual(self.window.stage_table.columnCount(), 4)
        self.assertEqual(format_stage_duration(5.2), "5s")
        self.assertEqual(format_stage_duration(65), "1m 05s")
        self.window._stage_estimates_seconds[0] = 20.0
        self.window._set_stage_status(0, "waiting")
        self.assertEqual(
            self.window.stage_table.item(0, 3).text(),
            "Ước tính 20s",
        )

    def test_stage_markers_start_and_finish_exact_stage(self) -> None:
        self.window._track_stage_from_log("STAGE_START:CUT")

        self.assertEqual(self.window._stage_statuses[0], "done")
        self.assertEqual(self.window._stage_statuses[1], "done")
        self.assertEqual(self.window._stage_statuses[2], "running")
        self.assertEqual(self.window._stage_statuses[3], "waiting")

        self.window._track_stage_from_log("STAGE_END:CUT")

        self.assertEqual(self.window._stage_statuses[2], "done")
        self.assertEqual(self.window._stage_statuses[3], "waiting")
        self.assertEqual(self.window._stage_progress[2], 100)

    def test_completion_popups_cover_all_user_workflows(self) -> None:
        expected = {
            "analyze": ("Phân tích hoàn tất", "cập nhật Timeline"),
            "analyze_force": ("Phân tích hoàn tất", "cập nhật Timeline"),
            "render": ("Tạo video hoàn tất", "output.mp4"),
            "export_scenes": ("Xuất video hoàn tất", "selected_scenes"),
            "export_capcut": ("Xuất CapCut hoàn tất", "capcut_package"),
        }
        for mode, (expected_title, expected_detail) in expected.items():
            with self.subTest(mode=mode):
                title, message = completion_popup_content(
                    mode, expected_detail
                )
                self.assertEqual(title, expected_title)
                self.assertIn(expected_detail, message)

    def test_process_finish_shows_popup_only_after_success(self) -> None:
        self.window._run_mode = "render"
        self.window.output_edit.setText("output.mp4")
        with (
            patch.object(self.window, "_save_project_stage_state"),
            patch(
                "video_builder.ui.main_window.QMessageBox.information"
            ) as information,
        ):
            self.window._on_process_finished(
                0, QProcess.ExitStatus.NormalExit
            )
            information.assert_called_once()
            information.reset_mock()

            self.window._on_process_finished(
                1, QProcess.ExitStatus.NormalExit
            )
            information.assert_not_called()

    def test_capcut_export_arguments_include_template_and_drafts_root(self) -> None:
        self.window._capcut_output_dir = Path("capcut_package")
        self.window._capcut_template_dir = Path("template_draft")
        self.window._capcut_drafts_root = Path("capcut_drafts")
        self.window._capcut_draft_name = "NewDraft"

        arguments = self.window._build_cli_arguments("export_capcut")

        self.assertIn("--capcut-template-dir", arguments)
        self.assertIn("template_draft", arguments)
        self.assertIn("--capcut-drafts-root", arguments)
        self.assertIn("capcut_drafts", arguments)
        self.assertIn("--capcut-draft-name", arguments)
        self.assertIn("NewDraft", arguments)
        self.assertIn("--caption-max-lines", arguments)
        self.assertEqual(
            arguments[arguments.index("--caption-max-lines") + 1], "4"
        )
        self.assertIn("--caption-max-characters-per-line", arguments)
        self.assertEqual(
            arguments[
                arguments.index("--caption-max-characters-per-line") + 1
            ],
            "14",
        )

    def test_capcut_export_accepts_two_digit_characters_per_line(self) -> None:
        self.window.builder_settings = replace(
            self.window.builder_settings,
            caption_max_characters_per_line=16,
        )

        arguments = self.window._build_cli_arguments("export_capcut")

        self.assertEqual(
            arguments[
                arguments.index("--caption-max-characters-per-line") + 1
            ],
            "16",
        )

    def test_minimum_video_minutes_accepts_two_decimals(self) -> None:
        dialog = SettingsDialog(
            default_config(),
            BuilderUiSettings(minimum_video_minutes=25.12),
        )
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.minimum_video_spin.decimals(), 2)
        self.assertAlmostEqual(dialog.minimum_video_spin.value(), 25.12)
        self.assertAlmostEqual(
            dialog.values.minimum_video_minutes,
            25.12,
        )

    def test_settings_can_delete_imported_capcut_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / "capcut_templates"
            template = library / "DWG_Template"
            template.mkdir(parents=True)
            (template / "draft_content.json").write_text("{}", encoding="utf-8")

            with patch.object(
                SettingsDialog,
                "_template_library_dir",
                return_value=library,
            ):
                dialog = SettingsDialog(
                    default_config(),
                    BuilderUiSettings(capcut_template_dir=str(template)),
                )
                self.addCleanup(dialog.close)

                with patch(
                    "video_builder.ui.settings_dialog.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ):
                    dialog._delete_capcut_template()

            self.assertFalse(template.exists())
            self.assertEqual(dialog._selected_template_path(), "")

    def test_capcut_template_actions_are_icon_buttons_with_tooltips(self) -> None:
        dialog = SettingsDialog(default_config(), BuilderUiSettings())
        self.addCleanup(dialog.close)

        buttons = [
            (dialog.capcut_import_btn, "Import template"),
            (dialog.capcut_delete_btn, "Xóa template"),
            (dialog.capcut_apply_btn, "Apply mặc định"),
        ]
        for button, name in buttons:
            with self.subTest(name=name):
                self.assertEqual(button.accessibleName(), name)
                self.assertEqual(button.text(), "")
                self.assertFalse(button.icon().isNull())
                self.assertTrue(button.toolTip())

    def test_beat_table_names_audio_and_footage_timelines(self) -> None:
        self.assertEqual(
            self.window.beat_table.horizontalHeaderItem(2).text(),
            "Audio/Video",
        )
        self.assertEqual(
            self.window.beat_table.horizontalHeaderItem(4).text(),
            "Footage gốc",
        )
        self.assertIn(
            "timeline video",
            self.window.beat_table.horizontalHeaderItem(2).toolTip(),
        )
        self.assertIn(
            "footage gốc",
            self.window.beat_table.horizontalHeaderItem(4).toolTip(),
        )

    def test_beat_and_status_columns_are_fixed_without_horizontal_scroll(self) -> None:
        frozen = self.window.frozen_beat_table

        self.assertEqual(frozen.horizontalHeaderItem(0).text(), "Beat")
        self.assertEqual(frozen.horizontalHeaderItem(1).text(), "Kiểm tra")
        self.assertEqual(
            frozen.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertEqual(frozen.minimumWidth(), frozen.maximumWidth())

    def test_beat_code_cell_tracks_analysis_state_colors(self) -> None:
        self.window.frozen_beat_table.setRowCount(1)
        self.window.frozen_beat_table.setItem(
            0, 0, QTableWidgetItem("H01")
        )
        self.window.frozen_beat_table.setItem(
            0, 1, QTableWidgetItem("Đang chờ")
        )
        self.window._beat_rows = {"H01": 0}

        expected = {
            "running": "#3b2a74",
            "done": "#14532d",
            "error": "#5f1f1f",
        }
        for style, color in expected.items():
            self.window._set_beat_status("H01", style, style)
            code_item = self.window.frozen_beat_table.item(0, 0)
            self.assertEqual(code_item.background().color().name(), color)
            self.assertEqual(code_item.text(), "H01")


if __name__ == "__main__":
    unittest.main()
