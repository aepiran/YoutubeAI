"""QProcess wrapper for the multi-source worker."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from gui_settings import GuiSettings, model_cache_dir, source_root


class WorkerRunner(QObject):
    line_received = Signal(str)
    beat_status = Signal(str, str)
    finished = Signal(int, str)
    started = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.started.connect(self.started)
        self.process.finished.connect(self._handle_finished)
        self.process.errorOccurred.connect(self._handle_error)
        self._buffer = ""
        self._stopping = False

    @property
    def is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start(
        self,
        *,
        project_dir: Path,
        csv_path: Path,
        settings: GuiSettings,
        pexels_key: str,
        pixabay_key: str,
        force: bool = False,
    ) -> None:
        if self.is_running:
            raise RuntimeError("Worker is already running")
        providers = []
        if settings.use_pexels:
            providers.append("pexels")
        if settings.use_pixabay:
            providers.append("pixabay")
        args = [
            "--project-dir", str(project_dir),
            "--csv", str(csv_path),
            "--output-dir", str(project_dir / "video"),
            "--manifest", str(
                project_dir / ".cache" / "stock-footage-supplement.json"
                if csv_path.name == "footage_download_plan.csv"
                else project_dir / "selected-footage.json"
            ),
            "--providers", ",".join(providers),
            "--max-queries", str(settings.max_queries),
            "--max-pages", str(settings.max_pages),
            "--per-page", str(settings.per_page),
            "--workers", str(settings.workers),
            "--clips-per-beat", str(settings.clips_per_beat),
            "--candidate-pool", str(settings.candidate_pool),
            "--shortlist", str(settings.shortlist),
            "--min-duration", str(settings.min_duration),
            "--min-score", str(settings.min_score),
            "--min-width", str(settings.min_width),
            "--min-height", str(settings.min_height),
            "--max-pixabay-downloads", str(settings.max_pixabay_downloads),
            "--model-cache-dir", str(model_cache_dir(settings)),
            "--library-dir", settings.library_dir,
        ]
        if not settings.use_local_library:
            args.append("--no-local-library")
        if not settings.auto_archive_library:
            args.append("--no-auto-archive")
        if settings.dry_run:
            args.append("--dry-run")
        if force:
            args.append("--force")

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("HF_HUB_DISABLE_TELEMETRY", "1")
        environment.insert("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        environment.insert("PEXELS_API_KEY", pexels_key)
        environment.insert("PIXABAY_API_KEY", pixabay_key)
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(source_root()))
        self._buffer = ""
        self._stopping = False

        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = ["--stock-worker", *args]
        else:
            program = sys.executable
            arguments = ["-u", str(source_root() / "multi_source.py"), *args]
        self.process.start(program, arguments)

    def stop(self) -> None:
        if not self.is_running:
            return
        self._stopping = True
        self.line_received.emit("Stopping worker...")
        self.process.terminate()
        QTimer.singleShot(3000, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self.is_running:
            self.process.kill()

    def _read_output(self) -> None:
        chunk = bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._process_line(line.rstrip("\r"))

    def _process_line(self, line: str) -> None:
        if not line:
            return
        self.line_received.emit(line)
        patterns = [
            (r"^([A-Za-z]+\d+): ranked (\d+) candidates", lambda m: f"Ranked {m.group(2)}"),
            (r"^([A-Za-z]+\d+): downloaded (.+)$", lambda m: "Downloaded"),
            (r"^([A-Za-z]+\d+): reused (.+)$", lambda m: "Reused"),
            (r"^([A-Za-z]+\d+): download failed", lambda m: "Download error"),
            (r"^([A-Za-z]+\d+): no suitable candidate", lambda m: "No result"),
            (r"^([A-Za-z]+\d+): resume", lambda m: "Resumed"),
        ]
        for pattern, status_builder in patterns:
            match = re.search(pattern, line)
            if match:
                self.beat_status.emit(match.group(1), status_builder(match))
                break

    def _handle_finished(self, exit_code: int, _status) -> None:
        if self._buffer.strip():
            self._process_line(self._buffer.strip())
        message = "Stopped" if self._stopping else ("Completed" if exit_code == 0 else "Failed")
        self.finished.emit(exit_code, message)

    def _handle_error(self, error) -> None:
        self.line_received.emit(f"Process error: {error}")
