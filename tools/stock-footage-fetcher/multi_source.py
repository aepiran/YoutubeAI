"""Search, rank and download stock footage from Pexels and Pixabay.

The CSV contract intentionally stays compatible with Footage Video Builder:
ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from PIL import Image

from footage_library import FootageLibrary
from stock_fetcher_core import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_CACHE,
    VisualScorer,
    load_env_file,
)


ROOT_DIR = Path(__file__).resolve().parent
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"
PROVIDERS = ("pexels", "pixabay")
CSV_REQUIRED = {"ma_beat", "tu_khoa", "hinh_can_tim", "tranh"}
FIXED_STYLE_PROMPT = (
    "Peaceful cinematic stock footage with soft natural morning light, "
    "slow stable movement, warm hopeful atmosphere, visually uncluttered, "
    "suitable for a Christian morning prayer video."
)
FIXED_AVOID_PROMPT = (
    "vertical video, text overlay, subtitles, watermark, logo, advertisement, "
    "fast camera movement, shaky footage, horror, violence, fantasy, "
    "AI generated Jesus, exaggerated acting, oversaturated colors"
)


def parse_queries(value: str, maximum: int = 3) -> list[str]:
    """Return complete alternative stock queries in priority order.

    A pipe is preferred because a descriptive query may contain commas. Legacy
    CSV files that only use commas remain supported.
    """
    value = (value or "").strip()
    if not value:
        return []
    separator = r"[|;\n]+" if re.search(r"[|;\n]", value) else r",+"
    result: list[str] = []
    seen: set[str] = set()
    for raw in re.split(separator, value):
        query = re.sub(r"\s+", " ", raw).strip(" ,")
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        result.append(query[:100])
        if len(result) >= maximum:
            break
    return result


def row_queries(row: dict[str, str], maximum: int) -> list[str]:
    queries = parse_queries(row.get("tu_khoa", ""), maximum)
    if queries:
        return queries
    visual = re.sub(r"\s+", " ", row.get("hinh_can_tim", "")).strip()
    return [" ".join(visual.split()[:10])] if visual else []


def positive_prompt(row: dict[str, str]) -> str:
    parts = [
        row.get("hinh_can_tim", "").strip(),
        row.get("y_chinh", "").strip(),
        FIXED_STYLE_PROMPT,
    ]
    return ". ".join(part for part in parts if part)


def avoid_prompt(row: dict[str, str]) -> str:
    custom = row.get("tranh", "").strip()
    return ", ".join(part for part in (custom, FIXED_AVOID_PROMPT) if part)


@dataclass(slots=True)
class Candidate:
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
    semantic_score: float = -math.inf
    final_score: float = -math.inf
    visual_hash: str = ""
    origin: str = "online"
    local_path: str = ""
    asset_id: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.video_id}"

    def scorer_payload(self) -> dict[str, Any]:
        quality = "uhd" if self.width >= 3000 else "hd"
        return {
            "id": self.key,
            "image": self.preview_url,
            "duration": self.duration,
            "video_files": [
                {
                    "link": self.download_url,
                    "quality": quality,
                    "width": self.width,
                    "height": self.height,
                }
            ],
            "_candidate_key": self.key,
        }


@dataclass(slots=True)
class Selection:
    beat_id: str
    rank: int
    candidate: Candidate
    filename: str = ""
    status: str = "selected"
    error: str = ""
    selected_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z")
    )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self.candidate)
        result.update(
            {
                "beat_id": self.beat_id,
                "rank": self.rank,
                "filename": self.filename,
                "status": self.status,
                "error": self.error,
                "selected_at": self.selected_at,
            }
        )
        return result


class JsonCache:
    def __init__(self, root: Path, ttl_seconds: int = 86400) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.lock = Lock()

    def _path(self, provider: str, params: dict[str, Any]) -> Path:
        payload = json.dumps(params, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.root / provider / f"{digest}.json"

    def get(self, provider: str, params: dict[str, Any]) -> dict | None:
        path = self._path(provider, params)
        if not path.is_file():
            return None
        if time.time() - path.stat().st_mtime > self.ttl_seconds:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def put(self, provider: str, params: dict[str, Any], data: dict) -> None:
        path = self._path(provider, params)
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(path)


class RateLimiter:
    def __init__(self, minimum_interval: float) -> None:
        self.minimum_interval = max(0.0, minimum_interval)
        self.lock = Lock()
        self.last_request = 0.0

    def wait(self) -> None:
        with self.lock:
            elapsed = time.monotonic() - self.last_request
            remaining = self.minimum_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self.last_request = time.monotonic()


class Provider:
    name = "provider"

    def __init__(
        self,
        *,
        api_key: str,
        cache: JsonCache,
        session: requests.Session,
        minimum_interval: float,
    ) -> None:
        self.api_key = api_key
        self.cache = cache
        self.session = session
        self.rate_limiter = RateLimiter(minimum_interval)
        self.request_lock = Lock()

    def request_json(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict:
        cached = self.cache.get(self.name, params)
        if cached is not None:
            return cached
        with self.request_lock:
            cached = self.cache.get(self.name, params)
            if cached is not None:
                return cached
            self.rate_limiter.wait()
            response = self.session.get(
                url, params=params, headers=headers, timeout=30
            )
            if response.status_code == 429:
                raise RuntimeError(f"{self.name} API rate limit exceeded")
            if response.status_code in {401, 403}:
                raise RuntimeError(f"{self.name} API rejected the configured key")
            response.raise_for_status()
            data = response.json()
            self.cache.put(self.name, params, data)
            return data

    def search(
        self,
        query: str,
        *,
        max_pages: int,
        per_page: int,
        min_width: int,
        min_height: int,
        min_duration: float,
    ) -> list[Candidate]:
        raise NotImplementedError


class LocalLibraryProvider:
    """Expose catalog assets through the same Candidate contract as APIs."""

    name = "library"

    def __init__(self, library: FootageLibrary) -> None:
        self.library = library

    def search(
        self,
        query: str,
        *,
        max_pages: int,
        per_page: int,
        min_width: int,
        min_height: int,
        min_duration: float,
    ) -> list[Candidate]:
        rows = self.library.search(
            query,
            min_width=min_width,
            min_height=min_height,
            min_duration=min_duration,
            limit=max_pages * per_page,
        )
        return [
            Candidate(
                provider=str(row["provider"]),
                video_id=str(row["video_id"]),
                page_url=str(row["page_url"] or ""),
                download_url=str(row["canonical_path"]),
                preview_url=str(row["preview_path"]),
                width=int(row["width"] or 0),
                height=int(row["height"] or 0),
                duration=float(row["duration"] or 0),
                contributor=str(row["contributor"] or ""),
                tags=str(row["tags"] or ""),
                query=query,
                visual_hash=str(row["visual_hash"] or ""),
                origin="library",
                local_path=str(row["canonical_path"]),
                asset_id=str(row["asset_id"]),
            )
            for row in rows
        ]


def _best_pexels_file(video: dict, min_width: int, min_height: int) -> dict | None:
    files = [item for item in video.get("video_files", []) if item.get("link")]
    landscape = [
        item
        for item in files
        if int(item.get("width") or 0) >= int(item.get("height") or 0)
    ]
    if not landscape:
        return None
    qualified = [
        item
        for item in landscape
        if int(item.get("width") or 0) >= min_width
        and int(item.get("height") or 0) >= min_height
    ]
    if not qualified:
        return None
    return max(
        qualified,
        key=lambda item: (
            int(item.get("width") or 0) * int(item.get("height") or 0),
            -int(item.get("file_size") or 0),
        ),
    )


class PexelsProvider(Provider):
    name = "pexels"

    def search(
        self,
        query: str,
        *,
        max_pages: int,
        per_page: int,
        min_width: int,
        min_height: int,
        min_duration: float,
    ) -> list[Candidate]:
        result: list[Candidate] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            params = {
                "query": query,
                "orientation": "landscape",
                "size": "medium",
                "page": page,
                "per_page": min(80, per_page),
            }
            data = self.request_json(
                PEXELS_SEARCH_URL,
                params=params,
                headers={"Authorization": self.api_key},
            )
            videos = data.get("videos", [])
            if not videos:
                break
            for video in videos:
                video_id = str(video.get("id") or "")
                duration = float(video.get("duration") or 0)
                best = _best_pexels_file(video, min_width, min_height)
                if not video_id or video_id in seen or best is None:
                    continue
                width = int(best.get("width") or 0)
                height = int(best.get("height") or 0)
                if duration < min_duration or width < height:
                    continue
                seen.add(video_id)
                user = video.get("user") or {}
                result.append(
                    Candidate(
                        provider=self.name,
                        video_id=video_id,
                        page_url=str(video.get("url") or ""),
                        download_url=str(best.get("link") or ""),
                        preview_url=str(video.get("image") or ""),
                        width=width,
                        height=height,
                        duration=duration,
                        contributor=str(user.get("name") or ""),
                        query=query,
                    )
                )
            total = int(data.get("total_results") or 0)
            if total and page * min(80, per_page) >= total:
                break
        return result


def _best_pixabay_file(video: dict, min_width: int, min_height: int) -> dict | None:
    files = [
        value
        for value in (video.get("videos") or {}).values()
        if isinstance(value, dict) and value.get("url")
    ]
    landscape = [
        item
        for item in files
        if int(item.get("width") or 0) >= int(item.get("height") or 0)
    ]
    if not landscape:
        return None
    qualified = [
        item
        for item in landscape
        if int(item.get("width") or 0) >= min_width
        and int(item.get("height") or 0) >= min_height
    ]
    if not qualified:
        return None
    return max(
        qualified,
        key=lambda item: (
            int(item.get("width") or 0) * int(item.get("height") or 0),
            -int(item.get("size") or 0),
        ),
    )


class PixabayProvider(Provider):
    name = "pixabay"

    def search(
        self,
        query: str,
        *,
        max_pages: int,
        per_page: int,
        min_width: int,
        min_height: int,
        min_duration: float,
    ) -> list[Candidate]:
        result: list[Candidate] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            params = {
                "key": self.api_key,
                "q": query,
                "lang": "en",
                "video_type": "film",
                "safesearch": "true",
                "order": "popular",
                "min_width": min_width,
                "min_height": min_height,
                "page": page,
                "per_page": min(200, max(3, per_page)),
            }
            cache_params = dict(params)
            cache_params["key"] = hashlib.sha256(
                self.api_key.encode("utf-8")
            ).hexdigest()[:12]
            cached = self.cache.get(self.name, cache_params)
            if cached is None:
                with self.request_lock:
                    cached = self.cache.get(self.name, cache_params)
                    if cached is None:
                        self.rate_limiter.wait()
                        response = self.session.get(
                            PIXABAY_SEARCH_URL, params=params, timeout=30
                        )
                        if response.status_code == 429:
                            raise RuntimeError("pixabay API rate limit exceeded")
                        if response.status_code in {401, 403}:
                            raise RuntimeError("pixabay API rejected the configured key")
                        response.raise_for_status()
                        data = response.json()
                        self.cache.put(self.name, cache_params, data)
                    else:
                        data = cached
            else:
                data = cached
            hits = data.get("hits", [])
            if not hits:
                break
            for video in hits:
                video_id = str(video.get("id") or "")
                duration = float(video.get("duration") or 0)
                best = _best_pixabay_file(video, min_width, min_height)
                if not video_id or video_id in seen or best is None:
                    continue
                width = int(best.get("width") or 0)
                height = int(best.get("height") or 0)
                if duration < min_duration or width < height:
                    continue
                seen.add(video_id)
                popularity = math.log1p(float(video.get("likes") or 0)) / 100
                result.append(
                    Candidate(
                        provider=self.name,
                        video_id=video_id,
                        page_url=str(video.get("pageURL") or ""),
                        download_url=str(best.get("url") or ""),
                        preview_url=str(best.get("thumbnail") or ""),
                        width=width,
                        height=height,
                        duration=duration,
                        contributor=str(video.get("user") or ""),
                        tags=str(video.get("tags") or ""),
                        query=query,
                        popularity=popularity,
                    )
                )
            total = int(data.get("totalHits") or 0)
            if total and page * min(200, max(3, per_page)) >= total:
                break
        return result


def deduplicate_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    result: list[Candidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.key in seen:
            continue
        seen.add(candidate.key)
        result.append(candidate)
    return result


def balanced_candidate_pool(
    candidates: Iterable[Candidate], limit: int
) -> list[Candidate]:
    """Round-robin API-ranked results across provider/query buckets.

    This keeps thumbnail scoring bounded without allowing the first provider or
    first query to consume the whole visual-scoring budget.
    """
    unique = deduplicate_candidates(candidates)
    buckets: dict[tuple[str, str], list[Candidate]] = {}
    order: list[tuple[str, str]] = []
    for candidate in unique:
        key = (candidate.provider, candidate.query.casefold())
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(candidate)
    result: list[Candidate] = []
    index = 0
    while len(result) < limit and any(buckets.values()):
        key = order[index % len(order)]
        index += 1
        bucket = buckets[key]
        if bucket:
            result.append(bucket.pop(0))
    return result


def score_candidates(
    scorer: VisualScorer,
    candidates: list[Candidate],
    row: dict[str, str],
    min_duration: float,
) -> list[Candidate]:
    payloads = [candidate.scorer_payload() for candidate in candidates]
    scored = scorer.score_videos(
        payloads,
        positive_prompt(row),
        avoid_prompt(row),
        min_duration,
    )
    by_key = {candidate.key: candidate for candidate in candidates}
    ranked: list[Candidate] = []
    for payload, semantic_score in scored:
        candidate = by_key[str(payload["_candidate_key"])]
        candidate.semantic_score = semantic_score
        resolution = min(1.0, (candidate.width * candidate.height) / (1920 * 1080))
        duration = min(1.0, candidate.duration / 15.0)
        candidate.final_score = (
            semantic_score + 0.018 * resolution + 0.012 * duration
            + min(0.01, candidate.popularity)
        )
        ranked.append(candidate)
    ranked.sort(key=lambda item: item.final_score, reverse=True)
    return ranked


def difference_hash(image: Image.Image, size: int = 9) -> str:
    gray = image.convert("L").resize((size, size - 1), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    bits: list[str] = []
    for y in range(size - 1):
        row = pixels[y * size : (y + 1) * size]
        bits.extend("1" if row[x] > row[x + 1] else "0" for x in range(size - 1))
    return f"{int(''.join(bits), 2):016x}"


def hamming_distance(left: str, right: str) -> int:
    if not left or not right:
        return 64
    return (int(left, 16) ^ int(right, 16)).bit_count()


def fetch_visual_hash(candidate: Candidate, session: requests.Session) -> str:
    if candidate.visual_hash or not candidate.preview_url:
        return candidate.visual_hash
    try:
        preview_path = Path(candidate.preview_url).expanduser()
        if preview_path.is_file():
            image = Image.open(preview_path).convert("RGB")
        else:
            response = session.get(candidate.preview_url, timeout=20)
            response.raise_for_status()
            from io import BytesIO

            image = Image.open(BytesIO(response.content)).convert("RGB")
        candidate.visual_hash = difference_hash(image)
    except (requests.RequestException, OSError, ValueError):
        candidate.visual_hash = ""
    return candidate.visual_hash


class SelectionRegistry:
    def __init__(self, existing: Iterable[dict[str, Any]] = ()) -> None:
        self.used_keys: set[str] = set()
        self.hashes: list[str] = []
        self.contributor_counts: dict[str, int] = {}
        self.provider_counts: dict[str, int] = {}
        seen_records: set[str] = set()
        for item in existing:
            provider = str(item.get("provider") or "")
            video_id = str(item.get("video_id") or "")
            record_key = (
                f"{provider}:{video_id}"
                if provider and video_id
                else str(item.get("filename") or "")
            )
            if record_key and record_key in seen_records:
                continue
            if record_key:
                seen_records.add(record_key)
            if provider and video_id:
                self.used_keys.add(f"{provider}:{video_id}")
                self.provider_counts[provider] = self.provider_counts.get(provider, 0) + 1
            visual_hash = str(item.get("visual_hash") or "")
            if visual_hash and visual_hash not in self.hashes:
                self.hashes.append(visual_hash)
            contributor = str(item.get("contributor") or "").casefold()
            if contributor:
                self.contributor_counts[contributor] = (
                    self.contributor_counts.get(contributor, 0) + 1
                )

    def adjusted_score(self, candidate: Candidate) -> float:
        score = candidate.final_score
        if candidate.key in self.used_keys:
            score -= 1.0
        if candidate.visual_hash and any(
            hamming_distance(candidate.visual_hash, prior) <= 5
            for prior in self.hashes
        ):
            score -= 0.30
        contributor = candidate.contributor.casefold()
        count = self.contributor_counts.get(contributor, 0) if contributor else 0
        score -= max(0, count - 2) * 0.035
        return score

    def add(self, candidate: Candidate) -> None:
        self.used_keys.add(candidate.key)
        self.provider_counts[candidate.provider] = (
            self.provider_counts.get(candidate.provider, 0) + 1
        )
        if candidate.visual_hash:
            self.hashes.append(candidate.visual_hash)
        contributor = candidate.contributor.casefold()
        if contributor:
            self.contributor_counts[contributor] = (
                self.contributor_counts.get(contributor, 0) + 1
            )


def select_candidates(
    ranked: list[Candidate],
    registry: SelectionRegistry,
    *,
    count: int,
    session: requests.Session,
    hash_shortlist: int = 12,
    provider_limits: dict[str, int] | None = None,
) -> list[Candidate]:
    for candidate in ranked[:hash_shortlist]:
        fetch_visual_hash(candidate, session)
    available = list(ranked)
    chosen: list[Candidate] = []
    while available and len(chosen) < count:
        if provider_limits:
            available = [
                candidate
                for candidate in available
                if registry.provider_counts.get(candidate.provider, 0)
                < provider_limits.get(candidate.provider, sys.maxsize)
            ]
        if not available:
            break
        available.sort(key=registry.adjusted_score, reverse=True)
        candidate = available.pop(0)
        if candidate.key in registry.used_keys:
            continue
        candidate.final_score = registry.adjusted_score(candidate)
        chosen.append(candidate)
        registry.add(candidate)
    return chosen


def add_download_parameter(url: str) -> str:
    parsed = urlparse(url)
    values = dict(parse_qsl(parsed.query, keep_blank_values=True))
    values["download"] = "1"
    return urlunparse(parsed._replace(query=urlencode(values)))


def download_candidate(
    selection: Selection,
    output_dir: Path,
    session: requests.Session,
    library: FootageLibrary | None = None,
) -> Path:
    candidate = selection.candidate
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{selection.beat_id}_{candidate.provider.upper()}_"
        f"{candidate.video_id}.mp4"
    )
    destination = output_dir / filename
    if destination.is_file() and destination.stat().st_size > 0:
        selection.filename = filename
        selection.status = "downloaded"
        return destination
    if candidate.origin == "library" and candidate.local_path:
        if library is None:
            raise RuntimeError("local footage requires a configured library")
        library.materialize(Path(candidate.local_path), destination)
        selection.filename = filename
        selection.status = "reused"
        return destination
    url = (
        add_download_parameter(candidate.download_url)
        if candidate.provider == "pixabay"
        else candidate.download_url
    )
    temporary = destination.with_suffix(".part")
    try:
        with session.get(url, stream=True, timeout=180) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("download produced an empty file")
        temporary.replace(destination)
        selection.filename = filename
        selection.status = "downloaded"
        return destination
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fields = set(rows[0]) if rows else set()
    missing = CSV_REQUIRED - fields
    if missing:
        raise ValueError(f"{path.name} missing columns: {', '.join(sorted(missing))}")
    normalized: list[dict[str, str]] = []
    used_codes: set[str] = set()
    for index, row in enumerate(rows, start=1):
        code = re.sub(r"\s+", "", row.get("ma_beat", "")).upper()
        if not code:
            raise ValueError(f"row {index} has an empty ma_beat")
        if code in used_codes:
            raise ValueError(f"duplicate ma_beat: {code}")
        used_codes.add(code)
        clean = {key: str(value or "").strip() for key, value in row.items()}
        clean["ma_beat"] = code
        normalized.append(clean)
    return normalized


def load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return list(data.get("selections", [])) if isinstance(data, dict) else []


def row_min_duration(row: dict[str, str], default: float) -> float:
    try:
        value = float(row.get("min_duration", "") or default)
    except (TypeError, ValueError):
        value = default
    return max(default, value)


def row_target_file_count(row: dict[str, str], default: int) -> int:
    try:
        value = int(float(row.get("target_downloaded_files", "") or default))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def output_inventory(output_dir: Path) -> tuple[dict[str, int], list[dict[str, str]]]:
    """Count local assets and seed provider-ID dedup even across manifests."""
    counts: dict[str, int] = {}
    registry_rows = []
    if not output_dir.is_dir():
        return counts, registry_rows
    pattern = re.compile(
        r"^(?P<beat>[A-Za-z]+\d+)_(?P<provider>[A-Za-z][A-Za-z0-9-]*)_"
        r"(?P<video_id>[^._]+)",
        re.IGNORECASE,
    )
    for path in output_dir.iterdir():
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        match = pattern.match(path.name)
        if not match:
            continue
        beat = match.group("beat").upper()
        counts[beat] = counts.get(beat, 0) + 1
        registry_rows.append(
            {
                "provider": match.group("provider").lower(),
                "video_id": match.group("video_id"),
            }
        )
    return counts, registry_rows


def save_manifest(
    path: Path,
    selections: Iterable[Selection | dict[str, Any]],
    *,
    csv_path: Path,
) -> None:
    rows = [item.to_dict() if isinstance(item, Selection) else item for item in selections]
    payload = {
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_csv": str(csv_path),
        "selections": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)

    csv_manifest = path.with_suffix(".csv")
    fieldnames = [
        "beat_id", "rank", "origin", "asset_id", "provider", "video_id",
        "query", "semantic_score",
        "final_score", "width", "height", "duration", "contributor", "page_url",
        "filename", "status", "error",
    ]
    with csv_manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search and download ranked Pexels/Pixabay footage for script_beat.csv"
    )
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--library-dir", type=Path)
    parser.add_argument("--no-local-library", action="store_true")
    parser.add_argument("--no-auto-archive", action="store_true")
    parser.add_argument(
        "--providers", default="pexels,pixabay",
        help="Comma-separated providers: pexels,pixabay",
    )
    parser.add_argument("--pexels-api-key", default=os.environ.get("PEXELS_API_KEY", ""))
    parser.add_argument("--pixabay-api-key", default=os.environ.get("PIXABAY_API_KEY", ""))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-cache-dir", type=Path, default=DEFAULT_MODEL_CACHE)
    parser.add_argument("--max-queries", type=int, default=2)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=40)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--clips-per-beat", type=int, default=2)
    parser.add_argument(
        "--candidate-pool",
        type=int,
        default=24,
        help="Maximum API candidates per Beat sent to visual scoring.",
    )
    parser.add_argument("--shortlist", type=int, default=6)
    parser.add_argument("--min-duration", type=float, default=8.0)
    parser.add_argument("--min-score", type=float, default=0.18)
    parser.add_argument("--min-width", type=int, default=1920)
    parser.add_argument("--min-height", type=int, default=1080)
    parser.add_argument("--cache-ttl-hours", type=float, default=24.0)
    parser.add_argument(
        "--max-pixabay-downloads",
        type=int,
        default=20,
        help="Safety cap per project run; Pixabay disallows systematic mass downloads.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def resolve_paths(args: argparse.Namespace) -> None:
    project = args.project_dir.expanduser().resolve() if args.project_dir else ROOT_DIR
    args.project_dir = project
    args.csv = (args.csv or project / "script_beat.csv").expanduser().resolve()
    args.output_dir = (args.output_dir or project / "video").expanduser().resolve()
    args.manifest = (
        args.manifest or project / "selected-footage.json"
    ).expanduser().resolve()
    args.cache_dir = project / ".cache" / "stock-search"
    default_library = Path(
        os.environ.get(
            "FOOTAGE_LIBRARY_DIR",
            str(ROOT_DIR / "FootageLibrary"),
        )
    )
    args.library_dir = (args.library_dir or default_library).expanduser().resolve()


def validate_args(args: argparse.Namespace) -> list[str]:
    providers = [item.strip().lower() for item in args.providers.split(",") if item.strip()]
    invalid = set(providers) - set(PROVIDERS)
    if invalid:
        raise ValueError(f"unknown providers: {', '.join(sorted(invalid))}")
    if not providers:
        raise ValueError("at least one provider is required")
    if "pexels" in providers and not args.pexels_api_key:
        raise ValueError("PEXELS_API_KEY is required for provider pexels")
    if "pixabay" in providers and not args.pixabay_api_key:
        raise ValueError("PIXABAY_API_KEY is required for provider pixabay")
    if not args.csv.is_file():
        raise FileNotFoundError(f"CSV not found: {args.csv}")
    if not 1 <= args.workers <= 8:
        raise ValueError("--workers must be between 1 and 8")
    if not 1 <= args.max_queries <= 5:
        raise ValueError("--max-queries must be between 1 and 5")
    if not 1 <= args.max_pages <= 10:
        raise ValueError("--max-pages must be between 1 and 10")
    if not 1 <= args.clips_per_beat <= 4:
        raise ValueError("--clips-per-beat must be between 1 and 4")
    if not 4 <= args.candidate_pool <= 100:
        raise ValueError("--candidate-pool must be between 4 and 100")
    if args.max_pixabay_downloads < 0:
        raise ValueError("--max-pixabay-downloads cannot be negative")
    if "pixabay" in providers and args.cache_ttl_hours < 24:
        raise ValueError("Pixabay API results must be cached for at least 24 hours")
    return providers


def make_providers(
    names: list[str], args: argparse.Namespace, cache: JsonCache
) -> list[Provider]:
    providers: list[Provider] = []
    if "pexels" in names:
        providers.append(
            PexelsProvider(
                api_key=args.pexels_api_key,
                cache=cache,
                session=requests.Session(),
                minimum_interval=0.20,
            )
        )
    if "pixabay" in names:
        providers.append(
            PixabayProvider(
                api_key=args.pixabay_api_key,
                cache=cache,
                session=requests.Session(),
                minimum_interval=0.65,
            )
        )
    return providers


def main(argv: Iterable[str] | None = None) -> int:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if callable(getattr(stream, "reconfigure", None)):
            stream.reconfigure(encoding="utf-8", errors="replace")
    load_env_file()
    args = build_parser().parse_args(argv)
    resolve_paths(args)
    provider_names = validate_args(args)
    rows = load_rows(args.csv)
    cache = JsonCache(args.cache_dir, int(args.cache_ttl_hours * 3600))
    providers = make_providers(provider_names, args, cache)
    library = None if args.no_local_library else FootageLibrary(args.library_dir)

    manifest_paths = [
        args.project_dir / "selected-footage.json",
        args.project_dir / ".cache" / "stock-footage-supplement.json",
        args.manifest,
    ]
    prior_all = [] if args.force else load_manifest(args.manifest)
    project_manifest = args.project_dir / "selected-footage.json"
    catalog_prior = (
        load_manifest(project_manifest)
        if project_manifest.resolve() != args.manifest.resolve()
        else []
    )
    # Only successful, still-present files participate in resume and dedup.
    # Planned/failed records are intentionally retried on the next real run.
    prior: list[dict[str, Any]] = []
    completed_by_beat: dict[str, list[dict[str, Any]]] = {}
    for item in prior_all:
        if item.get("status") in {"downloaded", "reused"} and item.get("filename"):
            file_path = args.output_dir / str(item["filename"])
            if file_path.is_file() and file_path.stat().st_size > 0:
                prior.append(item)
                completed_by_beat.setdefault(str(item.get("beat_id")), []).append(item)

    inventory_counts, inventory_registry = output_inventory(args.output_dir)
    unavailable_keys = {
        f"{item.get('provider')}:{item.get('video_id')}"
        for item in [*prior, *catalog_prior, *inventory_registry]
        if item.get("provider") and item.get("video_id")
    }
    rows_to_search = [
        row for row in rows
        if inventory_counts.get(row["ma_beat"], 0)
        < row_target_file_count(row, args.clips_per_beat)
    ]
    print(
        f"Loaded {len(rows)} beats; searching {len(rows_to_search)} beats across "
        f"{', '.join(provider_names)}."
    )
    if not rows_to_search:
        print(f"Complete: all requested Beat files already exist. Manifest: {args.manifest}")
        return 0

    scorer = VisualScorer(args.model, requests.Session(), args.model_cache_dir)
    score_lock = Lock()
    local_provider = LocalLibraryProvider(library) if library is not None else None

    def search_one(row: dict[str, str]) -> tuple[str, list[Candidate], str]:
        local_candidates: list[Candidate] = []
        online_candidates: list[Candidate] = []
        errors: list[str] = []
        queries = row_queries(row, args.max_queries)
        minimum_duration = row_min_duration(row, args.min_duration)
        needed = max(
            0,
            row_target_file_count(row, args.clips_per_beat)
            - inventory_counts.get(row["ma_beat"], 0),
        )
        if local_provider is not None:
            for query in queries:
                try:
                    local_candidates.extend(
                        local_provider.search(
                            query,
                            max_pages=1,
                            per_page=args.candidate_pool,
                            min_width=args.min_width,
                            min_height=args.min_height,
                            min_duration=minimum_duration,
                        )
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    errors.append(f"library: {exc}")
        local_pool = [
            candidate
            for candidate in balanced_candidate_pool(
                local_candidates, args.candidate_pool
            )
            if candidate.key not in unavailable_keys
        ]
        with score_lock:
            local_ranked = (
                score_candidates(scorer, local_pool, row, minimum_duration)
                if local_pool
                else []
            )
        local_ranked = [
            item for item in local_ranked if item.final_score >= args.min_score
        ]
        if len(local_ranked) >= needed:
            return (
                row["ma_beat"],
                local_ranked,
                f"library satisfied {len(local_ranked)}/{needed}",
            )

        for query in queries:
            for provider in providers:
                try:
                    found = provider.search(
                        query,
                        max_pages=args.max_pages,
                        per_page=args.per_page,
                        min_width=args.min_width,
                        min_height=args.min_height,
                        min_duration=minimum_duration,
                    )
                    online_candidates.extend(found)
                except (requests.RequestException, RuntimeError, ValueError) as exc:
                    errors.append(f"{provider.name}: {exc}")
        pool = balanced_candidate_pool(online_candidates, args.candidate_pool)
        with score_lock:
            online_ranked = (
                score_candidates(scorer, pool, row, minimum_duration) if pool else []
            )
        ranked = [
            item
            for item in [*local_ranked, *online_ranked]
            if item.final_score >= args.min_score
        ]
        ranked.sort(key=lambda item: item.final_score, reverse=True)
        if local_ranked:
            errors.append(f"library supplied {len(local_ranked)}/{needed}")
        return row["ma_beat"], ranked, "; ".join(errors)

    ranked_by_beat: dict[str, list[Candidate]] = {}
    errors_by_beat: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(args.workers, max(1, len(rows_to_search)))) as pool:
        future_map = {pool.submit(search_one, row): row for row in rows_to_search}
        for future in as_completed(future_map):
            source_row = future_map[future]
            try:
                beat_id, ranked, error = future.result()
            except Exception as exc:
                beat_id = source_row["ma_beat"]
                ranked = []
                error = str(exc)
            ranked_by_beat[beat_id] = ranked
            errors_by_beat[beat_id] = error
            print(f"{beat_id}: ranked {len(ranked)} candidates" + (f"; {error}" if error else ""))

    selections: list[Selection | dict[str, Any]] = list(prior)
    registry = SelectionRegistry(
        [*prior, *catalog_prior, *inventory_registry]
    )
    selection_session = requests.Session()
    download_session = requests.Session()

    for row in rows:
        beat_id = row["ma_beat"]
        existing_count = inventory_counts.get(beat_id, 0)
        target_count = row_target_file_count(row, args.clips_per_beat)
        needed = max(0, target_count - existing_count)
        if needed == 0:
            print(f"{beat_id}: resume, already has {existing_count} files")
            continue
        ranked = ranked_by_beat.get(beat_id, [])
        local_ranked = [item for item in ranked if item.origin == "library"]
        online_ranked = [item for item in ranked if item.origin != "library"]
        chosen = select_candidates(
            local_ranked,
            registry,
            count=needed,
            session=selection_session,
            hash_shortlist=args.shortlist,
        )
        if len(chosen) < needed:
            chosen.extend(
                select_candidates(
                    online_ranked,
                    registry,
                    count=needed - len(chosen),
                    session=selection_session,
                    hash_shortlist=args.shortlist,
                    provider_limits={"pixabay": args.max_pixabay_downloads},
                )
            )
        if not chosen:
            print(f"{beat_id}: no suitable candidate; {errors_by_beat.get(beat_id, '')}")
            continue
        for offset, candidate in enumerate(chosen, start=1):
            selection = Selection(
                beat_id=beat_id,
                rank=existing_count + offset,
                candidate=candidate,
            )
            if args.dry_run:
                selection.status = "planned"
            else:
                try:
                    destination = download_candidate(
                        selection, args.output_dir, download_session, library
                    )
                    action = "reused" if selection.status == "reused" else "downloaded"
                    print(f"{beat_id}: {action} {destination.name}")
                    if library is not None and candidate.asset_id:
                        library.record_candidate_usage(
                            candidate.asset_id,
                            args.project_dir,
                            beat_id=beat_id,
                            query=candidate.query,
                            semantic_score=candidate.semantic_score,
                        )
                except (requests.RequestException, RuntimeError, OSError) as exc:
                    selection.status = "failed"
                    selection.error = str(exc)
                    print(f"{beat_id}: download failed: {exc}")
            selections.append(selection)
            save_manifest(args.manifest, selections, csv_path=args.csv)

    save_manifest(args.manifest, selections, csv_path=args.csv)
    if library is not None and not args.no_auto_archive and not args.dry_run:
        downloaded_filenames = [
            item.filename
            for item in selections
            if isinstance(item, Selection)
            and item.status == "downloaded"
            and item.candidate.origin != "library"
        ]
        archived = library.archive_project(
            args.project_dir,
            output_dir=args.output_dir,
            manifest_paths=manifest_paths,
            filenames=downloaded_filenames,
        )
        print(
            "Library storage: "
            f"{archived.imported} imported, {archived.duplicates} duplicates, "
            f"{archived.linked} hard-linked, {archived.failed} failed."
        )
        for item in selections:
            filename = (
                item.filename if isinstance(item, Selection)
                else str(item.get("filename") or "")
            )
            asset_id = archived.asset_ids.get(filename)
            if not asset_id:
                continue
            if isinstance(item, Selection):
                item.candidate.asset_id = asset_id
            else:
                item["asset_id"] = asset_id
        save_manifest(args.manifest, selections, csv_path=args.csv)
    downloaded = sum(
        1
        for item in selections
        if (item.status if isinstance(item, Selection) else item.get("status"))
        in {"downloaded", "reused"}
    )
    print(f"Complete: {downloaded} downloaded files. Manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
