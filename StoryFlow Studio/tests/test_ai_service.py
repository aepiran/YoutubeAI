from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from storyflow_studio.core.settings import AISettings
from storyflow_studio.modules.ai.claude_service import ClaudeAIService
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


class FakeClaudeQuery:
    def __init__(self, messages: list[object]) -> None:
        self.messages = messages
        self.calls: list[dict[str, object]] = []

    async def __call__(self, *, prompt: str, options: object):
        self.calls.append({"prompt": prompt, "options": options})
        for message in self.messages:
            yield message


class FakeSubprocessRunner:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: object) -> SimpleNamespace:
        self.calls.append(command)
        return SimpleNamespace(stdout=self.stdout, stderr="", returncode=self.returncode)


def _options_factory(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


class ClaudeAIServiceTests(unittest.TestCase):
    def test_snapshot_reports_missing_cli(self) -> None:
        service = ClaudeAIService(
            query_fn=FakeClaudeQuery([]),
            options_factory=_options_factory,
            cli_resolver=lambda: None,
            subprocess_runner=FakeSubprocessRunner(),
        )
        snapshot = service.snapshot()
        self.assertFalse(snapshot.auth.authenticated)
        self.assertEqual(snapshot.auth.label, "Claude CLI not found")

    def test_snapshot_accepts_claude_session(self) -> None:
        runner = FakeSubprocessRunner(
            stdout=(
                '{"loggedIn": true, "email": "user@example.com", '
                '"subscriptionType": "pro"}'
            )
        )
        service = ClaudeAIService(
            query_fn=FakeClaudeQuery([]),
            options_factory=_options_factory,
            cli_resolver=lambda: "claude",
            subprocess_runner=runner,
        )
        snapshot = service.snapshot()
        self.assertTrue(snapshot.auth.authenticated)
        self.assertIn("user@example.com", snapshot.auth.detail)
        self.assertTrue(snapshot.models)
        self.assertEqual(runner.calls[-1], ["claude", "auth", "status"])

    def test_snapshot_rejects_logged_out_session(self) -> None:
        runner = FakeSubprocessRunner(stdout='{"loggedIn": false}', returncode=1)
        service = ClaudeAIService(
            query_fn=FakeClaudeQuery([]),
            options_factory=_options_factory,
            cli_resolver=lambda: "claude",
            subprocess_runner=runner,
        )
        snapshot = service.snapshot()
        self.assertFalse(snapshot.auth.authenticated)
        self.assertEqual(snapshot.models, ())

    def test_run_passes_project_scope_model_and_effort(self) -> None:
        result_message = SimpleNamespace(is_error=False, result="done")
        query_fn = FakeClaudeQuery([result_message])
        service = ClaudeAIService(
            query_fn=query_fn,
            options_factory=_options_factory,
            cli_resolver=lambda: "claude",
            subprocess_runner=FakeSubprocessRunner(),
        )
        with tempfile.TemporaryDirectory() as directory:
            resolved = str(Path(directory).resolve())
            result = service.run(
                "Do the task",
                directory,
                AISettings("claude-opus-5", "high", "claude"),
            )
        self.assertEqual(result, "done")
        options = query_fn.calls[0]["options"]
        self.assertEqual(options.cwd, resolved)
        self.assertEqual(options.model, "claude-opus-5")
        self.assertEqual(options.effort, "high")
        self.assertEqual(options.permission_mode, "bypassPermissions")

    def test_run_raises_on_error_result(self) -> None:
        result_message = SimpleNamespace(is_error=True, result="boom")
        service = ClaudeAIService(
            query_fn=FakeClaudeQuery([result_message]),
            options_factory=_options_factory,
            cli_resolver=lambda: "claude",
            subprocess_runner=FakeSubprocessRunner(),
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                service.run("Do the task", directory, AISettings())


if __name__ == "__main__":
    unittest.main()
