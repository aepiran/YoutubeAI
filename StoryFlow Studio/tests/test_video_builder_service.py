from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path

from storyflow_studio.core.media import MediaInfo
from storyflow_studio.core.settings import AppSettings, VideoBuilderSettings
from storyflow_studio.modules.tts import CancellationToken
from storyflow_studio.modules.video_builder import (
    VideoBuilderService,
    VideoBuilderWorkflowError,
    VideoRenderResult,
)
from storyflow_studio.modules.video_builder import service as video_builder_service_module
from storyflow_studio.modules.video_builder.visual import SceneRange
from storyflow_studio.modules.workspace import WorkspaceService


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VideoBuilderServiceTests(unittest.TestCase):
    def create_ready_project(self, root: Path, *, second_clip: bool = True):
        project = WorkspaceService().create_project(
            root / "workspace", "Builder", "builder", AppSettings()
        )
        script = project.path_for("tts_script")
        subtitle = project.path_for("subtitle_file")
        beat_file = project.path_for("beat_file")
        script.write_text("Hope rises. Walk in peace.", encoding="utf-8")
        subtitle.write_text(
            "1\n00:00:00,000 --> 00:00:04,000\nHope rises.\n\n"
            "2\n00:00:04,000 --> 00:00:08,000\nWalk in peace.\n",
            encoding="utf-8",
        )
        project.path_for("audio_file").write_bytes(b"audio")
        beat_file.write_text(
            "ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh\n"
            "H01,Hope,sunrise,Golden sunrise,logo\n"
            "H02,Peace,walking,A calm walking path,traffic\n",
            encoding="utf-8",
        )
        video_dir = project.path_for("footage_dir")
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "H01_PEXELS_101.mp4").write_bytes(b"video-one")
        if second_clip:
            (video_dir / "H02_PEXELS_202.mp4").write_bytes(b"video-two")
        timing = {
            "schema_version": 1,
            "duration_seconds": 8.0,
            "sources": {
                "script": "script_tts.txt",
                "subtitle": "audio/narration.srt",
                "beat_csv": "footage.csv",
                "script_sha256": sha256(script),
                "subtitle_sha256": sha256(subtitle),
                "beat_csv_sha256": sha256(beat_file),
            },
            "beats": [
                {
                    "code": "H01",
                    "start_seconds": 0.0,
                    "end_seconds": 4.0,
                    "narration": "Hope rises.",
                },
                {
                    "code": "H02",
                    "start_seconds": 4.0,
                    "end_seconds": 8.0,
                    "narration": "Walk in peace.",
                },
            ],
        }
        timing_file = project.path_for("beat_timing_file")
        timing_file.parent.mkdir(parents=True, exist_ok=True)
        timing_file.write_text(json.dumps(timing), encoding="utf-8")
        return project

    def test_reuses_beat_timing_and_footage_assignment_for_draft_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            updates = []
            result = VideoBuilderService(duration_probe=lambda _path: 12.0).analyze(
                project,
                AppSettings(video_builder=VideoBuilderSettings()),
                updates.append,
                CancellationToken(),
            )

            self.assertEqual(result.cut_count, 2)
            self.assertEqual(result.warning_count, 0)
            report = json.loads(result.timeline_file.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["analysis_mode"], "technical_review")
            self.assertTrue(report["technical_scoring"])
            self.assertFalse(report["visual_ai_scoring"])
            self.assertFalse(report["render_supported"])
            self.assertEqual(
                [row["footage"] for row in report["timeline"]],
                ["video/H01_PEXELS_101.mp4", "video/H02_PEXELS_202.mp4"],
            )
            self.assertEqual(updates[-1].state, "completed")
            reopened = WorkspaceService().open_project(project.root)
            self.assertEqual(reopened.manifest.stages["video_plan"], "completed")
            self.assertEqual(reopened.manifest.stages["video_render"], "pending")
            review = VideoBuilderService(
                duration_probe=lambda _path: 12.0
            ).review(project, AppSettings())
            self.assertFalse(review.stale)
            self.assertEqual(review.cut_count, 2)

    def test_missing_beat_footage_is_a_review_warning_not_a_fake_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory), second_clip=False)
            result = VideoBuilderService(duration_probe=lambda _path: 12.0).analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )

            report = json.loads(result.timeline_file.read_text(encoding="utf-8"))
            missing = report["timeline"][1]
            self.assertEqual(missing["footage"], "")
            self.assertIn("missing_footage", missing["warnings"])
            self.assertEqual(report["status"], "review_required")
            review = VideoBuilderService(
                duration_probe=lambda _path: 12.0
            ).review(project, AppSettings())
            self.assertEqual(review.missing_beats, ("H02",))

    def test_review_marks_timeline_stale_after_footage_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            service = VideoBuilderService(duration_probe=lambda _path: 12.0)
            service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            (project.path_for("footage_dir") / "H01_EXTRA.mp4").write_bytes(b"new")

            review = service.review(project, AppSettings())

            self.assertTrue(review.stale)
            self.assertEqual(review.status, "stale")

    def test_render_uses_saved_timeline_when_inputs_are_stale(self) -> None:
        class CapturingRenderer:
            def __init__(self) -> None:
                self.rows = ()

            def render(
                self,
                project,
                settings,
                rows,
                duration,
                progress,
                cancellation,
                *,
                replace_existing=False,
            ):
                self.rows = rows
                return VideoRenderResult(
                    project.path_for("final_video_file"),
                    project.path_for("attribution_file"),
                    duration,
                    1,
                    len(rows),
                )

        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            renderer = CapturingRenderer()
            service = VideoBuilderService(
                duration_probe=lambda _path: 12.0,
                renderer=renderer,
            )
            result = service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            (project.path_for("footage_dir") / "H01_EXTRA.mp4").write_bytes(b"new")
            self.assertTrue(service.review(project, AppSettings()).stale)

            rendered = service.render(
                project,
                AppSettings(),
                lambda _update: None,
                CancellationToken(),
            )

            self.assertEqual(rendered.cut_count, result.cut_count)
            self.assertEqual(len(renderer.rows), result.cut_count)

    def test_technical_score_uses_verified_duration_and_manifest_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            project.path_for("footage_manifest").write_text(
                json.dumps(
                    {
                        "selections": [
                            {
                                "filename": "H01_PEXELS_101.mp4",
                                "duration": 12,
                                "width": 1920,
                                "height": 1080,
                            },
                            {
                                "filename": "H02_PEXELS_202.mp4",
                                "duration": 12,
                                "width": 1920,
                                "height": 1080,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = VideoBuilderService(duration_probe=lambda _path: 12.0).analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )

            report = json.loads(result.timeline_file.read_text(encoding="utf-8"))
            self.assertEqual(
                [row["technical_score"] for row in report["timeline"]], [1.0, 1.0]
            )
            self.assertEqual(report["timeline"][0]["source_width"], 1920)

    def test_scene_semantic_adapter_and_optimizer_select_distinct_windows(self) -> None:
        class Scenes:
            def detect(self, path, duration, threshold, minimum):
                return (SceneRange(0, 0.0, 6.0), SceneRange(1, 6.0, 12.0))

        class Scorer:
            model_name = "openai/clip-vit-base-patch32"

            def score(self, text, path, timestamp):
                return 0.9 if timestamp >= 6.0 else 0.7

        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            settings = AppSettings(
                video_builder=VideoBuilderSettings(
                    min_cut_seconds=1.0,
                    target_cut_seconds=2.0,
                    max_cut_seconds=2.0,
                    visual_model="openai/clip-vit-base-patch32",
                )
            )
            service = VideoBuilderService(
                duration_probe=lambda _path: 12.0,
                scene_detector=Scenes(),
                semantic_scorer_factory=lambda *_args: Scorer(),
            )
            result = service.analyze(
                project, settings, lambda _update: None, CancellationToken()
            )

            report = json.loads(result.timeline_file.read_text(encoding="utf-8"))
            self.assertTrue(report["visual_ai_scoring"])
            self.assertEqual(report["visual_model"], "openai/clip-vit-base-patch32")
            self.assertTrue(
                all(row["semantic_score"] is not None for row in report["timeline"])
            )
            h01_windows = {
                (row["source_start"], row["source_end"])
                for row in report["timeline"]
                if row["beat"] == "H01"
            }
            self.assertGreater(len(h01_windows), 1)

    def test_analyze_again_reuses_semantic_score_cache(self) -> None:
        class Scenes:
            def detect(self, path, duration, threshold, minimum):
                return (SceneRange(0, 0.0, duration),)

        class CountingScorer:
            model_name = "openai/clip-vit-base-patch32"

            def __init__(self) -> None:
                self.calls = 0

            def score(self, text, path, timestamp):
                self.calls += 1
                return 0.8

        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            scorer = CountingScorer()
            settings = AppSettings(
                video_builder=VideoBuilderSettings(
                    visual_model="openai/clip-vit-base-patch32",
                )
            )
            service = VideoBuilderService(
                duration_probe=lambda _path: 12.0,
                scene_detector=Scenes(),
                semantic_scorer_factory=lambda *_args: scorer,
            )
            first = service.analyze(
                project, settings, lambda _update: None, CancellationToken()
            )
            first_calls = scorer.calls
            first_score = json.loads(first.timeline_file.read_text(encoding="utf-8"))[
                "timeline"
            ][0]["semantic_score"]
            self.assertGreater(first_calls, 0)

            second = service.analyze(
                project,
                settings,
                lambda _update: None,
                CancellationToken(),
                replace_existing=True,
            )

            self.assertEqual(scorer.calls, first_calls)
            self.assertEqual(
                first_score,
                json.loads(second.timeline_file.read_text(encoding="utf-8"))[
                    "timeline"
                ][0]["semantic_score"],
            )

    def test_analyze_again_reuses_cached_beat_plans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            service = VideoBuilderService(
                duration_probe=lambda _path: 12.0,
                media_probe=lambda _path: None,
            )
            first = service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            first_rows = json.loads(first.timeline_file.read_text(encoding="utf-8"))[
                "timeline"
            ]
            original_plan_beat = video_builder_service_module._plan_beat

            def fail_plan(*_args, **_kwargs):
                raise AssertionError("beat plan cache was not reused")

            video_builder_service_module._plan_beat = fail_plan
            try:
                second = service.analyze(
                    project,
                    AppSettings(),
                    lambda _update: None,
                    CancellationToken(),
                    replace_existing=True,
                )
            finally:
                video_builder_service_module._plan_beat = original_plan_beat

            second_rows = json.loads(second.timeline_file.read_text(encoding="utf-8"))[
                "timeline"
            ]
            self.assertEqual(first_rows, second_rows)
            self.assertTrue(
                (project.metadata_dir / "video-builder" / "cache" / "plans").is_dir()
            )

    def test_clear_analysis_cache_removes_video_builder_cache_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            service = VideoBuilderService(
                duration_probe=lambda _path: 12.0,
                media_probe=lambda _path: None,
            )
            service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            cache_root = project.metadata_dir / "video-builder" / "cache"
            timeline_file = project.path_for("video_timeline_file")

            removed = service.clear_analysis_cache(project)

            self.assertGreater(removed, 0)
            self.assertFalse(cache_root.exists())
            self.assertTrue(timeline_file.is_file())

    def test_analysis_workers_scan_footage_concurrently(self) -> None:
        class ConcurrentScenes:
            def __init__(self) -> None:
                self.barrier = threading.Barrier(2, timeout=2)
                self.thread_ids: set[int] = set()
                self.lock = threading.Lock()

            def detect(self, path, duration, threshold, minimum):
                with self.lock:
                    self.thread_ids.add(threading.get_ident())
                self.barrier.wait()
                return (SceneRange(0, 0.0, duration),)

        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            scenes = ConcurrentScenes()
            updates = []
            result = VideoBuilderService(
                duration_probe=lambda _path: 12.0,
                scene_detector=scenes,
            ).analyze(
                project,
                AppSettings(
                    video_builder=VideoBuilderSettings(analysis_workers=2)
                ),
                updates.append,
                CancellationToken(),
            )

            self.assertEqual(result.cut_count, 2)
            self.assertEqual(len(scenes.thread_ids), 2)
            self.assertTrue(
                any("Analyzed footage 2/2" in update.message for update in updates)
            )

    def test_analyze_again_reuses_inventory_and_scene_cache(self) -> None:
        class CountingScenes:
            def __init__(self) -> None:
                self.calls = 0

            def detect(self, path, duration, threshold, minimum):
                self.calls += 1
                return (SceneRange(0, 0.0, duration),)

        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            scenes = CountingScenes()
            duration_calls = []

            def duration_probe(path):
                duration_calls.append(path)
                return 12.0

            service = VideoBuilderService(
                duration_probe=duration_probe,
                media_probe=lambda _path: None,
                scene_detector=scenes,
            )
            service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            updates = []
            service.analyze(
                project,
                AppSettings(),
                updates.append,
                CancellationToken(),
                replace_existing=True,
            )

            self.assertEqual(scenes.calls, 2)
            self.assertEqual(len(duration_calls), 2)
            self.assertTrue(
                any("Cached footage 2/2" in update.message for update in updates)
            )
            self.assertTrue(
                (
                    project.metadata_dir
                    / "video-builder"
                    / "cache"
                    / "inventory.json"
                ).is_file()
            )

    def test_footage_change_invalidates_only_that_file_cache(self) -> None:
        class CountingScenes:
            def __init__(self) -> None:
                self.calls = 0

            def detect(self, path, duration, threshold, minimum):
                self.calls += 1
                return (SceneRange(0, 0.0, duration),)

        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            scenes = CountingScenes()
            duration_calls = []

            def duration_probe(path):
                duration_calls.append(path)
                return 12.0

            service = VideoBuilderService(
                duration_probe=duration_probe,
                media_probe=lambda _path: None,
                scene_detector=scenes,
            )
            service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            changed = project.path_for("footage_dir") / "H01_PEXELS_101.mp4"
            changed.write_bytes(changed.read_bytes() + b"-changed")
            updates = []

            service.analyze(
                project,
                AppSettings(),
                updates.append,
                CancellationToken(),
                replace_existing=True,
            )

            self.assertEqual(scenes.calls, 3)
            self.assertEqual(len(duration_calls), 3)
            self.assertEqual(
                sum("Cached footage" in update.message for update in updates), 1
            )
            self.assertEqual(
                sum("Analyzed footage" in update.message for update in updates), 1
            )

    def test_scene_setting_change_reuses_metadata_but_redetects_scenes(self) -> None:
        class CountingScenes:
            def __init__(self) -> None:
                self.calls = 0

            def detect(self, path, duration, threshold, minimum):
                self.calls += 1
                return (SceneRange(0, 0.0, duration),)

        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            scenes = CountingScenes()
            duration_calls = []

            def duration_probe(path):
                duration_calls.append(path)
                return 12.0

            service = VideoBuilderService(
                duration_probe=duration_probe,
                media_probe=lambda _path: None,
                scene_detector=scenes,
            )
            service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            changed_settings = AppSettings(
                video_builder=VideoBuilderSettings(scene_threshold=0.45)
            )

            service.analyze(
                project,
                changed_settings,
                lambda _update: None,
                CancellationToken(),
                replace_existing=True,
            )

            self.assertEqual(len(duration_calls), 2)
            self.assertEqual(scenes.calls, 4)

    def test_media_probe_supplies_verified_dimensions_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            service = VideoBuilderService(
                duration_probe=lambda _path: self.fail(
                    "duration fallback should not run when media probe succeeds"
                ),
                media_probe=lambda _path: MediaInfo(
                    duration=12.0,
                    width=1920,
                    height=1080,
                    fps=29.97,
                    codec="h264",
                ),
            )

            result = service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )

            report = json.loads(result.timeline_file.read_text(encoding="utf-8"))
            self.assertTrue(
                all(row["source_width"] == 1920 for row in report["timeline"])
            )
            self.assertTrue(
                all(row["source_height"] == 1080 for row in report["timeline"])
            )
            self.assertTrue(
                all(row["technical_score"] == 1.0 for row in report["timeline"])
            )

    def test_replace_clip_updates_json_and_csv_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            replacement = project.path_for("footage_dir") / "H01_ALT.mp4"
            replacement.write_bytes(b"replacement")
            service = VideoBuilderService(duration_probe=lambda _path: 12.0)
            result = service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            report = json.loads(result.timeline_file.read_text(encoding="utf-8"))
            cut = report["timeline"][0]
            selected = project.root / cut["footage"]
            replacement = next(
                path
                for path in (
                    project.path_for("footage_dir") / "H01_PEXELS_101.mp4",
                    project.path_for("footage_dir") / "H01_ALT.mp4",
                )
                if path != selected
            )

            review = service.replace_clip(
                project, AppSettings(), int(cut["cut"]), replacement
            )

            updated = json.loads(result.timeline_file.read_text(encoding="utf-8"))
            self.assertEqual(updated["timeline"][0]["footage"], f"video/{replacement.name}")
            self.assertIn(
                "manual_replacement_pending_semantic_review",
                updated["timeline"][0]["warnings"],
            )
            self.assertFalse(review.stale)
            self.assertIn(replacement.name, project.path_for("video_timeline_csv").read_text())

    def test_stale_beat_timing_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            project.path_for("subtitle_file").write_text(
                "changed", encoding="utf-8"
            )

            with self.assertRaisesRegex(
                VideoBuilderWorkflowError, "đã thay đổi sau Beat DNA"
            ):
                VideoBuilderService(duration_probe=lambda _path: 12.0).analyze(
                    project, AppSettings(), lambda _update: None, CancellationToken()
                )

    def test_analyze_again_replaces_existing_plan_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_ready_project(Path(directory))
            service = VideoBuilderService(duration_probe=lambda _path: 12.0)
            service.analyze(
                project, AppSettings(), lambda _update: None, CancellationToken()
            )
            timeline_csv = project.path_for("video_timeline_csv")
            timeline_csv.write_text("old-plan", encoding="utf-8")

            with self.assertRaisesRegex(
                VideoBuilderWorkflowError, "Analyze Again"
            ):
                service.analyze(
                    project, AppSettings(), lambda _update: None, CancellationToken()
                )

            result = service.analyze(
                project,
                AppSettings(),
                lambda _update: None,
                CancellationToken(),
                replace_existing=True,
            )
            self.assertEqual(result.cut_count, 2)
            self.assertNotEqual(timeline_csv.read_text(encoding="utf-8"), "old-plan")


if __name__ == "__main__":
    unittest.main()
