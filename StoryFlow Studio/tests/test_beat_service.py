from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import (
    AISettings,
    AppSettings,
    BeatSettings,
    WorkspaceSettings,
)
from storyflow_studio.modules.ai import BEAT_DNA_SKILL
from storyflow_studio.modules.beat import (
    REQUIRED_COLUMNS,
    BeatWorkflowError,
    BeatWorkflowService,
)
from storyflow_studio.modules.workspace import WorkspaceService


class FakeCancellation:
    cancelled = False

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError("cancelled")


class BeatAIService:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompt = ""
        self.workdir: Path | None = None
        self.skill: str | None = None

    def run(self, prompt, workdir, settings, *, skill=None) -> str:
        self.prompt = prompt
        self.workdir = Path(workdir)
        self.skill = skill
        return json.dumps(self.payload, ensure_ascii=False)


def valid_payload() -> dict:
    return {
        "beats": [
            {
                "ma_beat": "H01",
                "cue_start": 1,
                "cue_end": 1,
                "narration": "Hope rises with the morning.",
                "y_chinh": "Hope begins at sunrise",
                "tu_khoa": "peaceful sunrise|golden dawn",
                "hinh_can_tim": "A calm sunrise over distant mountains",
                "tranh": "night, storm, logo",
            },
            {
                "ma_beat": "H02",
                "cue_start": 2,
                "cue_end": 2,
                "narration": "Walk forward in peace.",
                "y_chinh": "Move into the day peacefully",
                "tu_khoa": "walking sunrise|quiet morning path",
                "hinh_can_tim": "A person walking toward warm morning light",
                "tranh": "crowd, traffic, text overlay",
            },
        ]
    }


