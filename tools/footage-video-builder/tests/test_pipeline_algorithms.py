from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from video_builder.alignment import align_beats_to_script
from video_builder.config import default_config
from video_builder.models import Beat, Candidate, SpeechSegment, WordTiming
from video_builder.low_memory_render import _narration_mux_command
from video_builder.optimization import (
    select_global_timeline,
    transition_penalty,
    violates_recent_visual_reuse,
)
from video_builder.output import (
    _OutputProgressLogger,
    save_report,
    select_render_sections,
)
from video_builder.quality_scoring import (
    _ANALYSIS_CONFIG_FIELDS,
    _load_video_analysis_cache,
    _save_video_analysis_cache,
)
from video_builder.segmentation import cut_duration_cost, group_beats_by_duration
from video_builder.scene_candidates import make_candidates
from video_builder.source_coverage import analyze_source_coverage


def make_beat(number: int, idea: str) -> Beat:
    return Beat(
        number=number,
        code=f"H{number:02d}",
        main_idea=idea,
        keywords=idea,
        desired_visual=idea,
        avoid="",
    )


class AlignmentTests(unittest.TestCase):
    def test_alignment_is_monotonic_and_covers_script(self) -> None:
        clauses = [
            "river strangers appear.",
            "water separates the groups.",
            "chimpanzee patrol begins.",
            "rivals are attacked.",
            "cemetery bones remain.",
            "repeated wounds are visible.",
            "village walls rise.",
            "stored grain changes conflict.",
        ]
        words = " ".join(clauses).split()
        timings = [
            WordTiming(word, float(index), float(index + 1))
            for index, word in enumerate(words)
        ]
        beats = [
            make_beat(1, "river strangers and water"),
            make_beat(2, "chimpanzee patrol attacks rivals"),
            make_beat(3, "cemetery bones show repeated wounds"),
            make_beat(4, "village walls and stored grain"),
        ]

        ranges = align_beats_to_script(timings, beats)

        self.assertEqual(len(ranges), len(beats))
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], len(words))
        self.assertTrue(
            all(
                previous_end == current_start
                for (_, previous_end), (current_start, _) in zip(
                    ranges, ranges[1:]
                )
            )
        )
        for beat, (start, end) in zip(beats, ranges):
            phrase = " ".join(item.word for item in timings[start:end])
            key_word = beat.main_idea.split()[0]
            self.assertIn(key_word, phrase)


class SectionRenderTests(unittest.TestCase):
    def test_low_memory_mux_never_trims_narration_to_video(self) -> None:
        command = _narration_mux_command(
            "ffmpeg",
            Path("concat.txt"),
            Path("narration.wav"),
            Path("output.mp4"),
        )

        self.assertNotIn("-shortest", command)
        audio_map = command.index("-map", command.index("-map") + 1)
        self.assertEqual(command[audio_map + 1], "1:a:0")

    def test_output_logger_emits_frame_percentage(self) -> None:
        logger = _OutputProgressLogger()
        output = StringIO()

        with redirect_stdout(output):
            logger(t__total=100)
            logger(t__index=42)

        self.assertIn("OUTPUT_PROGRESS: 42", output.getvalue())

    def test_multiple_sections_are_rebased_without_gaps(self) -> None:
        beats = [make_beat(index, f"idea {index}") for index in range(1, 4)]
        segments = [
            SpeechSegment(0, (beats[0],), "one", 0.0, 2.0, 1, "A"),
            SpeechSegment(1, (beats[1],), "two", 5.0, 7.0, 2, "B"),
            SpeechSegment(2, (beats[2],), "three", 10.0, 13.0, 3, "C"),
        ]
        candidates = [
            Candidate(index, Path(f"{index}.mp4"), 0, 0, 3, 3)
            for index in range(3)
        ]
        voices = [
            {"start": 0.0, "duration": 5.0},
            {"start": 5.0, "duration": 5.0},
            {"start": 10.0, "duration": 4.0},
        ]

        rebuilt, chosen, ordered = select_render_sections(
            segments, candidates, voices, {1, 3}
        )

        self.assertEqual(ordered, [1, 3])
        self.assertEqual([item.section_index for item in rebuilt], [1, 3])
        self.assertEqual([(item.start, item.end) for item in rebuilt],
                         [(0.0, 2.0), (5.0, 8.0)])
        self.assertEqual([item.candidate_id for item in chosen], [0, 2])

    def test_incomplete_beat_csv_is_rejected(self) -> None:
        covered = [
            "river strangers appear.",
            "chimpanzee patrol begins.",
            "cemetery wounds remain.",
            "lagoon projectiles strike.",
        ]
        trailing = [
            f"unrelated trailing section number {index}."
            for index in range(40)
        ]
        words = " ".join(covered + trailing).split()
        timings = [
            WordTiming(word, float(index), float(index + 1))
            for index, word in enumerate(words)
        ]
        beats = [
            make_beat(1, "river strangers"),
            make_beat(2, "chimpanzee patrol"),
            make_beat(3, "cemetery wounds"),
            make_beat(4, "lagoon projectiles"),
        ]

        with self.assertRaisesRegex(RuntimeError, "chưa bao phủ"):
            align_beats_to_script(timings, beats)


