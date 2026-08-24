from __future__ import annotations

import unittest

from storyflow_studio.modules.ai.text import strip_markdown_fence


class StripMarkdownFenceTests(unittest.TestCase):
    def test_returns_plain_text_unchanged(self) -> None:
        self.assertEqual(strip_markdown_fence('{"a": 1}'), '{"a": 1}')

    def test_strips_fence_with_language_tag(self) -> None:
        wrapped = '```json\n{"a": 1}\n```'
        self.assertEqual(strip_markdown_fence(wrapped), '{"a": 1}')

    def test_strips_fence_without_language_tag(self) -> None:
        wrapped = "```\nplain text body\n```"
        self.assertEqual(strip_markdown_fence(wrapped), "plain text body")

    def test_strips_fence_with_surrounding_whitespace(self) -> None:
        wrapped = "  \n```json\n{\"a\": 1}\n```\n  "
        self.assertEqual(strip_markdown_fence(wrapped), '{"a": 1}')

    def test_preserves_multiline_body(self) -> None:
        wrapped = "```\nline one\nline two\n```"
        self.assertEqual(strip_markdown_fence(wrapped), "line one\nline two")

    def test_leaves_stray_single_sided_backticks_unchanged(self) -> None:
        one_sided = "```json\n{\"a\": 1}"
        self.assertEqual(strip_markdown_fence(one_sided), one_sided)

    def test_leaves_backticks_inside_body_unchanged_when_not_wrapping(self) -> None:
        value = 'Use `inline code` here.'
        self.assertEqual(strip_markdown_fence(value), value)

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(strip_markdown_fence(""), "")


if __name__ == "__main__":
    unittest.main()
