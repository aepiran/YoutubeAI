from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from footage_library import (
    FootageLibrary,
    file_sha256,
    online_project_footage_filenames,
)
from multi_source import LocalLibraryProvider, Selection, download_candidate


def fake_video_metadata(_path: Path, thumbnail: Path) -> dict:
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 180), "navy").save(thumbnail, "JPEG")
    return {"width": 1920, "height": 1080, "duration": 12.0, "fps": 24.0}


def write_manifest(
    path: Path,
    filename: str,
    video_id: str = "42",
    query: str = "peaceful morning window",
) -> None:
    path.write_text(
        json.dumps(
            {
                "selections": [
                    {
                        "provider": "pexels",
                        "video_id": video_id,
                        "filename": filename,
                        "beat_id": "H01",
                        "query": query,
                        "tags": "window, morning, woman",
                        "width": 1920,
                        "height": 1080,
                        "duration": 12,
                        "status": "downloaded",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class FootageLibraryTests(unittest.TestCase):
    def test_project_import_only_includes_online_pexels_pixabay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video"
            video.mkdir()
            names = [
                "H01_PEXELS_42.mp4",
                "H02_PIXABAY_99.mp4",
                "H03_PEXELS_77.mp4",
                "H04_MANUAL_custom.mp4",
            ]
            for name in names:
                (video / name).write_bytes(name.encode())
            manifest = root / "selected-footage.json"
            manifest.write_text(
                json.dumps(
                    {
                        "selections": [
                            {
                                "filename": names[0],
                                "provider": "pexels",
                                "origin": "online",
                                "status": "downloaded",
                            },
                            {
                                "filename": names[1],
                                "provider": "pixabay",
                                "origin": "library",
                                "status": "reused",
                            },
                            {
                                "filename": names[3],
                                "provider": "manual",
                                "origin": "online",
                                "status": "downloaded",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = online_project_footage_filenames(video, [manifest])

            self.assertEqual(result, [names[0], names[2]])

    def test_archive_filter_leaves_unselected_project_files_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            video = project / "video"
            video.mkdir(parents=True)
            selected = video / "H01_PEXELS_42.mp4"
            untouched = video / "H02_PEXELS_99.mp4"
            selected.write_bytes(b"selected-video")
            untouched.write_bytes(b"existing-project-video")
            manifest = project / "selected-footage.json"
            write_manifest(manifest, selected.name)
            library = FootageLibrary(root / "library")

            with patch("footage_library._video_metadata", fake_video_metadata):
                result = library.archive_project(
                    project,
                    manifest_paths=[manifest],
                    filenames=[selected.name],
                )

            self.assertEqual(result.imported, 1)
            self.assertEqual(untouched.read_bytes(), b"existing-project-video")
            with closing(sqlite3.connect(library.database_path)) as connection:
                count = connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            self.assertEqual(count, 1)

    def test_archive_moves_asset_and_keeps_project_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            video = project / "video"
            video.mkdir(parents=True)
            source = video / "H01_PEXELS_42.mp4"
            source.write_bytes(b"video-content")
            manifest = project / "selected-footage.json"
            write_manifest(manifest, source.name)
            library = FootageLibrary(root / "library")

            with patch("footage_library._video_metadata", fake_video_metadata):
                result = library.archive_project(
                    project, manifest_paths=[manifest]
                )

            self.assertEqual(result.imported, 1)
            self.assertTrue(source.is_file())
            with closing(sqlite3.connect(library.database_path)) as connection:
                row = connection.execute(
                    "SELECT canonical_path, sha256 FROM assets"
                ).fetchone()
            canonical = Path(row[0])
            self.assertTrue(canonical.is_file())
            self.assertEqual(row[1], file_sha256(source))
            self.assertEqual(canonical.stat().st_ino, source.stat().st_ino)

    def test_duplicate_content_is_not_added_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = FootageLibrary(root / "library")
            projects = []
            for index, video_id in enumerate(("42", "99"), start=1):
                project = root / f"project-{index}"
                video = project / "video"
                video.mkdir(parents=True)
                source = video / f"H0{index}_PEXELS_{video_id}.mp4"
                source.write_bytes(b"same-video-content")
                manifest = project / "selected-footage.json"
                write_manifest(
                    manifest,
                    source.name,
                    video_id,
                    "peaceful morning window" if index == 1 else "woman at window",
                )
                projects.append((project, manifest))

            with patch("footage_library._video_metadata", fake_video_metadata):
                first = library.archive_project(
                    projects[0][0], manifest_paths=[projects[0][1]]
                )
                second = library.archive_project(
                    projects[1][0], manifest_paths=[projects[1][1]]
                )

            self.assertEqual(first.imported, 1)
            self.assertEqual(second.duplicates, 1)
            with closing(sqlite3.connect(library.database_path)) as connection:
                count = connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
                queries = json.loads(
                    connection.execute("SELECT queries FROM assets").fetchone()[0]
                )
            self.assertEqual(count, 1)
            self.assertEqual(
                queries, ["peaceful morning window", "woman at window"]
            )

    def test_local_provider_uses_same_candidate_and_materialization_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "source-project"
            video = project / "video"
            video.mkdir(parents=True)
            source = video / "H01_PEXELS_42.mp4"
            source.write_bytes(b"video-content")
            manifest = project / "selected-footage.json"
            write_manifest(manifest, source.name)
            library = FootageLibrary(root / "library")
            with patch("footage_library._video_metadata", fake_video_metadata):
                library.archive_project(project, manifest_paths=[manifest])

            candidates = LocalLibraryProvider(library).search(
                "morning window",
                max_pages=1,
                per_page=10,
                min_width=1920,
                min_height=1080,
                min_duration=8,
            )
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].origin, "library")
            selection = Selection("B02", 1, candidates[0])
            destination = download_candidate(
                selection, root / "target-project" / "video", object(), library
            )
            self.assertTrue(destination.is_file())
            self.assertEqual(selection.status, "reused")


if __name__ == "__main__":
    unittest.main()
