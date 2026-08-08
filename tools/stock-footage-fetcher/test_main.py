from __future__ import annotations

import argparse
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("main.py")
SPEC = importlib.util.spec_from_file_location("download_pexels_main", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))


class FakeSession:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls = []

    def get(self, _url, **kwargs):
        self.calls.append(kwargs)
        page = int(kwargs["params"]["page"])
        return FakeResponse(self.pages[page - 1])


class FakeScorer:
    def score_videos(self, videos, _positive, _avoid, _min_duration):
        return [(video, float(video["score"])) for video in videos]


class PaginationTests(unittest.TestCase):
    def test_no_arguments_routes_to_desktop_app(self) -> None:
        with patch("stock_footage_app.main", return_value=0) as desktop_main:
            self.assertEqual(MODULE.entrypoint([]), 0)
        desktop_main.assert_called_once_with([])

    def test_default_worker_count_is_two(self) -> None:
        args = MODULE.build_parser().parse_args([])
        self.assertEqual(args.workers, 2)

    def test_uses_official_pexels_video_api(self) -> None:
        self.assertEqual(
            MODULE.PEXELS_SEARCH_URL,
            "https://api.pexels.com/v1/videos/search",
        )

    def test_project_dir_resolves_csv_and_video_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve()
            args = argparse.Namespace(
                project_dir=project,
                csv=None,
                output_dir=None,
            )

            MODULE.resolve_project_paths(args)

            self.assertEqual(args.csv, project / "footage.csv")
            self.assertEqual(args.output_dir, project / "video")

    def test_env_file_loads_api_key(self) -> None:
        previous = os.environ.pop("PEXELS_API_KEY", None)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                env_file = Path(temporary) / ".env"
                env_file.write_text(
                    'PEXELS_API_KEY="fixture-key"\n',
                    encoding="utf-8",
                )
                MODULE.load_env_file(env_file)
            self.assertEqual(
                os.environ.get("PEXELS_API_KEY"), "fixture-key"
            )
        finally:
            os.environ.pop("PEXELS_API_KEY", None)
            if previous is not None:
                os.environ["PEXELS_API_KEY"] = previous

    def test_moves_to_page_two_until_quality_threshold_is_met(self) -> None:
        session = FakeSession(
            [
                {
                    "videos": [{"id": 1, "score": 0.10}],
                    "total_results": 3,
                },
                {
                    "videos": [
                        {"id": 2, "score": 0.31},
                        {"id": 3, "score": 0.20},
                    ],
                    "total_results": 3,
                },
            ]
        )

        video, score, pages = MODULE.search_best_video(
            row={
                "tu_khoa": "medieval castle, stone fortress",
                "hinh_can_tim": "A real medieval castle",
                "y_chinh": "Castle ownership",
                "tranh": "cartoon",
            },
            api_key="fixture",
            scorer=FakeScorer(),
            session=session,
            max_pages=5,
            per_page=2,
            min_score=0.24,
            min_duration=5.0,
        )

        self.assertEqual(video["id"], 2)
        self.assertEqual(score, 0.31)
        self.assertEqual(pages, 2)
        self.assertEqual(len(session.calls), 2)
        first_request = session.calls[0]
        self.assertEqual(first_request["params"]["query"], "medieval castle")
        self.assertNotIn("q", first_request["params"])
        self.assertNotIn("locale", first_request["params"])
        self.assertEqual(
            first_request["headers"]["Authorization"], "fixture"
        )

    def test_stops_after_configured_maximum_pages(self) -> None:
        session = FakeSession(
            [
                {"videos": [{"id": 1, "score": 0.10}]},
                {"videos": [{"id": 2, "score": 0.20}]},
            ]
        )

        video, score, pages = MODULE.search_best_video(
            row={
                "tu_khoa": "castle",
                "hinh_can_tim": "castle",
                "y_chinh": "",
                "tranh": "",
            },
            api_key="fixture",
            scorer=FakeScorer(),
            session=session,
            max_pages=2,
            per_page=1,
            min_score=0.50,
            min_duration=5.0,
        )

        self.assertEqual(video["id"], 2)
        self.assertEqual(score, 0.20)
        self.assertEqual(pages, 2)


if __name__ == "__main__":
    unittest.main()
