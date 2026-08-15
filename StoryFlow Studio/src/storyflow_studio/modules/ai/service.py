"""Codex integration backed by the user's saved ChatGPT session."""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

try:
    from openai_codex import Codex, Sandbox
except ImportError:  # Show a useful UI error before dependencies are installed.
    Codex = None  # type: ignore[assignment]
    Sandbox = None  # type: ignore[assignment]

from ...core.settings import AISettings


@dataclass(frozen=True, slots=True)
class AuthStatus:
    authenticated: bool
    label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ModelOption:
    model_id: str
    display_name: str
    description: str = ""
    is_default: bool = False
    reasoning_efforts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AISnapshot:
    auth: AuthStatus
    models: tuple[ModelOption, ...] = ()


class AIService(Protocol):
    def snapshot(self) -> AISnapshot: ...

    def login_chatgpt(self) -> AISnapshot: ...

    def run(
        self,
        prompt: str,
        workdir: str | Path,
        settings: AISettings,
    ) -> str: ...


class CodexAIService:
    """Thin adapter around the Codex SDK; never accepts an OpenAI API key."""

    def __init__(
        self,
        codex_factory: Callable[[], Any] | None = None,
        browser_open: Callable[[str], Any] = webbrowser.open,
    ) -> None:
        self._codex_factory = codex_factory
        self._browser_open = browser_open

    def _new_codex(self) -> Any:
        if self._codex_factory is not None:
            return self._codex_factory()
        if Codex is None:
            raise RuntimeError(
                "Codex SDK chưa được cài. Hãy cài dependencies của StoryFlow Studio."
            )
        return Codex()

    def snapshot(self) -> AISnapshot:
        try:
            with self._new_codex() as codex:
                auth = self._auth_from_response(codex.account())
                models = self._models_from_response(codex.models()) if auth.authenticated else ()
                return AISnapshot(auth=auth, models=models)
        except Exception as exc:
            return AISnapshot(AuthStatus(False, "Codex unavailable", str(exc)))

    def login_chatgpt(self) -> AISnapshot:
        try:
            with self._new_codex() as codex:
                handle = codex.login_chatgpt()
                if not self._browser_open(handle.auth_url):
                    raise RuntimeError(
                        "Không mở được browser. Hãy kiểm tra default browser của hệ thống."
                    )
                completed = handle.wait()
                if not completed.success:
                    raise RuntimeError(completed.error or "ChatGPT login không hoàn thành.")
        except Exception as exc:
            return AISnapshot(AuthStatus(False, "Sign-in failed", str(exc)))
        return self.snapshot()

    def run(
        self,
        prompt: str,
        workdir: str | Path,
        settings: AISettings,
    ) -> str:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise ValueError("Prompt không được để trống.")
        directory = Path(workdir).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError(f"Project directory không tồn tại: {directory}")
        if Sandbox is None and self._codex_factory is None:
            raise RuntimeError("Codex SDK chưa được cài.")

        options: dict[str, Any] = {
            "cwd": str(directory),
            "sandbox": Sandbox.workspace_write if Sandbox is not None else "workspace-write",
        }
        normalized = settings.normalized()
        if normalized.model:
            options["model"] = normalized.model
        if normalized.reasoning_effort != "default":
            options["config"] = {
                "model_reasoning_effort": normalized.reasoning_effort,
            }

        with self._new_codex() as codex:
            result = codex.thread_start(**options).run(clean_prompt)
        return result.final_response

    @staticmethod
    def _auth_from_response(response: Any) -> AuthStatus:
        account_wrapper = getattr(response, "account", None)
        if account_wrapper is None:
            return AuthStatus(False, "Codex disconnected", "Sign in with ChatGPT")
        account = getattr(account_wrapper, "root", account_wrapper)
        if getattr(account, "type", "") != "chatgpt":
            return AuthStatus(
                False,
                "ChatGPT sign-in required",
                "StoryFlow Studio không sử dụng OpenAI API-key sessions.",
            )
        plan = getattr(account, "plan_type", "")
        plan_value = getattr(plan, "value", plan)
        email = getattr(account, "email", None)
        details = " · ".join(part for part in (email, str(plan_value or "")) if part)
        return AuthStatus(True, "Codex connected", details)

    @staticmethod
    def _models_from_response(response: Any) -> tuple[ModelOption, ...]:
        options = []
        for model in getattr(response, "data", ()):
            efforts = tuple(
                str(
                    getattr(
                        getattr(item, "effort", item),
                        "value",
                        getattr(item, "effort", item),
                    )
                )
                for item in (getattr(model, "supported_reasoning_efforts", ()) or ())
            )
            options.append(
                ModelOption(
                    model_id=str(getattr(model, "model", "")),
                    display_name=str(getattr(model, "display_name", "")),
                    description=str(getattr(model, "description", "")),
                    is_default=bool(getattr(model, "is_default", False)),
                    reasoning_efforts=efforts,
                )
            )
        return tuple(option for option in options if option.model_id)
