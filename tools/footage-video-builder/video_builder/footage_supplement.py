"""Create conservative per-Beat download plans from coverage reports."""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path


PLAN_FIELDS = (
    "recommended_additional_files",
    "target_downloaded_files",
    "min_duration",
    "missing_seconds",
    "target_additional_seconds",
    "required_seconds",
    "available_unique_seconds",
    "download_reason",
)


def coverage_download_request(coverage: dict) -> dict | None:
    """Return one conservative download request for an unhealthy Beat."""
    required = max(0.0, float(coverage.get("required_seconds", 0.0)))
    available = max(
        0.0, float(coverage.get("available_unique_seconds", 0.0))
    )
    cut_count = max(0, int(coverage.get("cut_count", 0)))
    file_count = max(0, int(coverage.get("file_count", 0)))
    longest_required = max(
        0.0, float(coverage.get("longest_required_seconds", 0.0))
    )
    longest_available = max(
        0.0, float(coverage.get("longest_candidate_seconds", 0.0))
    )
    healthy_target = min(required * 1.15, required + 10.0)
    missing = max(0.0, required - available)
    target_missing = max(0.0, healthy_target - available)
    diversity_gap = max(0, min(cut_count, 3) - file_count)
    continuous_gap = longest_available + 0.05 < longest_required
    needs_download = (
        missing > 0.05
        or target_missing > 0.05
        or continuous_gap
    )
    if not needs_download:
        return None
    reasons = []
    if missing > 0.05:
        reasons.append(f"thiếu {missing:.2f}s bắt buộc")
    elif target_missing > 0.05:
        reasons.append(f"thiếu {target_missing:.2f}s dự phòng")
    if diversity_gap:
        reasons.append(f"thiếu {diversity_gap} nguồn hình độc lập")
    if continuous_gap:
        reasons.append("chưa có cảnh liên tục đủ dài")
    # One file per analysis cycle prevents a long, useful stock clip from
    # causing unnecessary additional downloads.
    return {
        "recommended_additional_files": 1,
        "min_duration": int(math.ceil(max(8.0, longest_required + 1.0))),
        "missing_seconds": round(missing, 3),
        "target_additional_seconds": round(target_missing, 3),
        "required_seconds": round(required, 3),
        "available_unique_seconds": round(available, 3),
        "download_reason": "; ".join(reasons) or "nguồn footage mỏng",
    }


def build_supplement_rows(
    footage_rows: list[dict[str, str]],
    coverage_rows: list[dict],
    existing_download_counts: dict[str, int] | None = None,
) -> list[dict[str, str]]:
    coverage_by_code = {
        str(row.get("beat", "")).strip().upper(): row
        for row in coverage_rows
    }
    result = []
    for footage in footage_rows:
        code = str(footage.get("ma_beat", "")).strip().upper()
        request = coverage_download_request(coverage_by_code.get(code, {}))
        if request is None:
            continue
        row = dict(footage)
        current_downloads = (existing_download_counts or {}).get(code, 0)
        request["target_downloaded_files"] = current_downloads + 1
        row.update({key: str(value) for key, value in request.items()})
        result.append(row)
    return result


def write_supplement_plan(
    beats_file: Path, report_file: Path, destination: Path
) -> tuple[Path, list[dict[str, str]]]:
    if not report_file.is_file():
        raise FileNotFoundError(
            "Chưa có report phân tích để xác định footage cần bổ sung."
        )
    with beats_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        footage_rows = [dict(row) for row in reader]
    report = json.loads(report_file.read_text(encoding="utf-8-sig"))
    existing_download_counts: dict[str, int] = {}
    video_dir = beats_file.parent / "video"
    if video_dir.is_dir():
        for path in video_dir.iterdir():
            if not path.is_file():
                continue
            match = re.match(
                r"^(?P<beat>[A-Za-z]+\d+)_(?:PEXELS|PIXABAY)_",
                path.name,
                re.IGNORECASE,
            )
            if match is None:
                continue
            code = match.group("beat").upper()
            existing_download_counts[code] = (
                existing_download_counts.get(code, 0) + 1
            )
    rows = build_supplement_rows(
        footage_rows,
        list(report.get("source_coverage", [])),
        existing_download_counts,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_fields = [*fieldnames, *(f for f in PLAN_FIELDS if f not in fieldnames)]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(rows)
    return destination, rows
