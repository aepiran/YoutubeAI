from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import AppSettings, VideoBuilderSettings
from storyflow_studio.modules.tts import CancellationToken
from storyflow_studio.modules.video_builder import CapCutPackageExporter
from storyflow_studio.modules.workspace import WorkspaceService


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class CapCutExportTests(unittest.TestCase):
    def test_exports_portable_editable_package_from_saved_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = WorkspaceService().create_project(
                Path(directory) / "workspace", "CapCut", "capcut", AppSettings()
            )
            source = project.path_for("footage_dir") / "H01_LOCAL.mp4"
            source.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
                ],
                check=True,
            )
            project.path_for("audio_file").write_bytes(b"narration")
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nTest\n", encoding="utf-8"
            )
            rows = tuple(
                {
                    "cut": index + 1,
                    "beat": "H01",
                    "timeline_start": float(index),
                    "timeline_end": float(index + 1),
                    "footage": "video/H01_LOCAL.mp4",
                    "source_start": float(index),
                }
                for index in range(2)
            )
            updates = []

            result = CapCutPackageExporter().export(
                project,
                AppSettings(
                    video_builder=VideoBuilderSettings(
                        resolution="720p", encoder_preset="ultrafast"
                    )
                ),
                rows,
                2.0,
                updates.append,
                CancellationToken(),
            )

            self.assertEqual(result.scene_count, 2)
            self.assertEqual(len(tuple((result.package_dir / "scenes").glob("*.mp4"))), 2)
            self.assertTrue((result.package_dir / "narration.mp3").is_file())
            self.assertTrue((result.package_dir / "captions.srt").is_file())
            self.assertTrue((result.package_dir / "selected_scenes.csv").is_file())
            self.assertTrue((result.package_dir / "README_CAPCUT.txt").is_file())
            manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "storyflow.capcut-package")
            self.assertEqual(manifest["canvas"]["duration_seconds"], 2.0)
            self.assertEqual(len(manifest["tracks"]["video"]), 2)
            self.assertEqual(updates[-1].state, "completed")


if __name__ == "__main__":
    unittest.main()