class SegmentationTests(unittest.TestCase):
    def test_default_cut_profile_is_three_four_five(self) -> None:
        config = default_config()

        self.assertEqual(
            (
                config.min_speech_seconds,
                config.target_speech_seconds,
                config.max_speech_seconds,
            ),
            (3.0, 4.0, 5.0),
        )

    def test_long_scene_candidate_can_cover_near_max_cut(self) -> None:
        config = default_config()

        candidates = make_candidates(
            config,
            Path("H01_source.mp4"),
            [(0.0, 10.0)],
            source_duration=10.0,
        )

        self.assertTrue(candidates)
        self.assertTrue(
            all(candidate.duration <= 5.36 for candidate in candidates)
        )
        self.assertTrue(
            all(
                current.start >= previous.end - 1e-6
                for previous, current in zip(candidates, candidates[1:])
            )
        )
        self.assertAlmostEqual(candidates[0].start, 0.0)
        self.assertAlmostEqual(candidates[-1].end, 10.0)

    def test_duration_cost_prefers_below_target_over_near_maximum(self) -> None:
        below_target = cut_duration_cost(3.5, 3.0, 4.0, 5.0)
        above_target = cut_duration_cost(4.8, 3.0, 4.0, 5.0)

        self.assertLess(below_target, above_target)

    def test_long_unsplittable_pause_relaxes_maximum(self) -> None:
        starts = [0.0, 1.0, 2.0, 7.3, 8.3, 9.3, 10.3, 11.3]
        timings = [
            WordTiming(f"word{index}.", start, start + 0.2)
            for index, start in enumerate(starts)
        ]
        beat = make_beat(1, "complete narration")
        config = SimpleNamespace(
            min_speech_seconds=2.0,
            target_speech_seconds=3.0,
            max_speech_seconds=4.0,
        )

        segments = group_beats_by_duration(
            config,
            timings,
            [beat],
            [(0, len(timings))],
            12.3,
        )

        self.assertTrue(segments)
        self.assertEqual(segments[0].start, 0.0)
        self.assertEqual(segments[-1].end, 12.3)
        self.assertLessEqual(max(segment.duration for segment in segments), 4.0)


class SourceCoverageTests(unittest.TestCase):
    def test_insufficient_unique_source_seconds_are_reported(self) -> None:
        beat = make_beat(31, "long narration")
        segments = [
            SpeechSegment(0, (beat,), "one", 0.0, 5.0),
            SpeechSegment(1, (beat,), "two", 5.0, 10.0),
            SpeechSegment(2, (beat,), "three", 10.0, 16.0),
        ]
        path = Path("H31_only-source.mp4")
        candidates = [
            Candidate(0, path, 0, 0.0, 5.0, 9.4),
            Candidate(1, path, 0, 2.5, 7.5, 9.4),
            Candidate(2, path, 0, 4.4, 9.4, 9.4),
        ]

        coverage = analyze_source_coverage(segments, candidates)[0]

        self.assertEqual(coverage["status"], "critical")
        self.assertAlmostEqual(
            coverage["available_unique_seconds"], 9.4
        )
        self.assertAlmostEqual(coverage["required_seconds"], 16.0)
        self.assertEqual(coverage["recommended_additional_files"], 2)


