"""PyInstaller entry point for StoryFlow Studio."""

import sys


def _verify_bundle() -> int:
    """Verify resources that PyInstaller cannot discover from static imports."""
    from codex_cli_bin import bundled_codex_path, bundled_package_dir

    bundled_package_dir()
    bundled_codex_path()
    return 0


if "--verify-bundle" in sys.argv:
    raise SystemExit(_verify_bundle())

from storyflow_studio.app import main


raise SystemExit(main())
