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

from storyflow_studio.core.settings import (
    AISettings,
    AppSettings,
    MusicSettings,
    WorkspaceSettings,
)
from storyflow_studio.modules.ai import BACKGROUND_MUSIC_DNA_SKILL
from storyflow_studio.modules.music import (
    MUSIC_CUE_COLUMNS,
    FFmpegMusicRenderer,
    MusicCue,
    MusicDNAService,
    MusicWorkflowError,
    MusicWorkflowService,
    MusicDNAPlan,
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


class RecommendationDNAService:
    def generate(self, *args, **kwargs):
        return MusicDNAPlan(
            cue_rows(),
            [
                {
                    "section_id": "S01",
                    "cue_start": 1,
                    "cue_end": 1,
                    "purpose": "Opening prayer",
                    "mood": ["peaceful", "hopeful"],
                    "energy": "low",
                    "tempo": "slow",
                    "instruments": ["piano", "ambient strings"],
                    "avoid": ["vocals"],
                    "selected_track": "calm.mp3",
                    "confidence": 0.55,
                    "alternatives": ["warm.mp3"],
                    "rationale": "The library has no ideal hopeful lift.",
                    "needs_more_music": True,
                    "search_queries": ["hopeful prayer piano instrumental"],
                }
            ],
            [
                {
                    "section_id": "S01",
                    "reason": "A better hopeful lift is recommended.",
                    "desired_mood": ["hopeful", "warm"],
                    "energy": "low",
                    "tempo": "slow",
                    "instruments": ["piano"],
                    "avoid": ["vocals"],
                    "minimum_duration_seconds": 10,
                    "search_queries": ["hopeful prayer piano instrumental"],
                }
            ],
        )


class MusicAIService:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompt = ""
        self.skill: str | None = None

    def run(self, prompt, workdir, settings, *, skill=None) -> str:
        self.prompt = prompt
        self.skill = skill
        return json.dumps(self.payload, ensure_ascii=False)


class FakeRenderer:
    def __init__(self) -> None:
        self.cues = []

    def render(self, cues, destination, duration, cancellation) -> None:
        cancellation.raise_if_cancelled()
        self.cues = cues
        destination.write_bytes(b"rendered mp3")


class MusicDNAServiceTests(unittest.TestCase):
    def test_generate_strips_markdown_fence_some_models_add_despite_instructions(
        self,
    ) -> None:
        payload = {"cues": cue_rows(), "sections": [], "recommendations": []}
        ai = MusicAIService(payload)
        ai.run = lambda prompt, workdir, settings, *, skill=None: (
            "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        )

        plan = MusicDNAService(ai).generate(
            "script", [], [], "dna", 10.0, Path("."), AISettings()
        )

        self.assertEqual(plan.cue_rows, cue_rows())


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

    def test_crossfade_mismatch_between_declared_and_actual_is_reconciled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory)
            tracks = []
            for name in ("calm.mp3", "warm.mp3"):
                (library / name).write_bytes(b"audio")
                tracks.append({"filename": name, "duration_seconds": 60})
            rows = cue_rows()
            # C01 declares crossfade_out_seconds=2, but its timestamps now
            # give an actual overlap of 3s with C02 (start=00:04.000) — the
            # kind of ~1s drift observed from Claude on long cue sheets.
            rows[0]["end"] = "00:07.000"

            cues = parse_and_validate_music_cues(rows, library, tracks, 10.0)

            self.assertEqual(cues[0].end - cues[1].start, 3.0)
            self.assertEqual(cues[0].fade_out, 3.0)
            self.assertEqual(cues[1].fade_in, 3.0)

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

    def test_claude_provider_syncs_workspace_skill_for_background_music_dna(self) -> None:
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
            workspace_root = root / "workspace"
            settings = AppSettings(
                ai=AISettings(provider="claude"),
                workspace=WorkspaceSettings(workspace_root=str(workspace_root)),
                music=MusicSettings(library_folder=str(library), enabled=True),
            )
            project = WorkspaceService().create_project(
                workspace_root, "Music", "music", settings
            )
            project.path_for("tts_script").write_text(
                "A gentle prayer.", encoding="utf-8"
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:10,000\nA gentle prayer.\n",
                encoding="utf-8",
            )
            project.path_for("audio_file").write_bytes(b"narration")
            ai = MusicAIService(
                {"cues": cue_rows(), "sections": [], "recommendations": []}
            )
            service = MusicWorkflowService(
                ai_service=ai,
                dna_service=MusicDNAService(ai),
                renderer=FakeRenderer(),
                duration_probe=lambda _path: 10.0,
            )

            service.run(
                project, settings, lambda _progress: None, CancellationToken()
            )

            self.assertEqual(ai.skill, BACKGROUND_MUSIC_DNA_SKILL)
            self.assertIn(BACKGROUND_MUSIC_DNA_SKILL, ai.prompt)
            skill_file = (
                workspace_root
                / ".claude"
                / "skills"
                / BACKGROUND_MUSIC_DNA_SKILL
                / "SKILL.md"
            )
            self.assertTrue(skill_file.is_file())

    def test_workflow_writes_script_analysis_and_can_replace_safely(self) -> None:
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
                root / "workspace", "Music Analysis", "music-analysis", AppSettings()
            )
            project.path_for("tts_script").write_text(
                "A gentle prayer.", encoding="utf-8"
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:10,000\nA gentle prayer.\n",
                encoding="utf-8",
            )
            project.path_for("audio_file").write_bytes(b"narration")
            service = MusicWorkflowService(
                ai_service=object(),
                dna_service=RecommendationDNAService(),
                renderer=FakeRenderer(),
                duration_probe=lambda _path: 10.0,
            )
            settings = AppSettings(
                music=MusicSettings(library_folder=str(library), enabled=True)
            )

            result = service.run(
                project, settings, lambda _progress: None, CancellationToken()
            )

            self.assertTrue(result.analysis_file.is_file())
            self.assertTrue(result.recommendations_file.is_file())
            self.assertEqual(result.recommendation_count, 1)
            analysis = json.loads(result.analysis_file.read_text(encoding="utf-8"))
            self.assertEqual(analysis["sections"][0]["selected_track"], "calm.mp3")
            self.assertEqual(
                analysis["recommendations"][0]["search_queries"],
                ["hopeful prayer piano instrumental"],
            )

            with self.assertRaisesRegex(MusicWorkflowError, "Generate Again"):
                service.run(
                    project, settings, lambda _progress: None, CancellationToken()
                )
            replaced = service.run(
                project,
                settings,
                lambda _progress: None,
                CancellationToken(),
                replace_existing=True,
            )
            self.assertEqual(replaced.recommendation_count, 1)

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
