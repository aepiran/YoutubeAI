"""Claude Code CLI integration backed by the user's saved Claude session."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

try:
    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk import query as claude_query
except ImportError:  # Show a useful UI error before dependencies are installed.
    ClaudeAgentOptions = None  # type: ignore[assignment]
    claude_query = None

from ...core.process import WINDOWS_NO_WINDOW
from ...core.settings import AISettings
from .service import AISnapshot, AuthStatus, ModelOption


def _patch_anyio_no_console() -> None:
    """Stop the Claude Agent SDK from flashing a console window on Windows.

    The SDK spawns the bundled `claude.exe` via `anyio.open_process`, which
    does not set `CREATE_NO_WINDOW`. Since claude.exe is a console-subsystem
    binary, Windows allocates a visible console for it unless that flag is
    passed. We patch `anyio.open_process` in place so every caller (including
    the SDK's internal version check) gets the flag for free.
    """
    if not WINDOWS_NO_WINDOW:
        return
    try:
        import anyio
    except ImportError:
        return
    if getattr(anyio.open_process, "_storyflow_no_console", False):
        return
    original_open_process = anyio.open_process

    async def _open_process_no_console(*args: Any, **kwargs: Any) -> Any:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | WINDOWS_NO_WINDOW
        return await original_open_process(*args, **kwargs)

    _open_process_no_console._storyflow_no_console = True  # type: ignore[attr-defined]
    anyio.open_process = _open_process_no_console


_patch_anyio_no_console()


INSTALL_HINT = (
    "Không tìm thấy Claude Code CLI. `claude-agent-sdk` thường đã kèm sẵn CLI "
    "cho nền tảng được hỗ trợ (ví dụ Windows x64); nếu máy không có bản kèm "
    "sẵn, hãy cài Claude Code CLI theo hướng dẫn chính thức tại "
    "https://docs.claude.com/en/docs/claude-code/setup rồi chạy `claude auth "
    "login` một lần trước khi dùng."
)

CLAUDE_MODEL_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption("claude-opus-5", "Opus 5", "Highest-capability Claude model", is_default=True),
    ModelOption("claude-sonnet-5", "Sonnet 5", "Balanced Claude model"),
    ModelOption(
        "claude-haiku-4-5-20251001", "Haiku 4.5", "Fast, lightweight Claude model"
    ),
    ModelOption("claude-fable-5", "Fable 5", "Claude model variant"),
)

# ClaudeAgentOptions.effort accepts low/medium/high/xhigh/max; AISettings uses
# the same first four tiers plus "default" (meaning: let Claude decide).
_EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh"}


def _resolve_bundled_cli() -> str | None:
    """Return the CLI binary bundled inside the installed claude-agent-sdk wheel."""
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    cli_name = "claude.exe" if os.name == "nt" else "claude"
    bundled = Path(claude_agent_sdk.__file__).resolve().parent / "_bundled" / cli_name
    return str(bundled) if bundled.is_file() else None


def default_cli_resolver() -> str | None:
    """Locate the Claude CLI: prefer the bundled binary, fall back to PATH."""
    return _resolve_bundled_cli() or shutil.which("claude")


class ClaudeAIService:
    """Thin adapter around the Claude Agent SDK/CLI; never accepts an API key."""

    def __init__(
        self,
        query_fn: Callable[..., Any] | None = None,
        options_factory: Callable[..., Any] | None = None,
        cli_resolver: Callable[[], str | None] = default_cli_resolver,
        subprocess_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self._query_fn = query_fn if query_fn is not None else claude_query
        self._options_factory = (
            options_factory if options_factory is not None else ClaudeAgentOptions
        )
        self._cli_resolver = cli_resolver
        self._subprocess_runner = subprocess_runner

    def snapshot(self) -> AISnapshot:
        executable = self._cli_resolver()
        if not executable:
            return AISnapshot(AuthStatus(False, "Claude CLI not found", INSTALL_HINT))
        try:
            completed = self._subprocess_runner(
                [executable, "auth", "status"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=WINDOWS_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return AISnapshot(AuthStatus(False, "Claude CLI unavailable", str(exc)))
        try:
            data = json.loads(completed.stdout or "{}")
        except ValueError:
            return AISnapshot(
                AuthStatus(
                    False,
                    "Claude CLI unavailable",
                    (completed.stderr or "").strip()[:200],
                )
            )
        if not isinstance(data, dict) or not data.get("loggedIn"):
            return AISnapshot(
                AuthStatus(False, "Claude disconnected", "Sign in with your Claude account")
            )
        email = str(data.get("email") or "")
        plan = str(data.get("subscriptionType") or "")
        details = " · ".join(part for part in (email, plan) if part)
        return AISnapshot(AuthStatus(True, "Claude connected", details), CLAUDE_MODEL_OPTIONS)

    def login(self) -> AISnapshot:
        executable = self._cli_resolver()
        if not executable:
            return AISnapshot(AuthStatus(False, "Claude CLI not found", INSTALL_HINT))
        try:
            self._subprocess_runner(
                [executable, "auth", "login", "--claudeai"],
                timeout=300,
                creationflags=WINDOWS_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return AISnapshot(AuthStatus(False, "Sign-in failed", str(exc)))
        return self.snapshot()

    def run(
        self,
        prompt: str,
        workdir: str | Path,
        settings: AISettings,
        *,
        skill: str | None = None,
    ) -> str:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise ValueError("Prompt không được để trống.")
        directory = Path(workdir).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError(f"Project directory không tồn tại: {directory}")
        if self._query_fn is None or self._options_factory is None:
            raise RuntimeError(
                "Claude Agent SDK chưa được cài. Hãy cài dependency extra "
                "`claude` của StoryFlow Studio."
            )

        normalized = settings.normalized()
        option_kwargs: dict[str, Any] = {
            "cwd": str(directory),
            "permission_mode": "bypassPermissions",
        }
        if normalized.model:
            option_kwargs["model"] = normalized.model
        effort = _EFFORT_MAP.get(normalized.reasoning_effort)
        if effort:
            option_kwargs["effort"] = effort
        if skill:
            option_kwargs["skills"] = [skill]
            clean_prompt = f"/{skill}\n\n{clean_prompt}"
        options = self._options_factory(**option_kwargs)

        return asyncio.run(self._collect_result(clean_prompt, options))

    async def _collect_result(self, prompt: str, options: Any) -> str:
        result_text: str | None = None
        async for message in self._query_fn(prompt=prompt, options=options):
            if hasattr(message, "is_error") and hasattr(message, "result"):
                if message.is_error:
                    raise RuntimeError(
                        str(message.result or "Claude query thất bại.")
                    )
                result_text = message.result
        if result_text is None:
            raise RuntimeError("Claude không trả kết quả.")
        return result_text
