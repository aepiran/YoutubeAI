"""Pexels/Pixabay footage finder without video-building responsibilities."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

import requests

from ...core.settings import AppSettings, FootageSettings
from ..workspace import Project


PEXELS_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"
FOOTAGE_COLUMNS = ("ma_beat", "y_chinh", "tu_khoa", "hinh_can_tim", "tranh")
SELECTION_COLUMNS = (
    "beat_id",
    "rank",
    "provider",
    "video_id",
    "query",
    "score",
    "width",
    "height",
    "duration",
    "contributor",
    "page_url",
    "filename",
    "status",
    "error",
)


class FootageWorkflowError(RuntimeError):
    pass


class Cancellation(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


@dataclass(frozen=True, slots=True)
class FootageCandidate:
    provider: str
    video_id: str
    page_url: str
    download_url: str
    preview_url: str
    width: int
    height: int
    duration: float
    contributor: str = ""
    tags: str = ""
    query: str = ""
    popularity: float = 0.0
    score: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.video_id}"


@dataclass(frozen=True, slots=True)
class FootageSelection:
    beat_id: str
    rank: int
    provider: str
    video_id: str
    query: str
    score: float
    width: int
    height: int
    duration: float
    contributor: str
    page_url: str
    filename: str
    status: str
    error: str = ""

    def csv_row(self) -> dict[str, str | int | float]:
        return {name: getattr(self, name) for name in SELECTION_COLUMNS}


@dataclass(frozen=True, slots=True)
class FootageProgress:
    stage: str
    state: str
    percent: int | None
    message: str


@dataclass(frozen=True, slots=True)
class FootageWorkflowResult:
    output_dir: Path
    manifest_file: Path
    manifest_csv: Path
    downloaded_count: int
    planned_count: int
    beat_count: int


class SearchProvider(Protocol):
    name: str

    def search(
        self,
        query: str,
        settings: FootageSettings,
        cancellation: Cancellation,
    ) -> list[FootageCandidate]: ...


class JsonSearchCache:
    def __init__(self, root: Path, ttl_seconds: int = 86400) -> None:
        self.root = root
        self.ttl_seconds = max(86400, ttl_seconds)

    def _path(self, provider: str, params: dict[str, Any]) -> Path:
        encoded = json.dumps(params, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return self.root / provider / f"{digest}.json"

    def get(self, provider: str, params: dict[str, Any]) -> dict | None:
        path = self._path(provider, params)
        if not path.is_file() or time.time() - path.stat().st_mtime > self.ttl_seconds:
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def put(self, provider: str, params: dict[str, Any], value: dict) -> None:
        path = self._path(provider, params)
        _atomic_json(path, value)


class _HttpProvider:
    name = "provider"

    def __init__(
        self,
        api_key: str,
        cache: JsonSearchCache,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.cache = cache
        self.session = session or requests.Session()

    def _json(
        self,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict:
        cached = self.cache.get(self.name, params)
        if cached is not None:
            return cached
        response = self.session.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 429:
            raise FootageWorkflowError(f"{self.name} API rate limit exceeded.")
        if response.status_code in {401, 403}:
            raise FootageWorkflowError(f"{self.name} API rejected the configured key.")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise FootageWorkflowError(f"{self.name} API returned invalid JSON.")
        self.cache.put(self.name, params, value)
        return value


class PexelsProvider(_HttpProvider):
    name = "pexels"

    def search(
        self,
        query: str,
        settings: FootageSettings,
        cancellation: Cancellation,
    ) -> list[FootageCandidate]:
        found: list[FootageCandidate] = []
        for page in range(1, settings.max_pages + 1):
            cancellation.raise_if_cancelled()
            params = {
                "query": query,
                "orientation": "landscape",
                "size": "medium",
                "locale": "en-US",
                "page": page,
                "per_page": min(80, settings.per_page),
            }
            payload = self._json(
                PEXELS_SEARCH_URL,
                params,
                {"Authorization": self.api_key},
            )
            videos = payload.get("videos")
            if not isinstance(videos, list) or not videos:
                break
            for video in videos:
                candidate = _pexels_candidate(video, query, settings)
                if candidate is not None:
                    found.append(candidate)
        return found


class PixabayProvider(_HttpProvider):
    name = "pixabay"

    def search(
        self,
        query: str,
        settings: FootageSettings,
        cancellation: Cancellation,
    ) -> list[FootageCandidate]:
        found: list[FootageCandidate] = []
        for page in range(1, settings.max_pages + 1):
            cancellation.raise_if_cancelled()
            params = {
                "key": self.api_key,
                "q": query[:100],
                "lang": "en",
                "video_type": "film",
                "min_width": settings.min_width,
                "min_height": settings.min_height,
                "safesearch": "true",
                "order": "popular",
                "page": page,
                "per_page": min(80, settings.per_page),
            }
            cache_params = {key: value for key, value in params.items() if key != "key"}
            cached = self.cache.get(self.name, cache_params)
            if cached is None:
                response = self.session.get(PIXABAY_SEARCH_URL, params=params, timeout=30)
                if response.status_code == 429:
                    raise FootageWorkflowError("pixabay API rate limit exceeded.")
                if response.status_code in {400, 401, 403}:
                    raise FootageWorkflowError("pixabay API rejected the configured key.")
                response.raise_for_status()
                cached = response.json()
                if not isinstance(cached, dict):
                    raise FootageWorkflowError("pixabay API returned invalid JSON.")
                self.cache.put(self.name, cache_params, cached)
            videos = cached.get("hits")
            if not isinstance(videos, list) or not videos:
                break
            for video in videos:
                candidate = _pixabay_candidate(video, query, settings)
                if candidate is not None:
                    found.append(candidate)
        return found


ProviderFactory = Callable[[FootageSettings, Path], list[SearchProvider]]


class FootageWorkflowService:
    def __init__(
        self,
        provider_factory: ProviderFactory | None = None,
        download_session: requests.Session | None = None,
    ) -> None:
        self.provider_factory = provider_factory or self._providers
        self.download_session = download_session or requests.Session()

    @staticmethod
    def _providers(settings: FootageSettings, cache_dir: Path) -> list[SearchProvider]:
        cache = JsonSearchCache(cache_dir)
        providers: list[SearchProvider] = []
        if settings.use_pexels:
            providers.append(PexelsProvider(settings.pexels_api_key, cache))
        if settings.use_pixabay:
            providers.append(PixabayProvider(settings.pixabay_api_key, cache))
        return providers

    def run(
        self,
        project: Project,
        settings: AppSettings,
        progress: Callable[[FootageProgress], None],
        cancellation: Cancellation,
    ) -> FootageWorkflowResult:
        value = settings.normalized().footage
        _validate_settings(value)
        beat_file = project.path_for("beat_file")
        rows = _load_beat_rows(beat_file)
        output_dir = project.path_for("footage_dir")
        manifest_file = project.path_for("footage_manifest")
        manifest_csv = project.path_for("footage_manifest_csv")
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = project.metadata_dir / "cache" / "stock-search"
        providers = self.provider_factory(value, cache_dir)
        if not providers:
            raise FootageWorkflowError("Hãy bật ít nhất một Footage provider.")
        selections = _load_selections(manifest_file)
        completed_by_beat = _completed_inventory(selections, output_dir)
        used_keys = {
            f"{item.provider}:{item.video_id}"
            for item in selections
            if item.status == "downloaded"
        }
        file_counts, file_keys = _file_inventory(output_dir)
        for beat_id, count in file_counts.items():
            completed_by_beat[beat_id] = max(
                completed_by_beat.get(beat_id, 0), count
            )
        used_keys.update(file_keys)
        pixabay_downloads = sum(
            1 for candidate_key in used_keys if candidate_key.startswith("pixabay:")
        )
        progress(
            FootageProgress(
                "footage",
                "running",
                5,
                f"Loaded {len(rows)} beats · {len(providers)} providers",
            )
        )
        missing: list[str] = []
        for position, row in enumerate(rows, start=1):
            cancellation.raise_if_cancelled()
            beat_id = row["ma_beat"]
            existing = completed_by_beat.get(beat_id, 0)
            needed = max(0, value.clips_per_beat - existing)
            percent = 8 + int(82 * (position - 1) / max(1, len(rows)))
            if needed == 0:
                progress(
                    FootageProgress(
                        "footage", "running", percent, f"{beat_id} · already complete"
                    )
                )
                continue
            candidates: dict[str, FootageCandidate] = {}
            errors: list[str] = []
            for query in parse_queries(row.get("tu_khoa", ""), value.max_queries):
                for provider in providers:
                    try:
                        for candidate in provider.search(query, value, cancellation):
                            if candidate.key not in used_keys:
                                current = candidates.get(candidate.key)
                                if current is None or candidate.score > current.score:
                                    candidates[candidate.key] = candidate
                    except (requests.RequestException, FootageWorkflowError) as exc:
                        errors.append(str(exc))
            ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
            chosen: list[FootageCandidate] = []
            for candidate in ranked:
                if candidate.provider == "pixabay" and (
                    pixabay_downloads + len(
                        [item for item in chosen if item.provider == "pixabay"]
                    )
                    >= value.max_pixabay_downloads
                ):
                    continue
                chosen.append(candidate)
                if len(chosen) >= needed:
                    break
            if len(chosen) < needed:
                missing.append(beat_id)
            for candidate in chosen:
                cancellation.raise_if_cancelled()
                rank = existing + 1 + sum(
                    1
                    for item in selections
                    if item.beat_id == beat_id and item.status == "planned"
                )
                filename = (
                    f"{beat_id}_{candidate.provider.upper()}_"
                    f"{_safe_id(candidate.video_id)}.mp4"
                )
                status = "planned" if value.dry_run else "downloaded"
                error = ""
                if not value.dry_run:
                    try:
                        _download_video(
                            self.download_session,
                            candidate.download_url,
                            output_dir / filename,
                            cancellation,
                        )
                    except (
                        OSError,
                        requests.RequestException,
                        FootageWorkflowError,
                    ) as exc:
                        status = "failed"
                        error = str(exc)
                        missing.append(beat_id)
                selection = FootageSelection(
                    beat_id,
                    rank,
                    candidate.provider,
                    candidate.video_id,
                    candidate.query,
                    round(candidate.score, 6),
                    candidate.width,
                    candidate.height,
                    candidate.duration,
                    candidate.contributor,
                    candidate.page_url,
                    filename,
                    status,
                    error,
                )
                selections.append(selection)
                used_keys.add(candidate.key)
                if status == "downloaded":
                    existing += 1
                    completed_by_beat[beat_id] = existing
                    if candidate.provider == "pixabay":
                        pixabay_downloads += 1
                _save_manifests(
                    manifest_file,
                    manifest_csv,
                    beat_file,
                    selections,
                    len(rows),
                )
            detail = f"{beat_id} · selected {len(chosen)}/{needed}"
            if errors and not chosen:
                detail += f" · {errors[0]}"
            progress(FootageProgress("footage", "running", percent, detail))
        downloaded = sum(
            1
            for item in output_dir.iterdir()
            if item.is_file() and item.suffix.lower() == ".mp4"
        )
        planned = sum(item.status == "planned" for item in selections)
        _save_manifests(
            manifest_file,
            manifest_csv,
            beat_file,
            selections,
            len(rows),
            complete=not missing and not value.dry_run,
        )
        if missing:
            unique_missing = list(dict.fromkeys(missing))
            raise FootageWorkflowError(
                "Chưa đủ footage cho Beat: " + ", ".join(unique_missing)
            )
        message = (
            f"Planned {planned} clips · no MP4 downloaded"
            if value.dry_run
            else f"Downloaded {downloaded} clips for {len(rows)} beats"
        )
        progress(FootageProgress("footage", "completed", 100, message))
        return FootageWorkflowResult(
            output_dir,
            manifest_file,
            manifest_csv,
            downloaded,
            planned,
            len(rows),
        )

    @staticmethod
    def write_supplement_request(
        project: Project, missing_beats: tuple[str, ...] | list[str]
    ) -> Path:
        """Write the original search rows for Beats missing from a video plan."""

        rows = _load_beat_rows(project.path_for("beat_file"))
        requested = {
            str(beat_id).strip().upper() for beat_id in missing_beats if str(beat_id).strip()
        }
        selected = [row for row in rows if row["ma_beat"] in requested]
        found = {row["ma_beat"] for row in selected}
        unknown = sorted(requested - found)
        if unknown:
            raise FootageWorkflowError(
                "Beat thiếu footage không có trong footage.csv: " + ", ".join(unknown)
            )
        if not selected:
            raise FootageWorkflowError("Không có Beat thiếu footage để tạo file bổ sung.")
        output = project.root / "footage_supplement.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            delete=False,
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
        )
        temporary = Path(handle.name)
        try:
            with handle:
                writer = csv.DictWriter(handle, fieldnames=FOOTAGE_COLUMNS)
                writer.writeheader()
                writer.writerows(
                    {column: row[column] for column in FOOTAGE_COLUMNS}
                    for row in selected
                )
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
        return output


def parse_queries(value: str, maximum: int = 3) -> list[str]:
    clean = (value or "").strip()
    if not clean:
        return []
    separator = r"[|;\n]+" if re.search(r"[|;\n]", clean) else r",+"
    result: list[str] = []
    seen: set[str] = set()
    for item in re.split(separator, clean):
        query = re.sub(r"\s+", " ", item).strip(" ,")[:100]
        key = query.casefold()
        if query and key not in seen:
            result.append(query)
            seen.add(key)
        if len(result) >= maximum:
            break
    return result


def _pexels_candidate(
    video: dict, query: str, settings: FootageSettings
) -> FootageCandidate | None:
    video_id = str(video.get("id") or "")
    duration = float(video.get("duration") or 0)
    if not video_id:
        return None
    if duration < settings.min_duration:
        return None
    files = video.get("video_files") if isinstance(video.get("video_files"), list) else []
    qualified = [
        item
        for item in files
        if item.get("link")
        and int(item.get("width") or 0) >= settings.min_width
        and int(item.get("height") or 0) >= settings.min_height
        and int(item.get("width") or 0) >= int(item.get("height") or 0)
    ]
    if not qualified:
        return None
    best = max(qualified, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0))
    user = video.get("user") if isinstance(video.get("user"), dict) else {}
    width, height = int(best.get("width") or 0), int(best.get("height") or 0)
    return FootageCandidate(
        "pexels",
        video_id,
        str(video.get("url") or ""),
        str(best.get("link") or ""),
        str(video.get("image") or ""),
        width,
        height,
        duration,
        str(user.get("name") or ""),
        "",
        query,
        0.0,
        _candidate_score(width, height, duration, 0.0),
    )


def _pixabay_candidate(
    video: dict, query: str, settings: FootageSettings
) -> FootageCandidate | None:
    video_id = str(video.get("id") or "")
    duration = float(video.get("duration") or 0)
    if not video_id:
        return None
    if duration < settings.min_duration:
        return None
    streams = video.get("videos") if isinstance(video.get("videos"), dict) else {}
    qualified = [
        item
        for item in streams.values()
        if isinstance(item, dict)
        and item.get("url")
        and int(item.get("width") or 0) >= settings.min_width
        and int(item.get("height") or 0) >= settings.min_height
        and int(item.get("width") or 0) >= int(item.get("height") or 0)
    ]
    if not qualified:
        return None
    best = max(qualified, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0))
    width, height = int(best.get("width") or 0), int(best.get("height") or 0)
    popularity = float(video.get("downloads") or video.get("views") or 0)
    return FootageCandidate(
        "pixabay",
        video_id,
        str(video.get("pageURL") or ""),
        str(best.get("url") or ""),
        str(best.get("thumbnail") or ""),
        width,
        height,
        duration,
        str(video.get("user") or ""),
        str(video.get("tags") or ""),
        query,
        popularity,
        _candidate_score(width, height, duration, popularity),
    )


def _candidate_score(width: int, height: int, duration: float, popularity: float) -> float:
    pixels = max(1, width * height)
    return math.log10(pixels) + min(duration, 60.0) / 120.0 + math.log10(popularity + 1) / 20.0


def _validate_settings(settings: FootageSettings) -> None:
    if not settings.use_pexels and not settings.use_pixabay:
        raise FootageWorkflowError("Hãy bật Pexels hoặc Pixabay trong Settings.")
    if settings.use_pexels and not settings.pexels_api_key:
        raise FootageWorkflowError("Thiếu Pexels API Key trong Settings.")
    if settings.use_pixabay and not settings.pixabay_api_key:
        raise FootageWorkflowError("Thiếu Pixabay API Key trong Settings.")


def _load_beat_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FootageWorkflowError("Chưa có footage.csv. Hãy chạy Beat DNA trước.")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FOOTAGE_COLUMNS:
            raise FootageWorkflowError("footage.csv không đúng schema năm cột.")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    if not rows:
        raise FootageWorkflowError("footage.csv không có Beat.")
    seen: set[str] = set()
    for position, row in enumerate(rows, start=1):
        code = row["ma_beat"].upper()
        if not code or code in seen:
            raise FootageWorkflowError(f"Mã Beat không hợp lệ tại dòng {position + 1}.")
        if not parse_queries(row["tu_khoa"]):
            fallback = " ".join(row["hinh_can_tim"].split()[:10])
            row["tu_khoa"] = fallback
        if not row["tu_khoa"]:
            raise FootageWorkflowError(f"{code} không có search query.")
        row["ma_beat"] = code
        seen.add(code)
    return rows


def _download_video(
    session: requests.Session,
    url: str,
    destination: Path,
    cancellation: Cancellation,
) -> None:
    if destination.exists():
        raise FootageWorkflowError(f"File đã tồn tại: {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = session.get(url, stream=True, timeout=300)
    response.raise_for_status()
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            for chunk in response.iter_content(chunk_size=512 * 1024):
                cancellation.raise_if_cancelled()
                if chunk:
                    handle.write(chunk)
        if temporary.stat().st_size == 0:
            raise FootageWorkflowError(f"Download rỗng: {destination.name}")
        os.replace(temporary, destination)
    finally:
        response.close()
        if temporary.exists():
            temporary.unlink()


def _load_selections(path: Path) -> list[FootageSelection]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = payload.get("selections", []) if isinstance(payload, dict) else []
    result: list[FootageSelection] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            result.append(
                FootageSelection(
                    beat_id=str(item["beat_id"]),
                    rank=int(item["rank"]),
                    provider=str(item["provider"]),
                    video_id=str(item["video_id"]),
                    query=str(item.get("query", "")),
                    score=float(item.get("score", 0)),
                    width=int(item.get("width", 0)),
                    height=int(item.get("height", 0)),
                    duration=float(item.get("duration", 0)),
                    contributor=str(item.get("contributor", "")),
                    page_url=str(item.get("page_url", "")),
                    filename=str(item.get("filename", "")),
                    status=str(item.get("status", "")),
                    error=str(item.get("error", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _completed_inventory(
    selections: list[FootageSelection], output_dir: Path
) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in selections:
        if (
            item.status == "downloaded"
            and item.filename
            and (output_dir / item.filename).is_file()
        ):
            result[item.beat_id] = result.get(item.beat_id, 0) + 1
    return result


def _file_inventory(output_dir: Path) -> tuple[dict[str, int], set[str]]:
    counts: dict[str, int] = {}
    keys: set[str] = set()
    if not output_dir.is_dir():
        return counts, keys
    pattern = re.compile(
        r"^(?P<beat>[A-Za-z]+\d+)_(?P<provider>PEXELS|PIXABAY)_"
        r"(?P<video>[A-Za-z0-9_-]+)\.mp4$",
        re.IGNORECASE,
    )
    for path in output_dir.iterdir():
        match = pattern.fullmatch(path.name) if path.is_file() else None
        if not match:
            continue
        beat = match.group("beat").upper()
        provider = match.group("provider").lower()
        counts[beat] = counts.get(beat, 0) + 1
        keys.add(f"{provider}:{match.group('video')}")
    return counts, keys


def _save_manifests(
    json_path: Path,
    csv_path: Path,
    source_csv: Path,
    selections: list[FootageSelection],
    beat_count: int,
    complete: bool = False,
) -> None:
    payload = {
        "schema_version": 1,
        "source_csv": source_csv.name,
        "updated_at": datetime.now(UTC).isoformat(),
        "beat_count": beat_count,
        "complete": complete,
        "selections": [asdict(item) for item in selections],
    }
    _atomic_json(json_path, payload)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
        dir=csv_path.parent,
        prefix=f".{csv_path.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=SELECTION_COLUMNS)
            writer.writeheader()
            writer.writerows(item.csv_row() for item in selections)
        os.replace(temporary, csv_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]", "", value)
    return clean or "unknown"
