"""Convert StoryFlow DNA content into Claude Code Skills for the Claude provider.

Codex has no skill concept; ``resolve_dna_content`` is a no-op for any
provider other than "claude" (returns the DNA text unchanged, skill=None).

Skill files are written to ``<workspace_root>/.claude/skills/<name>/SKILL.md``
rather than inside each project: Claude Code discovers ``.claude/skills`` by
walking up from the session's ``cwd`` to its ancestors, so every project
opened from that Workspace Root sees the same skill without a per-project copy.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


TTS_DNA_SKILL = "tts-dna"
BEAT_DNA_SKILL = "beat-dna"
SCREEN_SRT_DNA_SKILL = "screen-srt-dna"
BACKGROUND_MUSIC_DNA_SKILL = "background-music-dna"

_SKILL_DESCRIPTIONS = {
    TTS_DNA_SKILL: (
        "Apply the StoryFlow TTS DNA to transform a raw script into a "
        "TTS-ready script. Use when asked to apply TTS DNA."
    ),
    BEAT_DNA_SKILL: (
        "Apply the StoryFlow Beat DNA to segment narration timing into "
        "beats for the Footage Video Builder. Use when asked to apply Beat DNA."
    ),
    SCREEN_SRT_DNA_SKILL: (
        "Apply the StoryFlow Screen SRT DNA to convert narration SRT into "
        "viewer-facing captions. Use when asked to apply Screen SRT DNA."
    ),
    BACKGROUND_MUSIC_DNA_SKILL: (
        "Apply the StoryFlow Background Music DNA to select and time "
        "background music cues from the music library. Use when asked to "
        "apply Background Music DNA."
    ),
}

_SKILL_NOTE = (
    "The full DNA content is already loaded for this session via the "
    "'/{name}' skill invoked above. Follow it exactly as the authoritative "
    "source; do not ask for it again or claim it is missing."
)


def resolve_dna_content(
    provider: str,
    workspace_root: str,
    skill_name: str,
    dna_text: str,
) -> tuple[str, str | None]:
    """Return ``(dna_for_prompt, skill_name_to_enable)`` for one AI call.

    Codex, or a Claude session with no Workspace Root configured yet, falls
    back to returning ``dna_text`` unchanged with ``skill_name_to_enable``
    ``None`` — the caller embeds the DNA inline exactly as before.
    """
    if provider != "claude" or not workspace_root.strip():
        return dna_text, None
    root = Path(workspace_root).expanduser().resolve()
    _sync_dna_skill(root, skill_name, _SKILL_DESCRIPTIONS[skill_name], dna_text)
    return _SKILL_NOTE.format(name=skill_name), skill_name


def _sync_dna_skill(
    workspace_root: Path, name: str, description: str, content: str
) -> None:
    skill_dir = workspace_root / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    safe_description = description.replace('"', "'")
    document = (
        "---\n"
        f"name: {name}\n"
        f'description: "{safe_description}"\n'
        "---\n\n"
        f"{content.strip()}\n"
    )
    _atomic_write_text(skill_dir / "SKILL.md", document)


def _atomic_write_text(path: Path, content: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
