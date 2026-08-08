from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem

from video_builder.ui.main_window import (
    MainWindow,
    build_timeline_health_tooltip,
    completion_popup_content,
    footage_search_keywords,
    format_stage_duration,
    inspect_timeline_health,
    preferred_project_voice,
)


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
            (
                arguments[arguments.index("--min-cut-seconds") + 1],
                arguments[arguments.index("--target-cut-seconds") + 1],
                arguments[arguments.index("--max-cut-seconds") + 1],
            ),
            ("3.0", "4.0", "5.0"),
        )

    def test_full_reanalysis_is_explicit_and_forces_cache_refresh(self) -> None:
        arguments = self.window._build_cli_arguments("analyze_force")

        self.assertIn("--analyze-only", arguments)
        self.assertIn("--force-analysis", arguments)

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
