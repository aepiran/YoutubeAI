"""Desktop entry point and packaged worker entry point."""

from __future__ import annotations

import argparse
import sys


def run_gui(initial_project: str | None = None) -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from gui_main_window import MainWindow
    from gui_settings import icon_path

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Stock Footage Finder")
    app.setOrganizationName("TOOL-YOUTUBE")
    icon = icon_path()
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow(initial_project=initial_project)
    window.showMaximized()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"--worker", "--stock-worker"}:
        from multi_source import main as worker_main

        return worker_main(arguments[1:])
    parser = argparse.ArgumentParser(description="Stock Footage Finder GUI")
    parser.add_argument("--project", help="Project folder or script_beat.csv to open")
    parsed = parser.parse_args(arguments)
    return run_gui(parsed.project)


if __name__ == "__main__":
    raise SystemExit(main())
