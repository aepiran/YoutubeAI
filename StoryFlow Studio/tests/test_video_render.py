from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from storyflow_studio.core.settings import AppSettings, MusicSettings, VideoBuilderSettings
from storyflow_studio.modules.tts import CancellationToken
from storyflow_studio.modules.video_builder import FFmpegTimelineRenderer
from storyflow_studio.modules.workspace import WorkspaceService


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VideoRenderTests(unittest.TestCase):
    def test_low_memory_render_creates_valid_mp4_and_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Render", "render", AppSettings()
            )
            video = project.path_for("footage_dir") / "H01_LOCAL.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x180:rate=24:duration=2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-y",
                    str(video),
                ],
                check=True,
            )
            music = project.path_for("background_music_file")
            subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=220:duration=1",
                    "-q:a",
                    "5",
                    "-y",
                    str(music),
                ],
                check=True,
            )
            narration = project.path_for("audio_file")
            narration.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2",
                    "-q:a",
                    "5",
                    "-y",
                    str(narration),
                ],
                check=True,
            )
            rows = tuple(
                {
                    "cut": index + 1,
                    "beat": "H01",
                    "timeline_start": float(index),
                    "timeline_end": float(index + 1),
                    "duration": 1.0,
                    "footage": "video/H01_LOCAL.mp4",
                    "source_start": float(index),
                    "source_end": float(index + 1),
                    "warnings": [],
                }
                for index in range(2)
            )
            updates = []
            renderer = FFmpegTimelineRenderer(
                disk_usage=lambda _path: SimpleNamespace(free=10 * 1024**3)
            )

            result = renderer.render(
                project,
                AppSettings(
                    music=MusicSettings(enabled=True),
                    video_builder=VideoBuilderSettings(
                        resolution="720p", encoder_preset="ultrafast"
                    )
                ),
                rows,
                2.0,
                updates.append,
                CancellationToken(),
            )

            self.assertTrue(result.final_file.is_file())
            self.assertGreater(result.size_bytes, 0)
            self.assertGreaterEqual(result.duration_seconds, 1.85)
            self.assertTrue(result.attribution_file.is_file())
            self.assertIn("video/H01_LOCAL.mp4", result.attribution_file.read_text())
            self.assertEqual(updates[-1].state, "completed")
            probe = subprocess.run(
                [
                    shutil.which("ffprobe"),
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,width,height",
                    "-of",
                    "json",
                    str(result.final_file),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            streams = json.loads(probe.stdout)["streams"]
            video_stream = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual((video_stream["width"], video_stream["height"]), (1280, 720))
            self.assertTrue(any(item["codec_type"] == "audio" for item in streams))


if __name__ == "__main__":
    unittest.main()
