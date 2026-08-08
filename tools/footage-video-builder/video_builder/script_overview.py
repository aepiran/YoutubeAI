"""Build a cached, project-wide semantic context before section analysis."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from .config import PipelineConfig
from .models import Beat, ScriptSection


OVERVIEW_SCHEMA_VERSION = 1
_STOP_WORDS = {
    "and", "are", "but", "for", "from", "into", "its", "not", "that",
    "the", "their", "then", "they", "this", "was", "were", "with",
    "các", "cho", "của", "được", "khi", "là", "một", "những", "theo",
    "trong", "và", "với",
}


def _split_concepts(value: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"[,;\n|]+", value)
        if item.strip()
    ]


def _rank_concepts(beats: list[Beat], limit: int = 14) -> list[str]:
    concepts = [
        concept
        for beat in beats
        for concept in _split_concepts(beat.keywords)
    ]
    counts = Counter(concept.lower() for concept in concepts)
    first_seen = {}
    display = {}
    for index, concept in enumerate(concepts):
        key = concept.lower()
        first_seen.setdefault(key, index)
        display.setdefault(key, concept)
    ranked = sorted(
        counts,
        key=lambda key: (-counts[key], first_seen[key]),
    )
    if ranked:
        return [display[key] for key in ranked[:limit]]

    words = [
        word
        for beat in beats
        for word in re.findall(r"[^\W_]+", beat.main_idea.lower())
        if len(word) > 2 and word not in _STOP_WORDS
    ]
    word_counts = Counter(words)
    return [
        word
        for word, _count in sorted(
            word_counts.items(),
            key=lambda item: (-item[1], words.index(item[0])),
        )[:limit]
    ]


def _section_synopsis(sections: list[ScriptSection]) -> list[dict]:
    rows = []
    for section in sections:
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+", section.text)
            if item.strip()
        ]
        excerpt = (sentences[0] if sentences else section.text).strip()
        rows.append(
            {
                "index": section.index,
                "name": section.name,
                "excerpt": excerpt[:240],
            }
        )
    return rows


def _overview_payload(
    script: str,
    sections: list[ScriptSection],
    beats: list[Beat],
) -> dict:
    themes = _rank_concepts(beats)
    section_rows = _section_synopsis(sections)
    visual_directions = list(
        dict.fromkeys(
            beat.desired_visual.strip()
            for beat in beats
            if beat.desired_visual.strip()
        )
    )[:6]
    avoid = list(
        dict.fromkeys(
            concept
            for beat in beats
            for concept in _split_concepts(beat.avoid)
        )
    )[:12]
    section_names = [
        row["name"] for row in section_rows if row["name"]
    ]
    story = " ".join(row["excerpt"] for row in section_rows)
    prompt_parts = ["Cohesive documentary footage"]
    if themes:
        prompt_parts.append("about " + ", ".join(themes))
    if section_names:
        prompt_parts.append(
            "following the story structure " + " to ".join(section_names)
        )
    if story:
        prompt_parts.append("overall story: " + story[:420])
    return {
        "schema_version": OVERVIEW_SCHEMA_VERSION,
        "script_characters": len(script),
        "section_count": len(sections),
        "beat_count": len(beats),
        "themes": themes,
        "visual_directions": visual_directions,
        "avoid": avoid,
        "sections": section_rows,
        "semantic_prompt": ". ".join(prompt_parts),
    }


def create_script_overview(
    config: PipelineConfig,
    script: str,
    sections: list[ScriptSection],
    beats: list[Beat],
    force_refresh: bool = False,
) -> dict:
    """Return a cached overview whose fingerprint covers the whole script."""
    source = {
        "version": OVERVIEW_SCHEMA_VERSION,
        "script": script,
        "sections": [
            {"index": item.index, "name": item.name, "text": item.text}
            for item in sections
        ],
        "beats": [
            {
                "code": beat.code,
                "section": beat.section,
                "main_idea": beat.main_idea,
                "keywords": beat.keywords,
                "desired_visual": beat.desired_visual,
                "avoid": beat.avoid,
            }
            for beat in beats
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            source, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    path = config.cache_dir / "script_overview.json"
    if path.is_file() and not force_refresh:
        try:
            cached = json.loads(path.read_text(encoding="utf-8-sig"))
            if cached.get("fingerprint") == fingerprint:
                cached["cache_status"] = "cached"
                print("Script Overview: dùng lại ngữ cảnh toàn kịch bản.")
                return cached
        except (OSError, ValueError, TypeError):
            pass

    overview = _overview_payload(script, sections, beats)
    overview["fingerprint"] = fingerprint
    overview["cache_status"] = "analyzed"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(overview, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "Script Overview: đã phân tích toàn bộ kịch bản "
        f"({len(sections)} Section, {len(beats)} Beat)."
    )
    return overview
