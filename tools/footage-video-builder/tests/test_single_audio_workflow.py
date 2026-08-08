from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from video_builder.config import default_config
from video_builder.inputs import discover_voice_files, filename_beat_code, load_script


class SingleAudioWorkflowTests(unittest.TestCase):
    def test_legacy_script_headers_become_one_complete_script(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "script.txt"
            audio = root / "narration.mp3"
            script.write_text(
                "SCRIPT:\n[HOOK]\nOpening words.\n[BODY]\nMain story.",
                encoding="utf-8",
            )
            audio.write_bytes(b"fixture")

            narration, sections = load_script(script, [audio])

        self.assertEqual(narration, "Opening words.\n\nMain story.")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].name, "FULL SCRIPT")
        self.assertEqual(sections[0].text, narration)

    def test_multiple_selected_audio_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "one.mp3"
            second = root / "two.mp3"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            config = replace(
                default_config(),
                selected_voice_files=(first, second),
            )

            with self.assertRaisesRegex(ValueError, "đúng 1 file Audio"):
                discover_voice_files(config)

    def test_script_marker_after_metadata_and_pause_markers_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "script.txt"
            audio = root / "narration.mp3"
            script.write_text(
                "E:\\NE\\scripts\\test-pexels\\script.txt<#3#>\n"
                "SCRIPT:\n\n"
                "First spoken sentence.\n\n"
                "<#1#>\n\n"
                "Second spoken sentence.",
                encoding="utf-8",
            )
            audio.write_bytes(b"fixture")

            narration, sections = load_script(script, [audio])

        self.assertEqual(
            narration,
            "First spoken sentence.\n\nSecond spoken sentence.",
        )
        self.assertNotIn("SCRIPT:", narration)
        self.assertNotIn("<#", narration)
        self.assertEqual(sections[0].text, narration)

    def test_filename_beat_code_supports_non_h_prefixes(self) -> None:
        known_codes = {"B044", "H31"}

        self.assertEqual(
            filename_beat_code(Path("B044_PEXELS_123.mp4"), known_codes),
            "B044",
        )
        self.assertEqual(
            filename_beat_code(Path("H31_castle.mp4"), known_codes),
            "H31",
        )


if __name__ == "__main__":
    unittest.main()
