from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from storyflow_studio.core.settings import AISettings
from storyflow_studio.modules.ai.service import CodexAIService


class FakeThread:
    def run(self, _prompt: str):
        return SimpleNamespace(final_response="done")


class FakeCodex:
    def __init__(self) -> None:
        self.thread_options = None

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def account(self):
        account = SimpleNamespace(
            root=SimpleNamespace(type="chatgpt", email="user@example.com", plan_type="pro")
        )
        return SimpleNamespace(account=account)

    def models(self):
        model = SimpleNamespace(
            model="gpt-test",
            display_name="GPT Test",
            description="Test model",
            is_default=True,
            supported_reasoning_efforts=(),
        )
        return SimpleNamespace(data=[model])

    def thread_start(self, **options):
        self.thread_options = options
        return FakeThread()


class CodexAIServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.codex = FakeCodex()
        self.service = CodexAIService(codex_factory=lambda: self.codex)

    def test_snapshot_accepts_chatgpt_session(self) -> None:
        snapshot = self.service.snapshot()
        self.assertTrue(snapshot.auth.authenticated)
        self.assertEqual(snapshot.models[0].model_id, "gpt-test")

    def test_snapshot_rejects_api_key_session(self) -> None:
        self.codex.account = lambda: SimpleNamespace(
            account=SimpleNamespace(root=SimpleNamespace(type="apiKey"))
        )
        snapshot = self.service.snapshot()
        self.assertFalse(snapshot.auth.authenticated)
        self.assertIn("ChatGPT", snapshot.auth.label)
        self.assertEqual(snapshot.models, ())

    def test_run_passes_project_scope_model_and_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            resolved = str(Path(directory).resolve())
            result = self.service.run(
                "Do the task",
                directory,
                AISettings("gpt-test", "high"),
            )
        self.assertEqual(result, "done")
        self.assertEqual(self.codex.thread_options["model"], "gpt-test")
        self.assertEqual(
            self.codex.thread_options["config"],
            {"model_reasoning_effort": "high"},
        )
        self.assertEqual(self.codex.thread_options["cwd"], resolved)


if __name__ == "__main__":
    unittest.main()
