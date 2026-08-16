from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.modules.music import (
    CCMixterCatalogService,
    MusicLibraryService,
)


class FakeResponse:
    def __init__(self, *, payload=None, content=b"", content_type="audio/mpeg"):
        self.payload = payload
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size=0):
        del chunk_size
        yield self.content


class FakeSession:
    def __init__(self, track):
        self.track = track
        self.headers = {}
        self.search_calls = []
        self.download_calls = []

    def get(self, url, **kwargs):
        if kwargs.get("params") is not None:
            self.search_calls.append(kwargs["params"])
            return FakeResponse(payload=[self.track])
        self.download_calls.append(url)
        return FakeResponse(content=b"valid fake mp3")


class CCMixterCatalogServiceTests(unittest.TestCase):
    def test_recommendation_download_is_imported_with_license_and_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recommendation_file = root / "project" / "audio" / "music_recommendations.json"
            recommendation_file.parent.mkdir(parents=True)
            recommendation_file.write_text(
                json.dumps(
                    {
                        "recommendations": [
                            {
                                "section_id": "S01",
                                "desired_mood": ["hopeful", "peaceful"],
                                "energy": "low",
                                "tempo": "slow",
                                "instruments": ["piano"],
                                "avoid": ["vocals"],
                                "minimum_duration_seconds": 120,
                                "search_queries": [
                                    "hopeful peaceful piano instrumental"
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            api_track = {
                "upload_id": 42,
                "upload_name": "Quiet Hope",
                "user_real_name": "Example Artist",
                "file_page_url": "https://ccmixter.org/files/example/42",
                "license_name": "Attribution",
                "license_url": "http://creativecommons.org/licenses/by/4.0/",
                "upload_tags": "ambient,hopeful,instrumental,piano,attribution",
                "files": [
                    {
                        "file_name": "example_-_Quiet_Hope.mp3",
                        "download_url": "https://ccmixter.org/content/example/quiet.mp3",
                        "file_format_info": {"ps": "3:20"},
                    }
                ],
            }
            session = FakeSession(api_track)
            service = CCMixterCatalogService(
                session=session,
                library_service=MusicLibraryService(
                    duration_probe=lambda _path: 200.0
                ),
            )

            result = service.find_and_download(
                recommendation_file, root / "library"
            )

            self.assertEqual(len(result.imported), 1)
            self.assertEqual(result.imported[0].source, "ccMixter")
            self.assertEqual(result.imported[0].artist, "Example Artist")
            self.assertIn("creativecommons.org/licenses/by/", result.imported[0].license_url)
            self.assertTrue(result.attribution_file.is_file())
            self.assertIn(
                "Quiet Hope", result.attribution_file.read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (root / "library" / "music_library.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("Example Artist", manifest["tracks"][0]["attribution"])
            self.assertTrue(session.search_calls)
            self.assertEqual(
                session.download_calls,
                ["https://ccmixter.org/content/example/quiet.mp3"],
            )

    def test_noncommercial_track_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recommendation_file = root / "audio" / "music_recommendations.json"
            recommendation_file.parent.mkdir()
            recommendation_file.write_text(
                json.dumps(
                    {
                        "recommendations": [
                            {
                                "section_id": "S01",
                                "search_queries": ["prayer piano"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            track = {
                "upload_id": 9,
                "upload_name": "NC Track",
                "user_real_name": "Artist",
                "file_page_url": "https://ccmixter.org/files/artist/9",
                "license_name": "Attribution Noncommercial",
                "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
                "files": [
                    {
                        "file_name": "nc.mp3",
                        "download_url": "https://ccmixter.org/content/artist/nc.mp3",
                        "file_format_info": {"ps": "2:00"},
                    }
                ],
            }
            service = CCMixterCatalogService(
                session=FakeSession(track),
                library_service=MusicLibraryService(
                    duration_probe=lambda _path: 120.0
                ),
            )

            with self.assertRaisesRegex(Exception, "Không tải được"):
                service.find_and_download(recommendation_file, root / "library")


if __name__ == "__main__":
    unittest.main()
