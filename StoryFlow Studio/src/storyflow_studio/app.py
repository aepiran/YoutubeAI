"""StoryFlow Studio desktop entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .core.settings import SettingsStore
from .core.version import application_version
from .desktop.branding import application_icon
from .desktop.main_window import MainWindow
from .desktop.theme import APP_STYLE_SHEET
from .modules.ai import create_ai_service


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("StoryFlow Studio")
    app.setApplicationDisplayName("StoryFlow Studio")
    app.setApplicationVersion(application_version())
    app.setOrganizationName("StoryFlow Studio")
    app.setWindowIcon(application_icon())
    app.setStyleSheet(APP_STYLE_SHEET)
    return app


def main() -> int:
    app = create_application()
    settings_store = SettingsStore()
    window = MainWindow(
        ai_service=create_ai_service(settings_store.load().ai.provider),
        settings_store=settings_store,
    )
    window.showMaximized()
    return app.exec()
