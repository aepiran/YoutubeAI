from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.modules.music import (
    MIXKIT_CATALOG_URL,
    MIXKIT_LICENSE_NAME,
    MIXKIT_LICENSE_URL,
    MusicLibraryError,
    MusicLibraryService,
)


class MusicLibraryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MusicLibraryService(duration_probe=lambda _path: 42.125)

    def test_import_copies_track_and_records_license_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "downloads" / "gentle-prayer.mp3"
            source.parent.mkdir()
            source.write_bytes(b"fake audio payload")
            library = root / "music"

            result = self.service.import_files([source], library)

            self.assertEqual(len(result.imported), 1)
            track = result.imported[0]
            self.assertEqual(track.filename, source.name)
            self.assertEqual(track.duration_seconds, 42.125)
            self.assertEqual(track.source, "Mixkit")
            self.assertEqual(track.source_url, MIXKIT_CATALOG_URL)
            self.assertEqual(track.license, MIXKIT_LICENSE_NAME)
            self.assertEqual(track.license_url, MIXKIT_LICENSE_URL)
            self.assertEqual((library / source.name).read_bytes(), source.read_bytes())

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(len(manifest["tracks"]), 1)
            self.assertEqual(
                manifest["tracks"][0]["sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )

    def test_duplicate_content_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "track.mp3"
            source.write_bytes(b"same track")
            library = root / "music"

            self.service.import_files([source], library)
            result = self.service.import_files([source], library)

            self.assertEqual(result.imported, ())
            self.assertEqual(result.skipped, (source.name,))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["tracks"]), 1)

    def test_name_collision_uses_hash_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one" / "music.mp3"
            second = root / "two" / "music.mp3"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            library = root / "library"

            self.service.import_files([first], library)
            result = self.service.import_files([second], library)

            digest = hashlib.sha256(second.read_bytes()).hexdigest()
            self.assertEqual(result.imported[0].filename, f"music-{digest[:8]}.mp3")
            self.assertEqual((library / result.imported[0].filename).read_bytes(), b"second")

    def test_rejects_unreadable_audio_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "broken.mp3"
            source.write_bytes(b"not audio")
            service = MusicLibraryService(duration_probe=lambda _path: None)

            with self.assertRaisesRegex(MusicLibraryError, "audio metadata"):
                service.import_files([source], Path(directory) / "library")


if __name__ == "__main__":
    unittest.main()
