"""Make bundled command-line media tools discoverable by StoryFlow."""

from __future__ import annotations

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    os.environ["PATH"] = str(bundle_root) + os.pathsep + os.environ.get("PATH", "")
