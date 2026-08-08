from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location(
    "stock_multi_source", ROOT / "multi_source.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def candidate(
    provider: str,
    video_id: str,
    score: float,
    *,
    visual_hash: str = "",
    contributor: str = "",
) -> MODULE.Candidate:
    return MODULE.Candidate(
        provider=provider,
        video_id=video_id,
        page_url="https://example.test/page",
        download_url="https://example.test/video.mp4",
        preview_url="",
        width=1920,
        height=1080,
        duration=12,
        contributor=contributor,
        semantic_score=score,
        final_score=score,
        visual_hash=visual_hash,
    )


class QueryTests(unittest.TestCase):
    def test_pipe_preserves_complete_queries_with_commas(self) -> None:
        value = "sunrise, warm light|woman praying, morning window|open Bible"
        self.assertEqual(
            MODULE.parse_queries(value, 2),
            ["sunrise, warm light", "woman praying, morning window"],
        )

    def test_legacy_commas_remain_supported(self) -> None:
        self.assertEqual(
            MODULE.parse_queries("peaceful sunrise, open Bible, calm lake", 2),
            ["peaceful sunrise", "open Bible"],
        )

    def test_candidate_pool_balances_provider_and_query(self) -> None:
        items = [
            candidate("pexels", "p1", 0.5),
            candidate("pexels", "p2", 0.5),
            candidate("pixabay", "x1", 0.5),
            candidate("pixabay", "x2", 0.5),
        ]
        items[0].query = items[1].query = "sunrise"
        items[2].query = items[3].query = "morning window"
        pool = MODULE.balanced_candidate_pool(items, 2)
        self.assertEqual([item.provider for item in pool], ["pexels", "pixabay"])


class ProviderNormalizationTests(unittest.TestCase):
    def test_pexels_requires_full_hd_and_chooses_largest(self) -> None:
        video = {
            "video_files": [
                {"link": "720", "quality": "hd", "width": 1280, "height": 720},
                {"link": "1080", "quality": "hd", "width": 1920, "height": 1080},
                {"link": "4k", "quality": "uhd", "width": 3840, "height": 2160},
            ]
        }
        result = MODULE._best_pexels_file(video, 1920, 1080)
        self.assertEqual(result["link"], "4k")

    def test_pexels_rejects_below_minimum_resolution(self) -> None:
        video = {
            "video_files": [
                {"link": "720", "quality": "hd", "width": 1280, "height": 720}
            ]
        }
        self.assertIsNone(MODULE._best_pexels_file(video, 1920, 1080))

    def test_pixabay_chooses_qualified_landscape_file(self) -> None:
        video = {
            "videos": {
                "large": {"url": "4k", "width": 3840, "height": 2160},
                "medium": {"url": "1080", "width": 1920, "height": 1080},
                "small": {"url": "portrait", "width": 720, "height": 1280},
            }
        }
        result = MODULE._best_pixabay_file(video, 1920, 1080)
        self.assertEqual(result["url"], "4k")

    def test_pexels_provider_normalizes_api_response(self) -> None:
        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "total_results": 1,
                    "videos": [
                        {
                            "id": 10,
                            "url": "https://pexels.test/10",
                            "image": "https://pexels.test/10.jpg",
                            "duration": 14,
                            "user": {"name": "Creator"},
                            "video_files": [
                                {
                                    "link": "https://pexels.test/10.mp4",
                                    "width": 1920,
                                    "height": 1080,
                                }
                            ],
                        }
                    ],
                }

        class Session:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return Response()

        with tempfile.TemporaryDirectory() as temporary:
            session = Session()
            provider = MODULE.PexelsProvider(
                api_key="key",
                cache=MODULE.JsonCache(Path(temporary)),
                session=session,
                minimum_interval=0,
            )
            results = provider.search(
                "peaceful sunrise",
                max_pages=1,
                per_page=20,
                min_width=1920,
                min_height=1080,
                min_duration=8,
            )
        self.assertEqual(results[0].key, "pexels:10")
        self.assertEqual(session.calls[0][1]["headers"]["Authorization"], "key")
        self.assertEqual(session.calls[0][1]["params"]["orientation"], "landscape")

    def test_pixabay_provider_normalizes_api_response(self) -> None:
        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "totalHits": 1,
                    "hits": [
                        {
                            "id": 20,
                            "pageURL": "https://pixabay.test/20",
                            "duration": 11,
                            "user": "Creator",
                            "tags": "sunrise, morning",
                            "videos": {
                                "medium": {
                                    "url": "https://pixabay.test/20.mp4",
                                    "width": 1920,
                                    "height": 1080,
                                    "thumbnail": "https://pixabay.test/20.jpg",
                                }
                            },
                        }
                    ],
                }

        class Session:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return Response()

        with tempfile.TemporaryDirectory() as temporary:
            session = Session()
            provider = MODULE.PixabayProvider(
                api_key="key",
                cache=MODULE.JsonCache(Path(temporary)),
                session=session,
                minimum_interval=0,
            )
            results = provider.search(
                "morning window",
                max_pages=1,
                per_page=20,
                min_width=1920,
                min_height=1080,
                min_duration=8,
            )
        self.assertEqual(results[0].key, "pixabay:20")
        params = session.calls[0][1]["params"]
        self.assertEqual(params["video_type"], "film")
        self.assertEqual(params["safesearch"], "true")


