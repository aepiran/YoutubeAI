"""Unambiguous bridge to the legacy stock fetcher core module.

The integrated Builder also has a ``main.py``. Loading the stock core through
this bridge prevents ``multi_source`` from accidentally importing the Builder
entry point when both tools are packaged into one executable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _core_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "stock_fetcher" / "main.py"
    return Path(__file__).resolve().with_name("main.py")


_SPEC = importlib.util.spec_from_file_location(
    "_stock_footage_fetcher_core", _core_path()
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("Cannot load the Stock Footage Fetcher core module")
_CORE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CORE)

DEFAULT_MODEL = _CORE.DEFAULT_MODEL
DEFAULT_MODEL_CACHE = _CORE.DEFAULT_MODEL_CACHE
VisualScorer = _CORE.VisualScorer
load_env_file = _CORE.load_env_file
