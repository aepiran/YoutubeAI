from __future__ import annotations

import unittest

from storyflow_studio.core.script_text import extract_script_body


class ScriptTextTests(unittest.TestCase):
    def test_extracts_only_content_after_script_marker(self) -> None:
        document = (
            "TITLE:\nMorning Prayer | Bible Prayer\n\n"
            "SCRIPT:\n\nYou woke up this morning.\nSecond paragraph.\n"
        )

        self.assertEqual(
            extract_script_body(document),
            "You woke up this morning.\nSecond paragraph.\n",
        )

    def test_supports_inline_body_and_case_insensitive_marker(self) -> None:
        self.assertEqual(extract_script_body("script: Hello world."), "Hello world.")

    def test_preserves_legacy_document_without_marker(self) -> None:
        content = "This script: reference is part of the narration."
        self.assertEqual(extract_script_body(content), content)


if __name__ == "__main__":
    unittest.main()