class CacheTests(unittest.TestCase):
    def test_cache_round_trip_and_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = MODULE.JsonCache(Path(temporary), ttl_seconds=60)
            params = {"query": "sunrise", "page": 1}
            cache.put("pexels", params, {"videos": [1]})
            self.assertEqual(cache.get("pexels", params), {"videos": [1]})

            path = cache._path("pexels", params)
            old = time.time() - 120
            import os

            os.utime(path, (old, old))
            self.assertIsNone(cache.get("pexels", params))


class SelectionTests(unittest.TestCase):
    def test_registry_deduplicates_same_asset_from_manifest_and_inventory(self):
        asset = {
            "provider": "pexels",
            "video_id": "123",
            "filename": "B001_PEXELS_123.mp4",
            "visual_hash": "abcd",
            "contributor": "Creator",
        }
        registry = MODULE.SelectionRegistry([asset, dict(asset)])

        self.assertEqual(registry.provider_counts["pexels"], 1)
        self.assertEqual(registry.contributor_counts["creator"], 1)
        self.assertEqual(registry.hashes, ["abcd"])

    def test_same_id_is_not_selected_twice(self) -> None:
        registry = MODULE.SelectionRegistry(
            [{"provider": "pexels", "video_id": "1", "status": "downloaded"}]
        )
        chosen = MODULE.select_candidates(
            [candidate("pexels", "1", 0.9), candidate("pixabay", "2", 0.8)],
            registry,
            count=1,
            session=object(),
        )
        self.assertEqual(chosen[0].key, "pixabay:2")

    def test_near_duplicate_hash_receives_penalty(self) -> None:
        registry = MODULE.SelectionRegistry(
            [
                {
                    "provider": "pexels",
                    "video_id": "old",
                    "visual_hash": "0000000000000000",
                    "status": "downloaded",
                }
            ]
        )
        duplicate = candidate(
            "pixabay", "1", 0.90, visual_hash="0000000000000001"
        )
        distinct = candidate(
            "pexels", "2", 0.75, visual_hash="ffffffffffffffff"
        )
        chosen = MODULE.select_candidates(
            [duplicate, distinct], registry, count=1, session=object()
        )
        self.assertEqual(chosen[0].key, "pexels:2")

    def test_pixabay_project_cap_is_respected(self) -> None:
        registry = MODULE.SelectionRegistry(
            [{"provider": "pixabay", "video_id": "old", "status": "downloaded"}]
        )
        chosen = MODULE.select_candidates(
            [candidate("pixabay", "1", 0.95), candidate("pexels", "2", 0.70)],
            registry,
            count=1,
            session=object(),
            provider_limits={"pixabay": 1},
        )
        self.assertEqual(chosen[0].provider, "pexels")


class ManifestTests(unittest.TestCase):
    def test_manifest_writes_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "selected-footage.json"
            item = MODULE.Selection("H01", 1, candidate("pexels", "42", 0.8))
            item.status = "downloaded"
            item.filename = "H01_PEXELS_42.mp4"
            MODULE.save_manifest(path, [item], csv_path=root / "footage.csv")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["selections"][0]["beat_id"], "H01")
            self.assertTrue(path.with_suffix(".csv").is_file())


class SupplementPlanTests(unittest.TestCase):
    def test_row_overrides_default_target_and_minimum_duration(self) -> None:
        row = {
            "target_downloaded_files": "7",
            "min_duration": "11",
        }
        self.assertEqual(MODULE.row_target_file_count(row, 2), 7)
        self.assertEqual(MODULE.row_min_duration(row, 8.0), 11.0)

    def test_inventory_counts_files_and_seeds_provider_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "B001_PEXELS_123.mp4").write_bytes(b"video")
            (root / "B001_PIXABAY_456.mp4").write_bytes(b"video")
            (root / "B002_custom.mp4").write_bytes(b"video")

            counts, registry = MODULE.output_inventory(root)

            self.assertEqual(counts, {"B001": 2})
            self.assertEqual(
                {(row["provider"], row["video_id"]) for row in registry},
                {("pexels", "123"), ("pixabay", "456")},
            )


if __name__ == "__main__":
    unittest.main()
