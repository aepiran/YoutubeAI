from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storyflow_studio.modules.ai.skills import (
    BEAT_DNA_SKILL,
    TTS_DNA_SKILL,
    _sync_dna_skill,
    resolve_dna_content,
)


class ResolveDnaContentTests(unittest.TestCase):
    def test_codex_provider_returns_dna_unchanged_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_root = Path(directory) / "workspace"
            dna_for_prompt, skill = resolve_dna_content(
                "codex", str(workspace_root), TTS_DNA_SKILL, "Full DNA text."
            )
            self.assertEqual(dna_for_prompt, "Full DNA text.")
            self.assertIsNone(skill)
            self.assertFalse((workspace_root / ".claude").exists())

    def test_claude_provider_without_workspace_root_returns_dna_unchanged(self) -> None:
        dna_for_prompt, skill = resolve_dna_content(
            "claude", "", TTS_DNA_SKILL, "Full DNA text."
        )
        self.assertEqual(dna_for_prompt, "Full DNA text.")
        self.assertIsNone(skill)

    def test_claude_provider_writes_skill_and_returns_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_root = Path(directory) / "workspace"
            workspace_root.mkdir()
            dna_for_prompt, skill = resolve_dna_content(
                "claude", str(workspace_root), BEAT_DNA_SKILL, "Create calm visual beats."
            )
            self.assertEqual(skill, BEAT_DNA_SKILL)
            self.assertNotIn("Create calm visual beats.", dna_for_prompt)
            self.assertIn(f"/{BEAT_DNA_SKILL}", dna_for_prompt)

            skill_file = (
                workspace_root / ".claude" / "skills" / BEAT_DNA_SKILL / "SKILL.md"
            )
            self.assertTrue(skill_file.is_file())
            content = skill_file.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("---\n"))
            self.assertIn(f"name: {BEAT_DNA_SKILL}", content)
            self.assertIn("description:", content)
            self.assertIn("Create calm visual beats.", content)

    def test_resync_overwrites_previous_skill_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_root = Path(directory) / "workspace"
            workspace_root.mkdir()
            resolve_dna_content("claude", str(workspace_root), TTS_DNA_SKILL, "Old DNA.")
            resolve_dna_content("claude", str(workspace_root), TTS_DNA_SKILL, "New DNA.")

            skill_file = (
                workspace_root / ".claude" / "skills" / TTS_DNA_SKILL / "SKILL.md"
            )
            content = skill_file.read_text(encoding="utf-8")
            self.assertNotIn("Old DNA.", content)
            self.assertIn("New DNA.", content)

    def test_description_with_quotes_is_sanitized_for_yaml_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_root = Path(directory) / "workspace"
            workspace_root.mkdir()
            _sync_dna_skill(
                workspace_root,
                "custom-skill",
                'Use when the "Beat DNA" step needs it.',
                "DNA text.",
            )
            skill_file = workspace_root / ".claude" / "skills" / "custom-skill" / "SKILL.md"
            content = skill_file.read_text(encoding="utf-8")
            frontmatter, body = content.split("---\n", 2)[1:]
            description_line = next(
                line for line in frontmatter.splitlines() if line.startswith("description:")
            )
            self.assertEqual(
                description_line, "description: \"Use when the 'Beat DNA' step needs it.\""
            )


if __name__ == "__main__":
    unittest.main()
