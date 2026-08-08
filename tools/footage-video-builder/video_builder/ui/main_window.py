"""Main window styled after Footage Finder AI."""

from __future__ import annotations

import csv
import importlib.util
import inspect
import json
import re
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import (
    QFileInfo,
    QProcess,
    QProcessEnvironment,
    QUrl,
    QSize,
    QSettings,
    Signal,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QIcon,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialogButtonBox,
    QDialog,
    QFileDialog,
    QFileIconProvider,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..inputs import (
    VIDEO_EXTENSIONS,
    discover_srt_files,
    filename_beat_code,
    load_beats,
    normalize_beat_code,
    numbered_voice_files,
    parse_script_sections,
)
from ..section_processing import map_beats_for_preview
from ..config import VISION_MODELS, default_config
from ..model_manager import check_clip_cache
from ..footage_supplement import write_supplement_plan
from .settings_dialog import BuilderUiSettings, SettingsDialog
from .theme import (
    APP_STYLE_SHEET,
    HEADER_SUBTITLE_STYLE,
    HEADER_TITLE_STYLE,
    MUTED_LABEL_STYLE,
    SECTION_TITLE_STYLE,
)


APP_NAME = "Footage Video Builder"
APP_VERSION = "1.0"
ROOT_DIR = Path(__file__).resolve().parents[2]
ICON_PATH = ROOT_DIR / "assets" / "yt-vidbuilder-64.png"
PROJECT_NEW_ICON = ROOT_DIR / "assets" / "project-new.svg"
PROJECT_OPEN_ICON = ROOT_DIR / "assets" / "project-open.svg"
NAV_EXPAND_ICON = ROOT_DIR / "assets" / "nav-expand.svg"
NAV_COLLAPSE_ICON = ROOT_DIR / "assets" / "nav-collapse.svg"
SETTINGS_ICON = ROOT_DIR / "assets" / "settings.svg"
HELP_ICON = ROOT_DIR / "assets" / "help.svg"
REFRESH_ICON = ROOT_DIR / "assets" / "refresh.svg"
PROJECT_STATE_FILENAME = "footage_builder_state.json"
PROJECT_CONFIG_FILENAME = "footage_builder_config.json"
LOG_BEAT_CODES_PATTERN = r"([A-Za-z]+\d+(?:\+[A-Za-z]+\d+)*)"
BEAT_STATUS_COLUMN = 13
FROZEN_BEAT_COLUMN_WIDTHS = (70, 120)
HEALTH_LEVELS = {"ok": 0, "warning": 1, "critical": 2}
HEALTH_DETAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 20
HEALTH_KEYWORDS_ROLE = int(Qt.ItemDataRole.UserRole) + 21
BEAT_STATE_ROLE = int(Qt.ItemDataRole.UserRole) + 22


def format_stage_duration(seconds: float) -> str:
    """Format a live Stage duration without noisy sub-second precision."""
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def preferred_project_voice(root: Path) -> Path | None:
    """Prefer the canonical DWG narration file without blocking manual choice."""
    for folder in (root / "audio", root / "voice", root / "voices", root):
        if not folder.is_dir():
            continue
        match = next(
            (
                path
                for path in folder.iterdir()
                if path.is_file() and path.name.casefold() == "001.mp3"
            ),
            None,
        )
        if match is not None:
            return match.resolve()
    return None


def project_voice_directory(root: Path) -> Path:
    return next(
        (
            folder
            for folder in (root / "audio", root / "voice", root / "voices")
            if folder.is_dir()
        ),
        root / "audio",
    )


def inspect_timeline_health(timeline: list[dict]) -> list[dict]:
    """Return actionable visual warnings for every selected timeline cut."""
    results = []
    previous_end = None
    recent_footage: list[tuple[str, float, float]] = []
    for entry in timeline:
        warnings = []
        severity = "ok"

        def add(level: str, message: str) -> None:
            nonlocal severity
            if message not in warnings:
                warnings.append(message)
            if HEALTH_LEVELS[level] > HEALTH_LEVELS[severity]:
                severity = level

        timeline_start = float(entry.get("timeline_start", 0.0))
        timeline_end = float(entry.get("timeline_end", timeline_start))
        visual_start = float(entry.get("visual_start", timeline_start))
        visual_end = float(entry.get("visual_end", timeline_end))
        source_start = float(entry.get("source_start", 0.0))
        source_end = float(entry.get("source_end", source_start))
        source_duration = float(entry.get("source_duration", source_end))
        visual_duration = visual_end - visual_start
        source_window = source_end - source_start

        if timeline_end <= timeline_start:
            add("critical", "Thời gian Timeline không hợp lệ")
        if source_window <= 0:
            add("critical", "Khoảng footage nguồn không hợp lệ")
        shortage = visual_duration - source_window
        if shortage > 0.05:
            level = "critical" if shortage > 0.50 else "warning"
            add(
                level,
                f"Footage thiếu {shortage:.2f}s; phải giữ/kéo khung cuối",
            )
        if source_start < -0.01 or source_end > source_duration + 0.05:
            add("critical", "Khoảng cắt vượt thời lượng footage nguồn")

        quality = entry.get("quality")
        if not isinstance(quality, dict) or "quality_score" not in quality:
            add("warning", "Thiếu dữ liệu kiểm tra chất lượng")
        else:
            quality_score = float(quality.get("quality_score", 0.0))
            if quality_score < 0.50:
                add("critical", f"Chất lượng rất thấp ({quality_score:.3f})")
            elif quality_score < 0.62:
                add("warning", f"Chất lượng thấp ({quality_score:.3f})")
            if float(quality.get("shake", 0.0)) > 0.028:
                add("warning", "Footage có nguy cơ rung")
            if float(quality.get("black_fraction", 0.0)) > 0.55:
                add("warning", "Footage có tỷ lệ vùng đen cao")

        relevance = float(entry.get("relevance_score", 0.0))
        if relevance < 0.26:
            add("critical", f"Điểm phù hợp rất thấp ({relevance:.3f})")
        elif relevance < 0.285:
            add("warning", f"Điểm phù hợp thấp ({relevance:.3f})")
        if entry.get("selection_reason") == "cross_beat_fallback":
            add("warning", "Đang dùng footage dự phòng từ Beat khác")
        for allocation_warning in entry.get("selection_warnings", []):
            message = str(allocation_warning).strip()
            if not message:
                continue
            level = (
                "critical"
                if (
                    "không có fallback" in message.lower()
                    or "mở rộng khi render" in message.lower()
                    or "trước cooldown" in message.lower()
                )
                else "warning"
            )
            add(level, message)

        if previous_end is not None:
            if timeline_start < previous_end - 0.02:
                add("critical", "Timeline bị chồng thời gian")
            elif timeline_start > previous_end + 0.05:
                add(
                    "warning",
                    f"Timeline bị hở {timeline_start - previous_end:.2f}s",
                )
        previous_end = max(previous_end or timeline_end, timeline_end)

        footage = str(entry.get("footage", ""))
        if footage and not Path(footage).is_file():
            add("critical", "Không tìm thấy file footage")
        for distance, (old_footage, old_start, old_end) in enumerate(
            reversed(recent_footage[-3:]), start=1
        ):
            if footage and footage == old_footage:
                overlap = max(
                    0.0,
                    min(source_end, old_end) - max(source_start, old_start),
                )
                if distance == 1 and overlap > 0.10:
                    add(
                        "warning",
                        "Hai Cut liên tiếp lặp khung hình từ cùng footage",
                    )
                elif distance == 1 and source_start < old_start - 0.05:
                    add(
                        "warning",
                        "Footage ở Cut kế tiếp bị nhảy ngược thời gian",
                    )
                elif distance > 1 and overlap > 0.10:
                    add(
                        "warning",
                        f"Lặp lại khoảng nguồn vừa dùng cách {distance} Cut",
                    )
                break
        recent_footage.append((footage, source_start, source_end))
        results.append({"severity": severity, "warnings": warnings})
    return results


def _warning_resolution(warning: str) -> str:
    normalized = warning.lower()
    if "nhảy ngược thời gian" in normalized:
        return (
            "Đổi sang footage khác cùng mã Beat; hoặc chọn khoảng bắt đầu "
            "sau điểm kết thúc của Cut trước."
        )
    if "lặp" in normalized or "lặp lại" in normalized:
        return (
            "Đổi sang footage khác cùng mã Beat, hoặc chọn một khoảng nguồn "
            "chưa từng sử dụng."
        )
    if "thiếu" in normalized and (
        "footage" in normalized or "nguồn" in normalized
    ):
        return (
            "Bổ sung footage đủ dài cho đúng mã Beat rồi phân tích lại "
            "toàn bộ Timeline."
        )
    if "giữ/kéo khung cuối" in normalized:
        return "Thay bằng footage dài hơn để không phải giữ khung hình cuối."
    if "vượt thời lượng" in normalized or "khoảng footage" in normalized:
        return "Chọn lại khoảng nguồn nằm hoàn toàn bên trong thời lượng file."
    if "không tìm thấy file footage" in normalized:
        return "Khôi phục file về đường dẫn cũ hoặc bổ sung footage thay thế."
    if "chất lượng" in normalized:
        return (
            "Thay footage rõ nét hơn; nếu dữ liệu chất lượng bị thiếu, "
            "hãy phân tích lại Timeline."
        )
    if "rung" in normalized:
        return "Thay cảnh ổn định hơn hoặc dùng footage từ nguồn khác."
    if "vùng đen" in normalized:
        return "Thay footage ít viền đen hơn hoặc crop lại nguồn trước khi phân tích."
    if "phù hợp" in normalized:
        return (
            "Bổ sung footage có nội dung sát mô tả Beat và đặt đúng mã Beat "
            "trong tên file."
        )
    if "dự phòng từ beat khác" in normalized:
        return "Bổ sung footage đúng mã Beat để hệ thống không phải mượn nguồn khác."
    if "timeline bị chồng" in normalized:
        return "Phân tích lại Timeline; không chỉnh hoặc cắt audio để bù thời gian."
    if "timeline bị hở" in normalized:
        return "Phân tích lại Timeline để hình ảnh phủ đủ thời lượng audio."
    if "timeline không hợp lệ" in normalized:
        return "Phân tích lại toàn bộ Timeline và kiểm tra thời lượng audio nguồn."
    if normalized.startswith("nguồn:"):
        return "Bổ sung thêm footage đúng mã Beat theo số lượng được đề xuất."
    return "Kiểm tra footage của Beat này và phân tích lại Timeline sau khi sửa."


def build_timeline_health_tooltip(
    warnings: list[str],
    beat_code: str = "",
    *,
    coverage: dict | None = None,
    beat_details: dict | None = None,
    target_seconds: float = 5.0,
    max_seconds: float = 7.0,
) -> str:
    """Explain every Beat warning together with its specific resolution."""
    if not warnings:
        return "Không phát hiện bất thường."

    lines = [f"BEAT {beat_code}" if beat_code else "CẢNH BÁO BEAT"]
    for index, warning in enumerate(warnings, start=1):
        lines.extend(
            [
                "",
                f"Lỗi {index}: {warning}",
                f"Cách xử lý: {_warning_resolution(warning)}",
            ]
        )
    coverage = coverage or {}
    if coverage:
        required = float(coverage.get("required_seconds", 0.0))
        available = float(coverage.get("available_unique_seconds", 0.0))
        missing = max(0.0, required - available)
        healthy_target = min(required * 1.15, required + 10.0)
        recommended_missing = max(0.0, healthy_target - available)
        longest_cut = float(
            coverage.get("longest_required_seconds", 0.0)
        )
        continuous_target = max(target_seconds, longest_cut)
        file_count = int(coverage.get("file_count", 0))
        recommended_files = int(
            coverage.get("recommended_additional_files", 0)
        )
        lines.extend(
            [
                "",
                "FOOTAGE CẦN BỔ SUNG:",
                f"• Tổng Beat cần: {required:.2f}s footage độc lập.",
                f"• Hiện có: {available:.2f}s trong {file_count} file.",
                f"• Thiếu tối thiểu: {missing:.2f}s.",
                (
                    f"• Khuyến nghị bổ sung: {recommended_missing:.2f}s "
                    "để có tối đa 15% vùng dự phòng."
                ),
                (
                    f"• Mỗi cảnh nên liên tục khoảng "
                    f"{continuous_target:.2f}–"
                    f"{max(max_seconds, continuous_target):.2f}s."
                ),
            ]
        )
        if recommended_files:
            lines.append(
                f"• Nên tìm thêm ít nhất {recommended_files} file khác nhau."
            )
    beat_details = beat_details or {}
    desired = str(beat_details.get("desired_visual", "")).strip()
    main_idea = str(beat_details.get("main_idea", "")).strip()
    keywords = str(beat_details.get("keywords", "")).strip()
    avoid = str(beat_details.get("avoid", "")).strip()
    if any((desired, main_idea, keywords, avoid)):
        lines.extend(["", "VIDEO PHÙ HỢP NÊN TÌM:"])
        if desired:
            lines.append(f"• Hình cần tìm: {desired}")
        if main_idea:
            lines.append(f"• Ý chính cần thể hiện: {main_idea}")
        if keywords:
            lines.append(f"• Từ khóa tìm kiếm: {keywords}")
        if avoid:
            lines.append(f"• Cần tránh: {avoid}")
    lines.extend(
        [
            "",
            "Lưu ý: cảnh báo này chỉ liên quan hình ảnh; audio không bị cắt "
            "hoặc tua ngược.",
        ]
    )
    return "\n".join(lines)


def footage_search_keywords(beat_details: dict | None) -> str:
    """Return a copy-ready footage search query for one Beat."""
    details = beat_details or {}
    keywords = str(details.get("keywords", "")).strip()
    if keywords:
        return keywords
    return str(details.get("desired_visual", "")).strip()


class MiddleElideDelegate(QStyledItemDelegate):
    """Keep long filenames on one line while preserving both ends."""

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        available = max(40, option.rect.width() - 12)
        option.text = option.fontMetrics.elidedText(
            option.text,
            Qt.TextElideMode.ElideMiddle,
            available,
        )


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


PIPELINE_STAGES = [
    ("INPUT", "Audio + transcript + danh sách Beat + kho Footage"),
    ("ALIGN", "Căn lời thoại với Audio"),
    ("CUT", "Chia lời theo thời lượng đã cấu hình"),
    ("SHOT", "Phát hiện Shot và tạo Candidate"),
    ("CLIP", "Lọc chất lượng và chấm nội dung bằng model"),
    ("PLAN", "Tối ưu toàn bộ Timeline hình ảnh"),
    ("LOOK", "Thêm Transition, Animation và Color grade"),
    ("AUDIO", "Ghép Audio lời thoại"),
    ("OUTPUT", "Xuất Video và Report"),
]

PIPELINE_STAGE_INDEXES = {
    code: index for index, (code, _description) in enumerate(PIPELINE_STAGES)
}


STATUS_STYLE = {
    "waiting": ("Đang chờ", "#1d2a3d", "#9aa7bd"),
    "running": ("Đang chạy", "#3b2a74", "#c4b5fd"),
    "done": ("Hoàn tất", "#14532d", "#86efac"),
    "skipped": ("Bỏ qua", "#26364e", "#aab5c5"),
    "error": ("Lỗi", "#5f1f1f", "#fca5a5"),
}


def completion_popup_content(mode: str, destination: str = "") -> tuple[str, str]:
    """Return the success popup copy for each user-facing workflow."""
    destination_line = f"\n\nĐã lưu tại:\n{destination}" if destination else ""
    if mode in {"analyze", "analyze_force", "analyze_section"}:
        scope = "Section đã chọn" if mode == "analyze_section" else "kịch bản"
        return (
            "Phân tích hoàn tất",
            f"Đã phân tích xong {scope} và cập nhật Timeline.",
        )
    if mode == "render":
        return (
            "Tạo video hoàn tất",
            f"Video đã được tạo và xuất thành công.{destination_line}",
        )
    if mode == "export_scenes":
        return (
            "Xuất video hoàn tất",
            f"Các video cảnh đã được xuất thành công.{destination_line}",
        )
    if mode == "export_capcut":
        return (
            "Xuất CapCut hoàn tất",
            f"Gói dựng CapCut đã được xuất thành công.{destination_line}",
        )
    return ("Hoàn tất", "Tác vụ đã hoàn tất thành công.")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("AronVideo", "FootageVideoBuilder")
        self.process = QProcess(self)
        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.started.connect(self._on_process_started)
        self.process.finished.connect(self._on_process_finished)
        self.process.errorOccurred.connect(self._on_process_error)
        self.footage_process = QProcess(self)
        self.footage_process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )
        self.footage_process.readyReadStandardOutput.connect(self._on_footage_process_output)
        self.footage_process.finished.connect(self._on_footage_process_finished)
        self._output_buffer = ""
        self._stage_statuses = ["waiting"] * len(PIPELINE_STAGES)
        self._statuses_before_run = self._stage_statuses.copy()
        self._stage_started_at: list[float | None] = [
            None
        ] * len(PIPELINE_STAGES)
        self._stage_elapsed_seconds = [0.0] * len(PIPELINE_STAGES)
        self._stage_estimates_seconds: list[float | None] = [
            None
        ] * len(PIPELINE_STAGES)
        self._stage_progress: list[int | None] = [
            None
        ] * len(PIPELINE_STAGES)
        self._stage_timer = QTimer(self)
        self._stage_timer.setInterval(1000)
        self._stage_timer.timeout.connect(self._refresh_stage_times)
        self._stage_timer.start()
        self._running = False
        self._run_mode = "analyze"
        self._beat_rows: dict[str, int] = {}
        self._beat_metadata: dict[str, dict[str, str]] = {}
        self._selected_footage: dict[str, list[str]] = {}
        self._reading_selected_timeline = False
        self._scenes_output_dir: Path | None = None
        self._capcut_output_dir: Path | None = None
        self._capcut_template_dir: Path | None = None
        self._capcut_drafts_root: Path | None = None
        self._capcut_draft_name: str | None = None
        self._saved_capcut_draft_name: str = ""
        self._capcut_section_indexes: set[int] | None = None
        self._capcut_replace_existing = False
        self._analyze_section_indexes: set[int] = set()
        self._render_section_indexes: set[int] | None = None
        self._output_stage_percent = 0
        self._footage_output_buffer = ""
        self._project_nav_expanded = True
        self.builder_settings = BuilderUiSettings()

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1440, 900)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(APP_STYLE_SHEET)
        self._build_ui()
        self._restore_settings()
        self._refresh_project_summary()
        self._load_project_stage_state()
        self._refresh_beat_table()
        self._refresh_start_enabled()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)
        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self._section_separator())
        root_layout.addWidget(self._build_workflow_bar())
        self.project_edit = QLineEdit()
        self.project_edit.setVisible(False)
        self.project_edit.textChanged.connect(self._on_project_changed)
        self.project_chip = QLabel()
        self.project_chip.setVisible(False)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        inputs_panel = self._build_inputs_panel()
        footage_panel = self._build_run_monitor()
        job_panel = self._build_pipeline_panel()
        inputs_panel.setMinimumWidth(260)
        footage_panel.setMinimumWidth(620)
        job_panel.setMinimumWidth(290)
        splitter.addWidget(inputs_panel)
        splitter.addWidget(footage_panel)
        splitter.addWidget(job_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 7)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([280, 850, 310])
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter, 1)

    def _build_workflow_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("WorkflowBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(8)
        title = QLabel("QUY TRÌNH")
        title.setStyleSheet(
            "color:#7f8ca3; font-size:11px; font-weight:800;"
        )
        layout.addWidget(title)
        self.workflow_steps = []
        for number, label in enumerate(
            ("Chuẩn bị", "Phân tích", "Duyệt cảnh", "Xuất bản"),
            start=1,
        ):
            step = QLabel(f"{number}  {label}")
            step.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step.setMinimumWidth(116)
            self.workflow_steps.append(step)
            layout.addWidget(step)
            if number < 4:
                arrow = QLabel("›")
                arrow.setStyleSheet(
                    "color:#52627a; font-size:18px; font-weight:800;"
                )
                layout.addWidget(arrow)
        layout.addStretch(1)
        self._update_workflow_steps()
        return frame

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Header")
        frame.setFixedHeight(66)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        icon = QLabel("V")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(46, 46)
        logo = QPixmap(str(ICON_PATH))
        if logo.isNull():
            icon.setStyleSheet(
                "background:#6d42e8; color:white; border-radius:8px;"
                "font-size:24px; font-weight:800;"
            )
        else:
            icon.setText("")
            icon.setPixmap(
                logo.scaled(
                    46,
                    46,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(APP_NAME)
        title.setStyleSheet(HEADER_TITLE_STYLE)
        version = QLabel(f"v{APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setFixedHeight(22)
        version.setStyleSheet(
            "background:#18243a; color:#c7d2fe; border:1px solid #33445e;"
            "border-radius:6px; padding:1px 7px; font-size:11px; font-weight:700;"
        )
        title_row.addWidget(title)
        title_row.addWidget(version)
        title_row.addStretch(1)
        subtitle = QLabel(
            "Dựng Timeline Footage theo lời thoại bằng Whisper, model thị giác "
            "và tối ưu toàn cục."
        )
        subtitle.setStyleSheet(HEADER_SUBTITLE_STYLE)
        title_box.addLayout(title_row)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)

        header_icon_style = (
            "QPushButton { background:#1b2940; border:1px solid #52627a;"
            "border-radius:6px; padding:5px; }"
            "QPushButton:hover { background:#2b3b57; border-color:#a78bfa; }"
            "QPushButton:pressed { background:#35266b; border-color:#c4b5fd; }"
        )
        settings_btn = QPushButton()
        settings_btn.setIcon(QIcon(str(SETTINGS_ICON)))
        settings_btn.setIconSize(QSize(22, 22))
        settings_btn.setFixedSize(38, 34)
        settings_btn.setToolTip("Cấu hình")
        settings_btn.setAccessibleName("Cấu hình")
        settings_btn.setStyleSheet(header_icon_style)
        settings_btn.clicked.connect(self._open_settings)
        guide_btn = QPushButton()
        guide_btn.setIcon(QIcon(str(HELP_ICON)))
        guide_btn.setIconSize(QSize(22, 22))
        guide_btn.setFixedSize(38, 34)
        guide_btn.setToolTip("Hướng dẫn")
        guide_btn.setAccessibleName("Hướng dẫn")
        guide_btn.setStyleSheet(header_icon_style)
        guide_btn.clicked.connect(self._show_guide)
        layout.addWidget(settings_btn)
        layout.addWidget(guide_btn)
        return frame

    def _build_inputs_panel(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setObjectName("SidePanel")
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(10, 8, 6, 8)
        outer.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel("Dữ liệu Project")
        title.setStyleSheet(SECTION_TITLE_STYLE)
        title_row.addWidget(title)
        title_row.addStretch(1)
        new_btn = QPushButton()
        new_btn.setIcon(QIcon(str(PROJECT_NEW_ICON)))
        new_btn.setIconSize(QSize(22, 22))
        new_btn.setToolTip("Tạo Project mới")
        new_btn.setAccessibleName("Tạo Project mới")
        new_btn.setFixedSize(38, 34)
        new_btn.clicked.connect(self._create_project)
        open_btn = QPushButton()
        open_btn.setIcon(QIcon(str(PROJECT_OPEN_ICON)))
        open_btn.setIconSize(QSize(22, 22))
        open_btn.setToolTip("Mở Project")
        open_btn.setAccessibleName("Mở Project")
        open_btn.setFixedSize(38, 34)
        open_btn.clicked.connect(self._choose_project)
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(QIcon(str(REFRESH_ICON)))
        self.refresh_btn.setIconSize(QSize(22, 22))
        self.refresh_btn.setToolTip("Làm mới dữ liệu Project")
        self.refresh_btn.setAccessibleName("Làm mới dữ liệu Project")
        self.refresh_btn.setFixedSize(38, 34)
        self.refresh_btn.clicked.connect(self._refresh_project_data)
        self.nav_toggle_btn = QPushButton()
        self.nav_toggle_btn.setIcon(QIcon(str(NAV_COLLAPSE_ICON)))
        self.nav_toggle_btn.setIconSize(QSize(22, 22))
        self.nav_toggle_btn.setToolTip("Thu gọn Navigation")
        self.nav_toggle_btn.setAccessibleName("Thu gọn Navigation")
        self.nav_toggle_btn.setFixedSize(38, 34)
        self.nav_toggle_btn.clicked.connect(self._toggle_project_nav)
        nav_button_style = (
            "QPushButton { background:#1b2940; border:1px solid #52627a;"
            "border-radius:6px; padding:5px; }"
            "QPushButton:hover { background:#2b3b57; border-color:#a78bfa; }"
            "QPushButton:pressed { background:#35266b; border-color:#c4b5fd; }"
        )
        for button in (
            new_btn,
            open_btn,
            self.refresh_btn,
            self.nav_toggle_btn,
        ):
            button.setStyleSheet(nav_button_style)
        title_row.addWidget(new_btn)
        title_row.addWidget(open_btn)
        title_row.addWidget(self.refresh_btn)
        title_row.addWidget(self.nav_toggle_btn)
        outer.addLayout(title_row)
        outer.addWidget(self._section_separator())
        self.source_readiness_label = QLabel(
            "Đang kiểm tra Script, Audio, Beat và Footage…"
        )
        self.source_readiness_label.setWordWrap(True)
        self.source_readiness_label.setStyleSheet(
            "background:#162235; color:#d6deee; border:1px solid #33445e;"
            "border-radius:8px; padding:8px; font-weight:700;"
        )
        outer.addWidget(self.source_readiness_label)

        self.project_tree = QTreeWidget()
        self.project_tree.setColumnCount(3)
        self.project_tree.setHeaderHidden(True)
        self.project_tree.setAnimated(True)
        self.project_tree.setIndentation(18)
        self.project_tree.setUniformRowHeights(True)
        self.project_tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.project_tree.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        nav_header = self.project_tree.header()
        nav_header.setStretchLastSection(False)
        nav_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        nav_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        nav_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.project_tree.setColumnWidth(1, 32)
        self.project_tree.setColumnWidth(2, 32)
        self.project_tree.itemDoubleClicked.connect(
            self._on_project_tree_activated
        )
        outer.addWidget(self.project_tree, 1)

        # Paths remain internal pipeline state. They are intentionally hidden
        # because the project navigation above is now the single input view.
        self.voice_edit = self._hidden_path_edit()
        self.script_edit = self._hidden_path_edit()
        self.beats_edit = self._hidden_path_edit()
        self.footage_edit = self._hidden_path_edit()
        self.output_edit = self._hidden_path_edit()

        return wrapper

    def _hidden_path_edit(self) -> QLineEdit:
        edit = QLineEdit()
        edit.setVisible(False)
        edit.textChanged.connect(self._refresh_start_enabled)
        return edit

    @staticmethod
    def _section_separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setFixedHeight(1)
        line.setStyleSheet("background:#33445e; border:0;")
        return line

    def _create_stage_table(self) -> QTableWidget:
        table = QTableWidget(len(PIPELINE_STAGES), 4)
        table.setHorizontalHeaderLabels(
            ["#", "STAGE", "TRẠNG THÁI", "THỜI GIAN / ETA"]
        )
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 30)
        table.setColumnWidth(2, 90)
        table.setColumnWidth(3, 145)
        self.stage_table = table
        for row, (code, _description) in enumerate(PIPELINE_STAGES):
            number_item = QTableWidgetItem(str(row + 1))
            number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stage_item = QTableWidgetItem(
                f"{code}  ·  {self._stage_description(row)}"
            )
            stage_item.setForeground(QColor("#c4b5fd"))
            table.setItem(row, 0, number_item)
            table.setItem(row, 1, stage_item)
            self._set_stage_status(row, "waiting")
        table.resizeRowsToContents()
        return table

    def _toggle_stage_section(self, expanded: bool) -> None:
        self.stage_table.setVisible(expanded)
        self.stage_separator.setVisible(expanded)
        self.stage_section_btn.setText(
            "⌄  Chi tiết kỹ thuật · 9 Stage"
            if expanded else "›  Chi tiết kỹ thuật · 9 Stage"
        )

    def _build_pipeline_panel(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setObjectName("JobPanel")
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)
        title = QLabel("Công việc đang chạy")
        title.setStyleSheet(SECTION_TITLE_STYLE)
        outer.addWidget(title)
        outer.addWidget(self._section_separator())

        self.job_scope_label = QLabel("Chưa có công việc")
        self.job_scope_label.setWordWrap(True)
        self.job_scope_label.setStyleSheet(
            "color:#f7f9ff; font-size:14px; font-weight:800;"
        )
        outer.addWidget(self.job_scope_label)
        self.pipeline_summary = QLabel("9 Stage sẵn sàng")
        self.pipeline_summary.setStyleSheet(MUTED_LABEL_STYLE)
        self.pipeline_summary.setWordWrap(True)
        outer.addWidget(self.pipeline_summary)
        self.pipeline_config_label = QLabel()
        self.pipeline_config_label.setStyleSheet(
            "background:#18243a; color:#c7d2fe; border:1px solid #33445e;"
            "border-radius:6px; padding:3px 8px; font-size:11px; font-weight:700;"
        )
        self.pipeline_config_label.setWordWrap(True)
        outer.addWidget(self.pipeline_config_label)

        controls = QVBoxLayout()
        self.progress_label = QLabel("Tiến độ: 0 / 9")
        self.progress_label.setStyleSheet(
            "color:#f7f9ff; font-weight:700;"
        )
        self.current_label = QLabel("Hiện tại: -")
        self.current_label.setStyleSheet("color:#d6deee;")
        self.current_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.progress_percent_label = QLabel("0%")
        self.progress_percent_label.setFixedWidth(46)
        self.progress_percent_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.progress_percent_label.setStyleSheet(
            "color:#f7f9ff; font-weight:700;"
        )
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress_label)
        progress_row.addStretch(1)
        progress_row.addWidget(self.progress_percent_label)
        controls.addLayout(progress_row)
        controls.addWidget(self.current_label)
        outer.addLayout(controls)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(12)
        outer.addWidget(self.progress_bar)

        summary = QFrame()
        summary.setStyleSheet(
            "background:#162235; border:1px solid #27364d; border-radius:8px;"
        )
        summary_layout = QVBoxLayout(summary)
        self.input_stats_label = QLabel("Voice: —  •  Beat: —  •  Footage: —")
        self.input_stats_label.setStyleSheet("color:#d6deee; font-weight:600;")
        self.input_stats_label.setWordWrap(True)
        self.output_hint_label = ClickableLabel("Đầu ra: —")
        self.output_hint_label.setStyleSheet(
            "color:#d6deee; font-size:13px; font-weight:700;"
            "background:#101a2b; border:1px solid #33445e;"
            "border-radius:6px; padding:7px 9px;"
        )
        self.output_hint_label.setMinimumHeight(34)
        self.output_hint_label.setWordWrap(True)
        self.output_hint_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.output_hint_label.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.output_hint_label.setToolTip(
            "Mở thư mục chứa Video đầu ra"
        )
        self.output_hint_label.clicked.connect(self._open_output_folder)
        summary_layout.addWidget(self.input_stats_label)
        summary_layout.addWidget(self.output_hint_label)
        outer.addWidget(summary)

        self.stage_section_btn = QPushButton("›  Chi tiết kỹ thuật · 9 Stage")
        self.stage_section_btn.setObjectName("NavSectionButton")
        self.stage_section_btn.setCheckable(True)
        self.stage_section_btn.setChecked(True)
        self.stage_section_btn.clicked.connect(self._toggle_stage_section)
        outer.addWidget(self.stage_section_btn)
        self.stage_separator = self._section_separator()
        self.stage_separator.setVisible(True)
        outer.addWidget(self.stage_separator)
        self.stage_table = self._create_stage_table()
        self.stage_table.setVisible(True)
        self.stage_table.setMaximumHeight(300)
        outer.addWidget(self.stage_table)
        self._toggle_stage_section(True)

        self.log_toggle_btn = QPushButton("›  Nhật ký kỹ thuật")
        self.log_toggle_btn.setCheckable(True)
        self.log_toggle_btn.setChecked(True)
        self.log_toggle_btn.clicked.connect(self._toggle_log_view)
        outer.addWidget(self.log_toggle_btn)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setVisible(True)
        outer.addWidget(self.log_view, 1)
        self._toggle_log_view(True)
        outer.addStretch(1)
        return wrapper

    def _toggle_log_view(self, expanded: bool) -> None:
        self.log_view.setVisible(expanded)
        self.log_toggle_btn.setText(
            "⌄  Nhật ký kỹ thuật" if expanded else "›  Nhật ký kỹ thuật"
        )

    def _build_run_monitor(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("RunMonitor")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 6, 14, 8)
        layout.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel("Timeline kịch bản hoàn chỉnh")
        title.setStyleSheet(SECTION_TITLE_STYLE)
        title_row.addWidget(title)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        action_row = QHBoxLayout()
        self.start_btn = QPushButton("◆  Phân tích kịch bản")
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.setMinimumWidth(220)
        self.start_btn.clicked.connect(self._prompt_analysis_mode)
        self.start_btn.setToolTip(
            "Chọn để tiếp tục phân tích (dùng cache) hoặc phân tích lại từ đầu."
        )
        action_row.addWidget(self.start_btn)
        self.supplement_btn = QPushButton("＋  Tìm footage bổ sung")
        self.supplement_btn.setMinimumWidth(155)
        self.supplement_btn.setEnabled(False)
        self.supplement_btn.clicked.connect(self._launch_footage_downloader)
        action_row.addWidget(self.supplement_btn)
        action_row.addStretch(1)

        self.export_btn = QPushButton("▶  Xuất bản")
        self.export_btn.setMinimumWidth(125)
        self.export_btn.clicked.connect(self._show_export_dialog)

        self.stop_btn = QPushButton("■  Dừng job")
        self.stop_btn.setObjectName("DangerButton")
        self.stop_btn.setMinimumWidth(100)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_build)
        action_row.addWidget(self.export_btn)
        action_row.addWidget(self.stop_btn)
        layout.addLayout(action_row)
        layout.addWidget(self._section_separator())
        self.overview_status_label = QLabel(
            "Kịch bản hoàn chỉnh: Chưa phân tích"
        )
        self.overview_status_label.setStyleSheet(
            "color: #8f9bad; padding: 0 0 4px 2px;"
        )
        layout.addWidget(self.overview_status_label)
        self.section_stats_label = QLabel(
            "Audio gốc được giữ nguyên toàn bộ trong Timeline"
        )
        self.section_stats_label.setStyleSheet(
            "color:#c4b5fd; font-weight:700; padding:0 0 4px 2px;"
        )
        layout.addWidget(self.section_stats_label)
        beat_label = QLabel("Cut và Scene đã chọn trên toàn bộ Timeline")
        beat_label.setStyleSheet(SECTION_TITLE_STYLE)
        layout.addWidget(beat_label)
        self.timeline_health_label = QLabel(
            "Kiểm tra Timeline: Chưa có kết quả phân tích"
        )
        self.timeline_health_label.setStyleSheet(
            "background:#18243a; color:#9aa7bd; border:1px solid #33445e;"
            "border-radius:7px; padding:6px 9px; font-weight:700;"
        )
        layout.addWidget(self.timeline_health_label)

        table_container = QWidget()
        table_layout = QHBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        # Bảng "đóng băng" cho các cột cố định
        self.frozen_beat_table = QTableWidget(0, 2)
        self.frozen_beat_table.setObjectName("FrozenBeatTable")
        self.frozen_beat_table.setHorizontalHeaderLabels(["Beat", "Kiểm tra"])
        self.frozen_beat_table.verticalHeader().setVisible(False)
        self.frozen_beat_table.verticalHeader().setDefaultSectionSize(36)
        self.frozen_beat_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )
        self.frozen_beat_table.setAlternatingRowColors(True)
        self.frozen_beat_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.frozen_beat_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.frozen_beat_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.frozen_beat_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.frozen_beat_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        frozen_header = self.frozen_beat_table.horizontalHeader()
        frozen_header.setStretchLastSection(False)
        for column, width in enumerate(FROZEN_BEAT_COLUMN_WIDTHS):
            frozen_header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.Fixed
            )
            self.frozen_beat_table.setColumnWidth(column, width)
        # Khóa cả widget theo đúng tổng chiều rộng hai cột. Nếu chỉ khóa
        # section, QHBoxLayout vẫn có thể kéo giãn bảng và tạo vùng cuộn ngang.
        frozen_width = (
            sum(FROZEN_BEAT_COLUMN_WIDTHS)
            + (2 * self.frozen_beat_table.frameWidth())
        )
        self.frozen_beat_table.setFixedWidth(frozen_width)
        self.frozen_beat_table.cellClicked.connect(self._show_beat_issue_details)

        # Bảng chính cho các cột có thể cuộn
        self.beat_table = QTableWidget(0, 12)
        self.beat_table.setHorizontalHeaderLabels(
            [
                "Nội dung", "Footage", "Audio/Video", "Độ dài Beat",
                "Footage gốc", "Scene", "Visual", "Ý chính", "Từ khóa",
                "Cần tránh", "Chất lượng", "Lựa chọn",
            ]
        )
        header_tooltips = {
            1: "File footage được chọn cho Beat.",
            2: "Timeline của audio gốc, cũng chính là timeline video đầu ra.",
            3: "Thời lượng Beat theo audio gốc.",
            4: "Khoảng thời gian lấy trong file footage gốc.",
            5: "Scene index phân tích trong footage gốc.",
        }
        for column, tooltip in header_tooltips.items():
            self.beat_table.horizontalHeaderItem(column).setToolTip(tooltip)
        self.beat_table.verticalHeader().setVisible(False)
        self.beat_table.verticalHeader().setDefaultSectionSize(36)
        self.beat_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )
        self.beat_table.setAlternatingRowColors(True)
        self.beat_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.beat_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.beat_table.setWordWrap(False)
        self.beat_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.beat_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.beat_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.beat_table.cellClicked.connect(
            self._show_beat_issue_details
        )
        # Áp dụng delegate để hiển thị tên file dài một cách hợp lý
        self.beat_table.setItemDelegateForColumn(0, MiddleElideDelegate(self.beat_table))
        self.beat_table.setItemDelegateForColumn(1, MiddleElideDelegate(self.beat_table))

        beat_header = self.beat_table.horizontalHeader()
        beat_header.setStretchLastSection(False)
        beat_header.setMinimumSectionSize(48)
        scrollable_widths = [280, 260, 125, 105, 125, 65, 72, 72, 78, 78, 88, 155]
        for i, width in enumerate(scrollable_widths):
            beat_header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.beat_table.setColumnWidth(i, width)

        # Chừa đúng phần chân mà thanh cuộn ngang chiếm ở bảng nội dung.
        # Nhờ vậy viewport và giới hạn cuộn dọc của hai bảng luôn bằng nhau.
        frozen_container = QWidget()
        frozen_container.setFixedWidth(frozen_width)
        frozen_layout = QVBoxLayout(frozen_container)
        frozen_layout.setContentsMargins(0, 0, 0, 0)
        frozen_layout.setSpacing(0)
        frozen_layout.addWidget(self.frozen_beat_table, 1)
        self.frozen_beat_scrollbar_spacer = QWidget()
        self.frozen_beat_scrollbar_spacer.setFixedHeight(0)
        frozen_layout.addWidget(self.frozen_beat_scrollbar_spacer)

        # Thêm bảng cố định và bảng nội dung vào cùng một hàng.
        table_layout.addWidget(frozen_container)
        table_layout.addWidget(self.beat_table, 1)
        layout.addWidget(table_container, 1)

        # Đồng bộ hóa thanh cuộn dọc
        self.beat_table.verticalScrollBar().valueChanged.connect(
            self.frozen_beat_table.verticalScrollBar().setValue
        )
        self.frozen_beat_table.verticalScrollBar().valueChanged.connect(
            self.beat_table.verticalScrollBar().setValue
        )
        self.beat_table.horizontalScrollBar().rangeChanged.connect(
            self._sync_frozen_beat_table_viewport
        )
        self._sync_frozen_beat_table_viewport()
        return frame

    def _sync_frozen_beat_table_viewport(self, *_args) -> None:
        """Keep frozen and scrolling rows aligned above the horizontal bar."""
        horizontal_bar = self.beat_table.horizontalScrollBar()
        bottom_margin = (
            horizontal_bar.sizeHint().height()
            if horizontal_bar.maximum() > horizontal_bar.minimum()
            else 0
        )
        self.frozen_beat_scrollbar_spacer.setFixedHeight(bottom_margin)

    def _launch_footage_downloader(self) -> None:
        if self._running:
            QMessageBox.warning(
                self, "Tác vụ đang chạy", "Một tác vụ khác đang chạy. Vui lòng đợi."
            )
            return

        project = self._project_path()
        beats_file = Path(self.beats_edit.text().strip())
        report_file = project / ".cache" / "vfootage_timeline.json"
        plan_file = project / ".cache" / "footage_download_plan.csv"
        try:
            plan_file, rows = write_supplement_plan(beats_file, report_file, plan_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Không thể tạo kế hoạch tải footage", str(exc))
            return
        if not rows:
            QMessageBox.information(self, "Footage đã đủ", "Không có Beat nào cần tải bổ sung.")
            return

        fetcher_root = ROOT_DIR.parent / "stock-footage-fetcher"
        if not (fetcher_root / "stock_footage_app.py").is_file() and not (
            fetcher_root / "pyproject.toml"
        ).is_file():
            QMessageBox.warning(
                self,
                "Không tìm thấy Stock Footage Finder",
                f"Thiếu downloader tại:\n{fetcher_root}",
            )
            return

        answer = QMessageBox.question(
            self,
            "Bắt đầu tải footage?",
            f"Đã tạo kế hoạch tải cho {len(rows)} Beat. Quá trình này sẽ dùng API Pexels và có thể mất vài phút.\n\nBắt đầu tải ngay?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._run_mode = "download_footage"
        self.job_scope_label.setText("Tải footage bổ sung")
        self._reset_stage_times()
        self.log_view.clear()
        self._append_log_line(f"[INFO] Bắt đầu tải footage cho {len(rows)} Beat...")

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        self.footage_process.setProcessEnvironment(environment)
        script_path = fetcher_root / "stock_footage_app.py"
        program = sys.executable
        arguments = ["-u", str(script_path), "--project", str(plan_file)]
        self.footage_process.setWorkingDirectory(str(fetcher_root))

        self._running = True
        self._set_running_ui_state(True)
        self.current_label.setText("Hiện tại: Khởi động Footage Finder")
        self.progress_bar.setValue(0)
        self.progress_percent_label.setText("0%")
        self.pipeline_summary.setText(f"Đang chuẩn bị tải 0/{len(rows)} Beat")
        self.footage_process.start(program, arguments)

    def _choose_project(self) -> None:
        initial = self.project_edit.text() or str(ROOT_DIR)
        path = QFileDialog.getExistingDirectory(
            self, "Mở Project", initial
        )
        if path:
            self.project_edit.setText(path)

    def _create_project(self) -> None:
        parent = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục cha", self.project_edit.text() or str(ROOT_DIR)
        )
        if not parent:
            return
        name, accepted = self._ask_project_name()
        if not accepted:
            return
        safe_name = re.sub(r'[<>:"/\\\\|?*]+', "-", name.strip())
        if not safe_name:
            return
        root = Path(parent) / safe_name
        root.mkdir(parents=True, exist_ok=True)
        for directory in ("audio", "video", ".cache"):
            (root / directory).mkdir(exist_ok=True)
        templates = {
            "script.txt": "SCRIPT:\n",
            "footage.csv": (
                "ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh\n"
            ),
        }
        for filename, content in templates.items():
            path = root / filename
            if not path.exists():
                path.write_text(content, encoding="utf-8-sig")
        self.project_edit.setText(str(root))
        self._append_log_line(f"[INFO] Đã tạo Project: {root}")

    def _ask_project_name(self):
        from PySide6.QtWidgets import QInputDialog

        return QInputDialog.getText(
            self, "Tạo Project", "Tên Project:", text="video-moi"
        )

    def _choose_voice_files(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn một file Audio cho toàn bộ kịch bản",
            self._dialog_start(self.voice_edit),
            "Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;Tất cả file (*)",
        )
        if path:
            self.voice_edit.setText(path)

    def _choose_file(
        self, edit: QLineEdit, title: str, file_filter: str
    ) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, title, self._dialog_start(edit), file_filter
        )
        if path:
            edit.setText(path)

    def _choose_directory(self, edit: QLineEdit, title: str) -> None:
        path = QFileDialog.getExistingDirectory(
            self, title, self._dialog_start(edit)
        )
        if path:
            edit.setText(path)

    def _choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Chọn Video đầu ra",
            self.output_edit.text() or str(self._project_path() / "video_output.mp4"),
            "MP4 video (*.mp4)",
        )
        if path:
            if not path.lower().endswith(".mp4"):
                path += ".mp4"
            self.output_edit.setText(path)

    def _choose_render_output(self) -> None:
        self._render_section_indexes = None
        current = self.output_edit.text().strip()
        default_path = (
            Path(current)
            if current
            else self._project_path() / "video_output.mp4"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Chọn nơi lưu và đặt tên Video",
            str(default_path),
            "MP4 Video (*.mp4)",
        )
        if not path:
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        self.output_edit.setText(path)
        self._refresh_project_summary()
        self._start_build("render")

    def _show_export_dialog(self) -> None:
        if self._running:
            QMessageBox.warning(
                self, "Tác vụ đang chạy", "Một tác vụ khác đang chạy. Vui lòng đợi."
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Tùy chọn xuất bản")
        dialog.setModal(True)
        dialog.setMinimumWidth(450)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Chọn định dạng bạn muốn xuất bản")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #d6deee;")
        layout.addWidget(title)

        inputs_ready = self._are_inputs_ready()

        # Option 1: Render Video
        render_btn = QPushButton("🎬  Xuất Video MP4")
        render_btn.setObjectName("PrimaryButton")
        render_btn.setMinimumHeight(40)
        render_btn.setEnabled(inputs_ready)
        if not inputs_ready:
            render_btn.setToolTip("Cần có đủ Script, Audio, Beat và Footage để render video.")
        render_btn.clicked.connect(self._choose_render_output)
        render_btn.clicked.connect(dialog.accept)
        layout.addWidget(render_btn)

        # Option 2: CapCut
        capcut_btn = QPushButton("✂️  Xuất Draft CapCut")
        capcut_btn.setMinimumHeight(40)
        capcut_btn.clicked.connect(self._choose_capcut_export)
        capcut_btn.clicked.connect(dialog.accept)
        layout.addWidget(capcut_btn)

        # Option 3: Scenes
        scenes_btn = QPushButton("🎞️  Xuất các cảnh riêng lẻ")
        scenes_btn.setMinimumHeight(40)
        scenes_btn.clicked.connect(self._choose_scene_export)
        scenes_btn.clicked.connect(dialog.accept)
        layout.addWidget(scenes_btn)

        layout.addStretch(1)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        button_box.rejected.connect(dialog.reject)
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        layout.addWidget(button_box)
        dialog.exec()

    def _open_output_folder(self) -> None:
        output_value = self.output_edit.text().strip()
        folder = (
            Path(output_value).expanduser().parent
            if output_value
            else self._project_path()
        )
        if not folder.is_dir():
            QMessageBox.warning(
                self,
                "Không tìm thấy thư mục",
                f"Thư mục đầu ra không tồn tại:\n{folder}",
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(
                self,
                "Không thể mở thư mục",
                f"Không thể mở:\n{folder}",
            )

    def _choose_scene_export(self) -> None:
        default_dir = self._project_path() / "selected_scenes"
        start = default_dir if default_dir.exists() else self._project_path()
        path = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục xuất Scene",
            str(start),
        )
        if not path:
            return
        self._scenes_output_dir = Path(path)
        self._start_build("export_scenes")

    def _choose_capcut_export(self) -> None:
        self._capcut_section_indexes = None
        self._capcut_output_dir = (
            self._project_path() / "capcut_package"
        )
        self._capcut_replace_existing = False
        existing_draft = None
        manifest_path = (
            self._capcut_output_dir / "capcut_manifest.json"
        )
        if manifest_path.is_file():
            try:
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8-sig")
                )
                draft_info = manifest.get("capcut_draft", {})
                draft_path = Path(str(draft_info.get("path", "")))
                if (
                    draft_path.is_dir()
                    and (
                        draft_path
                        / "Resources"
                        / "CapCutAdapter"
                    ).is_dir()
                ):
                    existing_draft = draft_info
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
            ):
                existing_draft = None
        saved_template = self.builder_settings.capcut_template_dir
        template_path = (
            Path(saved_template)
            if saved_template
            else Path()
        )
        saved_draft_name = self._saved_capcut_draft_name.strip()
        if existing_draft is not None:
            stored_template = Path(
                str(existing_draft.get("template", ""))
            )
            if stored_template.is_dir():
                template_path = stored_template
        if not template_path.is_dir():
            QMessageBox.warning(
                self,
                "Chưa chọn Template CapCut",
                "Vào Cài đặt > CapCut để Import template và chọn template mặc định.",
            )
            return
        if existing_draft is not None:
            draft_name = str(existing_draft["name"])
            self._capcut_replace_existing = True
        elif saved_draft_name:
            draft_name = saved_draft_name
            self._capcut_replace_existing = True
        else:
            from PySide6.QtWidgets import QInputDialog

            default_name = self._project_path().name
            draft_name, accepted = QInputDialog.getText(
                self,
                "Tạo Draft CapCut",
                "Tên Draft mới:",
                text=default_name,
            )
            if not accepted or not draft_name.strip():
                return
        self._capcut_template_dir = template_path
        drafts_root = self.builder_settings.capcut_drafts_root.strip()
        self._capcut_drafts_root = (
            Path(drafts_root) if drafts_root else None
        )
        self._capcut_draft_name = draft_name.strip()
        if self._capcut_replace_existing:
            replace_root = self._capcut_drafts_root or template_path.parent
            draft_path = replace_root / self._capcut_draft_name
            owned_marker = draft_path / "Resources" / "CapCutAdapter"
            if draft_path.exists() and not owned_marker.is_dir():
                QMessageBox.warning(
                    self,
                    "KhÃ´ng thá»ƒ Replace Draft",
                    "Draft cÃ¹ng tÃªn Ä‘Ã£ tá»“n táº¡i nhÆ°ng khÃ´ng pháº£i draft do app táº¡o:\n"
                    f"{draft_path}",
                )
                return
        self._saved_capcut_draft_name = self._capcut_draft_name
        self.settings.setValue(
            "capcut/template_dir", str(template_path)
        )
        if self._capcut_drafts_root is not None:
            self.settings.setValue(
                "capcut/drafts_root", str(self._capcut_drafts_root)
            )
        self._save_project_settings()
        self._start_build("export_capcut")

    def _dialog_start(self, edit: QLineEdit) -> str:
        value = edit.text().split(";")[0].strip()
        return value or self.project_edit.text() or str(ROOT_DIR)

    def _on_project_changed(self) -> None:
        root = self._project_path()
        if self.project_edit.text().strip():
            self.script_edit.setText(str(root / "script.txt"))
            self.beats_edit.setText(str(root / "footage.csv"))
            self.footage_edit.setText(str(root / "video"))
            self.output_edit.setText(str(root / "video_output.mp4"))
            self.voice_edit.clear()
            preferred_voice = preferred_project_voice(root)
            if preferred_voice is not None:
                self.voice_edit.setText(str(preferred_voice))
        self._load_project_settings()
        self._refresh_project_summary()
        self._load_project_stage_state()
        self._refresh_beat_table()
        self._refresh_project_nav()
        self._refresh_start_enabled()

    def _refresh_project_data(self) -> None:
        if self._running:
            return
        self._refresh_project_summary()
        self._load_project_stage_state()
        self._refresh_beat_table()
        self._refresh_project_nav()
        self._refresh_start_enabled()
        self._append_log_line("[INFO] Đã làm mới dữ liệu Project.")

    def _project_path(self) -> Path:
        value = self.project_edit.text().strip()
        return Path(value).expanduser() if value else ROOT_DIR / "vfootage"

    def _refresh_project_nav(self) -> None:
        if not hasattr(self, "project_tree"):
            return
        self.project_tree.clear()
        root = self._project_path()
        if not root.is_dir():
            return
        icon_provider = QFileIconProvider()
        root_item = QTreeWidgetItem([root.name, ""])
        root_item.setIcon(0, icon_provider.icon(QFileInfo(str(root))))
        root_item.setData(0, Qt.ItemDataRole.UserRole, str(root))
        root_item.setToolTip(0, str(root))
        self.project_tree.addTopLevelItem(root_item)

        selected_voice_count = len(self._voice_paths())
        voice_count = (
            selected_voice_count
            if selected_voice_count
            else self._count_voice_files(root)
        )
        footage_count = self._count_footage_files(root / "video")
        script_ready = self._count_script_sections(
            root / "script.txt"
        )
        beat_count = self._count_csv_rows(root / "footage.csv")
        principal_rows = (
            (
                f"Kịch bản ({'sẵn sàng' if script_ready else 'thiếu'})",
                root / "script.txt",
            ),
            (
                f"Beat metadata ({beat_count} Beat)",
                root / "footage.csv",
            ),
            (f"Audio ({voice_count}/1)", project_voice_directory(root)),
            (f"Kho footage ({footage_count})", root / "video"),
        )
        for label, path in principal_rows:
            item = QTreeWidgetItem([label, "", ""])
            item.setIcon(0, icon_provider.icon(QFileInfo(str(path))))
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(0, str(path))
            root_item.addChild(item)
            browse = self._nav_row_button(
                PROJECT_OPEN_ICON,
                "Duyệt",
                lambda _checked=False, value=path: self._browse_nav_path(value),
            )
            self.project_tree.setItemWidget(item, 2, browse)
        root_item.setExpanded(True)
        self.project_tree.setVisible(self._project_nav_expanded)
        icon = (
            NAV_COLLAPSE_ICON
            if self._project_nav_expanded
            else NAV_EXPAND_ICON
        )
        action = (
            "Thu gọn Navigation"
            if self._project_nav_expanded
            else "Mở rộng Navigation"
        )
        self.nav_toggle_btn.setIcon(QIcon(str(icon)))
        self.nav_toggle_btn.setToolTip(action)
        self.nav_toggle_btn.setAccessibleName(action)

    def _toggle_project_nav(self) -> None:
        self._project_nav_expanded = not self._project_nav_expanded
        self.project_tree.setVisible(self._project_nav_expanded)
        icon = (
            NAV_COLLAPSE_ICON
            if self._project_nav_expanded
            else NAV_EXPAND_ICON
        )
        action = (
            "Thu gọn Navigation"
            if self._project_nav_expanded
            else "Mở rộng Navigation"
        )
        self.nav_toggle_btn.setIcon(QIcon(str(icon)))
        self.nav_toggle_btn.setToolTip(action)
        self.nav_toggle_btn.setAccessibleName(action)

    def _nav_row_button(
        self, icon_path: Path, tooltip: str, callback
    ) -> QPushButton:
        button = QPushButton()
        button.setIcon(QIcon(str(icon_path)))
        button.setIconSize(QSize(17, 17))
        button.setFixedSize(27, 25)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setStyleSheet(
            "QPushButton { background:transparent; border:0;"
            "border-radius:4px; padding:3px; }"
            "QPushButton:hover { background:#2b3b57;"
            "border:1px solid #7c5ce5; }"
            "QPushButton:pressed { background:#35266b; }"
        )
        button.clicked.connect(callback)
        return button

    def _browse_nav_path(self, path: Path) -> None:
        name = path.name.lower()
        if name == "script.txt":
            self._choose_file(
                self.script_edit,
                "Chọn kịch bản",
                "Text (*.txt);;Tất cả file (*)",
            )
        elif name == "footage.csv":
            self._choose_file(
                self.beats_edit,
                "Chọn file Beat CSV",
                "CSV (*.csv);;Tất cả file (*)",
            )
            self._refresh_beat_table()
        elif name == "voices":
            self._choose_voice_files()
        elif name == "video":
            self._choose_directory(
                self.footage_edit, "Chọn thư mục Footage"
            )
            self._refresh_beat_table()

    def _on_project_tree_activated(
        self, item: QTreeWidgetItem, column: int
    ) -> None:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if not value:
            return
        path = Path(value)
        if column == 1:
            name = path.name.lower()
            if name == "voices":
                self._choose_voice_files()
            elif name == "video":
                self._choose_directory(
                    self.footage_edit, "Chọn thư mục Footage"
                )
                self._refresh_beat_table()
            elif name == "script.txt":
                self._choose_file(
                    self.script_edit,
                    "Chọn transcript",
                    "Text (*.txt);;Tất cả file (*)",
                )
            elif name == "footage.csv":
                self._choose_file(
                    self.beats_edit,
                    "Chọn file Beat CSV",
                    "CSV (*.csv);;Tất cả file (*)",
                )
                self._refresh_beat_table()
            return
        if path.is_dir():
            item.setExpanded(not item.isExpanded())
            return
        name = path.name.lower()
        if name == "script.txt":
            self.script_edit.setText(str(path))
        elif name == "footage.csv":
            self.beats_edit.setText(str(path))
            self._refresh_beat_table()
        elif (
            path.suffix.lower() in VIDEO_EXTENSIONS
            and path.parent.name.lower() == "video"
        ):
            self.footage_edit.setText(str(path.parent))
            self._refresh_beat_table()

    def _project_state_path(self) -> Path:
        return self._project_path() / ".cache" / PROJECT_STATE_FILENAME

    def _project_config_path(self) -> Path:
        return self._project_path() / ".cache" / PROJECT_CONFIG_FILENAME

    def _save_project_settings(self) -> None:
        project = self._project_path()
        if not project.is_dir():
            return
        values = self.builder_settings
        payload = {
            "schema_version": 4,
            "vision_model": values.vision_model,
            "resolution": values.resolution,
            "analysis_workers": values.analysis_workers,
            "min_cut_seconds": values.min_cut_seconds,
            "target_cut_seconds": values.target_cut_seconds,
            "max_cut_seconds": values.max_cut_seconds,
            "minimum_video_minutes": values.minimum_video_minutes,
            "skip_whisper": values.skip_whisper,
            "auto_model_download": values.auto_model_download,
            "capcut_template_dir": values.capcut_template_dir,
            "capcut_drafts_root": values.capcut_drafts_root,
            "capcut_draft_name": self._saved_capcut_draft_name,
            "capcut_hook_music": values.capcut_hook_music,
            "capcut_hook_volume_db": values.capcut_hook_volume_db,
            "capcut_body_music": list(values.capcut_body_music),
            "music_dir": values.music_dir,
            "music_cue_sheet": values.music_cue_sheet,
            "capcut_use_main_music": values.capcut_use_main_music,
        }
        path = self._project_config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError as exc:
            self._append_log_line(
                f"[WARN] Không thể lưu cấu hình Project: {exc}"
            )

    def _load_project_settings(self) -> None:
        path = self._project_config_path()
        if not path.is_file():
            self._saved_capcut_draft_name = ""
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            current = self.builder_settings
            profile_version = int(payload.get("schema_version", 1))
            if profile_version < 4:
                payload = {
                    **payload,
                    "min_cut_seconds": 3.0,
                    "target_cut_seconds": 4.0,
                    "max_cut_seconds": 5.0,
                }
            model = str(
                payload.get("vision_model", current.vision_model)
            )
            if model not in VISION_MODELS.values():
                model = current.vision_model
            loaded = BuilderUiSettings(
                resolution=str(
                    payload.get("resolution", current.resolution)
                ),
                analysis_workers=int(
                    payload.get(
                        "analysis_workers", current.analysis_workers
                    )
                ),
                min_cut_seconds=float(
                    payload.get(
                        "min_cut_seconds", current.min_cut_seconds
                    )
                ),
                target_cut_seconds=float(
                    payload.get(
                        "target_cut_seconds", current.target_cut_seconds
                    )
                ),
                max_cut_seconds=float(
                    payload.get(
                        "max_cut_seconds", current.max_cut_seconds
                    )
                ),
                minimum_video_minutes=float(
                    payload.get(
                        "minimum_video_minutes",
                        current.minimum_video_minutes,
                    )
                ),
                skip_whisper=bool(
                    payload.get("skip_whisper", current.skip_whisper)
                ),
                auto_model_download=bool(
                    payload.get(
                        "auto_model_download",
                        current.auto_model_download,
                    )
                ),
                vision_model=model,
                capcut_template_dir=str(
                    payload.get(
                        "capcut_template_dir",
                        current.capcut_template_dir,
                    )
                ),
                capcut_drafts_root=str(
                    payload.get(
                        "capcut_drafts_root",
                        current.capcut_drafts_root,
                    )
                ),
                capcut_hook_music=str(
                    payload.get(
                        "capcut_hook_music",
                        current.capcut_hook_music,
                    )
                ),
                capcut_hook_volume_db=float(
                    payload.get(
                        "capcut_hook_volume_db",
                        current.capcut_hook_volume_db,
                    )
                ),
                capcut_body_music=tuple(
                    item
                    for item in payload.get(
                        "capcut_body_music",
                        current.capcut_body_music,
                    )
                    if isinstance(item, dict)
                ),
                music_dir=str(
                    payload.get(
                        "music_dir",
                        current.music_dir,
                    )
                ),
                music_cue_sheet=str(
                    payload.get(
                        "music_cue_sheet",
                        current.music_cue_sheet,
                    )
                ),
                capcut_use_main_music=bool(
                    payload.get("capcut_use_main_music", current.capcut_use_main_music)
                ),
            )
            if (
                loaded.min_cut_seconds
                <= loaded.target_cut_seconds
                <= loaded.max_cut_seconds
            ):
                self.builder_settings = loaded
                self._saved_capcut_draft_name = str(
                    payload.get("capcut_draft_name", "")
                ).strip()
        except (
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            self._append_log_line(
                f"[WARN] Không thể nạp cấu hình Project: {exc}"
            )

    def _load_project_stage_state(self) -> None:
        statuses = ["waiting"] * len(PIPELINE_STAGES)
        estimates: list[float | None] = [None] * len(PIPELINE_STAGES)
        state_path = self._project_state_path()
        if state_path.is_file():
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                saved = payload.get("stage_statuses", [])
                if (
                    isinstance(saved, list)
                    and len(saved) == len(PIPELINE_STAGES)
                    and all(item in STATUS_STYLE for item in saved)
                ):
                    statuses = saved
                saved_estimates = payload.get(
                    "stage_estimates_seconds",
                    payload.get("stage_durations_seconds", []),
                )
                if (
                    isinstance(saved_estimates, list)
                    and len(saved_estimates) == len(PIPELINE_STAGES)
                ):
                    estimates = [
                        float(value) if value is not None else None
                        for value in saved_estimates
                    ]
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
        elif (
            self._project_path() / ".cache" / "vfootage_timeline.json"
        ).is_file():
            # Backward compatibility for projects analyzed before this state
            # file was introduced.
            statuses = [
                "done", "done", "done", "done", "done", "done",
                "waiting", "waiting", "done",
            ]
        self._stage_estimates_seconds = estimates
        for row, status in enumerate(statuses):
            self._set_stage_status(row, status)
        self._statuses_before_run = statuses.copy()
        self._update_progress()

    def _save_project_stage_state(self, mode: str, success: bool) -> None:
        project = self._project_path()
        if not project.is_dir():
            return
        state_path = self._project_state_path()
        payload = {
            "schema_version": 2,
            "project": str(project.resolve()),
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "last_mode": mode,
            "last_run_success": success,
            "stage_statuses": self._stage_statuses,
            "stage_durations_seconds": [
                round(self._stage_elapsed(row), 3)
                for row in range(len(PIPELINE_STAGES))
            ],
            "stage_estimates_seconds": [
                round(value, 3) if value is not None else None
                for value in self._stage_estimates_seconds
            ],
        }
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(state_path)
        except OSError as exc:
            self._append_log_line(
                f"[WARN] Không thể lưu trạng thái Project: {exc}"
            )

    def _refresh_project_summary(self) -> None:
        root = self._project_path()
        valid = root.is_dir()
        if valid:
            self.project_chip.setText("Đã nạp Project")
            self._set_chip(
                self.project_chip, "#14532d", "#86efac", "#22c55e"
            )
        else:
            self.project_chip.setText("Chưa chọn Project")
            self._set_chip(
                self.project_chip, "#26364e", "#aab5c5", "#34445e"
            )
        selected_voice_count = len(self._voice_paths())
        voice_count = (
            selected_voice_count
            if selected_voice_count
            else self._count_voice_files(root)
        )
        script_ready = self._count_script_sections(
            Path(self.script_edit.text())
        )
        beat_count = self._count_csv_rows(Path(self.beats_edit.text()))
        footage_count = self._count_footage_files(Path(self.footage_edit.text()))
        self.input_stats_label.setText(
            f"Kịch bản: {'Sẵn sàng' if script_ready else 'Thiếu'}  •  "
            f"Audio: {voice_count}/1  •  "
            f"Beat: {beat_count}  •  Footage: {footage_count}"
        )
        if hasattr(self, "source_readiness_label"):
            checks = (
                ("Kịch bản", bool(script_ready)),
                ("Audio duy nhất", voice_count == 1),
                ("Beat metadata", beat_count > 0),
                ("Kho footage", footage_count > 0),
            )
            self.source_readiness_label.setText(
                "\n".join(
                    f"{'✓' if ready else '!' }  {label}"
                    for label, ready in checks
                )
            )
            all_ready = all(ready for _label, ready in checks)
            self.source_readiness_label.setStyleSheet(
                (
                    "background:#123524; color:#86efac; border:1px solid #22c55e;"
                    if all_ready
                    else "background:#3a2d12; color:#fde68a; border:1px solid #d6a52a;"
                )
                + "border-radius:8px; padding:8px; font-weight:700;"
            )
        if hasattr(self, "overview_status_label"):
            report_ready = (
                root / ".cache" / "vfootage_timeline.json"
            ).is_file()
            self.overview_status_label.setText(
                "Kịch bản hoàn chỉnh: Timeline đã sẵn sàng"
                if report_ready
                else "Kịch bản hoàn chỉnh: Cần phân tích"
            )
        output = self.output_edit.text().strip()
        self.output_hint_label.setText(
            f"Đầu ra: {Path(output).name}" if output else "Đầu ra: —"
        )
        self.output_hint_label.setToolTip(
            (
                f"Mở thư mục chứa Video:\n{Path(output).parent}"
                if output
                else "Mở thư mục Project"
            )
        )

    def _count_voice_files(self, root: Path) -> int:
        voices_dir = project_voice_directory(root)
        folder_voices = (
            [
                path
                for path in voices_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {
                    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"
                }
            ]
            if voices_dir.is_dir()
            else []
        )
        return len(folder_voices or numbered_voice_files(root))

    def _count_csv_rows(self, path: Path) -> int:
        if not path.is_file():
            return 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return sum(1 for _ in csv.DictReader(handle))
        except (OSError, UnicodeError, csv.Error):
            return 0

    def _count_script_sections(self, path: Path) -> int:
        if not path.is_file():
            return 0
        try:
            narration, _sections = parse_script_sections(
                path.read_text(encoding="utf-8-sig")
            )
            return int(bool(narration.strip()))
        except (OSError, UnicodeError, ValueError):
            return 0

    def _count_footage_files(self, path: Path) -> int:
        if not path.is_dir():
            return 0
        return sum(
            1
            for item in path.rglob("*")
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
        )

    def _refresh_beat_table(self) -> None:
        if not hasattr(self, "beat_table"):
            return
        self.frozen_beat_table.setRowCount(0)
        self.beat_table.setRowCount(0)
        self.timeline_health_label.setText(
            "Kiểm tra Timeline: Chưa có kết quả phân tích"
        )
        self.timeline_health_label.setStyleSheet(
            "background:#18243a; color:#9aa7bd; border:1px solid #33445e;"
            "border-radius:7px; padding:6px 9px; font-weight:700;"
        )
        self._beat_rows.clear()
        self._beat_metadata.clear()
        self._selected_footage.clear()
        beats_path = Path(self.beats_edit.text().strip())
        if not beats_path.is_file():
            return
        footage_counts: dict[str, int] = {}
        footage_dir = Path(self.footage_edit.text().strip())
        if footage_dir.is_dir():
            for path in footage_dir.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                code = filename_beat_code(path)
                if code:
                    footage_counts[code] = footage_counts.get(code, 0) + 1
        try:
            with beats_path.open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeError, csv.Error):
            return
        for source in rows:
            code = (source.get("ma_beat") or "").strip().upper()
            if not code:
                continue
            row = self.frozen_beat_table.rowCount()
            self.frozen_beat_table.insertRow(row)
            self.beat_table.insertRow(row)
            self._beat_rows[code] = row
            self._beat_metadata[code] = {
                "main_idea": (source.get("y_chinh") or "").strip(),
                "keywords": (source.get("tu_khoa") or "").strip(),
                "desired_visual": (source.get("hinh_can_tim") or "").strip(),
                "avoid": (source.get("tranh") or "").strip(),
            }

            # Cột cố định
            item_code = QTableWidgetItem(code)
            item_code.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
            self.frozen_beat_table.setItem(row, 0, item_code)
            item_status = QTableWidgetItem("Đang chờ")
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
            self.frozen_beat_table.setItem(row, 1, item_status)

            # Cột cuộn
            main_idea = (source.get("y_chinh") or "").strip()
            item_noidung = QTableWidgetItem(main_idea)
            item_noidung.setToolTip(main_idea)
            item_noidung.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.beat_table.setItem(row, 0, item_noidung)
            footage_count_str = f"{footage_counts.get(code, 0)} file"
            item_footage = QTableWidgetItem(footage_count_str)
            item_footage.setToolTip(footage_count_str)
            item_footage.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.beat_table.setItem(row, 1, item_footage)
            for i in range(2, 12):
                item = QTableWidgetItem("—")
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
                self.beat_table.setItem(row, i, item)

        self._restore_beat_results()
        for row in range(self.beat_table.rowCount()):
            self.beat_table.setRowHeight(row, 36)

    def _refresh_section_table(self) -> None:
        if not hasattr(self, "section_table"):
            return
        previously_checked = self._selected_section_indexes()
        self.section_table.setRowCount(0)
        self.section_stats_label.setText("Đã phân tích: 0/0 đoạn")
        script_path = Path(self.script_edit.text().strip())
        project = self._project_path()
        if not script_path.is_file() or not project.is_dir():
            self.overview_status_label.setText(
                "Overview toàn kịch bản: Chưa phân tích"
            )
            return
        overview_path = project / ".cache" / "script_overview.json"
        if overview_path.is_file():
            try:
                overview = json.loads(
                    overview_path.read_text(encoding="utf-8-sig")
                )
                self.overview_status_label.setText(
                    "Overview toàn kịch bản: Đã sẵn sàng · "
                    f"{int(overview.get('section_count', 0))} Section · "
                    f"{int(overview.get('beat_count', 0))} Beat"
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                self.overview_status_label.setText(
                    "Overview toàn kịch bản: Cache không hợp lệ"
                )
        else:
            self.overview_status_label.setText(
                "Overview toàn kịch bản: Cần phân tích"
            )
        try:
            _narration, sections = parse_script_sections(
                script_path.read_text(encoding="utf-8-sig")
            )
            voices = numbered_voice_files(project / "voices")
            if not voices:
                voices = numbered_voice_files(project)
            srt_files = discover_srt_files(voices) if voices else []
        except (OSError, UnicodeError, ValueError):
            return
        report_sections = {}
        report_path = project / ".cache" / "vfootage_timeline.json"
        if report_path.is_file():
            try:
                report = json.loads(
                    report_path.read_text(encoding="utf-8-sig")
                )
                report_sections = {
                    int(item["index"]): item
                    for item in report.get("sections", [])
                }
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                report_sections = {}
        preview_dir = project / ".cache" / "section_previews"
        if preview_dir.is_dir():
            for preview_path in preview_dir.glob("*.json"):
                try:
                    preview = json.loads(
                        preview_path.read_text(encoding="utf-8-sig")
                    )
                    if preview.get("analysis_scope") != "section_preview":
                        continue
                    for item in preview.get("sections", []):
                        report_sections[int(item["index"])] = {
                            **item,
                            "preview": True,
                        }
                except (
                    OSError,
                    UnicodeError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    continue
        explicit_counts: dict[str, int] = {}
        beats_path = Path(self.beats_edit.text().strip())
        if beats_path.is_file():
            try:
                with beats_path.open(
                    "r", encoding="utf-8-sig", newline=""
                ) as handle:
                    for beat in csv.DictReader(handle):
                        key = (beat.get("section") or "").strip().lower()
                        if key:
                            explicit_counts[key] = (
                                explicit_counts.get(key, 0) + 1
                            )
            except (OSError, UnicodeError, csv.Error):
                pass
        coverage_by_section: dict[int, tuple[int, int]] = {}
        try:
            beats = load_beats(beats_path)
            mapped_beats = map_beats_for_preview(sections, beats)
            available_codes = set()
            footage_dir = Path(self.footage_edit.text().strip())
            if footage_dir.is_dir():
                for footage in footage_dir.rglob("*"):
                    if (
                        not footage.is_file()
                        or footage.suffix.lower() not in VIDEO_EXTENSIONS
                    ):
                        continue
                    code = filename_beat_code(footage)
                    if code:
                        available_codes.add(code)
            coverage_by_section = {
                section.index: (
                    len(section_beats),
                    sum(
                        normalize_beat_code(beat.code) in available_codes
                        for beat in section_beats
                    ),
                )
                for section, section_beats in (
                    (section, mapped_beats.get(section.index, []))
                    for section in sections
                )
            }
        except (OSError, UnicodeError, ValueError, RuntimeError):
            coverage_by_section = {}
        for index, section in enumerate(sections):
            voice = voices[index] if index < len(voices) else None
            srt = srt_files[index] if index < len(srt_files) else None
            analyzed = report_sections.get(section.index, {})
            total_footage_beats, covered_footage_beats = (
                coverage_by_section.get(section.index, (0, 0))
            )
            footage_ready = (
                total_footage_beats > 0
                and covered_footage_beats == total_footage_beats
            )
            beat_count = analyzed.get("beat_count")
            if beat_count is None:
                beat_count = explicit_counts.get(
                    section.name.strip().lower()
                )
            status_text = (
                (
                    f"Thiếu footage "
                    f"{total_footage_beats - covered_footage_beats}/"
                    f"{total_footage_beats} Beat"
                )
                if not footage_ready
                else "Đã phân tích · preview"
                if analyzed.get("preview")
                else "Đã phân tích · cache"
                if analyzed.get("timing_status") == "cached"
                else "Đã phân tích"
                if analyzed
                else "Cần phân tích"
            )
            values = [
                f"{section.index:02d} · {section.name or 'UNTITLED'}",
                voice.name if voice is not None else "Thiếu Audio",
                srt.name if srt is not None else "Không có",
                (
                    str(beat_count)
                    if beat_count is not None
                    else "Tự động"
                ),
                str(analyzed.get("cut_count", "—")),
                (
                    f"{float(analyzed.get('duration', 0)):.2f}s"
                    if analyzed
                    else "—"
                ),
                status_text,
            ]
            row = self.section_table.rowCount()
            self.section_table.insertRow(row)
            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check_item.setCheckState(
                Qt.CheckState.Checked
                if section.index in previously_checked
                else Qt.CheckState.Unchecked
            )
            check_item.setData(
                Qt.ItemDataRole.UserRole, section.index
            )
            check_item.setData(
                int(Qt.ItemDataRole.UserRole) + 1,
                footage_ready,
            )
            check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.section_table.setItem(row, 0, check_item)
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if column == 7 and not footage_ready:
                    item.setBackground(QColor("#5f1f1f"))
                    item.setForeground(QColor("#fca5a5"))
                elif column == 7 and analyzed:
                    item.setBackground(
                        QColor(
                            "#3b2a74"
                            if analyzed.get("preview")
                            else "#14532d"
                        )
                    )
                    item.setForeground(
                        QColor(
                            "#c4b5fd"
                            if analyzed.get("preview")
                            else "#86efac"
                        )
                    )
                self.section_table.setItem(row, column, item)
            self.section_table.setRowHeight(row, 32)
        section_indexes = {section.index for section in sections}
        analyzed_count = len(section_indexes & set(report_sections))
        self.section_stats_label.setText(
            f"Đã phân tích: {analyzed_count}/{len(sections)} đoạn"
        )
        self._on_section_selection_changed()

    def _selected_section_indexes(self) -> set[int]:
        if not hasattr(self, "section_table"):
            return set()
        result = set()
        for row in range(self.section_table.rowCount()):
            item = self.section_table.item(row, 0)
            if (
                item is not None
                and item.checkState() == Qt.CheckState.Checked
            ):
                result.add(int(item.data(Qt.ItemDataRole.UserRole)))
        return result

    def _set_all_sections_checked(self, checked: bool) -> None:
        state = (
            Qt.CheckState.Checked
            if checked
            else Qt.CheckState.Unchecked
        )
        self.section_table.blockSignals(True)
        try:
            for row in range(self.section_table.rowCount()):
                item = self.section_table.item(row, 0)
                if item is not None:
                    item.setCheckState(state)
        finally:
            self.section_table.blockSignals(False)
        self._on_section_selection_changed()

    def _analyzed_section_indexes(self) -> set[int]:
        cache_dir = self._project_path() / ".cache"
        result = set()
        report_path = cache_dir / "vfootage_timeline.json"
        paths = [report_path]
        preview_dir = cache_dir / "section_previews"
        if preview_dir.is_dir():
            paths.extend(preview_dir.glob("*.json"))
        for path in paths:
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                result.update(
                    int(item["index"])
                    for item in payload.get("sections", [])
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                continue
        return result

    def _refresh_capcut_enabled(self) -> None:
        if not hasattr(self, "export_capcut_btn"):
            return
        full_report = (
            self._project_path() / ".cache" / "vfootage_timeline.json"
        ).is_file()
        selected = self._selected_section_indexes()
        selected_ready = bool(selected) and (
            selected <= self._analyzed_section_indexes()
        )
        self.export_capcut_btn.setEnabled(
            not self._running and (full_report or selected_ready)
        )

    def _refresh_render_enabled(self) -> None:
        if not hasattr(self, "render_btn"):
            return
        full_report = (
            self._project_path() / ".cache" / "vfootage_timeline.json"
        ).is_file()
        selected = self._selected_section_indexes()
        selected_ready = bool(selected) and (
            selected <= self._analyzed_section_indexes()
        )
        self.render_btn.setEnabled(
            not self._running and (full_report or selected_ready)
        )

    def _on_section_selection_changed(self, *_args) -> None:
        selected = self._selected_section_indexes()
        checked_items = [
            self.section_table.item(row, 0)
            for row in range(self.section_table.rowCount())
            if (
                self.section_table.item(row, 0) is not None
                and self.section_table.item(row, 0).checkState()
                == Qt.CheckState.Checked
            )
        ]
        footage_ready = bool(checked_items) and all(
            bool(
                item.data(int(Qt.ItemDataRole.UserRole) + 1)
            )
            for item in checked_items
        )
        enabled = (
            hasattr(self, "section_table")
            and footage_ready
            and not self._running
        )
        count = len(selected)
        if hasattr(self, "selection_summary_label"):
            self.selection_summary_label.setText(
                f"Đã chọn: {count} Section"
            )
        if hasattr(self, "workflow_scope_label"):
            self.workflow_scope_label.setText(
                f"Phạm vi hiện tại: {count} Section"
                if count
                else "Chưa chọn Section"
            )
        if hasattr(self, "analyze_section_btn"):
            self.analyze_section_btn.setEnabled(enabled)
            self.analyze_section_btn.setText(
                f"◆  Phân tích {count} Section"
                if count
                else "◆  Phân tích Section đã chọn"
            )
        self._refresh_capcut_enabled()
        self._refresh_render_enabled()

    def _analyze_selected_sections(self) -> None:
        selected = self._selected_section_indexes()
        if not selected:
            return
        self._analyze_section_indexes = set(selected)
        self._start_build("analyze_section")

    def _restore_beat_results(self) -> None:
        cache_dir = self._project_path() / ".cache"
        self._restore_beat_alignment(cache_dir / "vfootage_alignment.json")
        report_path = cache_dir / "vfootage_timeline.json"
        preview_dir = cache_dir / "section_previews"
        available_reports = (
            [report_path] if report_path.is_file() else []
        )
        if preview_dir.is_dir():
            available_reports.extend(preview_dir.glob("*.json"))
        if not available_reports:
            return

        report_path = max(
            available_reports,
            key=lambda path: path.stat().st_mtime_ns,
        )
        if not report_path.is_file():
            return
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            timeline = payload.get("timeline", [])
            source_coverage = payload.get("source_coverage", [])
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        for entry in timeline:
            filename = Path(str(entry.get("footage", ""))).name
            beat_value = entry.get("beats", [])
            codes = (
                beat_value
                if isinstance(beat_value, list)
                else str(beat_value).split("+")
            )
            for code in codes:
                code = code.strip().upper()
                if code in self._beat_rows:
                    self._add_selected_footage(code, filename)
                    row = self._beat_rows[code]
                    report_values = {
                        3: f"{float(entry.get('timeline_start', 0)):.2f}–{float(entry.get('timeline_end', 0)):.2f}s",
                        4: f"{float(entry.get('duration', 0)):.2f}s",
                        5: f"{float(entry.get('source_start', 0)):.2f}–{float(entry.get('source_end', 0)):.2f}s / {float(entry.get('source_duration', 0)):.2f}s",
                        6: str(entry.get("scene_index", 0)),
                        7: f"{float(entry.get('semantic_scores', {}).get('desired_visual_score', 0)):.3f}",
                        8: f"{float(entry.get('semantic_scores', {}).get('main_idea_score', 0)):.3f}",
                        9: f"{float(entry.get('semantic_scores', {}).get('keyword_score', 0)):.3f}",
                        10: f"{float(entry.get('semantic_scores', {}).get('avoid_score', 0)):.3f}",
                        11: f"{float(entry.get('quality', {}).get('quality_score', 0)):.3f}",
                        12: str(entry.get("selection_reason", "")).replace("_", " ").title(),
                    }
                    for column, value in report_values.items():
                        self._append_beat_cell(row, column, value)
                    self._set_timeline_cell_tooltips(row)
                    self._set_beat_status(code, "Đã chọn Scene", "done")
        if self.output_edit.text().strip() and Path(
            self.output_edit.text().strip()
        ).is_file():
            for code in self._beat_rows:
                self._set_beat_status(code, "Hoàn tất", "done")
        self._apply_timeline_health(timeline, source_coverage)

    def _restore_beat_alignment(self, alignment_path: Path) -> None:
        if not alignment_path.is_file():
            return
        try:
            payload = json.loads(alignment_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        audio_duration = float(payload.get("audio_duration", 0.0) or 0.0)
        if audio_duration > 0:
            self.timeline_health_label.setText(
                "Độ dài video theo audio gốc: "
                f"{audio_duration:.2f}s · "
                f"{int(payload.get('beat_count', 0) or 0)} Beat"
            )
        for entry in payload.get("beats", []):
            code = str(entry.get("beat", "")).strip().upper()
            row = self._beat_rows.get(code)
            if row is None:
                continue
            values = {
                3: f"{float(entry.get('timeline_start', 0)):.2f}–{float(entry.get('timeline_end', 0)):.2f}s",
                4: f"{float(entry.get('duration', 0)):.2f}s",
            }
            for column, value in values.items():
                phys_col = column - 1
                item = self.beat_table.item(row, phys_col)
                if item is None:
                    item = QTableWidgetItem()
                    self.beat_table.setItem(row, phys_col, item)
                if item.text() in {"", "—", "-"}:
                    item.setText(value)
                item.setToolTip("Thời lượng Beat theo audio gốc, lấy từ bước căn lời thoại.")
            self._set_timeline_cell_tooltips(row)

    def _set_timeline_cell_tooltips(self, row: int) -> None:
        descriptions = {
            2: "Timeline audio/video: vị trí Beat trên audio gốc và video đầu ra.",
            3: "Độ dài Beat: thời lượng tính từ timeline audio gốc.",
            4: "Timeline footage gốc: đoạn lấy trong file footage nguồn.",
        }
        for column, description in descriptions.items():
            item = self.beat_table.item(row, column)
            if item is None:
                continue
            values = item.text().replace(" | ", "\n")
            item.setToolTip(f"{description}\n{values}")

    def _apply_timeline_health(
        self,
        timeline: list[dict],
        source_coverage: list[dict] | None = None,
    ) -> None:
        health_rows = inspect_timeline_health(timeline)
        issues_by_code: dict[str, dict] = {}
        for entry, health in zip(timeline, health_rows):
            beat_value = entry.get("beats", [])
            codes = (
                beat_value
                if isinstance(beat_value, list)
                else str(beat_value).split("+")
            )
            for raw_code in codes:
                code = str(raw_code).strip().upper()
                if code not in self._beat_rows:
                    continue
                current = issues_by_code.setdefault(
                    code, {"severity": "ok", "warnings": []}
                )
                if (
                    HEALTH_LEVELS[health["severity"]]
                    > HEALTH_LEVELS[current["severity"]]
                ):
                    current["severity"] = health["severity"]
                for warning in health["warnings"]:
                    if warning not in current["warnings"]:
                        current["warnings"].append(warning)

        source_coverage = source_coverage or []
        coverage_by_code: dict[str, dict] = {}
        for coverage in source_coverage:
            code = str(coverage.get("beat", "")).strip().upper()
            if code not in self._beat_rows:
                continue
            coverage_by_code[code] = dict(coverage)
            current = issues_by_code.setdefault(
                code, {"severity": "ok", "warnings": []}
            )
            coverage_status = str(coverage.get("status", "ok"))
            if coverage_status not in HEALTH_LEVELS:
                coverage_status = "warning"
            if (
                HEALTH_LEVELS[coverage_status]
                > HEALTH_LEVELS[current["severity"]]
            ):
                current["severity"] = coverage_status
            for warning in coverage.get("warnings", []):
                message = f"Nguồn: {warning}"
                if message not in current["warnings"]:
                    current["warnings"].append(message)

        critical_count = sum(
            health["severity"] == "critical" for health in health_rows
        )
        warning_count = sum(
            health["severity"] == "warning" for health in health_rows
        )
        ok_count = len(health_rows) - critical_count - warning_count
        source_critical = sum(
            row.get("status") == "critical" for row in source_coverage
        )
        source_warning = sum(
            row.get("status") == "warning" for row in source_coverage
        )
        if critical_count or source_critical:
            label_background, label_foreground, label_border = (
                "#5f1f1f", "#fecaca", "#ef4444"
            )
        elif warning_count:
            label_background, label_foreground, label_border = (
                "#5a3a12", "#fde68a", "#f59e0b"
            )
        else:
            label_background, label_foreground, label_border = (
                "#14532d", "#86efac", "#22c55e"
            )
        self.timeline_health_label.setText(
            "Kiểm tra Timeline: "
            f"{ok_count} Cut ổn · {warning_count} cần xem lại · "
            f"{critical_count} bất thường · "
            f"{source_critical} Beat thiếu nguồn · "
            f"{source_warning} Beat nguồn mỏng"
        )
        self.timeline_health_label.setStyleSheet(
            f"background:{label_background}; color:{label_foreground};"
            f"border:1px solid {label_border}; border-radius:7px;"
            "padding:6px 9px; font-weight:800;"
        )

        styles = {
            "ok": ("Đạt", "#14532d", "#86efac"),
            "warning": ("Cần xem lại", "#5a3a12", "#fde68a"),
            "critical": ("Bất thường", "#5f1f1f", "#fecaca"),
        }
        for code, result in issues_by_code.items():
            row = self._beat_rows[code]
            label, background, foreground = styles[result["severity"]]
            warnings = result["warnings"]
            beat_coverage = coverage_by_code.get(code, {})
            if beat_coverage and not beat_coverage.get(
                "longest_required_seconds"
            ):
                beat_coverage["longest_required_seconds"] = max(
                    (
                        float(entry.get("duration", 0.0))
                        for entry in timeline
                        if code in {
                            str(value).strip().upper()
                            for value in (
                                entry.get("beats", [])
                                if isinstance(entry.get("beats", []), list)
                                else str(entry.get("beats", "")).split("+")
                            )
                        }
                    ),
                    default=0.0,
                )
            status = self.frozen_beat_table.item(row, 1)
            status.setText(
                label if not warnings else f"{label} · {len(warnings)}"
            )
            status.setBackground(QColor(background))
            status.setForeground(QColor(foreground))
            self._set_beat_code_style(row, "error" if result["severity"] == "critical" else "done")
            tooltip = build_timeline_health_tooltip(
                warnings,
                code,
                coverage=beat_coverage,
                beat_details=self._beat_metadata.get(code, {}),
                target_seconds=self.builder_settings.target_cut_seconds,
                max_seconds=self.builder_settings.max_cut_seconds,
            )
            keywords = footage_search_keywords(
                self._beat_metadata.get(code, {})
            )
            status.setToolTip("")
            status.setData(
                HEALTH_DETAIL_ROLE, tooltip if warnings else ""
            )
            status.setData(
                HEALTH_KEYWORDS_ROLE, keywords if warnings else ""
            )
            footage_item = self.beat_table.item(row, 1) # Cột "Footage" là cột thứ 2 (index 1) trong bảng cuộn
            if footage_item is not None and result["severity"] != "ok":
                footage_item.setBackground(QColor(background))
                footage_item.setForeground(QColor(foreground))
                footage_item.setToolTip("")
                footage_item.setData(HEALTH_DETAIL_ROLE, tooltip)
                footage_item.setData(HEALTH_KEYWORDS_ROLE, keywords)

    def _show_beat_issue_details(self, row: int, column: int) -> None:
        sender = self.sender()
        if not isinstance(sender, QTableWidget):
            return
        item = sender.item(row, column)
        if item is None:
            return
        detail = str(item.data(HEALTH_DETAIL_ROLE) or "").strip()
        if not detail:
            return
        keywords = str(item.data(HEALTH_KEYWORDS_ROLE) or "").strip()
        beat_item = self.frozen_beat_table.item(row, 0)
        beat_code = beat_item.text() if beat_item is not None else ""

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"Cảnh báo {beat_code}" if beat_code else "Chi tiết cảnh báo"
        )
        dialog.setMinimumSize(620, 460)
        layout = QVBoxLayout(dialog)
        title = QLabel(
            f"Chi tiết lỗi và cách xử lý · {beat_code}"
            if beat_code
            else "Chi tiết lỗi và cách xử lý"
        )
        title.setStyleSheet(SECTION_TITLE_STYLE)
        layout.addWidget(title)
        detail_view = QPlainTextEdit()
        detail_view.setReadOnly(True)
        detail_view.setPlainText(detail)
        detail_view.setToolTip(
            "Có thể bôi chọn và sao chép nội dung."
        )
        layout.addWidget(detail_view, 1)

        keyword_label = QLabel(
            f"Từ khóa tìm footage: {keywords}"
            if keywords
            else "Beat này chưa có từ khóa tìm footage."
        )
        keyword_label.setWordWrap(True)
        keyword_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        keyword_label.setStyleSheet(
            "background:#18243a; color:#c7d2fe; border:1px solid #33445e;"
            "border-radius:7px; padding:8px; font-weight:700;"
        )
        layout.addWidget(keyword_label)
        actions = QHBoxLayout()
        actions.addStretch(1)
        copy_btn = QPushButton("Sao chép từ khóa")
        copy_btn.setEnabled(bool(keywords))
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(keywords)
        )
        close_btn = QPushButton("Đóng")
        close_btn.clicked.connect(dialog.accept)
        actions.addWidget(copy_btn)
        actions.addWidget(close_btn)
        layout.addLayout(actions)
        dialog.exec()

    def _add_selected_footage(self, code: str, filename: str) -> None:
        if not filename:
            return
        selected = self._selected_footage.setdefault(code, [])
        if filename not in selected: selected.append(filename)
        row = self._beat_rows.get(code)
        if row is not None:
            # Cột "Footage" là cột thứ 2 (index 1) trong bảng cuộn
            item = self.beat_table.item(row, 1)
            item.setText(", ".join(selected))
            item.setToolTip("\n".join(selected))

    def _append_beat_cell(
        self, row: int, column: int, value: str
    ) -> None:
        if column == 0:
            table, phys_col = self.frozen_beat_table, 0
        elif column == BEAT_STATUS_COLUMN:
            table, phys_col = self.frozen_beat_table, 1
        elif 1 <= column < BEAT_STATUS_COLUMN:
            table, phys_col = self.beat_table, column - 1
        else:
            return
        item = table.item(row, phys_col)
        current = item.text() if item is not None else ""
        values = [] if current in {"", "-", "—"} else current.split(" | ")
        if value not in values: values.append(value)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, phys_col, item)
        item.setText(" | ".join(values))
        item.setToolTip("\n".join(values))

    def _set_beat_status(
        self, code: str, text: str, style: str = "running"
    ) -> None:
        row = self._beat_rows.get(code.upper())
        if row is None:
            return
        item = self.frozen_beat_table.item(row, 1)
        if item is None:
            item = QTableWidgetItem()
            self.frozen_beat_table.setItem(row, 1, item)
        item.setText(text)
        _, background, foreground = STATUS_STYLE[style]
        item.setBackground(QColor(background))
        item.setForeground(QColor(foreground))
        item.setData(BEAT_STATE_ROLE, style)
        self._set_beat_code_style(row, style)

    def _set_beat_code_style(self, row: int, style: str) -> None:
        """Mirror the analysis state on the Beat-code cell."""
        code_item = self.frozen_beat_table.item(row, 0)
        if code_item is None:
            return
        _, background, foreground = STATUS_STYLE[style]
        code_item.setBackground(QColor(background))
        code_item.setForeground(QColor(foreground))
        code_item.setData(BEAT_STATE_ROLE, style)
        code_item.setToolTip(
            {
                "running": "Beat đang được phân tích.",
                "done": "Beat đã phân tích xong.",
                "error": "Beat gặp lỗi khi phân tích.",
            }.get(style, "")
        )

    def _validate_inputs(self) -> list[str]:
        errors = []
        if not self.script_edit.text().strip() or not Path(
            self.script_edit.text().strip()
        ).is_file():
            errors.append("Không tìm thấy transcript.")
        if not self.beats_edit.text().strip() or not Path(
            self.beats_edit.text().strip()
        ).is_file():
            errors.append("Không tìm thấy file Beat CSV.")
        if not self.footage_edit.text().strip() or not Path(
            self.footage_edit.text().strip()
        ).is_dir():
            errors.append("Không tìm thấy thư mục Footage.")
        voice_values = self._voice_paths()
        discovered_voice_count = self._count_voice_files(
            self._project_path()
        )
        if voice_values and any(not path.is_file() for path in voice_values):
            errors.append("File Audio đã chọn không tồn tại.")
        if len(voice_values) > 1:
            errors.append("Chỉ được chọn đúng 1 file Audio.")
        if not voice_values and discovered_voice_count != 1:
            errors.append(
                "Project phải có đúng 1 file Audio trong thư mục voices "
                f"(hiện có {discovered_voice_count})."
            )
        if not (
            self.builder_settings.min_cut_seconds
            <= self.builder_settings.target_cut_seconds
            <= self.builder_settings.max_cut_seconds
        ):
            errors.append("Thời lượng Cut phải thỏa mãn Min ≤ Target ≤ Max.")
        model_status = check_clip_cache(
            replace(
                default_config(),
                clip_model=self.builder_settings.vision_model,
            )
        )
        if (
            not model_status.ready
            and not self.builder_settings.auto_model_download
        ):
            errors.append(
                "Model thị giác đã chọn chưa có trong Cache và chức năng "
                "tự động tải đang tắt. Hãy mở Cấu hình để tải model hoặc "
                "bật tự động tải."
            )
        if (
            "siglip2" in self.builder_settings.vision_model.lower()
            and importlib.util.find_spec("sentencepiece") is None
        ):
            errors.append(
                "SigLIP 2 cần thư viện sentencepiece. Hãy cài lại "
                "requirements.txt trước khi phân tích."
            )
        return errors

    def _are_inputs_ready(self) -> bool:
        """Check if all required input files and folders are configured."""
        has_required_paths = all(
            edit.text().strip()
            for edit in (self.script_edit, self.beats_edit, self.footage_edit)
        )
        selected_voice_count = len(self._voice_paths())
        voice_count = (
            selected_voice_count
            if selected_voice_count
            else self._count_voice_files(self._project_path())
        )
        return has_required_paths and voice_count == 1

    def _voice_paths(self) -> list[Path]:
        return [
            Path(value.strip())
            for value in self.voice_edit.text().split(";")
            if value.strip()
        ]

    def _build_cli_arguments(self, mode: str | None = None) -> list[str]:
        arguments = ["--cli", "--base-dir", str(self._project_path())]

        # --- Paths ---
        voices = self._voice_paths()
        if voices:
            arguments.extend(["--voice-files", *[str(path) for path in voices]])

        path_edits = {
            "--script": self.script_edit,
            "--beats": self.beats_edit,
            "--footage-dir": self.footage_edit,
            "--output": self.output_edit,
        }
        for option, edit in path_edits.items():
            if edit.text().strip():
                arguments.extend([option, edit.text().strip()])
        # --- General Settings ---
        settings = self.builder_settings
        arguments.extend([
            "--resolution", settings.resolution,
            "--analysis-workers", str(settings.analysis_workers),
            "--vision-model", settings.vision_model,
            "--min-cut-seconds", str(settings.min_cut_seconds),
            "--target-cut-seconds", str(settings.target_cut_seconds),
            "--max-cut-seconds", str(settings.max_cut_seconds),
            "--minimum-video-minutes", str(settings.minimum_video_minutes),
        ])
        if settings.skip_whisper:
            arguments.append("--skip-whisper")
        if not settings.auto_model_download:
            arguments.append("--no-model-download")

        # --- Mode-specific Arguments ---
        if mode in {"analyze", "analyze_force"}:
            arguments.append("--analyze-only")
        if mode == "analyze_force":
            arguments.append("--force-analysis")
        elif mode == "render":
            arguments.append("--render-only")
            # Add general music settings for render mode
            if settings.music_dir.strip():
                arguments.extend(["--music-dir", settings.music_dir.strip()])
            if settings.music_cue_sheet.strip():
                arguments.extend(["--music-cue-sheet", settings.music_cue_sheet.strip()])
        elif mode == "export_scenes":
            arguments.extend([
                "--export-scenes-only",
                "--scenes-output-dir",
                str(self._scenes_output_dir or self._project_path() / "selected_scenes"),
            ])
        elif mode == "export_capcut":
            arguments.extend([
                "--export-capcut-package",
                "--no-capcut-reference-video",
                "--capcut-output-dir",
                str(self._capcut_output_dir or self._project_path() / "capcut_package"),
            ])
            if self._capcut_template_dir is not None:
                arguments.extend([
                    "--capcut-template-dir", str(self._capcut_template_dir),
                    "--capcut-draft-name", self._capcut_draft_name or self._project_path().name,
                ])
                if self._capcut_drafts_root is not None:
                    arguments.extend(["--capcut-drafts-root", str(self._capcut_drafts_root)])

            # Music logic for CapCut
            if settings.capcut_use_main_music:
                # Use general project music
                if settings.music_dir.strip():
                    arguments.extend(["--music-dir", settings.music_dir.strip()])
                if settings.music_cue_sheet.strip():
                    arguments.extend(["--music-cue-sheet", settings.music_cue_sheet.strip()])
            else:
                # Use CapCut-specific music
                hook_music = settings.capcut_hook_music.strip()
                if hook_music:
                    arguments.extend(["--capcut-hook-music", hook_music])
                    arguments.extend([
                        "--capcut-hook-volume-db", str(settings.capcut_hook_volume_db),
                    ])
                for row in settings.capcut_body_music:
                    path = str(row.get("path", "")).strip()
                    if not path:
                        continue
                    value = path
                    if "volume_db" in row:
                        value += f"|volume_db={float(row['volume_db'])}"
                    if row.get("repeat", False):
                        value += "|repeat"
                    arguments.extend(["--capcut-body-music", value])
            if self._capcut_replace_existing:
                arguments.append("--replace-capcut-draft")
        return arguments

    def _start_build(self, mode: str) -> None:
        if mode in {"export_scenes", "export_capcut"}:
            report = (
                self._project_path()
                / ".cache"
                / "vfootage_timeline.json"
            )
            errors = [] if report.is_file() else [
                (
                    "Chưa có Report phân tích để xuất gói CapCut."
                    if mode == "export_capcut"
                    else "Chưa có Report phân tích để xuất Scene."
                )
            ]
        else:
            errors = self._validate_inputs()
        if errors:
            QMessageBox.warning(
                self, "Dữ liệu đầu vào không hợp lệ",
                "\n".join(f"• {item}" for item in errors)
            )
            return
        self._save_settings()
        self._run_mode = mode
        if hasattr(self, "job_scope_label"):
            if mode in {"analyze", "analyze_force"}:
                self.job_scope_label.setText(
                    "Phân tích lại toàn bộ từ đầu"
                    if mode == "analyze_force"
                    else "Cập nhật phân tích kịch bản"
                )
            elif mode == "render":
                self.job_scope_label.setText("Render Video")
            elif mode == "export_capcut":
                self.job_scope_label.setText("Xuất Draft CapCut")
            else:
                self.job_scope_label.setText("Xuất các Scene đã chọn")
        self._statuses_before_run = self._stage_statuses.copy()
        self._output_stage_percent = 0
        self._reset_stage_times()
        self._refresh_beat_table()
        self._reading_selected_timeline = False
        self._output_buffer = ""
        if mode in {"export_scenes", "export_capcut"}:
            self._set_stage_status(8, "running")
        else:
            for row in range(len(PIPELINE_STAGES)):
                self._set_stage_status(row, "waiting")
            self._set_stage_status(0, "running")
        self._update_progress()
        self._append_log_line("[INFO] Đang khởi động Footage Video Builder...")

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("FOOTAGE_BUILDER_UI_PROCESS", "1")
        self.process.setProcessEnvironment(environment)
        arguments = self._build_cli_arguments(mode)
        if getattr(sys, "frozen", False):
            program = sys.executable
            process_arguments = arguments
            working_directory = str(Path(sys.executable).resolve().parent)
        else:
            program = sys.executable
            process_arguments = ["-u", str(ROOT_DIR / "main.py"), *arguments]
            working_directory = str(ROOT_DIR)
        self.process.setWorkingDirectory(working_directory)
        self.process.start(program, process_arguments)

    def _prompt_analysis_mode(self) -> None:
        if self._running:
            QMessageBox.warning(
                self, "Tác vụ đang chạy", "Một tác vụ khác đang chạy. Vui lòng đợi."
            )
            return
        answer = QMessageBox.question(
            self,
            "Chế độ phân tích",
            "Bạn muốn tiếp tục phân tích (dùng cache) hay phân tích lại từ đầu (bỏ qua cache)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_build("analyze")
        elif answer == QMessageBox.StandardButton.No:
            self._start_build("analyze_force")
        # If Cancel, do nothing


    def _confirm_full_reanalysis(self) -> None:
        answer = QMessageBox.question(
            self,
            "Phân tích lại từ đầu",
            "Thao tác này sẽ bỏ qua toàn bộ cache phân tích và xử lý lại "
            "tất cả footage. Bạn có muốn tiếp tục?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_build("analyze_force")

    def _stop_build(self) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._append_log_line("[WARN] Đang dừng Pipeline...")
            self.process.terminate()
            if not self.process.waitForFinished(3000):
                self.process.kill()
        elif self.footage_process.state() != QProcess.ProcessState.NotRunning:
            self._append_log_line("[WARN] Đang dừng tác vụ tải footage...")
            self.footage_process.terminate()
            if not self.footage_process.waitForFinished(3000):
                self.footage_process.kill()
        else:
            self._running = False
            self._set_running_ui_state(False)

    def _on_process_started(self) -> None:
        self._running = True
        if self._run_mode in {
            "analyze", "analyze_force", "analyze_section"
        }:
            for code in self._beat_rows:
                self._set_beat_status(
                    code, "Đang phân tích", "running"
                )
        self._set_running_ui_state(True)
        self.current_label.setText("Hiện tại: Đang nạp dữ liệu Project")

    def _read_process_output(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self._output_buffer += data
        lines = self._output_buffer.splitlines(keepends=True)
        self._output_buffer = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            self._output_buffer = lines.pop()
        for line in lines:
            text = line.rstrip("\r\n")
            if text:
                self._track_stage_from_log(text)
                if text.startswith("STAGE_"):
                    continue
                self._append_log_line(text)
                self._track_beat_from_log(text)

    def _track_stage_from_log(self, line: str) -> None:
        stage_match = re.match(r"^STAGE_(START|END):\s*([A-Z0-9_]+)", line)
        if stage_match:
            action, code = stage_match.groups()
            index = PIPELINE_STAGE_INDEXES.get(code)
            if index is None:
                return
            if action == "START":
                self._advance_to_stage(index)
            else:
                self._finish_stage(index)
            return
        progress_match = re.search(r"OUTPUT_PROGRESS:\s*(\d+)", line)
        if progress_match:
            self._set_output_stage_progress(
                int(progress_match.group(1))
            )
            return
        counted_progress = re.search(
            r"\[(\d+)/(\d+) complete\]", line
        )
        if counted_progress:
            self._set_stage_count_progress(
                3,
                int(counted_progress.group(1)),
                int(counted_progress.group(2)),
            )
        beat_progress = re.search(r"Căn Beat:\s*(\d+)/(\d+)", line)
        if beat_progress:
            self._set_stage_count_progress(
                1,
                int(beat_progress.group(1)),
                int(beat_progress.group(2)),
            )
        scene_progress = re.search(
            r"(?:Xuất Scene|Scene export) \[(\d+)/(\d+)\]", line
        )
        if scene_progress:
            self._set_stage_count_progress(
                8,
                int(scene_progress.group(1)),
                int(scene_progress.group(2)),
            )
        rules = [
            (0, ("Inputs:", "Đầu vào:", "Voice timeline:", "Timeline Voice:")),
            (1, ("Script Overview:", "Speech timing:", "Timing lời thoại",
                 "Section cache [",
                 "Semantic beat alignment:",
                 "Căn chỉnh Semantic Beat:")),
            (
                2,
                (
                    "Narration cuts:",
                    "Các Cut lời thoại:",
                    "Các Cut lời thoại theo Section:",
                ),
            ),
            (3, ("Footage analysis:", "Phân tích Footage:")),
            (4, ("Candidate filter:", "Lọc Candidate:")),
            (5, ("Selected global timeline:",
                 "Timeline toàn cục đã chọn:")),
            (6, ("(visual ",)),
            (7, ("Narration audio: ready", "Audio lời thoại: sẵn sàng")),
            (
                8,
                (
                    "Exporting ", "Đang xuất ",
                    "Video ready:", "Video đã sẵn sàng:",
                    "Analyze-only mode:", "Chế độ chỉ phân tích:",
                    "Scene export [", "Xuất Scene [",
                    "Selected scenes ready:",
                    "Các Scene đã chọn đã sẵn sàng:",
                    "CapCut package ready:",
                    "Gói CapCut đã sẵn sàng:",
                    "CapCut manifest:",
                ),
            ),
        ]
        for index, markers in rules:
            if any(marker in line for marker in markers):
                self._advance_to_stage(index)
        if line.startswith(("Exporting ", "Đang xuất ")):
            self.current_label.setText("Hiện tại: Đang encode Video đầu ra")

    def _track_beat_from_log(self, line: str) -> None:
        if line.startswith("Beat timing:"):
            self._restore_beat_alignment(
                self._project_path() / ".cache" / "vfootage_alignment.json"
            )
            return
        scene_export_match = re.match(
            r"^(?:Scene export|Xuất Scene) \[\d+/\d+\]:\s+"
            rf"{LOG_BEAT_CODES_PATTERN}\s+->\s+(.+)$",
            line,
        )
        if scene_export_match:
            codes_text, filename = scene_export_match.groups()
            for code in codes_text.upper().split("+"):
                self._add_selected_footage(code, filename)
                self._set_beat_status(code, "Đã xuất Scene", "done")
            return
        if line in {
            "Selected global timeline:",
            "Timeline toàn cục đã chọn:",
        }:
            self._reading_selected_timeline = True
            return
        if line.endswith(":") and not line.startswith("  "):
            self._reading_selected_timeline = False

        footage_match = re.search(
            r"\[\d+/\d+ complete\]\s+([^:]+):\s+(.+)$", line
        )
        if footage_match:
            filename, result = footage_match.groups()
            code = filename_beat_code(Path(filename), set(self._beat_rows))
            if code:
                if any(
                    marker in result
                    for marker in ("rejected", "crashed", "bị loại", "gặp lỗi")
                ):
                    self._set_beat_status(code, "Lỗi phân tích", "error")
                else:
                    self._set_beat_status(code, "Đã phân tích", "done")
            return

        render_match = re.match(
            rf"^\s+{LOG_BEAT_CODES_PATTERN}\s+.+?<-\s+([^@]+?)\s+@",
            line,
        )
        if render_match:
            codes_text, filename = render_match.groups()
            for code in codes_text.upper().split("+"):
                self._add_selected_footage(code, filename.strip())
                self._set_beat_status(code, "Đang Render", "running")
            return

        beat_match = re.match(rf"^\s+{LOG_BEAT_CODES_PATTERN}:\s+(.+)$", line)
        if not beat_match:
            return
        codes_text, detail = beat_match.groups()
        codes = codes_text.upper().split("+")
        if self._reading_selected_timeline and "score=" in detail:
            filename = detail.split(" [", 1)[0].strip()
            for code in codes:
                self._add_selected_footage(code, filename)
                self._set_beat_status(code, "Đã chọn Scene", "done")
        elif "<-" in detail and "(visual " in detail:
            filename = detail.split("<-", 1)[1].split(" @", 1)[0].strip()
            for code in codes:
                self._add_selected_footage(code, filename)
                self._set_beat_status(code, "Đang Render", "running")
        elif not self._reading_selected_timeline:
            for code in codes:
                self._set_beat_status(code, "Đã căn lời", "done")

    def _advance_to_stage(self, index: int) -> None:
        for row in range(index):
            if self._stage_statuses[row] in {"waiting", "running"}:
                self._set_stage_status(row, "done")
        if self._stage_statuses[index] == "waiting":
            self._set_stage_status(index, "running")
        self.current_label.setText(
            f"Hiện tại: {self._stage_description(index)}"
        )
        self._update_progress()

    def _finish_stage(self, index: int) -> None:
        for row in range(index):
            if self._stage_statuses[row] in {"waiting", "running"}:
                self._set_stage_status(row, "done")
        if self._stage_statuses[index] in {"waiting", "running"}:
            self._stage_progress[index] = 100
            self._set_stage_status(index, "done")
        self._update_progress()

    def _show_completion_popup(self) -> None:
        destination = ""
        if self._run_mode == "render":
            destination = self.output_edit.text().strip()
        elif self._run_mode == "export_scenes":
            destination = str(
                self._scenes_output_dir
                or self._project_path() / "selected_scenes"
            )
        elif self._run_mode == "export_capcut":
            destination = str(
                self._capcut_output_dir
                or self._project_path() / "capcut_package"
            )
        title, message = completion_popup_content(
            self._run_mode, destination
        )
        QMessageBox.information(self, title, message)

    def _on_process_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        if self._output_buffer:
            self._track_stage_from_log(self._output_buffer)
            if not self._output_buffer.startswith("STAGE_"):
                self._append_log_line(self._output_buffer)
            self._output_buffer = ""
        was_stopped = exit_status == QProcess.ExitStatus.CrashExit
        success = exit_code == 0 and not was_stopped
        if success:
            section_preview = self._run_mode == "analyze_section"
            analyze_only = self._run_mode in {
                "analyze", "analyze_force", "analyze_section"
            }
            render_only = self._run_mode == "render"
            export_scenes = self._run_mode == "export_scenes"
            export_capcut = self._run_mode == "export_capcut"
            if section_preview:
                for row in range(len(PIPELINE_STAGES)):
                    self._set_stage_status(
                        row,
                        "skipped" if row in (6, 7) else "done",
                    )
            elif export_scenes or export_capcut:
                for row, previous in enumerate(self._statuses_before_run):
                    self._set_stage_status(row, previous)
                self._set_stage_status(8, "done")
            else:
                for row in range(len(PIPELINE_STAGES)):
                    if analyze_only and row in (6, 7):
                        self._set_stage_status(row, "skipped")
                    elif render_only and row < 6:
                        previous = self._statuses_before_run[row]
                        self._set_stage_status(
                            row,
                            previous
                            if previous in {"done", "skipped"}
                            else "skipped",
                        )
                    else:
                        self._set_stage_status(row, "done")
            self.current_label.setText("Hiện tại: Hoàn tất")
            self.job_scope_label.setText(
                f"Hoàn tất · {self.job_scope_label.text()}"
            )
            self._append_log_line("[SUCCESS] Pipeline đã hoàn tất.")
            if render_only:
                for code in self._beat_rows:
                    self._set_beat_status(code, "Hoàn tất", "done")
        else:
            for code, row in self._beat_rows.items():
                status_item = self.frozen_beat_table.item(row, 1)
                if status_item is not None and status_item.data(BEAT_STATE_ROLE) == "running":
                    self._set_beat_status(code, "Lỗi phân tích", "error")

            active = next(
                (
                    index
                    for index, status in enumerate(self._stage_statuses)
                    if status == "running"
                ),
                0,
            )
            self._set_stage_status(active, "error")
            self.current_label.setText(
                "Hiện tại: Đã dừng"
                if was_stopped else "Hiện tại: Pipeline gặp lỗi"
            )
            self.job_scope_label.setText(
                "Công việc đã dừng" if was_stopped else "Công việc gặp lỗi"
            )
            self._append_log_line(
                "[WARN] Pipeline đã dừng."
                if was_stopped
                else f"[ERROR] Pipeline kết thúc với mã {exit_code}."
            )
        self._save_project_stage_state(self._run_mode, success)
        self._set_running_ui_state(False)
        self._refresh_start_enabled()
        self._update_progress()
        self._refresh_project_summary()
        self._refresh_beat_table()
        if success:
            self._show_completion_popup()

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._append_log_line(
                f"[ERROR] Không thể khởi động process: "
                f"{self.process.errorString()}"
            )

    def _on_footage_process_output(self) -> None:
        data = bytes(self.footage_process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self._footage_output_buffer += data
        lines = self._footage_output_buffer.splitlines(keepends=True)
        if not lines:
            return
        self._footage_output_buffer = ""
        if not lines[-1].endswith(("\n", "\r")):
            self._footage_output_buffer = lines.pop()
        for line in lines:
            text = line.strip()
            if not text:
                continue
            self._append_log_line(f"[DOWNLOAD] {text}")
            progress_match = re.search(r"\((\d+)/(\d+)\)", text)
            if progress_match:
                current, total = map(int, progress_match.groups())
                percent = round(current * 100 / total) if total > 0 else 0
                self.progress_bar.setValue(percent)
                self.progress_percent_label.setText(f"{percent}%")
                message_match = re.search(r"Beat\s+\w+:\s*(.*)", text, re.IGNORECASE)
                message = (
                    message_match.group(1).strip() if message_match else "Đang tải..."
                )
                self.current_label.setText(f"Hiện tại: {message}")
                self.pipeline_summary.setText(f"Đang tải {current}/{total} Beat")

    def _on_footage_process_finished(
        self, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        was_stopped = exit_status == QProcess.ExitStatus.CrashExit
        success = exit_code == 0 and not was_stopped
        if success:
            self.progress_bar.setValue(100)
            self.progress_percent_label.setText("100%")
            self.current_label.setText("Hoàn tất")
            self.job_scope_label.setText("Hoàn tất · Tải footage bổ sung")
            self._append_log_line("[SUCCESS] Tải footage bổ sung hoàn tất.")
            QMessageBox.information(
                self,
                "Tải footage hoàn tất",
                "Đã tải xong footage bổ sung. Hãy bấm 'Phân tích kịch bản' để cập nhật Timeline với các file mới.",
            )
        else:
            self.current_label.setText("Lỗi")
            self.job_scope_label.setText("Lỗi · Tải footage bổ sung")
            error_message = (
                "[WARN] Tác vụ tải footage đã bị dừng."
                if was_stopped
                else f"[ERROR] Tác vụ tải footage thất bại với mã thoát {exit_code}."
            )
            self._append_log_line(error_message)
            QMessageBox.critical(self, "Tải footage thất bại", error_message)
        self._running = False
        self._set_running_ui_state(False)
        self._refresh_project_data()

    def _set_running_ui_state(self, running: bool) -> None:
        self._running = running
        self.start_btn.setEnabled(not running)
        self.supplement_btn.setEnabled(not running)
        self.export_btn.setEnabled(not running)
        self.refresh_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def _set_stage_status(self, row: int, status: str) -> None:
        previous_status = self._stage_statuses[row]
        now = time.monotonic()
        if status == "running" and previous_status != "running":
            self._stage_started_at[row] = now
        elif status != "running" and previous_status == "running":
            started_at = self._stage_started_at[row]
            if started_at is not None:
                self._stage_elapsed_seconds[row] += max(
                    0.0, now - started_at
                )
            self._stage_started_at[row] = None
            if status == "done" and self._stage_elapsed_seconds[row] >= 0.5:
                measured = self._stage_elapsed_seconds[row]
                previous_estimate = self._stage_estimates_seconds[row]
                self._stage_estimates_seconds[row] = (
                    measured
                    if previous_estimate is None
                    else previous_estimate * 0.70 + measured * 0.30
                )
        self._stage_statuses[row] = status
        text, background, foreground = STATUS_STYLE[status]
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setBackground(QColor(background))
        item.setForeground(QColor(foreground))
        self.stage_table.setItem(row, 2, item)
        self._refresh_stage_time(row)

    def _reset_stage_times(self) -> None:
        self._stage_started_at = [None] * len(PIPELINE_STAGES)
        self._stage_elapsed_seconds = [0.0] * len(PIPELINE_STAGES)
        self._stage_progress = [None] * len(PIPELINE_STAGES)
        self._refresh_stage_times()

    def _stage_elapsed(self, row: int) -> float:
        elapsed = self._stage_elapsed_seconds[row]
        started_at = self._stage_started_at[row]
        if started_at is not None:
            elapsed += max(0.0, time.monotonic() - started_at)
        return elapsed

    def _stage_eta(self, row: int, elapsed: float) -> float | None:
        progress = self._stage_progress[row]
        if progress is not None and 0 < progress < 100:
            return elapsed * (100 - progress) / progress
        estimate = self._stage_estimates_seconds[row]
        if estimate is not None and estimate > elapsed:
            return estimate - elapsed
        return None

    def _refresh_stage_time(self, row: int) -> None:
        if not hasattr(self, "stage_table"):
            return
        status = self._stage_statuses[row]
        elapsed = self._stage_elapsed(row)
        if status == "running":
            eta = self._stage_eta(row, elapsed)
            text = f"{format_stage_duration(elapsed)} · " + (
                f"ETA {format_stage_duration(eta)}"
                if eta is not None
                else "đang ước tính"
            )
        elif status in {"done", "error"}:
            if elapsed > 0:
                text = format_stage_duration(elapsed)
            else:
                estimate = self._stage_estimates_seconds[row]
                text = (
                    f"Lần trước {format_stage_duration(estimate)}"
                    if estimate is not None
                    else "—"
                )
        elif status == "skipped":
            text = "Bỏ qua"
        else:
            estimate = self._stage_estimates_seconds[row]
            text = (
                f"Ước tính {format_stage_duration(estimate)}"
                if estimate is not None
                else "—"
            )
        item = self.stage_table.item(row, 3)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stage_table.setItem(row, 3, item)
        item.setText(text)
        item.setToolTip(
            "ETA dựa trên tiến độ hiện tại hoặc thời gian lần chạy trước."
        )

    def _refresh_stage_times(self) -> None:
        for row in range(len(PIPELINE_STAGES)):
            self._refresh_stage_time(row)
        if hasattr(self, "pipeline_summary") and self._running:
            self._update_progress()

    def _set_output_stage_progress(self, percent: int) -> None:
        self._output_stage_percent = max(0, min(100, percent))
        self._stage_progress[8] = self._output_stage_percent
        self._advance_to_stage(8)
        _text, background, foreground = STATUS_STYLE["running"]
        item = QTableWidgetItem(
            f"Đang chạy · {self._output_stage_percent}%"
        )
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setBackground(QColor(background))
        item.setForeground(QColor(foreground))
        self.stage_table.setItem(8, 2, item)
        self._refresh_stage_time(8)
        self._update_progress()

    def _set_stage_count_progress(
        self, row: int, completed: int, total: int
    ) -> None:
        if total <= 0:
            return
        self._stage_progress[row] = max(
            0, min(100, round(completed * 100 / total))
        )
        self._advance_to_stage(row)
        self._refresh_stage_time(row)

    def _update_progress(self) -> None:
        done = sum(
            status in {"done", "skipped"} for status in self._stage_statuses
        )
        partial = (
            self._output_stage_percent / 100
            if self._stage_statuses[8] == "running"
            else 0
        )
        percent = round(
            (done + partial) * 100 / len(PIPELINE_STAGES)
        )
        self.progress_label.setText(
            f"Tiến độ: {done} / {len(PIPELINE_STAGES)}"
        )
        self.progress_percent_label.setText(f"{percent}%")
        self.progress_bar.setValue(percent)
        summary = (
            f"Đang xuất Video: {self._output_stage_percent}%"
            if self._stage_statuses[8] == "running"
            else f"Đã hoàn tất {done}/{len(PIPELINE_STAGES)} Stage"
        )
        active = next(
            (
                row
                for row, status in enumerate(self._stage_statuses)
                if status == "running"
            ),
            None,
        )
        if active is not None:
            eta = self._stage_eta(active, self._stage_elapsed(active))
            if eta is not None:
                summary += f" · Stage hiện tại còn khoảng {format_stage_duration(eta)}"
        self.pipeline_summary.setText(summary)
        self._update_workflow_steps()

    def _update_workflow_steps(self) -> None:
        if not hasattr(self, "workflow_steps"):
            return
        statuses = self._stage_statuses
        publishing = self._run_mode in {
            "render", "export_scenes", "export_capcut"
        }
        if statuses[8] == "running" and publishing:
            active = 3
        elif any(status == "running" for status in statuses[1:6]):
            active = 1
        elif all(status in {"done", "skipped"} for status in statuses[:6]):
            active = 2
        elif statuses[0] in {"done", "skipped"}:
            active = 1
        else:
            active = 0
        for index, step in enumerate(self.workflow_steps):
            completed = (
                index < active
                or (
                    index == 3
                    and statuses[8] == "done"
                    and publishing
                )
            )
            if index == active and not completed:
                background, foreground, border = (
                    "#3b2a74", "#f7f9ff", "#8b5cf6"
                )
            elif completed:
                background, foreground, border = (
                    "#14532d", "#86efac", "#22c55e"
                )
            else:
                background, foreground, border = (
                    "#18243a", "#8f9bad", "#33445e"
                )
            step.setStyleSheet(
                f"background:{background}; color:{foreground};"
                f"border:1px solid {border}; border-radius:7px;"
                "padding:6px 10px; font-weight:800;"
            )

    def _append_log_line(self, text: str) -> None:
        if hasattr(self, "log_view"):
            self.log_view.appendPlainText(text)
        project = self._project_path()
        if not project.is_dir():
            return
        log_path = project / ".cache" / "footage_builder.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().astimezone().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{timestamp}] {text}\n")
        except OSError:
            # Logging must never interrupt analysis or rendering.
            pass

    def _refresh_start_enabled(self) -> None:
        if not hasattr(self, "start_btn"):
            return
        inputs_ready = self._are_inputs_ready()
        self.start_btn.setEnabled(not self._running and inputs_ready)
        analysis_ready = (
            self._project_path() / ".cache" / "vfootage_timeline.json"
        ).is_file()
        if hasattr(self, "supplement_btn"):
            self.supplement_btn.setEnabled(
                not self._running and inputs_ready and analysis_ready
            )
        export_enabled = not self._running and analysis_ready
        if hasattr(self, "export_btn"):
            self.export_btn.setEnabled(export_enabled)
        if hasattr(self, "input_stats_label"):
            self._refresh_project_summary()

    def _set_chip(
        self, label: QLabel, background: str, foreground: str, border: str
    ) -> None:
        label.setStyleSheet(
            f"background:{background}; color:{foreground}; border:1px solid {border};"
            "border-radius:10px; padding:4px 9px; font-weight:700;"
        )

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            replace(
                default_config(),
                clip_model=self.builder_settings.vision_model,
            ),
            settings=self.builder_settings,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.builder_settings = dialog.values
            self._save_settings()
            self._save_project_settings()
            self._refresh_settings_summary()
            status = check_clip_cache(
                replace(
                    default_config(),
                    clip_model=self.builder_settings.vision_model,
                )
            )
            self._append_log_line(
                f"[INFO] Cấu hình model: {status.summary} "
                "Tự động tải="
                f"{'bật' if self.builder_settings.auto_model_download else 'tắt'}."
            )

    def _show_guide(self) -> None:
        QMessageBox.information(
            self,
            "Hướng dẫn nhanh",
            "1. Mở Project có sẵn hoặc tạo Project mới.\n"
            "2. Thêm Voice, script.txt, footage.csv và Video Footage.\n"
            "3. Kiểm tra thời lượng Cut, Whisper và Resolution.\n"
            "4. Nhấn Phân tích để tạo Timeline và lưu Report.\n"
            "5. Khi phân tích hoàn tất, nhấn Render Video để tạo file MP4.",
        )

    def _save_settings(self) -> None:
        self.settings.setValue("project", self.project_edit.text())
        self.settings.setValue("cut_profile_version", 3)
        values = self.builder_settings
        self.settings.setValue("resolution", values.resolution)
        self.settings.setValue("workers", values.analysis_workers)
        self.settings.setValue("min_cut", values.min_cut_seconds)
        self.settings.setValue("target_cut", values.target_cut_seconds)
        self.settings.setValue("max_cut", values.max_cut_seconds)
        self.settings.setValue(
            "minimum_video_minutes", values.minimum_video_minutes
        )
        self.settings.setValue(
            "skip_whisper", values.skip_whisper
        )
        self.settings.setValue(
            "auto_model_download", values.auto_model_download
        )
        self.settings.setValue("vision_model", values.vision_model)
        self.settings.setValue(
            "capcut/template_dir", values.capcut_template_dir
        )
        self.settings.setValue(
            "capcut/drafts_root", values.capcut_drafts_root
        )
        self.settings.setValue(
            "capcut/hook_music", values.capcut_hook_music
        )
        self.settings.setValue(
            "capcut/hook_volume_db", values.capcut_hook_volume_db
        )
        self.settings.setValue(
            "capcut/body_music",
            json.dumps(list(values.capcut_body_music), ensure_ascii=False),
        )
        self.settings.setValue("music_dir", values.music_dir)
        self.settings.setValue("music_cue_sheet", values.music_cue_sheet)
        self.settings.setValue("capcut_use_main_music", values.capcut_use_main_music)

    def _restore_settings(self) -> None:
        project = self.settings.value("project", "", type=str)
        if project:
            self.project_edit.setText(project)
        defaults = BuilderUiSettings()
        profile_version = self.settings.value(
            "cut_profile_version", 1, type=int
        )
        legacy_cut_values = (
            self.settings.value(
                "min_cut", defaults.min_cut_seconds, type=float
            ),
            self.settings.value(
                "target_cut", defaults.target_cut_seconds, type=float
            ),
            self.settings.value(
                "max_cut", defaults.max_cut_seconds, type=float
            ),
        )
        if profile_version < 3:
            legacy_cut_values = (3.0, 4.0, 5.0)
        body_music_settings = []
        try:
            body_music_settings = json.loads(
                self.settings.value("capcut/body_music", "[]", type=str)
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            body_music_settings = []
        if not isinstance(body_music_settings, list):
            body_music_settings = []
        self.builder_settings = BuilderUiSettings(
            resolution=self.settings.value(
                "resolution", defaults.resolution, type=str
            ),
            analysis_workers=self.settings.value(
                "workers", defaults.analysis_workers, type=int
            ),
            min_cut_seconds=legacy_cut_values[0],
            target_cut_seconds=legacy_cut_values[1],
            max_cut_seconds=legacy_cut_values[2],
            minimum_video_minutes=self.settings.value(
                "minimum_video_minutes",
                defaults.minimum_video_minutes,
                type=float,
            ),
            skip_whisper=self.settings.value(
                "skip_whisper", defaults.skip_whisper, type=bool
            ),
            auto_model_download=self.settings.value(
                "auto_model_download",
                defaults.auto_model_download,
                type=bool,
            ),
            vision_model=self.settings.value(
                "vision_model", defaults.vision_model, type=str
            ),
            capcut_template_dir=self.settings.value(
                "capcut/template_dir",
                defaults.capcut_template_dir,
                type=str,
            ),
            capcut_drafts_root=self.settings.value(
                "capcut/drafts_root",
                defaults.capcut_drafts_root,
                type=str,
            ),
            capcut_hook_music=self.settings.value(
                "capcut/hook_music",
                defaults.capcut_hook_music,
                type=str,
            ),
            capcut_hook_volume_db=self.settings.value(
                "capcut/hook_volume_db",
                defaults.capcut_hook_volume_db,
                type=float,
            ),
            capcut_body_music=tuple(
                item for item in body_music_settings if isinstance(item, dict)
            ),
            music_dir=self.settings.value(
                "music_dir", defaults.music_dir, type=str
            ),
            music_cue_sheet=self.settings.value(
                "music_cue_sheet", defaults.music_cue_sheet, type=str
            ),
            capcut_use_main_music=self.settings.value(
                "capcut_use_main_music", defaults.capcut_use_main_music, type=bool
            ),
        )
        self._load_project_settings()
        self._refresh_settings_summary()

    def _refresh_settings_summary(self) -> None:
        if not hasattr(self, "pipeline_config_label"):
            return
        values = self.builder_settings
        whisper = "Không dùng Whisper" if values.skip_whisper else "Whisper"
        model_label = next(
            (
                label
                for label, model_id in VISION_MODELS.items()
                if model_id == values.vision_model
            ),
            values.vision_model,
        )
        self.pipeline_config_label.setText(
            f"{values.resolution}  •  "
            f"{values.min_cut_seconds:g}/{values.target_cut_seconds:g}/"
            f"{values.max_cut_seconds:g}s  •  "
            f"min {values.minimum_video_minutes:g}m  •  "
            f"{values.analysis_workers} Worker  •  {whisper}  •  "
            f"{model_label}"
        )
        self._refresh_stage_descriptions()

    def _stage_description(self, index: int) -> str:
        if index == 2:
            values = self.builder_settings
            return (
                "Chia lời thoại thành các Cut "
                f"{values.min_cut_seconds:g}–"
                f"{values.max_cut_seconds:g} giây"
            )
        return PIPELINE_STAGES[index][1]

    def _refresh_stage_descriptions(self) -> None:
        if not hasattr(self, "stage_table"):
            return
        for row in range(len(PIPELINE_STAGES)):
            item = self.stage_table.item(row, 1)
            if item is None:
                item = QTableWidgetItem()
                self.stage_table.setItem(row, 1, item)
            code = PIPELINE_STAGES[row][0]
            description = self._stage_description(row)
            item.setText(f"{code}  ·  {description}")
            item.setToolTip(description)

    def closeEvent(self, event) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self,
                "Pipeline đang chạy",
                "Dừng Pipeline và đóng ứng dụng?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.process.kill()
            self.process.waitForFinished(2000)
        self._save_settings()
        event.accept()
