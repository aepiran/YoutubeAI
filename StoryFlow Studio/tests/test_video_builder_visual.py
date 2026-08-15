from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from storyflow_studio.modules.video_builder.visual import (
    HuggingFaceSemanticScorer,
    VisualAnalysisError,
)


class VideoBuilderVisualTests(unittest.TestCase):
    def test_semantic_text_uses_model_limit_and_truncation(self) -> None:
        calls = []

        class Processor:
            def __call__(self, **kwargs):
                calls.append(kwargs)
                return {"input_ids": "tokens", "pixel_values": "pixels"}

        scorer = HuggingFaceSemanticScorer.__new__(HuggingFaceSemanticScorer)
        scorer._processor = Processor()
        scorer._text_max_length = 64

        result = scorer._prepare_inputs("word " * 100, object())

        self.assertEqual(result["input_ids"], "tokens")
        self.assertTrue(calls[0]["truncation"])
        self.assertEqual(calls[0]["max_length"], 64)
        self.assertEqual(calls[0]["padding"], "max_length")

    def test_text_limit_prefers_model_position_embeddings(self) -> None:
        model = types.SimpleNamespace(
            config=types.SimpleNamespace(
                text_config=types.SimpleNamespace(max_position_embeddings=64)
            )
        )
        processor = types.SimpleNamespace(
            tokenizer=types.SimpleNamespace(model_max_length=10**30)
        )

        self.assertEqual(
            HuggingFaceSemanticScorer._resolve_text_max_length(model, processor),
            64,
        )

    def test_local_cache_miss_has_actionable_message_without_library_noise(self) -> None:
        class MissingProcessor:
            @staticmethod
            def from_pretrained(*args, **kwargs):
                raise OSError("raw Hugging Face cache error")

        class UnusedModel:
            @staticmethod
            def from_pretrained(*args, **kwargs):
                raise AssertionError("processor should fail first")

        fake_torch = types.ModuleType("torch")
        fake_transformers = types.ModuleType("transformers")
        fake_transformers.AutoProcessor = MissingProcessor
        fake_transformers.AutoModel = UnusedModel
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules,
            {"torch": fake_torch, "transformers": fake_transformers},
        ):
            with self.assertRaisesRegex(
                VisualAnalysisError,
                "Visual Model chưa có trong local cache",
            ) as raised:
                HuggingFaceSemanticScorer(
                    "openai/clip-vit-base-patch32",
                    Path(directory),
                    local_files_only=True,
                )

        self.assertNotIn("raw Hugging Face cache error", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
