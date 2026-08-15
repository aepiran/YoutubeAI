"""Read-only timeline review for Video Builder Phase 7B2A."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..modules.video_builder import TimelineReviewResult


class TimelineReviewDialog(QDialog):
    retry_missing_requested = Signal()
    preview_requested = Signal(str)
    replace_requested = Signal(int)

    def __init__(self, review: TimelineReviewResult, parent: QWidget | None = None):
        super().__init__(parent)
        self.review = review
        self.setWindowTitle("Timeline Review")
        self.resize(1180, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("Video Timeline Review")
        title.setObjectName("SettingsTitle")
        layout.addWidget(title)

        state = "INPUTS CHANGED · SAVED TIMELINE" if review.stale else review.status.upper()
        summary = QLabel(
            f"{review.cut_count} Cuts  ·  {review.warning_count} Warnings  ·  "
            f"{len(review.missing_beats)} Missing Beats  ·  {state}"
        )
        summary.setObjectName("InputSummary")
        summary.setProperty("stale", review.stale)
        layout.addWidget(summary)

        if review.stale:
            note = QLabel(
                "Script, Beat timing, footage inventory hoặc Video Builder settings "
                "đã thay đổi sau lần Analyze gần nhất. Render vẫn sử dụng timeline "
                "đã lưu này; chỉ chạy Analyze Again khi muốn cập nhật plan."
            )
            note.setObjectName("SettingsDescription")
            note.setWordWrap(True)
            layout.addWidget(note)

        self.table = QTableWidget(len(review.rows), 10)
        self.table.setObjectName("TimelineTable")
        self.table.setHorizontalHeaderLabels(
            (
                "Cut",
                "Beat",
                "Timeline",
                "Duration",
                "Footage",
                "Source Window",
                "Scene",
                "Technical",
                "Semantic",
                "Warnings",
            )
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)
        for row_index, row in enumerate(review.rows):
            warnings = row.get("warnings", [])
            footage = str(row.get("footage", ""))
            technical = row.get("technical_score")
            semantic = row.get("semantic_score")
            if not footage:
                technical_label = "Missing"
            elif isinstance(technical, (int, float)):
                technical_label = f"{float(technical) * 100:.0f}%"
            else:
                technical_label = "Pending"
            values = (
                str(row.get("cut", "")),
                str(row.get("beat", "")),
                f"{float(row.get('timeline_start', 0)):.2f}–"
                f"{float(row.get('timeline_end', 0)):.2f}s",
                f"{float(row.get('duration', 0)):.2f}s",
                footage or "Missing footage",
                (
                    f"{float(row.get('source_start', 0)):.2f}–"
                    f"{float(row.get('source_end', 0)):.2f}s"
                    if footage
                    else "—"
                ),
                str(row.get("scene_index", "—")),
                technical_label,
                (
                    f"{float(semantic) * 100:.0f}%"
                    if isinstance(semantic, (int, float))
                    else "Pending"
                ),
                ", ".join(warnings) if isinstance(warnings, list) else str(warnings),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {0, 1, 3, 6, 7, 8}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if footage:
                    item.setToolTip(
                        f"Footage: {footage}\n"
                        f"Narration: {row.get('narration', '')}\n"
                        f"Warnings: {values[9] or 'None'}"
                    )
                if warnings:
                    item.setForeground(QColor("#ffd38a"))
                elif column in {7, 8}:
                    item.setForeground(QColor("#78ddb7"))
                self.table.setItem(row_index, column, item)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.preview_button = QPushButton("Preview Clip")
        self.preview_button.setEnabled(False)
        self.preview_button.clicked.connect(self._preview_selected)
        footer.addWidget(self.preview_button)
        self.replace_button = QPushButton("Replace Clip")
        self.replace_button.setEnabled(False)
        self.replace_button.clicked.connect(self._replace_selected)
        footer.addWidget(self.replace_button)
        footer.addStretch(1)
        self.retry_button = QPushButton("Retry Missing")
        self.retry_button.setObjectName("PrimaryButton")
        self.retry_button.setEnabled(bool(review.missing_beats))
        self.retry_button.setToolTip(
            "Return missing Beats to Footage Finder, preserving downloaded clips"
        )
        self.retry_button.clicked.connect(self._retry_missing)
        footer.addWidget(self.retry_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)
        self.table.itemSelectionChanged.connect(self._selection_changed)

    def _retry_missing(self) -> None:
        self.retry_missing_requested.emit()
        self.accept()

    def _selected_row(self) -> dict | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        index = indexes[0].row()
        return self.review.rows[index] if index < len(self.review.rows) else None

    def _selection_changed(self) -> None:
        row = self._selected_row()
        self.preview_button.setEnabled(bool(row and row.get("footage")))
        self.replace_button.setEnabled(bool(row) and not self.review.stale)

    def _preview_selected(self) -> None:
        row = self._selected_row()
        if row and row.get("footage"):
            self.preview_requested.emit(str(row["footage"]))

    def _replace_selected(self) -> None:
        row = self._selected_row()
        if row is not None:
            self.replace_requested.emit(int(row.get("cut", 0)))