class BeatWorkflowServiceTests(unittest.TestCase):
    def create_ready_project(self, root: Path, dna: Path):
        settings = AppSettings(beat=BeatSettings(str(dna), "footage.csv"))
        project = WorkspaceService().create_project(
            root / "workspace", "Beat Story", "beat-story", settings
        )
        project.path_for("tts_script").write_text(
            "Hope rises with the morning. Walk forward in peace.",
            encoding="utf-8",
        )
        project.path_for("subtitle_file").write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n"
            "Hope rises with the morning.\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n"
            "Walk forward in peace.\n",
            encoding="utf-8",
        )
        project.path_for("audio_file").write_bytes(b"mp3-data")
        return project, settings

    def test_script_and_srt_create_builder_compatible_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna = root / "beat-dna.md"
            dna.write_text("Create calm visual beats.", encoding="utf-8")
            project, settings = self.create_ready_project(root, dna)
            ai = BeatAIService(valid_payload())
            updates = []
            result = BeatWorkflowService(
                ai, duration_probe=lambda path: 4.1
            ).run(project, settings, updates.append, FakeCancellation())

            self.assertEqual(result.beat_count, 2)
            self.assertEqual(result.duration_seconds, 4.1)
            self.assertEqual(ai.workdir, project.root)
            self.assertIn("<SCRIPT_TTS>", ai.prompt)
            self.assertIn("<SRT_CUES_JSON>", ai.prompt)
            self.assertIn("Create calm visual beats.", ai.prompt)
            with result.beat_file.open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(tuple(reader.fieldnames or ()), REQUIRED_COLUMNS)
            self.assertEqual([row["ma_beat"] for row in rows], ["H01", "H02"])
            self.assertEqual(result.timing_file, project.path_for("beat_timing_file"))
            timing = json.loads(result.timing_file.read_text(encoding="utf-8"))
            self.assertEqual(timing["schema_version"], 1)
            self.assertEqual(
                [row["code"] for row in timing["beats"]], ["H01", "H02"]
            )
            self.assertEqual(timing["beats"][0]["start_seconds"], 0.0)
            self.assertEqual(timing["beats"][1]["end_seconds"], 4.1)
            self.assertTrue(timing["sources"]["subtitle_sha256"])
            self.assertEqual(updates[-1].state, "completed")
            self.assertEqual(updates[-1].percent, 100)

    def test_claude_provider_syncs_workspace_skill_and_references_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna = root / "beat-dna.md"
            dna.write_text("Create calm visual beats.", encoding="utf-8")
            workspace_root = root / "workspace"
            settings = AppSettings(
                ai=AISettings(provider="claude"),
                workspace=WorkspaceSettings(workspace_root=str(workspace_root)),
                beat=BeatSettings(str(dna), "footage.csv"),
            )
            project = WorkspaceService().create_project(
                workspace_root, "Beat Story", "beat-story", settings
            )
            project.path_for("tts_script").write_text(
                "Hope rises with the morning. Walk forward in peace.",
                encoding="utf-8",
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\n"
                "Hope rises with the morning.\n\n"
                "2\n00:00:02,000 --> 00:00:04,000\n"
                "Walk forward in peace.\n",
                encoding="utf-8",
            )
            project.path_for("audio_file").write_bytes(b"mp3-data")
            ai = BeatAIService(valid_payload())
            BeatWorkflowService(ai, duration_probe=lambda path: 4.1).run(
                project, settings, lambda update: None, FakeCancellation()
            )

            self.assertEqual(ai.skill, BEAT_DNA_SKILL)
            self.assertNotIn("Create calm visual beats.", ai.prompt)
            self.assertIn(BEAT_DNA_SKILL, ai.prompt)
            skill_file = (
                workspace_root / ".claude" / "skills" / BEAT_DNA_SKILL / "SKILL.md"
            )
            self.assertTrue(skill_file.is_file())
            content = skill_file.read_text(encoding="utf-8")
            self.assertIn(f"name: {BEAT_DNA_SKILL}", content)
            self.assertIn("Create calm visual beats.", content)

    def test_gap_in_cue_coverage_never_publishes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna = root / "beat-dna.md"
            dna.write_text("DNA", encoding="utf-8")
            project, settings = self.create_ready_project(root, dna)
            payload = valid_payload()
            payload["beats"][1]["cue_start"] = 1
            service = BeatWorkflowService(
                BeatAIService(payload), duration_probe=lambda path: 4.0
            )

            with self.assertRaisesRegex(BeatWorkflowError, "không liên tục"):
                service.run(project, settings, lambda update: None, FakeCancellation())
            self.assertFalse(project.path_for("beat_file").exists())

    def test_script_srt_mismatch_stops_before_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna = root / "beat-dna.md"
            dna.write_text("DNA", encoding="utf-8")
            project, settings = self.create_ready_project(root, dna)
            project.path_for("tts_script").write_text(
                "Completely unrelated narration words and meaning.", encoding="utf-8"
            )
            ai = BeatAIService(valid_payload())

            with self.assertRaisesRegex(BeatWorkflowError, "SRT chỉ khớp"):
                BeatWorkflowService(ai, duration_probe=lambda path: 4.0).run(
                    project, settings, lambda update: None, FakeCancellation()
                )
            self.assertEqual(ai.prompt, "")

    def test_existing_csv_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna = root / "beat-dna.md"
            dna.write_text("DNA", encoding="utf-8")
            project, settings = self.create_ready_project(root, dna)
            output = project.path_for("beat_file")
            output.write_text("keep-me", encoding="utf-8")

            with self.assertRaisesRegex(BeatWorkflowError, "đã tồn tại"):
                BeatWorkflowService(
                    BeatAIService(valid_payload()), duration_probe=lambda path: 4.0
                ).run(project, settings, lambda update: None, FakeCancellation())
            self.assertEqual(output.read_text(encoding="utf-8"), "keep-me")

    def test_generate_again_replaces_csv_and_timing_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna = root / "beat-dna.md"
            dna.write_text("DNA", encoding="utf-8")
            project, settings = self.create_ready_project(root, dna)
            output = project.path_for("beat_file")
            timing = project.path_for("beat_timing_file")
            output.write_text("old-csv", encoding="utf-8")
            timing.parent.mkdir(parents=True, exist_ok=True)
            timing.write_text("old-timing", encoding="utf-8")

            result = BeatWorkflowService(
                BeatAIService(valid_payload()), duration_probe=lambda path: 4.0
            ).run(
                project,
                settings,
                lambda update: None,
                FakeCancellation(),
                replace_existing=True,
            )

            self.assertNotEqual(output.read_text(encoding="utf-8"), "old-csv")
            payload = json.loads(timing.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(result.timing_file, timing)


if __name__ == "__main__":
    unittest.main()
