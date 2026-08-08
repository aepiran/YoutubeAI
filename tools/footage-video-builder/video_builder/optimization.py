"""Stage 6: optimize the combination of shots across the full timeline."""

from __future__ import annotations

import numpy as np

from .models import Candidate, SpeechSegment


REUSE_COOLDOWN_CUTS = 18
REUSE_COOLDOWN_SECONDS = 90.0


def transition_penalty(
    previous: Candidate,
    current: Candidate,
    shared_visual_beat: bool = False,
) -> float:
    if (
        previous.path == current.path
        and previous.candidate_id == current.candidate_id
    ):
        # Restarting the exact same window on the next narration cut is very
        # noticeable: the picture jumps backwards even when a crossfade is
        # enabled. Only allow it when the semantic alternatives are much worse.
        return 1.25
    if previous.path != current.path:
        return 0.0
    overlap = max(
        0.0,
        min(previous.end, current.end) - max(previous.start, current.start),
    )
    if overlap <= 0:
        # Vùng chưa dùng trong cùng source vẫn là hình mới. Ưu tiên đi tới
        # theo thời gian; chỉ quay ngược khi kho candidate không đủ.
        if current.start >= previous.end - 0.05:
            return 0.01
        return 0.72
    overlap_ratio = overlap / max(
        min(previous.duration, current.duration), 0.001
    )
    # Candidate IDs are cheap sliding windows and frequently overlap by more
    # than half their duration. Treat them as the same visual region instead
    # of rewarding an ID change that repeats almost identical frames.
    base = 0.72 if shared_visual_beat else 0.92
    return base + 0.95 * overlap_ratio


def _duration_adjusted_scores(
    segments: list[SpeechSegment],
    candidates: list[Candidate],
    score_matrix: np.ndarray,
) -> np.ndarray:
    """Prefer candidates whose analyzed window covers the requested cut."""
    adjusted = np.asarray(score_matrix, dtype=float).copy()
    analyzed_durations = np.asarray(
        [candidate.duration for candidate in candidates],
        dtype=float,
    )
    for segment_index, segment in enumerate(segments):
        required = max(segment.duration, 0.001)
        # Half a second accounts for transition margins and timing rounding.
        # It must not make a 20-second source look fully analyzed when the
        # scored candidate window covers only seven seconds.
        long_enough = analyzed_durations + 0.50 + 1e-3 >= required
        # If every analyzed window is short, retain the semantic ranking and
        # let the report expose that the renderer had to expand the window.
        if not np.any(long_enough):
            continue
        short = ~long_enough
        shortage = np.maximum(0.0, required - analyzed_durations[short])
        adjusted[segment_index, short] -= 2.0 + shortage / required
    return adjusted


def recent_reuse_penalty(
    history: tuple[int, ...],
    current_index: int,
    candidates: list[Candidate],
    segment_index: int | None = None,
    segments: list[SpeechSegment] | None = None,
) -> float:
    """Apply a visual-region cooldown while allowing unused source intervals."""
    current = candidates[current_index]
    penalty = 0.0
    for distance, previous_index in enumerate(
        reversed(history[-20:]), start=1
    ):
        if distance == 1:
            continue
        previous = candidates[previous_index]
        if previous.path != current.path:
            continue
        time_gap = None
        if segment_index is not None and segments is not None:
            previous_segment = segment_index - distance
            if previous_segment >= 0:
                time_gap = max(
                    0.0,
                    segments[segment_index].start
                    - segments[previous_segment].end,
                )
        if (
            distance > REUSE_COOLDOWN_CUTS
            and (
                time_gap is None
                or time_gap >= REUSE_COOLDOWN_SECONDS
            )
        ):
            continue
        cut_weight = max(
            0.12,
            (REUSE_COOLDOWN_CUTS + 1.0 - distance)
            / REUSE_COOLDOWN_CUTS,
        )
        time_weight = (
            0.0
            if time_gap is None
            else max(
                0.0,
                (REUSE_COOLDOWN_SECONDS - time_gap)
                / REUSE_COOLDOWN_SECONDS,
            )
        )
        cooldown_weight = max(cut_weight, time_weight, 0.12)
        if (
            previous.path == current.path
            and previous.candidate_id == current.candidate_id
        ):
            penalty += 1.80 * cooldown_weight
            continue
        overlap = max(
            0.0,
            min(previous.end, current.end)
            - max(previous.start, current.start),
        )
        if overlap > 0:
            overlap_ratio = overlap / max(
                min(previous.duration, current.duration), 0.001
            )
            if overlap_ratio >= 0.20:
                penalty += 1.35 * overlap_ratio * cooldown_weight
        if current.start < previous.start - 0.05:
            # Going backwards in one source is allowed, but prefer consuming
            # its unused timeline in a forward direction first.
            penalty += 0.12 * cooldown_weight
    return penalty


