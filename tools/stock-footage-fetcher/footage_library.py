"""Shared footage library with atomic catalog and project materialization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
SOURCE_NAME_PATTERN = re.compile(
    r"^(?:[A-Za-z]+\d+_)?(?P<provider>[A-Za-z][A-Za-z0-9-]*)_"
    r"(?P<video_id>[^._]+)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ArchiveResult:
    imported: int = 0
    duplicates: int = 0
    linked: int = 0
    copied_back: int = 0
    failed: int = 0
    asset_ids: dict[str, str] = field(default_factory=dict)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return cleaned or fallback


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _load_manifest_rows(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("selections", [])
        except (OSError, ValueError, TypeError):
            continue
        for row in rows if isinstance(rows, list) else []:
            filename = str(row.get("filename") or "")
            if filename:
                result[filename.casefold()] = dict(row)
    return result


def online_project_footage_filenames(
    output_dir: Path,
    manifest_paths: Iterable[Path] = (),
) -> list[str]:
    """Return project files downloaded online, excluding library reuse/manual media."""
    if not output_dir.is_dir():
        return []
    metadata_by_name = _load_manifest_rows(manifest_paths)
    result: list[str] = []
    for path in output_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        metadata = metadata_by_name.get(path.name.casefold())
        if metadata is not None:
            provider = str(metadata.get("provider") or "").casefold()
            origin = str(metadata.get("origin") or "online").casefold()
            status = str(metadata.get("status") or "downloaded").casefold()
            if (
                provider in {"pexels", "pixabay"}
                and origin != "library"
                and status == "downloaded"
            ):
                result.append(path.name)
            continue
        match = SOURCE_NAME_PATTERN.match(path.name)
        if match and match.group("provider").casefold() in {"pexels", "pixabay"}:
            result.append(path.name)
    return sorted(set(result), key=str.casefold)


def _video_metadata(path: Path, thumbnail: Path) -> dict[str, Any]:
    """Read one frame and technical metadata with the bundled FFmpeg binary."""
    try:
        import imageio_ffmpeg

        frames = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgb24")
        metadata = next(frames)
        frame = next(frames)
        frames.close()
        width, height = metadata.get("size") or (0, 0)
        if width and height:
            image = Image.frombytes("RGB", (int(width), int(height)), frame)
            image.thumbnail((640, 360), Image.Resampling.LANCZOS)
            thumbnail.parent.mkdir(parents=True, exist_ok=True)
            image.save(thumbnail, "JPEG", quality=86, optimize=True)
        return {
            "width": int(width or 0),
            "height": int(height or 0),
            "duration": float(metadata.get("duration") or 0),
            "fps": float(metadata.get("fps") or 0),
        }
    except (ImportError, OSError, RuntimeError, StopIteration, ValueError):
        return {"width": 0, "height": 0, "duration": 0.0, "fps": 0.0}


class FootageLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.assets_dir = self.root / "assets"
        self.thumbnails_dir = self.root / "thumbnails"
        self.database_path = self.root / "catalog.sqlite"
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    canonical_path TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL UNIQUE,
                    preview_path TEXT NOT NULL DEFAULT '',
                    width INTEGER NOT NULL DEFAULT 0,
                    height INTEGER NOT NULL DEFAULT 0,
                    duration REAL NOT NULL DEFAULT 0,
                    fps REAL NOT NULL DEFAULT 0,
                    contributor TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '',
                    queries TEXT NOT NULL DEFAULT '[]',
                    page_url TEXT NOT NULL DEFAULT '',
                    visual_hash TEXT NOT NULL DEFAULT '',
                    search_text TEXT NOT NULL DEFAULT '',
                    downloaded_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS assets_provider_video
                    ON assets(provider, video_id);
                CREATE INDEX IF NOT EXISTS assets_search_text
                    ON assets(search_text);
                CREATE TABLE IF NOT EXISTS usages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
                    project_path TEXT NOT NULL,
                    beat_id TEXT NOT NULL DEFAULT '',
                    query TEXT NOT NULL DEFAULT '',
                    semantic_score REAL,
                    used_at TEXT NOT NULL,
                    UNIQUE(asset_id, project_path, beat_id, query)
                );
                """
            )

    def _find_asset(
        self,
        connection: sqlite3.Connection,
        *,
        provider: str,
        video_id: str,
        sha256: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM assets
            WHERE sha256 = ? OR (provider = ? AND video_id = ?)
            LIMIT 1
            """,
            (sha256, provider, video_id),
        ).fetchone()

    @staticmethod
    def _merge_asset_metadata(
        connection: sqlite3.Connection,
        asset_id: str,
        metadata: dict[str, Any],
    ) -> None:
        row = connection.execute(
            "SELECT queries, tags, search_text FROM assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            return
        try:
            queries = list(json.loads(row["queries"] or "[]"))
        except (ValueError, TypeError):
            queries = []
        query = str(metadata.get("query") or "").strip()
        if query and query.casefold() not in {item.casefold() for item in queries}:
            queries.append(query)
        old_tags = [item.strip() for item in str(row["tags"] or "").split(",") if item.strip()]
        new_tags = [
            item.strip()
            for item in str(metadata.get("tags") or "").split(",")
            if item.strip()
        ]
        tags = list(dict.fromkeys([*old_tags, *new_tags]))
        search_text = str(row["search_text"] or "").casefold()
        for part in [query, *new_tags]:
            normalized = part.casefold()
            if normalized and normalized not in search_text:
                search_text = f"{search_text} {normalized}".strip()
        connection.execute(
            """
            UPDATE assets
            SET queries = ?, tags = ?, search_text = ?, updated_at = ?
            WHERE asset_id = ?
            """,
            (
                json.dumps(queries, ensure_ascii=False),
                ", ".join(tags),
                search_text,
                _timestamp(),
                asset_id,
            ),
        )

    @staticmethod
    def _replace_with_library_link(source: Path, canonical: Path) -> str:
        """Replace a project duplicate without risking the only local copy."""
        try:
            if source.samefile(canonical):
                return "linked"
        except OSError:
            pass
        backup = source.with_name(f".{source.name}.library-backup")
        if backup.exists():
            backup.unlink()
        source.replace(backup)
        try:
            os.link(canonical, source)
            backup.unlink()
            return "linked"
        except OSError:
            if source.exists():
                source.unlink()
            backup.replace(source)
            return "kept"

    @staticmethod
    def _restore_project_reference(source: Path, canonical: Path) -> str:
        try:
            os.link(canonical, source)
            return "linked"
        except OSError:
            shutil.copy2(canonical, source)
            return "copied"

    def archive_project(
        self,
        project_dir: Path,
        *,
        output_dir: Path | None = None,
        manifest_paths: Iterable[Path] = (),
        filenames: Iterable[str] | None = None,
    ) -> ArchiveResult:
        """Store selected project footage and retain working references."""
        project_dir = project_dir.expanduser().resolve()
        output_dir = (output_dir or project_dir / "video").resolve()
        result = ArchiveResult()
        if not output_dir.is_dir():
            return result
        metadata_by_name = _load_manifest_rows(manifest_paths)
        selected_names = (
            {name.casefold() for name in filenames if name}
            if filenames is not None
            else None
        )
        files = [
            path
            for path in output_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in VIDEO_EXTENSIONS
            and self.root not in path.parents
            and (
                selected_names is None
                or path.name.casefold() in selected_names
            )
        ]
        for source in files:
            try:
                metadata = metadata_by_name.get(source.name.casefold(), {})
                name_match = SOURCE_NAME_PATTERN.match(source.name)
                provider = str(
                    metadata.get("provider")
                    or (name_match.group("provider") if name_match else "manual")
                ).lower()
                known_video_id = str(
                    metadata.get("video_id")
                    or (name_match.group("video_id") if name_match else "")
                )
                if known_video_id:
                    with closing(self._connect()) as connection, connection:
                        known = connection.execute(
                            "SELECT * FROM assets WHERE provider = ? AND video_id = ?",
                            (provider, known_video_id),
                        ).fetchone()
                        if known is not None:
                            canonical = Path(known["canonical_path"])
                            try:
                                already_linked = canonical.is_file() and source.samefile(canonical)
                            except OSError:
                                already_linked = False
                            if already_linked:
                                result.duplicates += 1
                                result.linked += 1
                                result.asset_ids[source.name] = str(known["asset_id"])
                                self._merge_asset_metadata(
                                    connection, str(known["asset_id"]), metadata
                                )
                                self._record_usage(
                                    connection,
                                    str(known["asset_id"]),
                                    project_dir,
                                    metadata,
                                )
                                continue
                sha256 = file_sha256(source)
                video_id = str(
                    known_video_id or sha256[:24]
                )
                with closing(self._connect()) as connection, connection:
                    existing = self._find_asset(
                        connection,
                        provider=provider,
                        video_id=video_id,
                        sha256=sha256,
                    )
                    if existing is not None:
                        canonical = Path(existing["canonical_path"])
                        if canonical.is_file():
                            mode = self._replace_with_library_link(source, canonical)
                            result.duplicates += 1
                            result.linked += mode == "linked"
                            result.asset_ids[source.name] = str(existing["asset_id"])
                            self._merge_asset_metadata(
                                connection, str(existing["asset_id"]), metadata
                            )
                            self._record_usage(
                                connection,
                                str(existing["asset_id"]),
                                project_dir,
                                metadata,
                            )
                            continue

                safe_provider = _safe_component(provider, "manual")
                safe_id = _safe_component(video_id, sha256[:24])
                canonical = self.assets_dir / safe_provider / f"{safe_id}{source.suffix.lower()}"
                canonical.parent.mkdir(parents=True, exist_ok=True)
                if canonical.exists():
                    canonical = canonical.with_name(f"{safe_id}-{sha256[:10]}{source.suffix.lower()}")
                shutil.move(str(source), str(canonical))
                reference_mode = self._restore_project_reference(source, canonical)
                thumbnail = self.thumbnails_dir / safe_provider / f"{safe_id}.jpg"
                technical = _video_metadata(canonical, thumbnail)
                width = int(metadata.get("width") or technical["width"])
                height = int(metadata.get("height") or technical["height"])
                duration = float(metadata.get("duration") or technical["duration"])
                query = str(metadata.get("query") or "").strip()
                tags = str(metadata.get("tags") or "").strip()
                search_text = " ".join(
                    part for part in (query, tags, source.stem, metadata.get("contributor", ""))
                    if str(part).strip()
                ).casefold()
                asset_id = f"{safe_provider}:{safe_id}"
                now = _timestamp()
                with closing(self._connect()) as connection, connection:
                    connection.execute(
                        """
                        INSERT INTO assets (
                            asset_id, provider, video_id, canonical_path, sha256,
                            preview_path, width, height, duration, fps, contributor,
                            tags, queries, page_url, visual_hash, search_text,
                            downloaded_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset_id, safe_provider, safe_id, str(canonical), sha256,
                            str(thumbnail) if thumbnail.is_file() else "", width, height,
                            duration, float(technical["fps"]),
                            str(metadata.get("contributor") or ""), tags,
                            json.dumps([query] if query else [], ensure_ascii=False),
                            str(metadata.get("page_url") or ""),
                            str(metadata.get("visual_hash") or ""), search_text,
                            str(metadata.get("selected_at") or now), now,
                        ),
                    )
                    self._record_usage(connection, asset_id, project_dir, metadata)
                result.imported += 1
                result.asset_ids[source.name] = asset_id
                result.linked += reference_mode == "linked"
                result.copied_back += reference_mode == "copied"
            except (OSError, ValueError, sqlite3.Error):
                result.failed += 1
        return result

    @staticmethod
    def _record_usage(
        connection: sqlite3.Connection,
        asset_id: str,
        project_dir: Path,
        metadata: dict[str, Any],
    ) -> None:
        score = metadata.get("semantic_score")
        try:
            normalized_score = float(score) if score not in {None, ""} else None
        except (TypeError, ValueError):
            normalized_score = None
        connection.execute(
            """
            INSERT OR IGNORE INTO usages (
                asset_id, project_path, beat_id, query, semantic_score, used_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                str(project_dir),
                str(metadata.get("beat_id") or ""),
                str(metadata.get("query") or ""),
                normalized_score,
                _timestamp(),
            ),
        )

    def search(
        self,
        query: str,
        *,
        min_width: int,
        min_height: int,
        min_duration: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", query.casefold())
            if len(token) > 1
        }
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT assets.*, COUNT(usages.id) AS use_count
                FROM assets
                LEFT JOIN usages ON usages.asset_id = assets.asset_id
                WHERE width >= ? AND height >= ? AND duration >= ?
                GROUP BY assets.asset_id
                """,
                (min_width, min_height, min_duration),
            ).fetchall()
        ranked = []
        for row in rows:
            canonical = Path(row["canonical_path"])
            preview = Path(row["preview_path"]) if row["preview_path"] else None
            if not canonical.is_file() or preview is None or not preview.is_file():
                continue
            haystack = str(row["search_text"] or "")
            overlap = sum(1 for token in tokens if token in haystack)
            ranked.append((overlap, -int(row["use_count"] or 0), dict(row)))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[: max(1, limit)]]

    def materialize(self, canonical: Path, destination: Path) -> str:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and destination.stat().st_size > 0:
            return "existing"
        try:
            os.link(canonical, destination)
            return "hardlink"
        except OSError:
            shutil.copy2(canonical, destination)
            return "copy"

    def record_candidate_usage(
        self,
        asset_id: str,
        project_dir: Path,
        *,
        beat_id: str,
        query: str,
        semantic_score: float,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            self._merge_asset_metadata(
                connection,
                asset_id,
                {"query": query},
            )
            self._record_usage(
                connection,
                asset_id,
                project_dir.resolve(),
                {
                    "beat_id": beat_id,
                    "query": query,
                    "semantic_score": semantic_score,
                },
            )
