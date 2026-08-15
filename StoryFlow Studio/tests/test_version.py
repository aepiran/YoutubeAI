from __future__ import annotations

import unittest
from unittest.mock import patch

from importlib import metadata

from storyflow_studio import __version__ as source_version
from storyflow_studio.core.version import application_version, version_badge


class VersionTests(unittest.TestCase):
    def test_version_comes_from_installed_build_metadata(self) -> None:
        with patch(
            "storyflow_studio.core.version.metadata.version",
            return_value="4.2.1",
        ):
            self.assertEqual(application_version(), "4.2.1")
            self.assertEqual(version_badge(), "v4.2.1")

    def test_source_version_is_used_without_an_installed_build(self) -> None:
        with patch(
            "storyflow_studio.core.version.metadata.version",
            side_effect=metadata.PackageNotFoundError,
        ):
            self.assertEqual(application_version(), source_version)


if __name__ == "__main__":
    unittest.main()
