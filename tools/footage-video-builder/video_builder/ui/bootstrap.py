"""Application bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def app_icon_path() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "yt-vidbuilder-64.png"


def run_app() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Footage Video Builder")
    app.setOrganizationName("AronVideo")
    app.setWindowIcon(QIcon(str(app_icon_path())))
    window = MainWindow()
    window.showMaximized()
    return app.exec()
