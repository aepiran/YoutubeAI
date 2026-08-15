"""DWG background-music cue parsing and MoviePy mixing helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip, afx


@dataclass(frozen=True)
class MusicCue:
    code: str
    start: float
    end: float
    track: Path
    section: str
    fade_in: float
    fade_out: float
    gain_db: float
    target_lufs: float | None
    notes: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_timestamp(value: str) -> float:
    """Parse MM:SS.mmm or HH:MM:SS.mmm timestamps."""
    parts = value.strip().split(":")
    if len(parts) not in {2, 3}:
        raise ValueError(f"Mốc thời gian nhạc không hợp lệ: {value!r}")
    try:
        seconds = float(parts[-1])
        minutes = int(parts[-2])
        hours = int(parts[-3]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError(f"Mốc thời gian nhạc không hợp lệ: {value!r}") from exc
    result = hours * 3600 + minutes * 60 + seconds
    if result < 0 or minutes < 0 or seconds < 0 or seconds >= 60:
        raise ValueError(f"Mốc thời gian nhạc không hợp lệ: {value!r}")
    return result


def db_to_volume(db: float) -> float:
    return 10 ** (db / 20.0)


def load_music_cues(cue_sheet: Path, music_dir: Path) -> list[MusicCue]:
    """Load and validate a DWG music cue sheet."""
    if not cue_sheet.is_file():
        raise FileNotFoundError(f"Không tìm thấy music cue sheet: {cue_sheet}")
    required = {
        "cue", "start", "end", "track", "crossfade_in_seconds",
        "crossfade_out_seconds", "gain_db",
    }
    with cue_sheet.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_columns = required - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(
                "Music cue sheet thiếu cột: "
                + ", ".join(sorted(missing_columns))
            )
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError(f"Music cue sheet không có cue: {cue_sheet}")

    cues: list[MusicCue] = []
    previous_start = -1.0
    for index, row in enumerate(raw_rows, start=2):
        start = parse_timestamp(row["start"])
        end = parse_timestamp(row["end"])
        if end <= start:
            raise ValueError(f"Cue dòng {index} phải có end > start")
        if start < previous_start:
            raise ValueError(f"Cue dòng {index} không theo thứ tự thời gian")
        previous_start = start
        track = (music_dir / row["track"].strip()).resolve()
        if not track.is_file():
            raise FileNotFoundError(f"Không tìm thấy file nhạc của cue: {track}")
        fade_in = float(row["crossfade_in_seconds"] or 0)
        fade_out = float(row["crossfade_out_seconds"] or 0)
        if fade_in < 0 or fade_out < 0:
            raise ValueError(f"Cue dòng {index} có crossfade âm")
        if fade_in + fade_out > end - start:
            raise ValueError(f"Cue dòng {index} có crossfade dài hơn cue")
        target = (row.get("target_music_lufs") or "").strip()
        cues.append(
            MusicCue(
                code=row["cue"].strip() or f"C{index - 1:02d}",
                start=start,
                end=end,
                track=track,
                section=(row.get("prayer_section") or "").strip(),
                fade_in=fade_in,
                fade_out=fade_out,
                gain_db=float(row["gain_db"]),
                target_lufs=float(target) if target else None,
                notes=(row.get("notes") or "").strip(),
            )
        )
    return cues


def cue_rows_for_duration(cues: list[MusicCue], duration: float) -> list[dict]:
    """Convert cues to portable timeline rows, cropped to the video."""
    rows = []
    for cue in cues:
        start = max(0.0, cue.start)
        end = min(float(duration), cue.end)
        if end <= start:
            continue
        cue_duration = end - start
        rows.append(
            {
                "cue": cue.code,
                "path": str(cue.track),
                "name": cue.track.name,
                "role": "dwg_cue",
                "section": cue.section,
                "timeline_start": round(start, 6),
                "duration": round(cue_duration, 6),
                "source_start": round(start - cue.start, 6),
                "source_duration": round(cue_duration, 6),
                "gain_db": cue.gain_db,
                "volume": db_to_volume(cue.gain_db),
                "fade_in": min(cue.fade_in, cue_duration),
                "fade_out": min(cue.fade_out, cue_duration),
                "target_music_lufs": cue.target_lufs,
                "notes": cue.notes,
                "repeat": False,
            }
        )
    if not rows or not cues:
        return rows
    target_duration = max(0.0, float(duration))
    last_row = max(
        rows,
        key=lambda row: float(row["timeline_start"]) + float(row["duration"]),
    )
    cursor = float(last_row["timeline_start"]) + float(last_row["duration"])
    if cursor >= target_duration - 0.001:
        return rows
    last_cue = next(
        cue for cue in cues if cue.code == str(last_row["cue"])
    )
    loop_duration = last_cue.duration
    extension_index = 1
    while cursor < target_duration - 0.001:
        segment_duration = min(loop_duration, target_duration - cursor)
        rows.append(
            {
                "cue": f"{last_cue.code}-OUTRO-{extension_index:02d}",
                "path": str(last_cue.track),
                "name": last_cue.track.name,
                "role": "dwg_outro_extension",
                "section": "DWG OUTRO",
                "timeline_start": round(cursor, 6),
                "duration": round(segment_duration, 6),
                "source_start": 0.0,
                "source_duration": round(segment_duration, 6),
                "gain_db": last_cue.gain_db,
                "volume": db_to_volume(last_cue.gain_db),
                "fade_in": min(last_cue.fade_in, segment_duration),
                "fade_out": min(last_cue.fade_out, segment_duration),
                "target_music_lufs": last_cue.target_lufs,
                "notes": "Auto-extended final cue to match minimum video duration",
                "repeat": True,
            }
        )
        cursor += segment_duration
        extension_index += 1
    return rows


def load_configured_music_rows(config, duration: float) -> list[dict]:
    if not config.enable_background_music:
        return []
    if config.music_dir is None or config.music_cue_sheet is None:
        return []
    cues = load_music_cues(config.music_cue_sheet, config.music_dir)
    return cue_rows_for_duration(cues, duration)


def mix_audio_with_music(
    narration,
    rows: list[dict],
    root: Path | None = None,
    duration: float | None = None,
):
    """Return (composite, opened music clips); caller closes both."""
    target_duration = max(
        float(narration.duration),
        float(duration) if duration is not None else 0.0,
    )
    if not rows and target_duration <= float(narration.duration) + 0.001:
        return narration, []
    music_clips = []
    for row in rows:
        path = Path(str(row.get("path") or row["file"]))
        if root is not None and not path.is_absolute():
            path = root / path
        source = AudioFileClip(str(path.resolve()))
        source_start = float(row.get("source_start", 0.0))
        requested = float(row["duration"])
        available = max(0.0, float(source.duration) - source_start)
        duration = min(requested, available)
        if duration <= 0:
            source.close()
            raise ValueError(f"Cue nhạc vượt ngoài thời lượng file: {path}")
        clip = source.subclipped(source_start, source_start + duration)
        clip = clip.with_volume_scaled(float(row.get("volume", 1.0)))
        fade_in = min(float(row.get("fade_in", 0.0)), duration)
        fade_out = min(float(row.get("fade_out", 0.0)), duration)
        effects = []
        if fade_in > 0:
            effects.append(afx.AudioFadeIn(fade_in))
        if fade_out > 0:
            effects.append(afx.AudioFadeOut(fade_out))
        if effects:
            clip = clip.with_effects(effects)
        music_clips.append(clip.with_start(float(row["timeline_start"])))
    mixed = CompositeAudioClip([narration, *music_clips]).with_duration(
        target_duration
    )
    return mixed, music_clips
