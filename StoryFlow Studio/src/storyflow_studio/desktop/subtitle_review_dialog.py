"""Read-only comparison of narration and viewer-facing subtitles."""

from __future__ import annotations

import os
from pathlib import Path
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..modules.beat import SubtitleCue, parse_srt


def _format_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def _overlapping_narration_text(
    cue: SubtitleCue, narration_cues: list[SubtitleCue]
) -> str:
    values: list[str] = []
    for narration in narration_cues:
        if narration.start >= cue.end or narration.end <= cue.start:
            continue
        if not values or values[-1] != narration.text:
            values.append(narration.text)
    return "\n".join(values)


def _same_visible_text(left: str, right: str) -> bool:
    """Ignore only wrapping/spacing when identifying a DNA text conversion."""

    return " ".join(left.split()) == " ".join(right.split())


class SubtitleReviewDialog(QDialog):
    """Compare narration.srt with screen.srt and safely edit screen text."""

    saved = Signal(str)

    def __init__(
        self,
        narration_path: Path,
        screen_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.screen_path = screen_path
        self.narration_cues = parse_srt(narration_path)
        self.screen_cues = parse_srt(screen_path)
        self.review_rows = [
            (cue, _overlapping_narration_text(cue, self.narration_cues))
            for cue in self.screen_cues
        ]
        self.original_screen_texts = [cue.text for cue in self.screen_cues]
        self.manually_edited_rows: set[int] = set()
        self._updating_table = False
        self.converted_row_count = sum(
            1
            for cue, narration_text in self.review_rows
            if narration_text and not _same_visible_text(narration_text, cue.text)
        )
        self.setWindowTitle("Screen Subtitle Review")
        self.resize(1180, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("Narration / Screen Subtitle Review")
        title.setObjectName("SettingsTitle")
        layout.addWidget(title)

        summary = QLabel(
            f"{len(self.narration_cues)} narration cues  ·  "
            f"{len(self.screen_cues)} screen cues  ·  "
            f"{self.converted_row_count} converted rows"
        )
        summary.setObjectName("InputSummary")
        layout.addWidget(summary)

        note = QLabel(
            "Mỗi dòng dùng timeline của screen.srt; cột Narration hiển thị nội dung "
            "gốc giao với timeline đó. Chỉ cột screen.srt được chỉnh sửa. Ô màu vàng "
            "là chuyển đổi theo DNA; ô màu xanh là nội dung đã sửa thủ công."
        )
        note.setObjectName("SettingsDescription")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(len(self.review_rows), 3)
        self.table.setObjectName("TimelineTable")
        self.table.setHorizontalHeaderLabels(
            ("Timeline", "narration.srt", "screen.srt")
        )
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.SelectedClicked
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self._updating_table = True
        for row, (cue, narration_text) in enumerate(self.review_rows):
            timeline = (
                f"{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}"
            )
            values = (timeline, narration_text, cue.text)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column != 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(
                    (Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                    if column
                    else (Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
                )
                converted = bool(
                    column == 2
                    and narration_text
                    and not _same_visible_text(narration_text, value)
                )
                if converted:
                    item.setBackground(QColor("#4a3b13"))
                    item.setForeground(QColor("#ffd66b"))
                    item.setData(Qt.ItemDataRole.UserRole, "converted")
                    item.setToolTip(f"Converted by Screen SRT DNA\n\n{value}")
                else:
                    item.setToolTip(value)
                self.table.setItem(row, column, item)
        self._updating_table = False
        self.table.resizeRowsToContents()
        self.table.itemChanged.connect(self._screen_text_changed)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.save_status = QLabel("")
        self.save_status.setObjectName("SettingsDescription")
        footer.addWidget(self.save_status)
        footer.addStretch(1)
        self.discard_button = QPushButton("Discard Changes")
        self.discard_button.setEnabled(False)
        self.discard_button.clicked.connect(self.discard_changes)
        footer.addWidget(self.discard_button)
        self.save_button = QPushButton("Save Changes")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_changes)
        footer.addWidget(self.save_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    @property
    def has_unsaved_changes(self) -> bool:
        return any(
            self.table.item(row, 2).text() != original
            for row, original in enumerate(self.original_screen_texts)
        )

    def _screen_text_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.column() != 2:
            return
        row = item.row()
        self._refresh_edit_state()
        self._apply_screen_cell_style(row)
        self.table.resizeRowToContents(row)

    def _refresh_edit_state(self) -> None:
        dirty = self.has_unsaved_changes
        self.save_button.setEnabled(dirty)
        self.discard_button.setEnabled(dirty)
        self.save_status.setText("Unsaved changes" if dirty else "")

    def _apply_screen_cell_style(self, row: int) -> None:
        item = self.table.item(row, 2)
        narration_text = self.review_rows[row][1]
        if item.text() != self.original_screen_texts[row] or row in self.manually_edited_rows:
            item.setBackground(QColor("#173f5f"))
            item.setForeground(QColor("#8fd3ff"))
            item.setData(Qt.ItemDataRole.UserRole, "edited")
            item.setToolTip(f"Manually edited screen subtitle\n\n{item.text()}")
        elif narration_text and not _same_visible_text(narration_text, item.text()):
            item.setBackground(QColor("#4a3b13"))
            item.setForeground(QColor("#ffd66b"))
            item.setData(Qt.ItemDataRole.UserRole, "converted")
            item.setToolTip(f"Converted by Screen SRT DNA\n\n{item.text()}")
        else:
            item.setData(Qt.ItemDataRole.BackgroundRole, None)
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
            item.setData(Qt.ItemDataRole.UserRole, None)
            item.setToolTip(item.text())

    def discard_changes(self) -> None:
        self._updating_table = True
        try:
            for row, original in enumerate(self.original_screen_texts):
                self.table.item(row, 2).setText(original)
                self._apply_screen_cell_style(row)
        finally:
            self._updating_table = False
        self._refresh_edit_state()
        self.table.resizeRowsToContents()

    def save_changes(self) -> None:
        if not self.has_unsaved_changes:
            return
        changed_rows = {
            row
            for row, original in enumerate(self.original_screen_texts)
            if self.table.item(row, 2).text() != original
        }
        blocks: list[str] = []
        for row, cue in enumerate(self.screen_cues):
            text = self.table.item(row, 2).text().replace("\r\n", "\n").replace("\r", "\n").strip()
            if not text or any(not line.strip() for line in text.split("\n")):
                QMessageBox.warning(
                    self,
                    "Save Screen Subtitles",
                    f"Dòng {row + 1} đang trống hoặc chứa dòng trống không hợp lệ.",
                )
                return
            blocks.append(
                f"{row + 1}\n{_format_timestamp(cue.start)} --> "
                f"{_format_timestamp(cue.end)}\n{text}"
            )
        content = "\n\n".join(blocks) + "\n"
        temporary = self.screen_path.parent / (
            f".{self.screen_path.name}.{uuid.uuid4().hex}.review"
        )
        try:
            temporary.write_text(content, encoding="utf-8")
            validated = parse_srt(temporary)
            os.replace(temporary, self.screen_path)
        except (OSError, ValueError, RuntimeError) as exc:
            temporary.unlink(missing_ok=True)
            QMessageBox.critical(self, "Save Screen Subtitles", str(exc))
            return

        self.screen_cues = validated
        self.original_screen_texts = [cue.text for cue in validated]
        self.manually_edited_rows.update(changed_rows)
        self._updating_table = True
        try:
            for row, text in enumerate(self.original_screen_texts):
                self.table.item(row, 2).setText(text)
                self._apply_screen_cell_style(row)
        finally:
            self._updating_table = False
        self._refresh_edit_state()
        self.save_status.setText("Saved")
        self.saved.emit(str(self.screen_path))

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.has_unsaved_changes:
            answer = QMessageBox.question(
                self,
                "Unsaved Screen Subtitle Changes",
                "Discard unsaved changes and close Review?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        event.accept()
