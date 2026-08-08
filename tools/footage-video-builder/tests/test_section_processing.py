from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


from video_builder.config import default_config
from video_builder.models import Beat, ScriptSection
from video_builder.section_processing import (
    assign_beats_to_sections,
    build_section_segments,
    create_cached_section_timings,
    select_beats_for_sections,
)
from video_builder.script_overview import create_script_overview


def beat(number: int, section: str) -> Beat:
    return Beat(
        number=number,
        code=f"H{number:02d}",
        main_idea=f"section {number} narration",
        keywords=f"section {number}",
        desired_visual=f"visual {number}",
        avoid="",
        section=section,
    )


class SectionProcessingTests(unittest.TestCase):
    def test_section_preview_ignores_unrelated_incomplete_sections(self) -> None:
        sections = [
            ScriptSection(1, "HOOK", "Hook narration."),
            ScriptSection(2, "BODY", "Body narration."),
            ScriptSection(3, "END", "Ending narration."),
        ]
        beats = [
            beat(1, "HOOK"),
            Beat(
                number=2,
                code="H02",
                main_idea="unfinished later beat",
                keywords="later",
                desired_visual="later visual",
                avoid="",
                section="",
            ),
        ]

        selected = select_beats_for_sections(
            sections, beats, {1}
        )

        self.assertEqual([item.code for item in selected], ["H01"])

    def test_section_preview_auto_maps_legacy_beats(self) -> None:
        sections = [
            ScriptSection(
                1, "HOOK", "Ancient city rises beside the river."
            ),
            ScriptSection(
                2, "BODY", "Modern railway workers build steel bridges."
            ),
        ]
        beats = [
            Beat(
                1, "H01", "ancient city", "city, river",
                "ancient city beside a river", "", "",
            ),
            Beat(
                2, "H02", "railway workers", "railway, bridge",
                "workers building a steel bridge", "", "",
            ),
        ]

        selected = select_beats_for_sections(sections, beats, {1})

        self.assertIn("H01", [item.code for item in selected])

    def test_whole_script_overview_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = default_config(Path(temporary))
            sections = [
                ScriptSection(1, "HOOK", "A city wakes before sunrise."),
                ScriptSection(2, "BODY", "Workers build the railway."),
            ]
            beats = [
                beat(1, "HOOK"),
                Beat(
                    number=2,
                    code="H02",
                    main_idea="railway construction",
                    keywords="workers, railway",
                    desired_visual="workers building a railway",
                    avoid="",
                    section="BODY",
                ),
            ]
            script = "\n\n".join(item.text for item in sections)

            first = create_script_overview(
                config, script, sections, beats
            )
            second = create_script_overview(
                config, script, sections, beats
            )

            self.assertEqual(first["cache_status"], "analyzed")
            self.assertEqual(second["cache_status"], "cached")
            self.assertEqual(second["section_count"], 2)
            self.assertIn("railway", second["semantic_prompt"])

    def test_explicit_csv_section_mapping(self) -> None:
        sections = [
            ScriptSection(1, "HOOK", "Hook narration here."),
            ScriptSection(2, "BODY", "Body narration here."),
        ]
        beats = [beat(1, "HOOK"), beat(2, "2")]

        assigned = assign_beats_to_sections(sections, [], beats)

        self.assertEqual([item.code for item in assigned[1]], ["H01"])
        self.assertEqual([item.code for item in assigned[2]], ["H02"])

    def test_section_alignment_cache_and_local_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = default_config(root)
            voices = []
            cursor = 0.0
            for index, duration in enumerate((3.0, 4.0), start=1):
                path = root / f"{index:03d}.mp3"
                path.write_bytes(f"voice-{index}".encode())
                voices.append(
                    {
                        "path": path,
                        "name": path.name,
                        "start": cursor,
                        "end": cursor + duration,
                        "duration": duration,
                        "srt_path": None,
                    }
                )
                cursor += duration
            sections = [
                ScriptSection(
                    1, "HOOK", "Hook section narration ends here."
                ),
                ScriptSection(
                    2, "BODY", "Body section narration also ends here."
                ),
            ]
            beats = [beat(1, "HOOK"), beat(2, "BODY")]

            timings, rows = create_cached_section_timings(
                config, sections, voices, skip_whisper=True
            )
            cached_timings, cached_rows = create_cached_section_timings(
                config, sections, voices, skip_whisper=True
            )
            segments, _assigned, beat_timings = build_section_segments(
                config,
                sections,
                voices,
                cached_timings,
                beats,
                cached_rows,
            )

            self.assertEqual(
                [item.word for item in timings],
                [item.word for item in cached_timings],
            )
            for original, cached in zip(timings, cached_timings):
                self.assertAlmostEqual(
                    original.start, cached.start, places=5
                )
                self.assertAlmostEqual(
                    original.end, cached.end, places=5
                )
            self.assertEqual(
                [row["timing_status"] for row in rows],
                ["analyzed", "analyzed"],
            )
            self.assertEqual(len(beat_timings), 2)
            self.assertEqual(
                [row["timing_status"] for row in cached_rows],
                ["cached", "cached"],
            )
            self.assertTrue(
                all(
                    segment.end <= 3.0
                    for segment in segments
                    if segment.section_index == 1
                )
            )
            self.assertTrue(
                all(
                    segment.start >= 3.0
                    for segment in segments
                    if segment.section_index == 2
                )
            )


if __name__ == "__main__":
    unittest.main()
