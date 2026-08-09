import csv
import json
import tempfile
import unittest
from pathlib import Path

from video_builder.footage_supplement import (
    build_supplement_rows,
    coverage_download_request,
    write_supplement_plan,
)


class FootageSupplementTests(unittest.TestCase):
    def test_one_file_is_requested_per_analysis_cycle(self) -> None:
        request = coverage_download_request(
            {
                "status": "critical",
                "required_seconds": 30,
                "available_unique_seconds": 8,
                "cut_count": 6,
                "file_count": 1,
                "longest_required_seconds": 7.2,
                "longest_candidate_seconds": 5,
            }
        )

        self.assertIsNotNone(request)
        self.assertEqual(request["recommended_additional_files"], 1)
        self.assertEqual(request["min_duration"], 9)
        self.assertEqual(request["missing_seconds"], 22.0)
        self.assertEqual(request["target_additional_seconds"], 26.5)

    def test_healthy_beat_is_not_added_to_plan(self) -> None:
        rows = build_supplement_rows(
            [{"ma_beat": "B001", "tu_khoa": "sunrise"}],
            [{
                "beat": "B001", "status": "ok",
                "required_seconds": 10, "available_unique_seconds": 12,
                "cut_count": 2, "file_count": 2,
                "longest_required_seconds": 5,
                "longest_candidate_seconds": 6,
            }],
        )
        self.assertEqual(rows, [])

    def test_plan_targets_exactly_one_more_downloaded_asset(self) -> None:
        rows = build_supplement_rows(
            [{"ma_beat": "B001", "tu_khoa": "sunrise"}],
            [{
                "beat": "B001", "status": "warning",
                "required_seconds": 10, "available_unique_seconds": 10,
                "cut_count": 2, "file_count": 1,
                "longest_required_seconds": 5,
                "longest_candidate_seconds": 5,
            }],
            {"B001": 4},
        )
        self.assertEqual(rows[0]["target_downloaded_files"], "5")

    def test_written_plan_keeps_original_dwg_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            beats = root / "script_beat.csv"
            with beats.open("w", encoding="utf-8", newline="") as handle:
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
            report = root / "report.json"
            report.write_text(json.dumps({"source_coverage": [{
                "beat": "B001", "status": "critical",
                "required_seconds": 10, "available_unique_seconds": 0,
                "cut_count": 2, "file_count": 0,
                "longest_required_seconds": 5,
                "longest_candidate_seconds": 0,
            }]}), encoding="utf-8")

            destination, rows = write_supplement_plan(
                beats, report, root / ".cache" / "footage_download_plan.csv"
            )

            self.assertTrue(destination.is_file())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["tranh"], "indoor")


if __name__ == "__main__":
    unittest.main()
