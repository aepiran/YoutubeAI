import csv
import tempfile
import unittest
from pathlib import Path

from video_builder.audio_mix import (
    MusicCue,
    cue_rows_for_duration,
    load_music_cues,
    parse_timestamp,
)


class DwgMusicCueTests(unittest.TestCase):
    def test_timestamp_supports_dwg_minute_format(self) -> None:
        self.assertEqual(parse_timestamp("20:03.140"), 1203.14)

    def test_cues_resolve_tracks_and_crop_to_video_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            track = root / "bed.mp3"
            track.write_bytes(b"audio")
            cue_sheet = root / "cues.csv"
            with cue_sheet.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "cue", "start", "end", "track", "prayer_section",
                        "crossfade_in_seconds", "crossfade_out_seconds",
                        "gain_db", "target_music_lufs", "notes",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "cue": "C01", "start": "00:00.000",
                        "end": "00:10.000", "track": track.name,
                        "prayer_section": "Hook",
                        "crossfade_in_seconds": "2",
                        "crossfade_out_seconds": "3", "gain_db": "-20",
                        "target_music_lufs": "-35", "notes": "soft",
                    }
                )

            cues = load_music_cues(cue_sheet, root)
            rows = cue_rows_for_duration(cues, 7.0)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["duration"], 7.0)
            self.assertEqual(rows[0]["gain_db"], -20.0)
            self.assertEqual(rows[0]["fade_in"], 2.0)
            self.assertEqual(rows[0]["fade_out"], 3.0)
            self.assertEqual(Path(rows[0]["path"]), track.resolve())

    def test_final_cue_repeats_to_cover_minimum_video_duration(self) -> None:
        cue = MusicCue(
            code="C08",
            start=0.0,
            end=10.0,
            track=Path("closing.mp3"),
            section="Closing",
            fade_in=2.0,
            fade_out=3.0,
            gain_db=-20.0,
            target_lufs=-35.0,
            notes="soft",
        )

        rows = cue_rows_for_duration([cue], 25.0)

        self.assertEqual(
            [row["duration"] for row in rows], [10.0, 10.0, 5.0]
        )
        self.assertEqual(rows[-1]["role"], "dwg_outro_extension")
        self.assertEqual(
            rows[-1]["timeline_start"] + rows[-1]["duration"], 25.0
        )


if __name__ == "__main__":
    unittest.main()
