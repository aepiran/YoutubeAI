"""Stage 2: align the written transcript and semantic beats to narration audio."""

from __future__ import annotations

import difflib
import json
import math
import re
from collections import Counter

import numpy as np

from .config import PipelineConfig
from .models import Beat, ScriptSection, SubtitleCue, WordTiming


def normalize_word(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def script_tokens(script: str) -> list[str]:
    return [token for token in re.findall(r"\S+", script) if normalize_word(token)]


def transcribe_voice_timeline(config: PipelineConfig, voice_timeline: list[dict]):
    signature = {
        "model": config.whisper_model,
        "voices": [
            {
                "name": item["path"].name,
                "size": item["path"].stat().st_size,
                "mtime_ns": item["path"].stat().st_mtime_ns,
                "offset": round(item["start"], 6),
                "duration": round(item["duration"], 6),
            }
            for item in voice_timeline
        ],
    }
    if config.whisper_cache_file.exists():
        try:
            cached = json.loads(
                config.whisper_cache_file.read_text(encoding="utf-8")
            )
            if cached.get("signature") == signature and cached.get("words"):
                print(
                    f"Đang dùng Timing Whisper từ Cache cho "
                    f"{len(voice_timeline)} file Voice "
                    f"({len(cached['words'])} từ)."
                )
                return cached["words"]
        except (OSError, ValueError, TypeError):
            print("Cảnh báo: Cache Whisper không hợp lệ; đang transcript lại.")

    import whisper

    print(f"Đang nạp model Whisper '{config.whisper_model}'...")
    config.whisper_model_dir.mkdir(parents=True, exist_ok=True)
    model = whisper.load_model(
        config.whisper_model, download_root=str(config.whisper_model_dir)
    )
    words = []
    for voice_index, voice in enumerate(voice_timeline, start=1):
        print(
            f"Đang transcript Voice {voice_index}/{len(voice_timeline)}: "
            f"{voice['name']} (Offset {voice['start']:.2f}s)"
        )
        result = model.transcribe(
            str(voice["path"]),
            language="en",
            word_timestamps=True,
            fp16=False,
            verbose=False,
        )
        for segment in result.get("segments", []):
            for item in segment.get("words", []):
                text = item.get("word", "").strip()
                if text:
                    words.append(
                        {
                            "word": text,
                            "start": float(item["start"]) + voice["start"],
                            "end": float(item["end"]) + voice["start"],
                            "voice": voice["name"],
                        }
                    )
    if not words:
        raise RuntimeError("Whisper không trả về Word timestamp")
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    config.whisper_cache_file.write_text(
        json.dumps({"signature": signature, "words": words}, ensure_ascii=False),
        encoding="utf-8",
    )
    return words


def align_script_words(
    script: str, recognized_words: list[dict], total_duration: float
) -> tuple[list[WordTiming], float]:
    tokens = script_tokens(script)
    recognized = [
        item for item in recognized_words if normalize_word(item.get("word", ""))
    ]
    if not tokens or not recognized:
        raise RuntimeError("Không có từ để căn chỉnh kịch bản với Audio")
    source = [normalize_word(token) for token in tokens]
    heard = [normalize_word(item["word"]) for item in recognized]
    matcher = difflib.SequenceMatcher(None, source, heard, autojunk=False)
    anchors = {}
    for match in matcher.get_matching_blocks():
        for offset in range(match.size):
            anchors[match.a + offset] = match.b + offset
    ratio = len(anchors) / len(tokens)
    if ratio < 0.50:
        raise RuntimeError(
            f"Chỉ {ratio:.0%} số từ trong kịch bản khớp với Whisper"
        )

    anchor_indices = [-1]
    anchor_times = [0.0]
    for token_index in sorted(anchors):
        anchor_indices.append(token_index)
        anchor_times.append(float(recognized[anchors[token_index]]["start"]))
    anchor_indices.append(len(tokens))
    anchor_times.append(total_duration)
    starts = np.interp(
        np.arange(len(tokens), dtype=float),
        np.asarray(anchor_indices, dtype=float),
        np.asarray(anchor_times, dtype=float),
    )
    starts = np.maximum.accumulate(np.clip(starts, 0.0, total_duration))
    timings = []
    for index, token in enumerate(tokens):
        end = starts[index + 1] if index + 1 < len(tokens) else total_duration
        timings.append(WordTiming(token, float(starts[index]), float(end)))
    return timings, ratio


def estimate_script_words(script: str, total_duration: float) -> list[WordTiming]:
    tokens = script_tokens(script)
    if not tokens:
        raise ValueError("The script contains no speakable words")
    weights = []
    for token in tokens:
        weight = max(1.0, len(normalize_word(token)) / 4.0)
        if re.search(r"[.!?][\"']?$", token):
            weight += 1.3
        elif re.search(r"[,;:][\"']?$", token):
            weight += 0.45
        weights.append(weight)
    timings = []
    cursor = 0.0
    total_weight = sum(weights)
    for token, weight in zip(tokens, weights):
        end = cursor + total_duration * weight / total_weight
        timings.append(WordTiming(token, cursor, end))
        cursor = end
    timings[-1] = WordTiming(timings[-1].word, timings[-1].start, total_duration)
    return timings


def _srt_timestamp_seconds(value: str) -> float:
    match = re.fullmatch(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
        value.strip(),
    )
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def parse_srt(filepath, audio_duration: float) -> list[SubtitleCue]:
    content = filepath.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    cues = []
    previous_end = 0.0
    for block_number, block in enumerate(blocks, start=1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            raise ValueError(
                f"{filepath.name}: invalid caption block {block_number}"
            )
        try:
            cue_index = int(lines[0])
        except ValueError as exc:
            raise ValueError(
                f"{filepath.name}: invalid caption index {lines[0]!r}"
            ) from exc
        timestamp_match = re.fullmatch(
            r"(.+?)\s*-->\s*(.+?)(?:\s+.*)?",
            lines[1],
        )
        if not timestamp_match:
            raise ValueError(
                f"{filepath.name}: invalid timestamp line {lines[1]!r}"
            )
        start = _srt_timestamp_seconds(timestamp_match.group(1))
        end = _srt_timestamp_seconds(timestamp_match.group(2))
        if start < 0 or end <= start:
            raise ValueError(
                f"{filepath.name}: invalid range at caption {cue_index}"
            )
        if start + 0.05 < previous_end:
            raise ValueError(
                f"{filepath.name}: overlapping caption {cue_index}"
            )
        text = " ".join(lines[2:]).strip()
        if not script_tokens(text):
            raise ValueError(
                f"{filepath.name}: empty caption {cue_index}"
            )
        cues.append(SubtitleCue(cue_index, start, end, text))
        previous_end = end
    if not cues:
        raise ValueError(f"{filepath.name}: no subtitle captions")
    if cues[-1].end > audio_duration + 2.0:
        raise ValueError(
            f"{filepath.name}: final caption exceeds audio duration by "
            f"{cues[-1].end - audio_duration:.2f}s"
        )
    return cues


def srt_script_word_timings(
    script: str,
    cues: list[SubtitleCue],
    total_duration: float,
) -> tuple[list[WordTiming], float]:
    recognized = []
    for cue in cues:
        tokens = script_tokens(cue.text)
        weights = [
            max(1.0, len(normalize_word(token)) / 4.0)
            for token in tokens
        ]
        total_weight = sum(weights)
        cursor = cue.start
        for token, weight in zip(tokens, weights):
            end = cursor + (cue.end - cue.start) * weight / total_weight
            recognized.append({"word": token, "start": cursor, "end": end})
            cursor = end
    return align_script_words(script, recognized, total_duration)


def _offset_timings(
    timings: list[WordTiming], offset: float
) -> list[WordTiming]:
    return [
        WordTiming(item.word, item.start + offset, item.end + offset)
        for item in timings
    ]


def merge_hybrid_timings(
    whisper_timings: list[WordTiming],
    srt_timings: list[WordTiming],
    total_duration: float,
) -> list[WordTiming]:
    if len(whisper_timings) != len(srt_timings):
        raise RuntimeError("Whisper and SRT produced different script lengths")
    starts = np.asarray(
        [
            0.72 * whisper.start + 0.28 * srt.start
            for whisper, srt in zip(whisper_timings, srt_timings)
        ],
        dtype=float,
    )
    starts = np.maximum.accumulate(np.clip(starts, 0.0, total_duration))
    result = []
    for index, whisper in enumerate(whisper_timings):
        end = starts[index + 1] if index + 1 < len(starts) else total_duration
        result.append(WordTiming(whisper.word, float(starts[index]), float(end)))
    return result


def text_match_score(beat: Beat, phrase: str) -> float:
    beat_tokens = [
        normalize_word(token)
        for token in re.findall(r"\S+", beat.main_idea)
        if normalize_word(token)
    ]
    phrase_tokens = [
        normalize_word(token)
        for token in re.findall(r"\S+", phrase)
        if normalize_word(token)
    ]
    ratio = difflib.SequenceMatcher(
        None, " ".join(beat_tokens), " ".join(phrase_tokens), autojunk=False
    ).ratio()
    overlap = len(set(beat_tokens) & set(phrase_tokens)) / max(
        1, min(len(set(beat_tokens)), len(set(phrase_tokens)))
    )
    return 0.62 * ratio + 0.38 * overlap


_ALIGNMENT_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "for", "from", "had", "has", "have", "he", "her", "his", "i", "in",
    "into", "is", "it", "its", "of", "on", "or", "our", "she", "that",
    "the", "their", "them", "they", "this", "to", "was", "we", "were",
    "what", "when", "where", "which", "who", "with", "you", "your",
}


def _content_tokens(words: list[str]) -> list[str]:
    normalized = [normalize_word(word) for word in words]
    content = [
        word
        for word in normalized
        if word and len(word) > 2 and word not in _ALIGNMENT_STOP_WORDS
    ]
    return content or [word for word in normalized if word]


def _range_match_score(
    beat_counts: Counter,
    beat_total: int,
    phrase_token_counts: Counter,
    phrase_word_count: int,
    target_word_count: float,
) -> float:
    """Score a bounded phrase without rebuilding or diffing long strings."""

    matched = sum(
        min(count, phrase_token_counts.get(token, 0))
        for token, count in beat_counts.items()
    )
    phrase_total = max(1, sum(phrase_token_counts.values()))
    recall = matched / beat_total
    precision = matched / phrase_total
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    length_error = abs(phrase_word_count - target_word_count) / max(
        target_word_count, 1.0
    )
    return 0.72 * recall + 0.28 * f1 - 0.22 * length_error**2


def align_beats_to_script(
    word_timings: list[WordTiming], beats: list[Beat]
) -> list[tuple[int, int]]:
    clause_ranges = []
    clause_start = 0
    for index, item in enumerate(word_timings, start=1):
        if re.search(r"[,;:.!?][\"']?$", item.word):
            clause_ranges.append((clause_start, index))
            clause_start = index
    if clause_start < len(word_timings):
        clause_ranges.append((clause_start, len(word_timings)))
    if len(clause_ranges) < len(beats):
        raise RuntimeError(
            f"Only {len(clause_ranges)} script clauses for {len(beats)} CSV beats"
        )

    beat_count = len(beats)
    clause_count = len(clause_ranges)
    average_clause_span = clause_count / beat_count
    # Keep the monotonic alignment flexible without exhaustively testing
    # every possible start against every possible end.
    max_clause_span = max(12, int(math.ceil(average_clause_span * 3.0)))

    clause_tokens = []
    clause_word_counts = []
    for word_start, word_end in clause_ranges:
        words = [word.word for word in word_timings[word_start:word_end]]
        clause_tokens.append(_content_tokens(words))
        clause_word_counts.append(word_end - word_start)

    beat_tokens = [
        _content_tokens(re.findall(r"\S+", beat.main_idea))
        for beat in beats
    ]
    beat_token_counts = [Counter(tokens) for tokens in beat_tokens]
    beat_token_totals = [
        max(1, sum(counts.values()))
        for counts in beat_token_counts
    ]
    beat_word_lengths = np.asarray(
        [
            max(1, len(script_tokens(beat.main_idea)))
            for beat in beats
        ],
        dtype=float,
    )
    # CSV main ideas are concise summaries. Their source passages are usually
    # a few times longer; unlike total_script_words / beat_count, this estimate
    # does not force an incomplete CSV to consume unrelated trailing sections.
    target_word_counts = np.clip(
        beat_word_lengths * 2.6,
        12.0,
        72.0,
    )

    scores = np.full((beat_count + 1, clause_count + 1), -np.inf)
    previous = np.full((beat_count + 1, clause_count + 1), -1, dtype=int)
    scores[0, 0] = 0.0
    for beat_index in range(1, beat_count + 1):
        remaining_beats = beat_count - beat_index
        min_clause_end = beat_index
        max_clause_end = min(
            beat_index * max_clause_span,
            clause_count - remaining_beats,
        )
        for clause_end in range(min_clause_end, max_clause_end + 1):
            earliest_start = max(
                beat_index - 1,
                clause_end - max_clause_span,
            )
            phrase_counts: Counter = Counter()
            phrase_word_count = 0
            for clause_start_index in range(
                clause_end - 1, earliest_start - 1, -1
            ):
                phrase_counts.update(clause_tokens[clause_start_index])
                phrase_word_count += clause_word_counts[clause_start_index]
                if not math.isfinite(scores[beat_index - 1, clause_start_index]):
                    continue
                match_score = _range_match_score(
                    beat_token_counts[beat_index - 1],
                    beat_token_totals[beat_index - 1],
                    phrase_counts,
                    phrase_word_count,
                    float(target_word_counts[beat_index - 1]),
                )
                score = (
                    scores[beat_index - 1, clause_start_index]
                    + match_score
                )
                if score > scores[beat_index, clause_end]:
                    scores[beat_index, clause_end] = score
                    previous[beat_index, clause_end] = clause_start_index
        if beat_index == 1 or beat_index % 10 == 0 or beat_index == beat_count:
            print(
                f"Căn Beat: {beat_index}/{beat_count} "
                f"(cửa sổ tối đa {max_clause_span} mệnh đề)."
            )
    final_scores = scores[beat_count]
    if not np.any(np.isfinite(final_scores)):
        raise RuntimeError("Could not align CSV beats to script clauses")

    cursor = int(np.nanargmax(final_scores))
    aligned_word_end = clause_ranges[cursor - 1][1]
    unaligned_word_count = len(word_timings) - aligned_word_end
    allowed_trailing_words = max(30, int(round(len(word_timings) * 0.03)))
    can_force_full_coverage = False
    if unaligned_word_count > allowed_trailing_words:
        tail_tokens = _content_tokens(
            item.word for item in word_timings[aligned_word_end:]
        )
        tail_counts = Counter(tail_tokens)
        all_beat_counts: Counter = Counter()
        for counts in beat_token_counts:
            all_beat_counts.update(counts)
        tail_overlap = sum(
            min(count, tail_counts.get(token, 0))
            for token, count in all_beat_counts.items()
        ) / max(1, sum(all_beat_counts.values()))
        average_words_per_beat = len(word_timings) / max(1, beat_count)
        can_force_full_coverage = (
            math.isfinite(final_scores[clause_count])
            and tail_overlap >= 0.08
            and average_words_per_beat <= 120.0
        )
        if can_force_full_coverage:
            cursor = clause_count
            aligned_word_end = len(word_timings)
            unaligned_word_count = 0
    if unaligned_word_count > allowed_trailing_words:
        coverage = aligned_word_end / max(1, len(word_timings))
        raise RuntimeError(
            "Beat CSV chưa bao phủ toàn bộ kịch bản: "
            f"chỉ căn được khoảng {coverage:.0%}, còn "
            f"{unaligned_word_count} từ chưa có Beat. "
            "Hãy bổ sung các dòng Beat còn thiếu trong script_beat.csv."
        )

    boundaries = [cursor]
    for beat_index in range(beat_count, 0, -1):
        cursor = int(previous[beat_index, cursor])
        boundaries.append(cursor)
    boundaries.reverse()
    ranges = [
        (
            clause_ranges[boundaries[index]][0],
            clause_ranges[boundaries[index + 1] - 1][1],
        )
        for index in range(beat_count)
    ]
    if unaligned_word_count:
        ranges[-1] = (ranges[-1][0], len(word_timings))
    return ranges


def create_word_timings(
    config: PipelineConfig,
    script_sections: list[ScriptSection],
    voice_timeline: list[dict],
    skip_whisper: bool,
) -> list[WordTiming]:
    recognized_words = None
    if not skip_whisper:
        try:
            recognized_words = transcribe_voice_timeline(
                config, voice_timeline
            )
        except Exception as exc:
            print(f"Cảnh báo: Whisper transcript thất bại: {exc}")

    all_timings = []
    for section, voice in zip(script_sections, voice_timeline):
        duration = float(voice["duration"])
        offset = float(voice["start"])
        srt_timings = None
        srt_ratio = None
        if voice.get("srt_path"):
            try:
                cues = parse_srt(voice["srt_path"], duration)
                srt_timings, srt_ratio = srt_script_word_timings(
                    section.text, cues, duration
                )
            except Exception as exc:
                print(
                    f"Cảnh báo: SRT của {voice['name']} bị từ chối: {exc}"
                )

        whisper_timings = None
        whisper_ratio = None
        if recognized_words is not None:
            local_words = [
                {
                    **item,
                    "start": float(item["start"]) - offset,
                    "end": float(item["end"]) - offset,
                }
                for item in recognized_words
                if item.get("voice") == voice["name"]
            ]
            try:
                whisper_timings, whisper_ratio = align_script_words(
                    section.text, local_words, duration
                )
            except Exception as exc:
                print(
                    f"Cảnh báo: Căn Whisper thất bại cho "
                    f"{voice['name']}: {exc}"
                )

        if whisper_timings is not None and srt_timings is not None:
            local_timings = merge_hybrid_timings(
                whisper_timings, srt_timings, duration
            )
            source = (
                f"Hybrid SRT + Whisper "
                f"(SRT {srt_ratio:.0%}, Whisper {whisper_ratio:.0%})"
            )
        elif srt_timings is not None:
            local_timings = srt_timings
            source = f"SRT (khớp {srt_ratio:.0%})"
        elif whisper_timings is not None:
            local_timings = whisper_timings
            source = f"Whisper (khớp {whisper_ratio:.0%})"
        else:
            local_timings = estimate_script_words(section.text, duration)
            source = "ước tính dự phòng"
        print(
            f"Timing lời thoại {voice['name']} [{section.name}]: {source}."
        )
        all_timings.extend(_offset_timings(local_timings, offset))
    return all_timings
