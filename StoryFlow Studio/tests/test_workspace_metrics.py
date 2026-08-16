from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import AppSettings
from storyflow_studio.modules.workspace import (
    ProjectMetricsService,
    WorkspaceService,
    format_duration,
)


class ProjectMetricsServiceTests(unittest.TestCase):
    def test_raw_script_metrics_ignore_title_and_script_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = WorkspaceService().create_project(
                directory, "Metrics", "metrics", AppSettings()
            )
            project.path_for("raw_script").write_text(
                "TITLE:\nIgnored title words\n\nSCRIPT:\nHello world.",
                encoding="utf-8",
            )

            metrics = ProjectMetricsService(
                duration_probe=lambda path: None
            ).snapshot(project)

            self.assertEqual(metrics.word_count, 2)
            self.assertEqual(metrics.character_count, 12)

    def test_metrics_prefer_tts_script_and_fallback_to_srt_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = WorkspaceService().create_project(
                directory, "Metrics", "metrics", AppSettings()
            )
            project.path_for("raw_script").write_text(
                "Hello world!\nAgain.", encoding="utf-8"
            )
            project.path_for("tts_script").write_text(
                "It's a new day.", encoding="utf-8"
            )
            project.path_for("audio_file").write_bytes(b"audio")
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:01:05,400\nIt's a new day.\n",
                encoding="utf-8",
            )
            project.path_for("beat_file").write_text(
                "ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh\n"
                "H01,One,one,one,none\n"
                "H02,Two,two,two,none\n",
                encoding="utf-8",
            )
            project.path_for("music_cue_file").write_text(
                "cue,start,end\nC01,00:00.000,00:30.000\n"
                "C02,00:22.000,01:05.400\n",
                encoding="utf-8",
            )
            timeline = project.path_for("video_timeline_file")
            timeline.parent.mkdir(parents=True, exist_ok=True)
            timeline.write_text(
                json.dumps(
                    {
                        "timeline": [
                            {"warnings": []},
                            {"warnings": ["missing_footage", "short_source"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            metrics = ProjectMetricsService(
                duration_probe=lambda path: None
            ).snapshot(project)

            self.assertEqual(metrics.word_count, 4)
            self.assertEqual(metrics.character_count, 15)
            self.assertEqual(metrics.script_source, "script_tts.txt")
            self.assertEqual(metrics.audio_duration_seconds, 65.4)
            self.assertEqual(format_duration(metrics.audio_duration_seconds), "01:05")
            self.assertEqual(metrics.beat_count, 2)
            self.assertEqual(metrics.music_cue_count, 2)
            self.assertEqual(metrics.video_cut_count, 2)
            self.assertEqual(metrics.video_warning_count, 2)

    def test_metrics_use_real_audio_duration_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = WorkspaceService().create_project(
                directory, "Audio", "audio", AppSettings()
            )
            project.path_for("audio_file").write_bytes(b"audio")
            metrics = ProjectMetricsService(
                duration_probe=lambda path: 3723.2
            ).snapshot(project)
            self.assertEqual(format_duration(metrics.audio_duration_seconds), "01:02:03")


if __name__ == "__main__":
    unittest.main()
