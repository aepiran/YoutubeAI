"""Review script-aware background-music choices and missing-library suggestions."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
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


class MusicReviewError(RuntimeError):
    pass


def _timeline(start: object, end: object) -> str:
    def stamp(value: object) -> str:
        seconds = max(0.0, float(value))
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes):02d}:{seconds:06.3f}"

    return f"{stamp(start)}–{stamp(end)}"


def _joined(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip())
    return str(value or "")


class MusicReviewDialog(QDialog):
    import_requested = Signal()
    download_requested = Signal()
    generate_again_requested = Signal()
    browse_catalog_requested = Signal()

    def __init__(self, analysis_file: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.analysis_file = analysis_file
        try:
            payload = json.loads(analysis_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MusicReviewError(f"Không đọc được music analysis: {exc}") from exc
        sections = payload.get("sections") if isinstance(payload, dict) else None
        recommendations = (
            payload.get("recommendations") if isinstance(payload, dict) else None
        )
        if not isinstance(sections, list) or not sections:
            raise MusicReviewError("music_analysis.json chưa có sections hợp lệ.")
        if not isinstance(recommendations, list):
            raise MusicReviewError("music_analysis.json recommendations không hợp lệ.")
        self.sections = sections
        self.recommendations = {
            str(item.get("section_id", "")): item
            for item in recommendations
            if isinstance(item, dict)
        }

        self.setWindowTitle("Background Music Review")
        self.resize(1280, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("Script-aware Background Music Review")
        title.setObjectName("SettingsTitle")
        layout.addWidget(title)
        summary = QLabel(
            f"{len(sections)} emotional sections  ·  "
            f"{len(recommendations)} music recommendations"
        )
        summary.setObjectName("InputSummary")
        layout.addWidget(summary)
        note = QLabel(
            "Codex selected only tracks already in Music Library. Yellow rows have "
            "low confidence or would benefit from additional music. Search terms "
            "can be used in Mixkit or CapCut before importing a new track."
        )
        note.setObjectName("SettingsDescription")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(len(sections), 8)
        self.table.setObjectName("TimelineTable")
        self.table.setHorizontalHeaderLabels(
            (
                "Timeline",
                "Section",
                "Mood / Energy",
                "Selected Track",
                "Confidence",
                "Alternatives",
                "Search Recommendation",
                "Rationale",
            )
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for column in (1, 2, 3, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

        for row, section in enumerate(sections):
            section_id = str(section.get("section_id", ""))
            recommendation = self.recommendations.get(section_id, {})
            queries = recommendation.get(
                "search_queries", section.get("search_queries", [])
            )
            try:
                confidence = float(section.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            needs_more = bool(section.get("needs_more_music")) or confidence < 0.65
            values = (
                _timeline(section.get("start_seconds", 0), section.get("end_seconds", 0)),
                f"{section_id} · {section.get('purpose', '')}",
                " · ".join(
                    value
                    for value in (
                        _joined(section.get("mood", [])),
                        str(section.get("energy", "")),
                        str(section.get("tempo", "")),
                    )
                    if value
                ),
                str(section.get("selected_track", "")),
                f"{confidence * 100:.0f}%",
                _joined(section.get("alternatives", [])) or "—",
                "\n".join(str(item) for item in queries) if isinstance(queries, list) else str(queries),
                str(recommendation.get("reason", section.get("rationale", ""))),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                item.setToolTip(value)
                if needs_more:
                    item.setBackground(QColor("#4a3b13"))
                    item.setForeground(QColor("#ffd66b"))
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.copy_query_button = QPushButton("Copy Search Query")
        self.copy_query_button.clicked.connect(self._copy_search_query)
        footer.addWidget(self.copy_query_button)
        self.catalog_button = QPushButton("Browse Mixkit")
        self.catalog_button.clicked.connect(self.browse_catalog_requested.emit)
        footer.addWidget(self.catalog_button)
        self.download_button = QPushButton("Find & Download")
        self.download_button.setToolTip(
            "Search ccMixter for CC BY/Public Domain tracks and import them"
        )
        self.download_button.setEnabled(bool(recommendations))
        self.download_button.clicked.connect(self._download_recommendations)
        footer.addWidget(self.download_button)
        self.import_button = QPushButton("Import More Music…")
        self.import_button.clicked.connect(self.import_requested.emit)
        footer.addWidget(self.import_button)
        footer.addStretch(1)
        self.generate_button = QPushButton("Generate Again")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self._generate_again)
        footer.addWidget(self.generate_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    def _copy_search_query(self) -> None:
        row = self.table.currentRow()
        if row < 0 and self.table.rowCount():
            row = 0
        if row >= 0:
            QApplication.clipboard().setText(self.table.item(row, 6).text())

    def _generate_again(self) -> None:
        self.generate_again_requested.emit()
        self.accept()

    def _download_recommendations(self) -> None:
        self.download_requested.emit()
        self.accept()
