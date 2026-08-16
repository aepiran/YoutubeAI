"""Search and download commercially usable music from the public ccMixter API."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from .library import ImportResult, MusicImportMetadata, MusicLibraryService


CCMIXTER_API_URL = "https://ccmixter.org/api/query"
CCMIXTER_CATALOG_URL = "https://ccmixter.org/"
CCMIXTER_TERMS_URL = "https://ccmixter.org/terms"
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024


class MusicCatalogError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogProgress:
    percent: int
    message: str


@dataclass(frozen=True, slots=True)
class CCMixterTrack:
    track_id: str
    title: str
    artist: str
    page_url: str
    download_url: str
    filename: str
    duration_seconds: float
    license_name: str
    license_url: str
    tags: tuple[str, ...]

    @property
    def attribution(self) -> str:
        return (
            f'"{self.title}" by {self.artist} · {self.license_name} · '
            f"{self.license_url} · {self.page_url}"
        )


@dataclass(frozen=True, slots=True)
class CatalogDownloadResult:
    imported: tuple
    skipped: tuple[str, ...]
    attribution_file: Path
    selected_tracks: tuple[CCMixterTrack, ...]


class CCMixterCatalogService:
    """Resolve DNA recommendations into local, attributed library tracks."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        library_service: MusicLibraryService | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.library_service = library_service or MusicLibraryService()
        self.session.headers.setdefault(
            "User-Agent", "StoryFlowStudio/1.0 (+https://ccmixter.org/)"
        )

    def find_and_download(
        self,
        recommendations_file: Path,
        library_folder: str | Path,
        progress: Callable[[CatalogProgress], None] | None = None,
        *,
        max_tracks: int = 3,
    ) -> CatalogDownloadResult:
        report = progress or (lambda _update: None)
        recommendations = self._load_recommendations(recommendations_file)
        if not recommendations:
            raise MusicCatalogError("Không có đề xuất nhạc nào cần tải thêm.")
        selected: list[CCMixterTrack] = []
        imported: list = []
        skipped: list[str] = []
        used_ids: set[str] = set()
        limit = min(max(1, max_tracks), len(recommendations))
        for index, recommendation in enumerate(recommendations[:limit], start=1):
            report(
                CatalogProgress(
                    5 + int((index - 1) / limit * 65),
                    f"Searching ccMixter for {recommendation['section_id']}…",
                )
            )
            track = self._find_track(recommendation, used_ids)
            if track is None:
                skipped.append(
                    f"{recommendation['section_id']}: no suitable CC BY/Public Domain track"
                )
                continue
            used_ids.add(track.track_id)
            with tempfile.TemporaryDirectory(prefix="storyflow-music-") as directory:
                source = Path(directory) / track.filename
                self._download(track, source)
                metadata = MusicImportMetadata(
                    source="ccMixter",
                    source_url=track.page_url,
                    license=track.license_name,
                    license_url=track.license_url,
                    title=track.title,
                    artist=track.artist,
                    attribution=track.attribution,
                )
                result: ImportResult = self.library_service.import_files(
                    [source], library_folder, metadata=metadata
                )
            imported.extend(result.imported)
            skipped.extend(result.skipped)
            if result.imported:
                selected.append(track)
            report(
                CatalogProgress(
                    10 + int(index / limit * 80),
                    f"Downloaded {track.title} by {track.artist}",
                )
            )
        if not imported:
            detail = "; ".join(skipped) or "no matching result"
            raise MusicCatalogError(f"Không tải được track phù hợp: {detail}")
        attribution_file = recommendations_file.parent / "music_attribution.txt"
        self._write_attribution(attribution_file, selected)
        report(
            CatalogProgress(
                100,
                f"Imported {len(imported)} ccMixter track(s) into Music Library.",
            )
        )
        return CatalogDownloadResult(
            tuple(imported), tuple(skipped), attribution_file, tuple(selected)
        )

    def _find_track(
        self, recommendation: dict, used_ids: set[str]
    ) -> CCMixterTrack | None:
        queries = recommendation.get("search_queries", [])
        if not isinstance(queries, list):
            queries = []
        desired = _words(
            " ".join(
                [
                    *[str(item) for item in recommendation.get("desired_mood", [])],
                    str(recommendation.get("energy", "")),
                    str(recommendation.get("tempo", "")),
                    *[str(item) for item in recommendation.get("instruments", [])],
                ]
            )
        )
        avoid = _words(" ".join(str(item) for item in recommendation.get("avoid", [])))
        minimum = max(0.0, float(recommendation.get("minimum_duration_seconds", 0)))
        candidates: dict[str, CCMixterTrack] = {}
        query_tags = []
        for query in [*queries[:2], " ".join(sorted(desired))]:
            tags = _query_tags(str(query))
            if tags and tags not in query_tags:
                query_tags.append(tags)
        for tags in query_tags:
            for track in self._search(tags, "by"):
                if track.track_id not in used_ids:
                    candidates.setdefault(track.track_id, track)
        if not candidates:
            for tags in query_tags:
                for track in self._search(tags, "pd"):
                    if track.track_id not in used_ids:
                        candidates.setdefault(track.track_id, track)
        eligible = [
            track
            for track in candidates.values()
            if not minimum or track.duration_seconds + 0.5 >= minimum
        ]
        if not eligible:
            eligible = list(candidates.values())
        if not eligible:
            return None

        def score(track: CCMixterTrack) -> tuple[int, float]:
            searchable = _words(f"{track.title} {' '.join(track.tags)}")
            value = len(desired & searchable) * 4 - len(avoid & searchable) * 8
            if "instrumental" in searchable:
                value += 5
            if searchable & {"vocal", "vocals", "spoken", "acappella"}:
                value -= 12
            return value, track.duration_seconds

        return max(eligible, key=score)

    def _search(self, tags: str, license_code: str) -> list[CCMixterTrack]:
        try:
            response = self.session.get(
                CCMIXTER_API_URL,
                params={
                    "f": "json",
                    "dataview": "info",
                    "limit": 12,
                    "type": "any",
                    "tags": tags,
                    "lic": license_code,
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise MusicCatalogError(f"ccMixter search failed: {exc}") from exc
        if not isinstance(payload, list):
            raise MusicCatalogError("ccMixter trả về dữ liệu tìm kiếm không hợp lệ.")
        tracks: list[CCMixterTrack] = []
        for item in payload:
            track = _parse_track(item)
            if track is not None:
                tracks.append(track)
        return tracks

    def _download(self, track: CCMixterTrack, destination: Path) -> None:
        try:
            response = self.session.get(track.download_url, stream=True, timeout=60)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not (
                content_type.startswith("audio/")
                or "octet-stream" in content_type
            ):
                raise MusicCatalogError(
                    f"ccMixter returned non-audio content for {track.title}."
                )
            size = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise MusicCatalogError(
                            f"Track vượt quá giới hạn 50 MB: {track.title}"
                        )
                    handle.write(chunk)
            if size == 0:
                raise MusicCatalogError(f"Track tải về đang trống: {track.title}")
        except requests.RequestException as exc:
            raise MusicCatalogError(f"Không tải được {track.title}: {exc}") from exc

    @staticmethod
    def _load_recommendations(path: Path) -> list[dict]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MusicCatalogError(f"Không đọc được music recommendations: {exc}") from exc
        rows = payload.get("recommendations") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise MusicCatalogError("music_recommendations.json không hợp lệ.")
        return rows

    @staticmethod
    def _write_attribution(path: Path, tracks: list[CCMixterTrack]) -> None:
        lines = [
            "Background music downloaded from ccMixter",
            "",
            *[track.attribution for track in tracks],
            "",
            f"ccMixter terms: {CCMIXTER_TERMS_URL}",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_track(item: object) -> CCMixterTrack | None:
    if not isinstance(item, dict):
        return None
    license_url = str(item.get("license_url", "")).replace("http://", "https://")
    if not (
        "creativecommons.org/licenses/by/" in license_url
        or "creativecommons.org/publicdomain/" in license_url
        or "creativecommons.org/public-domain/" in license_url
    ):
        return None
    files = item.get("files")
    if not isinstance(files, list):
        return None
    audio = next(
        (
            file
            for file in files
            if isinstance(file, dict)
            and str(file.get("download_url", "")).startswith("https://ccmixter.org/")
            and Path(str(file.get("file_name", ""))).suffix.lower() == ".mp3"
        ),
        None,
    )
    if audio is None:
        return None
    duration = _duration_seconds(
        audio.get("file_format_info", {}).get("ps", "")
        if isinstance(audio.get("file_format_info"), dict)
        else ""
    )
    title = str(item.get("upload_name", "")).strip()
    artist = str(item.get("user_real_name") or item.get("user_name") or "").strip()
    page_url = str(item.get("file_page_url", "")).strip()
    if not title or not artist or not page_url.startswith("https://ccmixter.org/"):
        return None
    filename = Path(str(audio.get("file_name", ""))).name
    return CCMixterTrack(
        str(item.get("upload_id", "")),
        title,
        artist,
        page_url,
        str(audio["download_url"]),
        filename,
        duration,
        str(item.get("license_name", "Creative Commons Attribution")),
        license_url,
        tuple(
            part.strip().lower()
            for part in str(item.get("upload_tags", "")).split(",")
            if part.strip()
        ),
    )


def _duration_seconds(value: object) -> float:
    parts = str(value).strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return 0.0
    return 0.0


def _words(value: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", value.lower())
        if len(word) > 2 and word not in {"music", "track", "background", "with"}
    }


def _query_tags(value: str) -> str:
    return "+".join(sorted(_words(value)))