def violates_recent_visual_reuse(
    history: tuple[int, ...],
    current_index: int,
    candidates: list[Candidate],
    segment_index: int,
    segments: list[SpeechSegment],
) -> bool:
    """Reject a repeated visual region nearby when a safe option exists."""
    current = candidates[current_index]
    for distance, previous_index in enumerate(reversed(history), start=1):
        previous = candidates[previous_index]
        previous_segment = segment_index - distance
        time_gap = (
            segments[segment_index].start - segments[previous_segment].end
            if previous_segment >= 0
            else 0.0
        )
        if distance > REUSE_COOLDOWN_CUTS and time_gap >= REUSE_COOLDOWN_SECONDS:
            break
        if (
            previous.path == current.path
            and previous.candidate_id == current.candidate_id
        ):
            return True
        if previous.path != current.path:
            continue
        if distance == 1 and current.start < previous.end - 0.05:
            # Hai Cut kề nhau dùng cùng file phải tiến đến vùng nguồn mới.
            # Caller chỉ fallback về vùng này nếu không có lựa chọn an toàn.
            return True
        overlap = max(
            0.0,
            min(previous.end, current.end)
            - max(previous.start, current.start),
        )
        overlap_ratio = overlap / max(
            min(previous.duration, current.duration), 0.001
        )
        if overlap_ratio >= 0.20:
            return True
    return False


def _candidate_shortlist(
    row_scores: np.ndarray,
    candidates: list[Candidate],
    identity_row: np.ndarray | None = None,
    limit: int = 64,
) -> list[int]:
    """Keep strong candidates and enough Beat-owned temporal alternatives."""
    ranked = np.argsort(row_scores)[::-1]
    selected = []
    per_path: dict[object, int] = {}
    for raw_index in ranked:
        index = int(raw_index)
        if row_scores[index] <= -1e5:
            continue
        path = candidates[index].path
        is_matching = bool(
            identity_row is not None and identity_row[index] >= 0.5
        )
        per_path_limit = 12 if is_matching else 4
        if per_path.get(path, 0) >= per_path_limit:
            continue
        selected.append(index)
        per_path[path] = per_path.get(path, 0) + 1
        if len(selected) >= limit:
            break
    if not selected:
        selected = [int(np.argmax(row_scores))]
    return selected


def _fallback_source_reuse_penalty(
    history: tuple[int, ...],
    current_index: int,
    segment_index: int,
    candidates: list[Candidate],
    beat_identity: np.ndarray | None,
) -> float:
    """Avoid turning one generic cross-Beat source into a global fallback."""
    if beat_identity is None or beat_identity[segment_index, current_index] >= 0.5:
        return 0.0
    current_path = candidates[current_index].path
    # Một vùng đúng Beat nhưng chưa dùng phải thắng fallback có điểm gần bằng.
    # Fallback vẫn được chọn khi nguồn đúng Beat thiếu hoặc semantic tốt hơn rõ.
    penalty = 0.10
    for distance, previous_index in enumerate(
        reversed(history[-8:]), start=1
    ):
        previous_segment = segment_index - distance
        if (
            candidates[previous_index].path == current_path
            and previous_segment >= 0
            and beat_identity[previous_segment, previous_index] < 0.5
        ):
            penalty += 0.32 / max(distance ** 0.5, 1.0)
    return penalty


