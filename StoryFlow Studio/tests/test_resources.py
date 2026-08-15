from __future__ import annotations

import unittest

from storyflow_studio.core.resources import builtin_background_music_dna


class ResourceTests(unittest.TestCase):
    def test_build_contains_default_background_music_dna(self) -> None:
        dna = builtin_background_music_dna()
        self.assertIn("# StoryFlow Background Music DNA", dna)
        self.assertIn("audio/background_music.mp3", dna)
        self.assertIn("audio/cue_music.csv", dna)
        self.assertIn("MUSIC_LIBRARY_JSON", dna)
        self.assertIn(
            "cue,start,end,track,prayer_section,crossfade_in_seconds,"
            "crossfade_out_seconds,gain_db,target_music_lufs,notes",
            dna,
        )
        self.assertIn('\"cue\": \"C01\"', dna)
        self.assertNotIn('\"cue\": \"M01\"', dna)


if __name__ == "__main__":
    unittest.main()
