from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import AppSettings, FootageSettings
from storyflow_studio.modules.footage import (
    FootageCandidate,
    FootageWorkflowService,
    parse_queries,
)
from storyflow_studio.modules.tts import CancellationToken
from storyflow_studio.modules.workspace import WorkspaceService


class FakeProvider:
    name = "pexels"

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query, settings, cancellation):
        cancellation.raise_if_cancelled()
        self.calls += 1
        return [
            FootageCandidate(
                provider="pexels",
                video_id=f"{self.calls}01",
                page_url="https://www.pexels.com/video/test/",
                download_url="https://videos.example.test/clip.mp4",
                preview_url="https://images.example.test/clip.jpg",
                width=1920,
                height=1080,
                duration=12.0,
                contributor="Creator",
                query=query,
                score=9.0,
            )
        ]


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield b"fake mp4 payload"

    def close(self):
        pass


class FakeSession:
    def get(self, url, **kwargs):
        return FakeResponse()


class FootageWorkflowServiceTests(unittest.TestCase):
    def test_parse_queries_keeps_pipe_separated_searches(self) -> None:
        self.assertEqual(
            parse_queries("morning window | golden sunrise | calm ocean", 2),
            ["morning window", "golden sunrise"],
        )

    def test_search_downloads_into_project_and_writes_attribution_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Finder", "finder", AppSettings()
            )
            project.path_for("beat_file").write_text(
                "ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh\n"
                "H01,Peace,morning window,Peaceful window,text overlay\n",
                encoding="utf-8",
            )
            provider = FakeProvider()
            service = FootageWorkflowService(
                provider_factory=lambda _settings, _cache: [provider],
                download_session=FakeSession(),
            )
            settings = AppSettings(
                footage=FootageSettings(
                    use_pexels=True,
                    pexels_api_key="secret",
                    clips_per_beat=1,
                )
            )

            result = service.run(
                project, settings, lambda _progress: None, CancellationToken()
            )

            self.assertEqual(result.downloaded_count, 1)
            self.assertEqual(result.beat_count, 1)
            clips = list(project.path_for("footage_dir").glob("*.mp4"))
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0].read_bytes(), b"fake mp4 payload")
            manifest = json.loads(
                project.path_for("footage_manifest").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["complete"])
            self.assertEqual(manifest["selections"][0]["provider"], "pexels")
            self.assertEqual(
                manifest["selections"][0]["page_url"],
                "https://www.pexels.com/video/test/",
            )
            with project.path_for("footage_manifest_csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["status"], "downloaded")

            reopened = WorkspaceService().open_project(project.root)
            self.assertEqual(reopened.manifest.stages["footage"], "completed")

            resumed = service.run(
                reopened, settings, lambda _progress: None, CancellationToken()
            )
            self.assertEqual(resumed.downloaded_count, 1)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(
                len(list(project.path_for("footage_dir").glob("*.mp4"))), 1
            )

    def test_dry_run_writes_plan_without_mp4_or_completed_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Plan", "plan", AppSettings()
            )
            project.path_for("beat_file").write_text(
                "ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh\n"
                "H01,Hope,sunrise,Golden sunrise,logo\n",
                encoding="utf-8",
            )
            service = FootageWorkflowService(
                provider_factory=lambda _settings, _cache: [FakeProvider()],
                download_session=FakeSession(),
            )
            settings = AppSettings(
                footage=FootageSettings(
                    use_pexels=True,
                    pexels_api_key="secret",
                    clips_per_beat=1,
                    dry_run=True,
                )
            )

            result = service.run(
                project, settings, lambda _progress: None, CancellationToken()
            )

            self.assertEqual(result.planned_count, 1)
            self.assertFalse(any(project.path_for("footage_dir").glob("*.mp4")))
            reopened = WorkspaceService().open_project(project.root)
            self.assertEqual(reopened.manifest.stages["footage"], "pending")


if __name__ == "__main__":
    unittest.main()
