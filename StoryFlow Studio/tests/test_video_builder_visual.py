from __future__ import annotations

import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from storyflow_studio.modules.tts import CancellationToken
from storyflow_studio.modules.tts.service import TTSWorkflowCancelled
from storyflow_studio.modules.video_builder.visual import (
    FFmpegSceneDetector,
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


class SceneDetectorCancellationTests(unittest.TestCase):
    def test_scene_detection_scales_frames_before_scene_scan(self) -> None:
        captured = {}

        class Process:
            def communicate(self, timeout=None):
                return "", "pts_time:2.5\npts_time:7.0\n"

            def poll(self):
                return 0

            def kill(self):
                raise AssertionError("completed process should not be killed")

        def popen(args, **kwargs):
            captured["args"] = args
            return Process()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.mp4"
            path.write_bytes(b"video")
            with patch(
                "storyflow_studio.modules.video_builder.visual.shutil.which",
                return_value="ffmpeg",
            ), patch(
                "storyflow_studio.modules.video_builder.visual.subprocess.Popen",
                side_effect=popen,
            ):
                scenes = FFmpegSceneDetector().detect(path, 10.0, 0.32, 1.0)

        vf_index = captured["args"].index("-vf")
        filter_value = captured["args"][vf_index + 1]
        self.assertIn("scale=w='min(426,iw)':h=-2:flags=fast_bilinear", filter_value)
        self.assertIn("select='gt(scene,0.3200)'", filter_value)
        self.assertEqual(
            scenes,
            (
                scenes[0].__class__(0, 0.0, 2.5),
                scenes[0].__class__(1, 2.5, 7.0),
                scenes[0].__class__(2, 7.0, 10.0),
            ),
        )

    def test_cancel_terminates_running_ffmpeg(self) -> None:
        cancellation = CancellationToken()

        class Process:
            def __init__(self) -> None:
                self.returncode = None
                self.terminated = False

            def communicate(self, timeout=None):
                cancellation.cancel()
                raise subprocess.TimeoutExpired("ffmpeg", timeout)

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        process = Process()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.mp4"
            path.write_bytes(b"video")
            with patch(
                "storyflow_studio.modules.video_builder.visual.shutil.which",
                return_value="ffmpeg",
            ):
                with patch(
                    "storyflow_studio.modules.video_builder.visual.subprocess.Popen",
                    return_value=process,
                ):
                    with self.assertRaises(TTSWorkflowCancelled):
                        FFmpegSceneDetector().detect(
                            path,
                            30.0,
                            0.32,
                            1.0,
                            cancellation=cancellation,
                        )

        self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()
