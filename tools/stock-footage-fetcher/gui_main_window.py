"""Main desktop window for the Pexels/Pixabay stock workflow."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QCloseEvent, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui_dialogs import GuideDialog, SettingsDialog
from gui_runner import WorkerRunner
from gui_settings import (
    GuiSettings,
    icon_path,
    load_api_keys,
    load_settings,
    save_api_keys,
    save_settings,
)
from gui_theme import (
    APP_STYLE_SHEET,
    HEADER_SUBTITLE_STYLE,
    HEADER_TITLE_STYLE,
    MUTED_LABEL_STYLE,
    SECTION_TITLE_STYLE,
    chip_style,
)


APP_NAME = "Stock Footage Finder"
APP_VERSION = "1.0.0"
REQUIRED_COLUMNS = {"ma_beat", "y_chinh", "tu_khoa", "hinh_can_tim", "tranh"}
TERMINAL_STATUSES = {"Downloaded", "Download error", "No result", "Resumed"}


class MainWindow(QMainWindow):
    def __init__(self, initial_project: str | None = None) -> None:
        super().__init__()
        self.settings: GuiSettings = load_settings()
        self.pexels_key, self.pixabay_key = load_api_keys()
        self.csv_path: Path | None = None
        self.project_dir: Path | None = None
        self.rows: list[dict[str, str]] = []
        self.row_by_beat: dict[str, int] = {}
        self.finished_beats: set[str] = set()
        self.runner = WorkerRunner(self)

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        icon = icon_path()
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1480, 920)
        self.setStyleSheet(APP_STYLE_SHEET)
        self._build_ui()
        self._connect_runner()
        self._refresh_source_chip()

        initial = initial_project or self.settings.last_project_dir
        if initial:
            self._load_path(Path(initial))

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_queue_panel())
        splitter.addWidget(self._build_result_panel())
        splitter.setSizes([520, 960])
        root_layout.addWidget(splitter, 1)

        root_layout.addWidget(self._build_log_panel())
        root_layout.addWidget(self._build_control_bar())

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Header")
        frame.setFixedHeight(68)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)

        logo = QLabel("S")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(46, 46)
        pixmap = QPixmap(str(icon_path()))
        if pixmap.isNull():
            logo.setStyleSheet(
                "background:#6d42e8;color:white;border-radius:9px;"
                "font-size:24px;font-weight:800;"
            )
        else:
            logo.setText("")
            logo.setPixmap(
                pixmap.scaled(
                    46,
                    46,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_row = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setStyleSheet(HEADER_TITLE_STYLE)
        version = QLabel(f"v{APP_VERSION}")
        version.setStyleSheet(chip_style("#18243a", "#c7d2fe", "#33445e"))
        title_row.addWidget(title)
        title_row.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        subtitle = QLabel("Tìm, chấm và tải footage Pexels + Pixabay bằng AI.")
        subtitle.setStyleSheet(HEADER_SUBTITLE_STYLE)
        title_box.addLayout(title_row)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)

        self.source_chip = QLabel()
        self.source_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.source_chip)
        settings_button = QPushButton("⚙ Settings")
        settings_button.clicked.connect(self._open_settings)
        guide_button = QPushButton("Hướng dẫn")
        guide_button.clicked.connect(lambda: GuideDialog(self).exec())
        layout.addWidget(settings_button)
        layout.addWidget(guide_button)
        return frame

    def _build_toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Toolbar")
        frame.setFixedHeight(64)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(9)

        label = QLabel("Project / CSV")
        label.setStyleSheet("color:#f7f9ff;font-weight:700;")
        layout.addWidget(label)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Chọn thư mục project hoặc file footage.csv")
        self.path_edit.returnPressed.connect(self._load_path_from_edit)
        layout.addWidget(self.path_edit, 1)

        choose_project = QPushButton("Chọn Project")
        choose_project.clicked.connect(self._choose_project)
        choose_csv = QPushButton("Chọn CSV")
        choose_csv.clicked.connect(self._choose_csv)
        reload_button = QPushButton("↻ Reload")
        reload_button.clicked.connect(self._reload_project)
        layout.addWidget(choose_project)
        layout.addWidget(choose_csv)
        layout.addWidget(reload_button)

        self.csv_chip = QLabel("0 Beat")
        self.csv_chip.setMinimumWidth(90)
        self.csv_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.csv_chip.setStyleSheet(chip_style("#172554", "#93c5fd", "#3b82f6"))
        layout.addWidget(self.csv_chip)
        return frame

    def _build_queue_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 6, 8)

        heading = QLabel("REQUEST QUEUE")
        heading.setStyleSheet(SECTION_TITLE_STYLE)
        layout.addWidget(heading)
        hint = QLabel("Các Beat được đọc trực tiếp từ footage.csv")
        hint.setStyleSheet(MUTED_LABEL_STYLE)
        layout.addWidget(hint)

        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(["#", "BEAT", "Ý CHÍNH", "STATUS"])
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.verticalHeader().setVisible(False)
        header = self.queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.queue_table, 1)
        return panel

    def _build_result_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 12, 12, 8)

        row = QHBoxLayout()
        heading = QLabel("SELECTED FOOTAGE")
        heading.setStyleSheet(SECTION_TITLE_STYLE)
        row.addWidget(heading)
        row.addStretch(1)
        refresh = QPushButton("↻ Load Manifest")
        refresh.clicked.connect(self._load_manifest)
        open_output = QPushButton("Mở thư mục Video")
        open_output.clicked.connect(self._open_output_folder)
        row.addWidget(refresh)
        row.addWidget(open_output)
        layout.addLayout(row)

        self.tabs = QTabWidget()
        self.result_table = QTableWidget(0, 9)
        self.result_table.setHorizontalHeaderLabels(
            ["Beat", "Rank", "Source", "Video ID", "Score", "Resolution", "Duration", "Status", "File"]
        )
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.doubleClicked.connect(self._open_selected_source)
        result_header = self.result_table.horizontalHeader()
        for column in range(8):
            result_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        result_header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.result_table, "Kết quả")

        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("Chọn một dòng kết quả để xem chi tiết nguồn và truy vấn.")
        self.result_table.itemSelectionChanged.connect(self._show_result_detail)
        detail_layout.addWidget(self.detail_text)
        self.tabs.addTab(detail_page, "Chi tiết")
        layout.addWidget(self.tabs, 1)
        return panel

    def _build_log_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Footer")
        frame.setMinimumHeight(150)
        frame.setMaximumHeight(220)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)
        row = QHBoxLayout()
        title = QLabel("PROCESS LOG")
        title.setStyleSheet(SECTION_TITLE_STYLE)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.log_edit.clear())
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(clear)
        layout.addLayout(row)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.document().setMaximumBlockCount(2000)
        layout.addWidget(self.log_edit)
        return frame

    def _build_control_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ControlBar")
        frame.setFixedHeight(64)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumWidth(320)
        layout.addWidget(self.progress, 1)

        self.progress_label = QLabel("Ready")
        self.progress_label.setMinimumWidth(150)
        self.progress_label.setStyleSheet(MUTED_LABEL_STYLE)
        layout.addWidget(self.progress_label)

        self.force_check = QCheckBox("Tìm lại từ đầu")
        self.force_check.setToolTip("Bỏ lựa chọn trong manifest cũ và chọn lại toàn bộ")
        layout.addWidget(self.force_check)

        self.start_button = QPushButton("▶ Start Search")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_search)
        self.stop_button = QPushButton("■ Stop")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.runner.stop)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        return frame

    def _connect_runner(self) -> None:
        self.runner.line_received.connect(self._append_log)
        self.runner.beat_status.connect(self._set_beat_status)
        self.runner.started.connect(self._worker_started)
        self.runner.finished.connect(self._worker_finished)

    def _choose_project(self) -> None:
        start = str(self.project_dir or Path.cwd())
        selected = QFileDialog.getExistingDirectory(self, "Chọn Project", start)
        if selected:
            self._load_path(Path(selected))

    def _choose_csv(self) -> None:
        start = str(self.project_dir or Path.cwd())
        selected, _ = QFileDialog.getOpenFileName(
            self, "Chọn footage.csv", start, "CSV files (*.csv)"
        )
        if selected:
            self._load_path(Path(selected))

    def _load_path_from_edit(self) -> None:
        raw = self.path_edit.text().strip().strip('"')
        if raw:
            self._load_path(Path(raw))

    def _load_path(self, path: Path) -> None:
        path = path.expanduser().resolve()
        csv_path = path / "footage.csv" if path.is_dir() else path
        if not csv_path.is_file():
            self._show_error(f"Không tìm thấy footage.csv tại:\n{csv_path}")
            return
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fields = set(reader.fieldnames or [])
                missing = REQUIRED_COLUMNS - fields
                if missing:
                    raise ValueError("Thiếu cột: " + ", ".join(sorted(missing)))
                rows = [
                    {key: str(value or "").strip() for key, value in row.items()}
                    for row in reader
                ]
        except (OSError, ValueError, csv.Error) as exc:
            self._show_error(f"Không thể đọc CSV:\n{exc}")
            return
        self.csv_path = csv_path
        self.project_dir = (
            csv_path.parent.parent
            if csv_path.name == "footage_download_plan.csv"
            and csv_path.parent.name == ".cache"
            else csv_path.parent
        )
        self.rows = rows
        self.settings.last_project_dir = str(self.project_dir)
        save_settings(self.settings)
        self.path_edit.setText(str(csv_path))
        self._populate_queue()
        self._load_manifest()
        self.csv_chip.setText(f"{len(rows)} Beat")
        self._append_log(f"Loaded {len(rows)} Beat from {csv_path.name}")

    def _reload_project(self) -> None:
        if self.csv_path:
            self._load_path(self.csv_path)

    def _populate_queue(self) -> None:
        self.queue_table.setRowCount(len(self.rows))
        self.row_by_beat.clear()
        self.finished_beats.clear()
        for index, source in enumerate(self.rows):
            beat = source.get("ma_beat", "").upper()
            self.row_by_beat[beat] = index
            values = [str(index + 1), beat, source.get("y_chinh", ""), "Pending"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {0, 1, 3}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.queue_table.setItem(index, column, item)
        self.progress.setValue(0)
        self.progress_label.setText("Ready")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self.settings, self.pexels_key, self.pixabay_key, self
        )
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        settings, pexels, pixabay = dialog.values()
        settings.last_project_dir = self.settings.last_project_dir
        self.settings = settings
        self.pexels_key = pexels
        self.pixabay_key = pixabay
        save_settings(self.settings)
        save_api_keys(pexels, pixabay)
        self._refresh_source_chip()
        self._append_log("Settings saved.")

    def _refresh_source_chip(self) -> None:
        sources = []
        if self.settings.use_pexels:
            sources.append("Pexels")
        if self.settings.use_pixabay:
            sources.append("Pixabay")
        text = " + ".join(sources) if sources else "No source"
        valid = (
            (not self.settings.use_pexels or bool(self.pexels_key))
            and (not self.settings.use_pixabay or bool(self.pixabay_key))
            and bool(sources)
        )
        self.source_chip.setText(text)
        self.source_chip.setStyleSheet(
            chip_style(
                "#143322" if valid else "#3b1d24",
                "#86efac" if valid else "#fca5a5",
                "#22c55e" if valid else "#ef4444",
            )
        )

    def _start_search(self) -> None:
        if not self.csv_path or not self.project_dir:
            self._show_error("Hãy chọn project có footage.csv trước.")
            return
        if not self.settings.use_pexels and not self.settings.use_pixabay:
            self._show_error("Hãy bật ít nhất một nguồn trong Settings.")
            return
        if self.settings.use_pexels and not self.pexels_key:
            self._show_error("Thiếu Pexels API key trong Settings.")
            return
        if self.settings.use_pixabay and not self.pixabay_key:
            self._show_error("Thiếu Pixabay API key trong Settings.")
            return
        for index in range(self.queue_table.rowCount()):
            self.queue_table.item(index, 3).setText("Pending")
        self.finished_beats.clear()
        self.progress.setValue(0)
        try:
            self.runner.start(
                project_dir=self.project_dir,
                csv_path=self.csv_path,
                settings=self.settings,
                pexels_key=self.pexels_key,
                pixabay_key=self.pixabay_key,
                force=self.force_check.isChecked(),
            )
        except RuntimeError as exc:
            self._show_error(str(exc))

    def _worker_started(self) -> None:
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress.setRange(0, 0)
        mode = "DRY RUN" if self.settings.dry_run else "DOWNLOAD"
        self.progress_label.setText(f"Running · {mode}")
        self._append_log("Worker started.")

    def _worker_finished(self, exit_code: int, message: str) -> None:
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if exit_code == 0 else self.progress.value())
        self.progress_label.setText(message)
        self._append_log(f"Worker finished with exit code {exit_code}.")
        self._load_manifest()
        if exit_code != 0 and message != "Stopped":
            QMessageBox.warning(
                self,
                "Workflow chưa hoàn tất",
                "Tiến trình kết thúc với lỗi. Hãy xem Process Log để biết chi tiết.",
            )

    def _set_beat_status(self, beat: str, status: str) -> None:
        row = self.row_by_beat.get(beat)
        if row is None:
            return
        item = self.queue_table.item(row, 3)
        item.setText(status)
        colors = {
            "Downloaded": "#4ade80",
            "Resumed": "#60a5fa",
            "No result": "#fbbf24",
            "Download error": "#f87171",
        }
        item.setForeground(QColor(colors.get(status, "#c4b5fd")))
        if status in TERMINAL_STATUSES:
            self.finished_beats.add(beat)
            total = max(1, len(self.rows))
            self.progress.setRange(0, 100)
            self.progress.setValue(round(len(self.finished_beats) / total * 100))
            self.progress_label.setText(f"{len(self.finished_beats)} / {len(self.rows)} Beat")

    def _load_manifest(self) -> None:
        self.result_table.setRowCount(0)
        self.result_table.setProperty("manifest_rows", [])
        if not self.project_dir:
            return
        path = (
            self.project_dir / ".cache" / "stock-footage-supplement.json"
            if self.csv_path is not None
            and self.csv_path.name == "footage_download_plan.csv"
            else self.project_dir / "selected-footage.json"
        )
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = list(payload.get("selections", []))
        except (OSError, ValueError, TypeError) as exc:
            self._append_log(f"Cannot read manifest: {exc}")
            return
        self.result_table.setProperty("manifest_rows", rows)
        self.result_table.setRowCount(len(rows))
        for index, source in enumerate(rows):
            width = source.get("width", "")
            height = source.get("height", "")
            duration = source.get("duration", "")
            try:
                score = f"{float(source.get('final_score', 0)):.3f}"
            except (TypeError, ValueError):
                score = ""
            values = [
                source.get("beat_id", ""),
                source.get("rank", ""),
                str(source.get("provider", "")).upper(),
                source.get("video_id", ""),
                score,
                f"{width}×{height}" if width and height else "",
                f"{float(duration):.1f}s" if duration not in {None, ""} else "",
                source.get("status", ""),
                source.get("filename", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column < 8:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.result_table.setItem(index, column, item)
        self.tabs.setTabText(0, f"Kết quả ({len(rows)})")

    def _manifest_row(self, table_row: int) -> dict:
        rows = self.result_table.property("manifest_rows") or []
        return rows[table_row] if 0 <= table_row < len(rows) else {}

    def _show_result_detail(self) -> None:
        selected = self.result_table.selectionModel().selectedRows()
        if not selected:
            self.detail_text.clear()
            return
        source = self._manifest_row(selected[0].row())
        lines = [
            f"Beat: {source.get('beat_id', '')}",
            f"Source: {str(source.get('provider', '')).upper()}",
            f"Video ID: {source.get('video_id', '')}",
            f"Contributor: {source.get('contributor', '')}",
            f"Query: {source.get('query', '')}",
            f"Semantic score: {source.get('semantic_score', '')}",
            f"Final score: {source.get('final_score', '')}",
            f"Resolution: {source.get('width', '')} × {source.get('height', '')}",
            f"Duration: {source.get('duration', '')} seconds",
            f"Status: {source.get('status', '')}",
            f"File: {source.get('filename', '')}",
            f"Source URL: {source.get('page_url', '')}",
            f"Error: {source.get('error', '')}",
        ]
        self.detail_text.setPlainText("\n".join(lines))

    def _open_selected_source(self, index) -> None:
        source = self._manifest_row(index.row())
        url = str(source.get("page_url") or "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _open_output_folder(self) -> None:
        if not self.project_dir:
            return
        output = self.project_dir / "video"
        output.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output)))

    def _append_log(self, message: str) -> None:
        self.log_edit.appendPlainText(message)
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, APP_NAME, message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.runner.is_running:
            answer = QMessageBox.question(
                self,
                "Đang chạy",
                "Workflow vẫn đang chạy. Bạn có muốn dừng và thoát?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.stop()
        save_settings(self.settings)
        event.accept()
