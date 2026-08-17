from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from storyflow_studio.core.media import probe_media_info


class MediaProbeTests(unittest.TestCase):
    def test_probe_media_info_reads_video_stream_metadata(self) -> None:
        payload = {
            "format": {"duration": "12.5"},
            "streams": [
                {
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.mp4"
            path.write_bytes(b"video")
            with patch("storyflow_studio.core.media.shutil.which", return_value="ffprobe"):
                with patch(
                    "storyflow_studio.core.media.subprocess.run",
                    return_value=SimpleNamespace(stdout=json.dumps(payload)),
                ):
                    info = probe_media_info(path)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.duration, 12.5)
        self.assertEqual((info.width, info.height), (1920, 1080))
        self.assertAlmostEqual(info.fps, 29.97003, places=5)
        self.assertEqual(info.codec, "h264")


if __name__ == "__main__":
    unittest.main()
