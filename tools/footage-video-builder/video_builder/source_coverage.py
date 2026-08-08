"""Measure whether each visual Beat has enough unique footage to cover it."""

from __future__ import annotations

from collections import defaultdict

from .inputs import filename_beat_code, normalize_beat_code
from .models import Candidate, SpeechSegment


def _merged_interval_duration(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    total = 0.0
    start, end = sorted(intervals)[0]
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start <= end + 0.05:
            end = max(end, next_end)
        else:
            total += max(0.0, end - start)
            start, end = next_start, next_end
    return total + max(0.0, end - start)


def analyze_source_coverage(
    segments: list[SpeechSegment],
    candidates: list[Candidate],
) -> list[dict]:
    """Build a serializable per-Beat source-capacity report."""
    required_seconds: dict[int, float] = defaultdict(float)
    required_cuts: dict[int, int] = defaultdict(int)
    beat_codes: dict[int, str] = {}
    number_by_code: dict[str, int] = {}
    for segment in segments:
        for beat in segment.beats:
            beat_codes[beat.number] = beat.code
            number_by_code[normalize_beat_code(beat.code)] = beat.number
            required_seconds[beat.number] += segment.duration
            required_cuts[beat.number] += 1

    intervals: dict[int, dict[object, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    longest_candidate: dict[int, float] = defaultdict(float)
    known_codes = set(number_by_code)
    for candidate in candidates:
        beat_code = filename_beat_code(candidate.path, known_codes)
        beat_number = number_by_code.get(beat_code or "")
        if beat_number is None:
            continue
        intervals[beat_number][candidate.path].append(
            (candidate.start, candidate.end)
        )
        longest_candidate[beat_number] = max(
            longest_candidate[beat_number], candidate.duration
        )

    rows = []
    for beat_number in sorted(required_seconds):
        required = required_seconds[beat_number]
        paths = intervals.get(beat_number, {})
        available = sum(
            _merged_interval_duration(path_intervals)
            for path_intervals in paths.values()
        )
        file_count = len(paths)
        cut_count = required_cuts[beat_number]
        longest_required = max(
            (
                segment.duration
                for segment in segments
                if any(beat.number == beat_number for beat in segment.beats)
            ),
            default=0.0,
        )
        ratio = available / max(required, 0.001)
        healthy_target = min(required * 1.15, required + 10.0)
        warnings = []
        if not paths:
            status = "critical"
            warnings.append("Không có footage đạt chất lượng cho Beat")
        elif available + 0.05 < required:
            status = "critical"
            warnings.append(
                f"Thiếu {required - available:.2f}s footage độc lập"
            )
        elif ratio < 1.15:
            status = "warning"
            warnings.append("Footage chỉ vừa đủ, không có vùng dự phòng")
        else:
            status = "ok"
        if file_count < min(2, cut_count) and cut_count > 1:
            if status == "ok":
                status = "warning"
            warnings.append(
                f"Chỉ có {file_count} file cho {cut_count} Cut; dễ lặp cảnh"
            )
        if paths and longest_candidate[beat_number] + 0.05 < longest_required:
            if status == "ok":
                status = "warning"
            warnings.append(
                "Không có cảnh liên tục đủ dài cho Cut dài nhất"
            )
        rows.append(
            {
                "beat": beat_codes.get(beat_number, f"H{beat_number:02d}"),
                "beat_number": beat_number,
                "status": status,
                "required_seconds": round(required, 6),
                "available_unique_seconds": round(available, 6),
                "coverage_ratio": round(ratio, 6),
                "target_seconds": round(healthy_target, 6),
                "missing_seconds": round(max(0.0, required - available), 6),
                "target_additional_seconds": round(
                    max(0.0, healthy_target - available), 6
                ),
                "cut_count": cut_count,
                "file_count": file_count,
                "longest_required_seconds": round(longest_required, 6),
                "longest_candidate_seconds": round(
                    longest_candidate[beat_number], 6
                ),
                "recommended_additional_files": max(
                    0, min(cut_count, 3) - file_count
                ),
                "warnings": warnings,
            }
        )
    return rows


def print_source_coverage(rows: list[dict]) -> None:
    print("Kiểm tra độ phủ Footage theo Beat:")
    for row in rows:
        detail = "; ".join(row["warnings"]) or "đủ nguồn"
        print(
            f"  SOURCE_COVERAGE: {row['beat']} | {row['status']} | "
            f"cần={row['required_seconds']:.2f}s | "
            f"có={row['available_unique_seconds']:.2f}s | "
            f"{row['file_count']} file/{row['cut_count']} Cut | {detail}"
        )