def select_global_timeline(
    segments: list[SpeechSegment],
    candidates: list[Candidate],
    score_matrix: np.ndarray,
    score_components: dict[str, np.ndarray] | None = None,
) -> tuple[list[Candidate], list[float], float]:
    """Allocate unused matching regions, then suitable fallback/reused shots."""
    segment_count, candidate_count = score_matrix.shape
    if segment_count == 0 or candidate_count == 0:
        raise ValueError("Timeline optimization requires segments and candidates")
    adjusted_scores = _duration_adjusted_scores(
        segments, candidates, score_matrix
    )
    components = score_components or {}
    beat_identity = components.get("beat_identity_score")
    fallback_eligible = components.get("fallback_eligible")
    if beat_identity is not None and beat_identity.shape != adjusted_scores.shape:
        raise ValueError("beat_identity_score shape must match score_matrix")
    if fallback_eligible is not None:
        if fallback_eligible.shape != adjusted_scores.shape:
            raise ValueError("fallback_eligible shape must match score_matrix")
        eligible = fallback_eligible >= 0.5
        if beat_identity is not None:
            eligible |= beat_identity >= 0.5
        for segment_index in range(segment_count):
            if np.any(eligible[segment_index]):
                adjusted_scores[segment_index, ~eligible[segment_index]] = -1e6

    beam_width = 192
    first_candidates = _candidate_shortlist(
        adjusted_scores[0],
        candidates,
        beat_identity[0] if beat_identity is not None else None,
    )
    beam = [
        (float(adjusted_scores[0, index]), (index,))
        for index in first_candidates
    ]
    beam.sort(key=lambda item: item[0], reverse=True)
    beam = beam[:beam_width]

    for segment_index in range(1, segment_count):
        previous_beats = {
            beat.number for beat in segments[segment_index - 1].beats
        }
        current_beats = {
            beat.number for beat in segments[segment_index].beats
        }
        shared_visual_beat = bool(previous_beats & current_beats)
        current_candidates = _candidate_shortlist(
            adjusted_scores[segment_index],
            candidates,
            (
                beat_identity[segment_index]
                if beat_identity is not None
                else None
            ),
        )
        next_states: dict[tuple[int, ...], float] = {}
        for accumulated, history in beam:
            previous = candidates[history[-1]]
            safe_candidates = [
                current_index
                for current_index in current_candidates
                if not violates_recent_visual_reuse(
                    history,
                    current_index,
                    candidates,
                    segment_index,
                    segments,
                )
            ]
            choices = safe_candidates or current_candidates
            for current_index in choices:
                current = candidates[current_index]
                score = (
                    accumulated
                    + float(adjusted_scores[segment_index, current_index])
                    - transition_penalty(
                        previous, current, shared_visual_beat
                    )
                    - recent_reuse_penalty(
                        history,
                        current_index,
                        candidates,
                        segment_index,
                        segments,
                    )
                    - _fallback_source_reuse_penalty(
                        history,
                        current_index,
                        segment_index,
                        candidates,
                        beat_identity,
                    )
                )
                new_history = (*history, current_index)
                existing = next_states.get(new_history)
                if existing is None or score > existing:
                    next_states[new_history] = score
        beam = sorted(
            (
                (score, history)
                for history, score in next_states.items()
            ),
            key=lambda item: item[0],
            reverse=True,
        )[:beam_width]
        if not beam:
            raise RuntimeError("Could not choose a footage timeline")

    total_score, best_history = beam[0]
    choices = list(best_history)
    return (
        [candidates[index] for index in choices],
        [
            float(score_matrix[index, candidate_index])
            for index, candidate_index in enumerate(choices)
        ],
        float(total_score),
    )
