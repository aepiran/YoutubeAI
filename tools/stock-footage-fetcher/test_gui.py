from __future__ import annotations

import os
import sys
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from gui_dialogs import SettingsDialog
from gui_main_window import MainWindow
from gui_runner import WorkerRunner
from gui_settings import GuiSettings, model_cache_dir


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_loads_prayer_csv(self) -> None:
        with patch("gui_main_window.save_settings"):
            window = MainWindow(initial_project=str(ROOT / "sample-prayer-footage.csv"))
            self.assertEqual(window.queue_table.rowCount(), 1)
            self.assertEqual(window.queue_table.item(0, 1).text(), "H01")
            self.assertEqual(window.csv_chip.text(), "1 Beat")
            self.assertEqual(
                window.archive_button.text(), "Bổ sung vào kho footage"
            )
            window.close()

    def test_settings_dialog_round_trip(self) -> None:
        source = GuiSettings(
            use_pexels=True,
            use_pixabay=False,
            max_queries=3,
            library_dir="D:/FootageLibrary",
            model_cache_dir="D:/AI-CACHE/huggingface/hub",
        )
        dialog = SettingsDialog(source, "pexels", "", None)
        settings, pexels, pixabay = dialog.values()
        self.assertTrue(settings.use_pexels)
        self.assertFalse(settings.use_pixabay)
        self.assertEqual(settings.max_queries, 3)
        self.assertTrue(settings.use_local_library)
        self.assertTrue(settings.auto_archive_library)
        self.assertEqual(settings.library_dir, "D:/FootageLibrary")
        self.assertEqual(settings.model_cache_dir, "D:/AI-CACHE/huggingface/hub")
        self.assertEqual(pexels, "pexels")
        self.assertEqual(pixabay, "")
        dialog.close()

    def test_dwg_recommended_button_applies_balanced_search_profile(self) -> None:
        dialog = SettingsDialog(GuiSettings(), "pexels", "pixabay", None)
        dialog.recommended_btn.click()
        settings, _, _ = dialog.values()

        self.assertTrue(settings.use_pexels)
        self.assertTrue(settings.use_pixabay)
        self.assertEqual(settings.max_queries, 3)
        self.assertEqual(settings.max_pages, 3)
        self.assertEqual(settings.candidate_pool, 40)
        self.assertEqual(settings.shortlist, 12)
        self.assertEqual(settings.min_duration, 8.0)
        self.assertEqual(settings.min_score, 0.16)
        self.assertEqual(settings.max_pixabay_downloads, 50)
        dialog.close()

    def test_runner_parses_worker_status_lines(self) -> None:
        runner = WorkerRunner()
        spy = QSignalSpy(runner.beat_status)
        runner._process_line("H01: ranked 12 candidates")
        runner._process_line("H01: downloaded H01_PEXELS_42.mp4")
        runner._process_line("H02: reused H02_PIXABAY_99.mp4")
        QCoreApplication.processEvents()
        self.assertEqual(spy.count(), 3)
        self.assertEqual(spy.at(0), ["H01", "Ranked 12"])
        self.assertEqual(spy.at(1), ["H01", "Downloaded"])
        self.assertEqual(spy.at(2), ["H02", "Reused"])

    def test_packaged_model_cache_uses_shared_app_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_root = Path(temporary) / "FootageVideoBuilder"
            executable = app_root / "FootageVideoBuilder.exe"
            expected = app_root / ".cache" / "huggingface" / "hub"

            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(executable)),
            ):
                self.assertEqual(model_cache_dir(), expected)
                self.assertTrue(expected.is_dir())

    def test_configured_model_cache_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            configured = Path(temporary) / "models"
            settings = GuiSettings(model_cache_dir=str(configured))

            self.assertEqual(model_cache_dir(settings), configured)
            self.assertTrue(configured.is_dir())

    def test_supplement_plan_uses_parent_project_not_cache_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            cache = project / ".cache"
            cache.mkdir()
            plan = cache / "footage_download_plan.csv"
            with plan.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "ma_beat", "y_chinh", "tu_khoa",
                        "hinh_can_tim", "tranh",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "ma_beat": "B001", "y_chinh": "peace",
                    "tu_khoa": "sunrise", "hinh_can_tim": "nature",
                    "tranh": "indoor",
                })

            with patch("gui_main_window.save_settings"):
                window = MainWindow(initial_project=str(plan))
                self.assertEqual(window.project_dir, project.resolve())
                window.close()


if __name__ == "__main__":
    unittest.main()