class AllocationReportTests(unittest.TestCase):
    def test_report_explains_borrowed_and_reused_source_region(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = default_config(root)
            beat = make_beat(1, "specific visual")
            segments = [
                SpeechSegment(0, (beat,), "first", 0.0, 3.0),
                SpeechSegment(1, (beat,), "second", 3.0, 6.0),
            ]
            candidate = Candidate(
                0,
                root / "H02_fallback.mp4",
                0,
                1.0,
                5.0,
                10.0,
                quality_score=0.8,
            )
            components = [
                {
                    "cross_beat_fallback": 1.0,
                    "fallback_eligible": 1.0,
                    "semantic_fit_score": 0.3,
                },
                {
                    "cross_beat_fallback": 1.0,
                    "fallback_eligible": 1.0,
                    "semantic_fit_score": 0.3,
                },
            ]

            save_report(
                config,
                segments,
                [candidate, candidate],
                [0.1, 0.1],
                0.2,
                [],
                [
                    {
                        "name": "voice.mp3",
                        "path": root / "voice.mp3",
                        "start": 0.0,
                        "end": 6.0,
                        "duration": 6.0,
                        "srt_path": None,
                    }
                ],
                selected_components=components,
                source_coverage=[
                    {
                        "beat": "H01",
                        "required_seconds": 6.0,
                        "available_unique_seconds": 2.0,
                    }
                ],
            )

            report = json.loads(
                config.report_file.read_text(encoding="utf-8")
            )
            first, second = report["timeline"]
            self.assertEqual(first["allocation_status"], "borrowed_cross_beat")
            self.assertTrue(first["selection_warnings"])
            self.assertEqual(
                second["allocation_status"],
                "forced_early_reuse",
            )
            self.assertTrue(
                any(
                    "tái sử dụng" in warning.lower()
                    for warning in second["selection_warnings"]
                )
            )


def brute_force_timeline(segments, candidates, score_matrix):
    segment_count, candidate_count = score_matrix.shape
    dp = np.full((segment_count, candidate_count), -np.inf, dtype=float)
    previous_choice = np.full(
        (segment_count, candidate_count), -1, dtype=np.int32
    )
    dp[0] = score_matrix[0]
    for segment_index in range(1, segment_count):
        shared = bool(
            {beat.number for beat in segments[segment_index - 1].beats}
            & {beat.number for beat in segments[segment_index].beats}
        )
        for current_index, current in enumerate(candidates):
            values = np.asarray(
                [
                    dp[segment_index - 1, previous_index]
                    - transition_penalty(previous, current, shared)
                    for previous_index, previous in enumerate(candidates)
                ]
            )
            previous_choice[segment_index, current_index] = int(
                np.argmax(values)
            )
            dp[segment_index, current_index] = (
                score_matrix[segment_index, current_index]
                + float(np.max(values))
            )
    choices = [int(np.argmax(dp[-1]))]
    for segment_index in range(segment_count - 1, 0, -1):
        choices.append(int(previous_choice[segment_index, choices[-1]]))
    choices.reverse()
    return choices, float(np.max(dp[-1]))


class TimelineOptimizationTests(unittest.TestCase):
    def test_candidate_ids_are_scoped_to_their_source_file(self) -> None:
        first = Candidate(0, Path("H01_first.mp4"), 0, 0.0, 4.0, 10.0)
        second = Candidate(0, Path("H01_second.mp4"), 0, 0.0, 4.0, 10.0)

        self.assertEqual(transition_penalty(first, second), 0.0)

    def test_adjacent_same_source_must_move_forward(self) -> None:
        beat = make_beat(1, "nature")
        segments = [
            SpeechSegment(0, (beat,), "one", 0.0, 4.0),
            SpeechSegment(1, (beat,), "two", 4.0, 8.0),
        ]
        candidates = [
            Candidate(0, Path("H01_source.mp4"), 0, 0.0, 4.0, 12.0),
            Candidate(1, Path("H01_source.mp4"), 0, 4.5, 9.5, 12.0),
        ]

        self.assertFalse(
            violates_recent_visual_reuse(
                (0,), 1, candidates, 1, segments
            )
        )
        self.assertTrue(
            violates_recent_visual_reuse(
                (1,), 0, candidates, 1, segments
            )
        )

    def test_nearby_overlapping_region_is_a_hard_reuse_violation(self) -> None:
        beat = make_beat(1, "nature")
        segments = [
            SpeechSegment(0, (beat,), "one", 0.0, 5.0),
            SpeechSegment(1, (beat,), "two", 5.0, 10.0),
        ]
        candidates = [
            Candidate(0, Path("B001_source.mp4"), 0, 0.0, 6.0, 17.0),
            Candidate(1, Path("B001_source.mp4"), 0, 1.0, 7.0, 17.0),
            Candidate(2, Path("B001_source.mp4"), 0, 8.0, 14.0, 17.0),
        ]

        self.assertTrue(
            violates_recent_visual_reuse(
                (0,), 1, candidates, 1, segments
            )
        )
        self.assertFalse(
            violates_recent_visual_reuse(
                (0,), 2, candidates, 1, segments
            )
        )

    @staticmethod
    def allocation_components(
        beat_identity: np.ndarray,
        fallback_eligible: np.ndarray | None = None,
    ) -> dict[str, np.ndarray]:
        if fallback_eligible is None:
            fallback_eligible = np.ones_like(beat_identity)
        return {
            "beat_identity_score": beat_identity,
            "fallback_eligible": fallback_eligible,
        }

    def test_matching_source_uses_distinct_regions_before_fallback(self) -> None:
        beat = make_beat(1, "long matching source")
        segments = [
            SpeechSegment(index, (beat,), "text", index * 3, (index + 1) * 3)
            for index in range(3)
        ]
        candidates = [
            Candidate(0, Path("H01_source.mp4"), 0, 0.0, 3.5, 20.0),
            Candidate(1, Path("H01_source.mp4"), 0, 4.0, 7.5, 20.0),
            Candidate(2, Path("H01_source.mp4"), 0, 8.0, 11.5, 20.0),
            Candidate(3, Path("H02_fallback.mp4"), 0, 0.0, 3.5, 20.0),
        ]
        scores = np.asarray(
            [
                [0.50, 0.48, 0.47, 0.46],
                [0.50, 0.48, 0.47, 0.46],
                [0.50, 0.48, 0.47, 0.46],
            ]
        )
        components = self.allocation_components(
            np.asarray([[1.0, 1.0, 1.0, 0.0]] * 3)
        )

        selected, _, _ = select_global_timeline(
            segments,
            candidates,
            scores,
            components,
        )

        self.assertEqual(
            {candidate.candidate_id for candidate in selected},
            {0, 1, 2},
        )
        self.assertTrue(
            all(candidate.path == Path("H01_source.mp4") for candidate in selected)
        )

    def test_overlapping_candidates_are_one_reused_visual_region(self) -> None:
        beat = make_beat(1, "matching source")
        segments = [
            SpeechSegment(index, (beat,), "text", index * 3, (index + 1) * 3)
            for index in range(2)
        ]
        candidates = [
            Candidate(0, Path("H01_source.mp4"), 0, 0.0, 5.0, 20.0),
            Candidate(1, Path("H01_source.mp4"), 0, 1.0, 6.0, 20.0),
            Candidate(2, Path("H01_source.mp4"), 0, 7.0, 12.0, 20.0),
        ]
        scores = np.asarray([[0.60, 0.59, 0.50], [0.60, 0.59, 0.50]])
        components = self.allocation_components(
            np.ones((len(segments), len(candidates)), dtype=float)
        )

        selected, _, _ = select_global_timeline(
            segments,
            candidates,
            scores,
            components,
        )

        self.assertEqual(
            [candidate.candidate_id for candidate in selected],
            [0, 2],
        )

    def test_semantically_ineligible_fallback_is_not_selected(self) -> None:
        beat = make_beat(1, "specific visual")
        segments = [SpeechSegment(0, (beat,), "text", 0.0, 3.0)]
        candidates = [
            Candidate(0, Path("H01_matching.mp4"), 0, 0.0, 3.5, 10.0),
            Candidate(1, Path("H02_wrong.mp4"), 0, 0.0, 3.5, 10.0),
        ]
        scores = np.asarray([[0.40, 0.95]])
        components = self.allocation_components(
            np.asarray([[1.0, 0.0]]),
            np.asarray([[1.0, 0.0]]),
        )

        selected, _, _ = select_global_timeline(
            segments,
            candidates,
            scores,
            components,
        )

        self.assertEqual(selected[0].candidate_id, 0)

    def test_recent_memory_prevents_abab_source_pattern(self) -> None:
        beat = make_beat(31, "long visual beat")
        segments = [
            SpeechSegment(index, (beat,), "text", index * 4, (index + 1) * 4)
            for index in range(4)
        ]
        candidates = [
            Candidate(0, Path("H31_primary.mp4"), 0, 0.0, 5.0, 9.4),
            Candidate(1, Path("H31_primary.mp4"), 0, 4.4, 9.4, 9.4),
            Candidate(2, Path("H30_related.mp4"), 0, 0.0, 5.0, 10.0),
            Candidate(3, Path("H32_related.mp4"), 0, 0.0, 5.0, 10.0),
        ]
        scores = np.asarray(
            [[0.30, 0.29, 0.13, 0.12]] * len(segments)
        )

        selected, _, _ = select_global_timeline(
            segments, candidates, scores
        )

        self.assertEqual(
            [candidate.candidate_id for candidate in selected],
            [0, 2, 3, 1],
        )

    def test_consecutive_cuts_prefer_a_different_footage_file(self) -> None:
        beat = make_beat(1, "same visual idea")
        segments = [
            SpeechSegment(index, (beat,), "text", index * 3, (index + 1) * 3)
            for index in range(2)
        ]
        candidates = [
            Candidate(0, Path("preferred.mp4"), 0, 0, 3.5, 20.0),
            Candidate(1, Path("alternative.mp4"), 0, 0, 3.5, 20.0),
        ]
        scores = np.asarray([[0.9, 0.7], [0.9, 0.7]])

        selected, _, _ = select_global_timeline(
            segments, candidates, scores
        )

        self.assertNotEqual(selected[0].path, selected[1].path)

    def test_short_source_is_avoided_to_prevent_render_loop(self) -> None:
        beat = make_beat(1, "visual idea")
        segments = [SpeechSegment(0, (beat,), "text", 0.0, 4.0)]
        candidates = [
            Candidate(0, Path("short.mp4"), 0, 0, 2.0, 2.0),
            Candidate(1, Path("long.mp4"), 0, 0, 3.5, 10.0),
        ]
        scores = np.asarray([[0.95, 0.70]])

        selected, _, _ = select_global_timeline(
            segments, candidates, scores
        )

        self.assertEqual(selected[0].path, Path("long.mp4"))

    def test_optimized_timeline_reduces_recent_source_reuse(self) -> None:
        beats = [make_beat(index + 1, f"idea {index + 1}") for index in range(4)]
        segments = [
            SpeechSegment(
                index=index,
                beats=(beats[index % len(beats)],),
                text=f"segment {index}",
                start=float(index * 4),
                end=float((index + 1) * 4),
            )
            for index in range(12)
        ]
        candidates = [
            Candidate(
                candidate_id=index,
                path=Path(f"video_{index % 5}.mp4"),
                scene_index=index % 3,
                start=float(index % 7),
                end=float(index % 7 + 3.5),
                source_duration=30.0,
            )
            for index in range(24)
        ]
        scores = np.random.default_rng(20260727).random(
            (len(segments), len(candidates))
        )

        previous_choices, _previous_total = brute_force_timeline(
            segments, candidates, scores
        )
        selected, _, total = select_global_timeline(
            segments, candidates, scores
        )
        selected_choices = [
            candidate.candidate_id for candidate in selected
        ]

        def recent_visual_region_reuse(choices: list[int]) -> int:
            return sum(
                (
                    candidates[current].path
                    == candidates[choices[index - distance]].path
                    and max(
                        0.0,
                        min(
                            candidates[current].end,
                            candidates[choices[index - distance]].end,
                        )
                        - max(
                            candidates[current].start,
                            candidates[choices[index - distance]].start,
                        ),
                    )
                    > 0
                )
                for index, current in enumerate(choices)
                for distance in range(1, min(4, index) + 1)
            )

        self.assertLessEqual(
            recent_visual_region_reuse(selected_choices),
            recent_visual_region_reuse(previous_choices),
        )
        self.assertTrue(np.isfinite(total))


class FootageCacheTests(unittest.TestCase):
    def test_candidate_features_round_trip_without_pickle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "H01_test.mp4"
            video.write_bytes(b"test-video-signature")
            settings = {
                field: 1.0
                for field in _ANALYSIS_CONFIG_FIELDS
            }
            settings["clip_model"] = "test/model"
            config = SimpleNamespace(
                cache_dir=root / ".cache",
                **settings,
            )
            accepted = Candidate(
                candidate_id=0,
                path=video,
                scene_index=2,
                start=1.0,
                end=4.5,
                source_duration=10.0,
                quality_score=0.75,
                feature=np.asarray([0.1, 0.2, 0.3], dtype=np.float32),
                frame_features=np.asarray(
                    [[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]],
                    dtype=np.float32,
                ),
            )
            rejected = Candidate(
                candidate_id=1,
                path=video,
                scene_index=3,
                start=5.0,
                end=8.5,
                source_duration=10.0,
                rejected_reason="too_dark",
            )

            _save_video_analysis_cache(
                config, video, [accepted], [rejected]
            )
            loaded = _load_video_analysis_cache(config, video)

            self.assertIsNotNone(loaded)
            loaded_accepted, loaded_rejected = loaded
            self.assertEqual(len(loaded_accepted), 1)
            self.assertEqual(len(loaded_rejected), 1)
            np.testing.assert_allclose(
                loaded_accepted[0].feature, accepted.feature
            )
            np.testing.assert_allclose(
                loaded_accepted[0].frame_features,
                accepted.frame_features,
            )
            self.assertEqual(
                loaded_rejected[0].rejected_reason, "too_dark"
            )

            video.write_bytes(b"changed-video-signature-with-new-size")
            self.assertIsNone(
                _load_video_analysis_cache(config, video),
                "Footage đã thay đổi phải được phân tích lại.",
            )


if __name__ == "__main__":
    unittest.main()
