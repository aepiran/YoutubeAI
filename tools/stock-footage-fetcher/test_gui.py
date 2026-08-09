from __future__ import annotations

import os
import sys
import csv
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from gui_dialogs import SettingsDialog
from gui_main_window import MainWindow
from gui_runner import WorkerRunner
from gui_settings import GuiSettings


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_loads_prayer_csv(self) -> None:
        window = MainWindow(initial_project=str(ROOT / "sample-prayer-script_beat.csv"))
        self.assertEqual(window.queue_table.rowCount(), 1)
        self.assertEqual(window.queue_table.item(0, 1).text(), "H01")
        self.assertEqual(window.csv_chip.text(), "1 Beat")
        window.close()

    def test_settings_dialog_round_trip(self) -> None:
        source = GuiSettings(use_pexels=True, use_pixabay=False, max_queries=3)
        dialog = SettingsDialog(source, "pexels", "", None)
        settings, pexels, pixabay = dialog.values()
        self.assertTrue(settings.use_pexels)
        self.assertFalse(settings.use_pixabay)
        self.assertEqual(settings.max_queries, 3)
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
        QCoreApplication.processEvents()
        self.assertEqual(spy.count(), 2)
        self.assertEqual(spy.at(0), ["H01", "Ranked 12"])
        self.assertEqual(spy.at(1), ["H01", "Downloaded"])

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

            window = MainWindow(initial_project=str(plan))
            self.assertEqual(window.project_dir, project.resolve())
            window.close()


if __name__ == "__main__":
    unittest.main()
