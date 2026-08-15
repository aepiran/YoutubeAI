from __future__ import annotations

import csv
import json
import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from storyflow_studio.core.settings import AppSettings, MusicSettings
from storyflow_studio.modules.music import (
    MUSIC_CUE_COLUMNS,
    FFmpegMusicRenderer,
    MusicCue,
    MusicWorkflowError,
    MusicWorkflowService,
    format_music_timestamp,
    parse_and_validate_music_cues,
    parse_music_timestamp,
)
from storyflow_studio.modules.tts import CancellationToken
from storyflow_studio.modules.workspace import WorkspaceService


def cue_rows() -> list[dict]:
    return [
        {
            "cue": "C01",
            "start": "00:00.000",
            "end": "00:06.000",
            "track": "calm.mp3",
            "prayer_section": "Pause and Hook",
            "crossfade_in_seconds": 2,
            "crossfade_out_seconds": 2,
            "gain_db": -18,
            "target_music_lufs": -35,
            "notes": "Gentle opening",
        },
        {
            "cue": "C02",
            "start": "00:04.000",
            "end": "00:10.000",
            "track": "warm.mp3",
            "prayer_section": "Prayer",
            "crossfade_in_seconds": 2,
            "crossfade_out_seconds": 2,
            "gain_db": -20,
            "target_music_lufs": -34.5,
            "notes": "Stay behind narration",
        },
    ]


class FakeDNAService:
    def generate(self, *args, **kwargs):
        return cue_rows()


class FakeRenderer:
    def __init__(self) -> None:
        self.cues = []

    def render(self, cues, destination, duration, cancellation) -> None:
        cancellation.raise_if_cancelled()
        self.cues = cues
        destination.write_bytes(b"rendered mp3")


class MusicWorkflowServiceTests(unittest.TestCase):
    def test_workflow_refuses_to_run_when_background_music_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = WorkspaceService().create_project(
                directory, "Disabled", "disabled", AppSettings()
            )
            service = MusicWorkflowService(
                ai_service=object(),
                dna_service=FakeDNAService(),
                renderer=FakeRenderer(),
                duration_probe=lambda _path: 10.0,
            )

            with self.assertRaisesRegex(MusicWorkflowError, "đang tắt"):
                service.run(
                    project,
                    AppSettings(),
                    lambda _progress: None,
                    CancellationToken(),
                )

    def test_legacy_timestamp_format(self) -> None:
        self.assertEqual(parse_music_timestamp("20:03.140"), 1203.14)
        self.assertEqual(format_music_timestamp(1203.14), "20:03.140")

    def test_crossfade_overlap_matches_legacy_cue_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory)
            tracks = []
            for name in ("calm.mp3", "warm.mp3"):
                (library / name).write_bytes(b"audio")
                tracks.append({"filename": name, "duration_seconds": 60})

            cues = parse_and_validate_music_cues(
                cue_rows(), library, tracks, 10.0
            )

            self.assertEqual([cue.code for cue in cues], ["C01", "C02"])
            self.assertEqual(cues[0].end - cues[1].start, 2.0)
            self.assertEqual(tuple(cues[0].csv_row()), MUSIC_CUE_COLUMNS)

    def test_gap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory)
            tracks = []
            for name in ("calm.mp3", "warm.mp3"):
                (library / name).write_bytes(b"audio")
                tracks.append({"filename": name})
            rows = cue_rows()
            rows[1]["start"] = "00:07.000"
            rows[1]["end"] = "00:12.000"

            with self.assertRaisesRegex(MusicWorkflowError, "gap"):
                parse_and_validate_music_cues(rows, library, tracks, 12.0)

    def test_workflow_writes_legacy_csv_and_music_mp3(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / "library"
            library.mkdir()
            tracks = []
            for name in ("calm.mp3", "warm.mp3"):
                (library / name).write_bytes(b"audio")
                tracks.append({"filename": name, "duration_seconds": 60})
            (library / "music_library.json").write_text(
                json.dumps({"schema_version": 1, "tracks": tracks}),
                encoding="utf-8",
            )
            project = WorkspaceService().create_project(
                root / "workspace", "Music", "music", AppSettings()
            )
            project.path_for("tts_script").write_text(
                "A gentle prayer.", encoding="utf-8"
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:10,000\nA gentle prayer.\n",
                encoding="utf-8",
            )
            project.path_for("audio_file").write_bytes(b"narration")
            renderer = FakeRenderer()
            service = MusicWorkflowService(
                ai_service=object(),
                dna_service=FakeDNAService(),
                renderer=renderer,
                duration_probe=lambda _path: 10.0,
            )

            result = service.run(
                project,
                AppSettings(
                    music=MusicSettings(
                        library_folder=str(library),
                        enabled=True,
                    )
                ),
                lambda _progress: None,
                CancellationToken(),
            )

            self.assertEqual(result.cue_file, project.root / "audio/cue_music.csv")
            self.assertEqual(
                result.audio_file, project.root / "audio/background_music.mp3"
            )
            self.assertEqual(result.audio_file.read_bytes(), b"rendered mp3")
            with result.cue_file.open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(tuple(reader.fieldnames or ()), MUSIC_CUE_COLUMNS)
                rows = list(reader)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["start"], "00:04.000")
            self.assertEqual(rows[1]["target_music_lufs"], "-34.5")
            self.assertEqual(len(renderer.cues), 2)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not installed")
    def test_ffmpeg_renderer_creates_music_only_mp3(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tone.wav"
            sample_rate = 8_000
            with wave.open(str(source), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(sample_rate)
                for index in range(sample_rate):
                    sample = int(
                        4_000 * math.sin(2 * math.pi * 220 * index / sample_rate)
                    )
                    handle.writeframesraw(struct.pack("<h", sample))
            cues = [
                MusicCue(
                    "C01", 0.0, 1.0, source.name, source, "Hook", 0.1, 0.2,
                    -18.0, -35.0, "Soft opening"
                ),
                MusicCue(
                    "C02", 0.8, 1.8, source.name, source, "Prayer", 0.2, 0.2,
                    -20.0, -35.0, "Soft close"
                ),
            ]
            output = root / "background_music.mp3"

            FFmpegMusicRenderer().render(
                cues, output, 1.8, CancellationToken()
            )

            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
