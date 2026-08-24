"""AI provider adapters: Codex (ChatGPT login) and Claude (Claude Code CLI)."""

from .claude_service import CLAUDE_MODEL_OPTIONS, ClaudeAIService
from .service import AIService, AISnapshot, AuthStatus, CodexAIService, ModelOption
from .skills import (
    BACKGROUND_MUSIC_DNA_SKILL,
    BEAT_DNA_SKILL,
    SCREEN_SRT_DNA_SKILL,
    TTS_DNA_SKILL,
    resolve_dna_content,
)
from .text import strip_markdown_fence


def create_ai_service(provider: str) -> AIService:
    """Build the AI provider adapter selected in Settings."""

    if provider.strip().lower() == "claude":
        return ClaudeAIService()
    return CodexAIService()


__all__ = [
    "AIService",
    "AISnapshot",
    "AuthStatus",
    "BACKGROUND_MUSIC_DNA_SKILL",
    "BEAT_DNA_SKILL",
    "CLAUDE_MODEL_OPTIONS",
    "ClaudeAIService",
    "CodexAIService",
    "ModelOption",
    "SCREEN_SRT_DNA_SKILL",
    "TTS_DNA_SKILL",
    "create_ai_service",
    "resolve_dna_content",
    "strip_markdown_fence",
]
