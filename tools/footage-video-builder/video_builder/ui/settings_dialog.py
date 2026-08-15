"""Model and runtime configuration dialog."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import imageio_ffmpeg
from PySide6.QtCore import QSize, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import PipelineConfig, VISION_MODELS
from ..model_manager import (
    ModelCacheStatus,
    check_clip_cache,
    download_clip_cache,
)
from .theme import MUTED_LABEL_STYLE


@dataclass(frozen=True)
class BuilderUiSettings:
    resolution: str = "1080p"
    analysis_workers: int = min(4, max(1, os.cpu_count() or 1))
    min_cut_seconds: float = 3.0
    target_cut_seconds: float = 4.0
    max_cut_seconds: float = 5.0
    minimum_video_minutes: float = 25.0
    skip_whisper: bool = False
    auto_model_download: bool = True
    vision_model: str = VISION_MODELS["CLIP ViT-B/32"]
    capcut_template_dir: str = ""
    capcut_drafts_root: str = ""
    capcut_hook_music: str = ""
    capcut_hook_volume_db: float = -17.0
    capcut_body_music: tuple[dict, ...] = ()
    # --- NEW FIELDS ---
    music_dir: str = ""
    music_cue_sheet: str = ""
    capcut_use_main_music: bool = False
    caption_max_lines: int = 4
    caption_max_characters_per_line: int = 14


class ModelDownloadWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, config: PipelineConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config

    def run(self) -> None:
        try:
            self.completed.emit(download_clip_cache(self.config))
        except Exception as exc:
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: PipelineConfig,
        settings: BuilderUiSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.worker: ModelDownloadWorker | None = None
        self.setWindowTitle("Cấu hình Footage Video Builder")
        self.setMinimumSize(820, 560)
        self.resize(860, 620)
        self.setModal(True)
        self._build_ui(settings)
        self.check_configuration()

    @property
    def values(self) -> BuilderUiSettings:
        return BuilderUiSettings(
            resolution=self.resolution_combo.currentText(),
            analysis_workers=self.workers_spin.value(),
            min_cut_seconds=self.min_cut_spin.value(),
            target_cut_seconds=self.target_cut_spin.value(),
            max_cut_seconds=self.max_cut_spin.value(),
            minimum_video_minutes=self.minimum_video_spin.value(),
            skip_whisper=self.skip_whisper_check.isChecked(),
            auto_model_download=self.auto_download_check.isChecked(),
            vision_model=self.vision_model_combo.currentData(),
            capcut_template_dir=self._selected_template_path(),
            capcut_drafts_root=self.capcut_drafts_edit.text().strip(),
            capcut_hook_music=self.capcut_hook_music_edit.text().strip(),
            capcut_hook_volume_db=self.capcut_hook_volume_spin.value(),
            capcut_body_music=tuple(self._body_music_rows()),
            # --- NEW FIELDS ---
            music_dir=self.music_dir_edit.text().strip(),
            music_cue_sheet=self.music_cue_sheet_edit.text().strip(),
            capcut_use_main_music=self.capcut_use_main_music_check.isChecked(),
            caption_max_lines=self.caption_max_lines_spin.value(),
            caption_max_characters_per_line=(
                self.caption_max_characters_spin.value()
            ),
        )

    def _build_ui(self, settings: BuilderUiSettings) -> None:
        self.setStyleSheet(self._dialog_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QFrame()
        body.setObjectName("SettingsBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("SettingsNav")
        self.nav_list.setFixedWidth(200)
        self.nav_list.setSpacing(6)
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        body_layout.addWidget(self.nav_list)

        self.pages = QStackedWidget()
        self.pages.setObjectName("SettingsPages")
        body_layout.addWidget(self.pages, 1)
        layout.addWidget(body, 1)

        self._add_page("🎬  Video", self._build_video_page(settings))
        self._add_page("🎵  Nhạc nền", self._build_general_music_page(settings))
        self._add_page("✂  CapCut", self._build_capcut_page(settings))
        self._add_page("🧠  AI Model", self._build_model_page(settings))
        self._add_page("⚙  Runtime", self._build_runtime_page())
        self.nav_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav_list.setCurrentRow(0)

        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 10, 12, 10)
        footer_layout.addStretch(1)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        ).setText("Lưu")
        self.button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        ).setText("Hủy")
        footer_layout.addWidget(self.button_box)
        layout.addWidget(footer)
        self._refresh_model_help()

    def _add_page(self, label: str, page: QWidget) -> None:
        item = QListWidgetItem(label)
        item.setSizeHint(QSize(172, 46))
        self.nav_list.addItem(item)
        self.pages.addWidget(page)

    def _icon_button(
        self,
        icon: QStyle.StandardPixmap,
        tooltip: str,
        accessible_name: str,
    ) -> QPushButton:
        button = QPushButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(36, 34)
        button.setToolTip(tooltip)
        button.setAccessibleName(accessible_name)
        return button

    def _page(self, title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("SettingsTitle")
        layout.addWidget(heading)
        if subtitle:
            description = QLabel(subtitle)
            description.setWordWrap(True)
            description.setStyleSheet(MUTED_LABEL_STYLE)
            layout.addWidget(description)
        return page, layout

    def _build_video_page(self, settings: BuilderUiSettings) -> QWidget:
        page, layout = self._page(
            "Video và Timeline",
            "Cấu hình chất lượng video, số worker phân tích và độ dài cut.",
        )
        group = QGroupBox("Video Builder")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["1080p", "720p"])
        self.resolution_combo.setCurrentText(settings.resolution)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, max(1, os.cpu_count() or 1))
        self.workers_spin.setValue(settings.analysis_workers)
        self.min_cut_spin = self._duration_spin(settings.min_cut_seconds)
        self.target_cut_spin = self._duration_spin(settings.target_cut_seconds)
        self.max_cut_spin = self._duration_spin(settings.max_cut_seconds)
        self.minimum_video_spin = QDoubleSpinBox()
        self.minimum_video_spin.setRange(0.0, 180.0)
        self.minimum_video_spin.setDecimals(1)
        self.minimum_video_spin.setSingleStep(1.0)
        self.minimum_video_spin.setSuffix(" phút")
        self.minimum_video_spin.setSpecialValueText("Tắt")
        self.minimum_video_spin.setValue(settings.minimum_video_minutes)
        self.minimum_video_spin.setToolTip(
            "Nếu narration ngắn hơn, Builder thêm outro thiên nhiên, tính phần "
            "thiếu vào coverage và kéo nhạc. Audio đủ hoặc dài hơn sẽ giữ nguyên."
        )
        self.skip_whisper_check = QCheckBox(
            "Bỏ qua Whisper (ước tính Timing)"
        )
        self.skip_whisper_check.setChecked(settings.skip_whisper)

        grid.addWidget(QLabel("Resolution"), 0, 0)
        grid.addWidget(self.resolution_combo, 0, 1)
        grid.addWidget(QLabel("Worker phân tích"), 0, 2)
        grid.addWidget(self.workers_spin, 0, 3)
        grid.addWidget(QLabel("Cut tối thiểu"), 1, 0)
        grid.addWidget(self.min_cut_spin, 1, 1)
        grid.addWidget(QLabel("Cut mục tiêu"), 1, 2)
        grid.addWidget(self.target_cut_spin, 1, 3)
        grid.addWidget(QLabel("Cut tối đa"), 2, 0)
        grid.addWidget(self.max_cut_spin, 2, 1)
        grid.addWidget(QLabel("Video tối thiểu"), 2, 2)
        grid.addWidget(self.minimum_video_spin, 2, 3)
        grid.addWidget(self.skip_whisper_check, 3, 0, 1, 4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _build_general_music_page(self, settings: BuilderUiSettings) -> QWidget:
        page, layout = self._page(
            "Nhạc nền chung",
            "Cấu hình nhạc nền mặc định cho Render Video và tùy chọn cho CapCut.",
        )
        group = QGroupBox("Nhạc nền chung (Render & CapCut)")
        form = QFormLayout(group)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.music_dir_edit = QLineEdit(settings.music_dir)
        self.music_dir_edit.setPlaceholderText("Thư mục chứa các file nhạc nền")
        self.music_dir_btn = QPushButton("Chọn...")
        self.music_dir_btn.clicked.connect(
            lambda: self._choose_directory(self.music_dir_edit)
        )
        music_dir_row = QHBoxLayout()
        music_dir_row.addWidget(self.music_dir_edit, 1)
        music_dir_row.addWidget(self.music_dir_btn)

        self.music_cue_sheet_edit = QLineEdit(settings.music_cue_sheet)
        self.music_cue_sheet_edit.setPlaceholderText("File CSV cue sheet nhạc nền")
        self.music_cue_sheet_btn = QPushButton("Chọn...")
        self.music_cue_sheet_btn.clicked.connect(
            lambda: self._choose_file(
                self.music_cue_sheet_edit,
                "Chọn file Cue Sheet nhạc nền",
                "CSV files (*.csv);;All files (*)",
            )
        )
        music_cue_sheet_row = QHBoxLayout()
        music_cue_sheet_row.addWidget(self.music_cue_sheet_edit, 1)
        music_cue_sheet_row.addWidget(self.music_cue_sheet_btn)

        form.addRow("Thư mục nhạc", music_dir_row)
        form.addRow("Cue Sheet nhạc", music_cue_sheet_row)

        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _toggle_capcut_music_options(self, checked: bool) -> None:
        # Ẩn/hiện các điều khiển nhạc nền CapCut chuyên biệt
        self.capcut_hook_music_edit.setVisible(not checked)
        self.capcut_hook_music_btn.setVisible(not checked)
        self.capcut_hook_volume_spin.setVisible(not checked)
        self.capcut_body_music_table.setVisible(not checked)
        self.capcut_add_music_btn.setVisible(not checked)
        self.capcut_remove_music_btn.setVisible(not checked)
        self.capcut_music_up_btn.setVisible(not checked)
        self.capcut_music_down_btn.setVisible(not checked)

    def _build_capcut_page(self, settings: BuilderUiSettings) -> QWidget:
        page, layout = self._page(
            "CapCut Draft",
            "Chọn template draft và thư mục nơi app sẽ tạo draft CapCut mới.",
        )
        group = QGroupBox("Draft Adapter")
        form = QFormLayout(group)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.capcut_template_combo = QComboBox()
        self.capcut_template_combo.setMinimumWidth(320)
        self.capcut_import_btn = self._icon_button(
            QStyle.StandardPixmap.SP_DialogOpenButton,
            "Import template Draft CapCut",
            "Import template",
        )
        self.capcut_import_btn.clicked.connect(self._import_capcut_template)
        self.capcut_delete_btn = self._icon_button(
            QStyle.StandardPixmap.SP_TrashIcon,
            "Xóa template đang chọn khỏi thư viện app",
            "Xóa template",
        )
        self.capcut_delete_btn.setObjectName("DangerButton")
        self.capcut_delete_btn.clicked.connect(self._delete_capcut_template)
        self.capcut_apply_btn = self._icon_button(
            QStyle.StandardPixmap.SP_DialogApplyButton,
            "Lưu template đang chọn làm mặc định",
            "Apply mặc định",
        )
        self.capcut_apply_btn.setObjectName("PrimaryButton")
        self.capcut_apply_btn.clicked.connect(self.accept)
        template_row = QHBoxLayout()
        template_row.addWidget(self.capcut_template_combo, 1)
        template_row.addWidget(self.capcut_import_btn)
        template_row.addWidget(self.capcut_delete_btn)
        template_row.addWidget(self.capcut_apply_btn)

        self.capcut_drafts_edit = QLineEdit(settings.capcut_drafts_root)
        self.capcut_drafts_edit.setPlaceholderText(
            "Thư mục chứa các Draft CapCut sẽ tạo"
        )
        self.capcut_drafts_btn = QPushButton("Chọn...")
        self.capcut_drafts_btn.clicked.connect(
            lambda: self._choose_directory(self.capcut_drafts_edit)
        )
        drafts_row = QHBoxLayout()
        drafts_row.addWidget(self.capcut_drafts_edit, 1)
        drafts_row.addWidget(self.capcut_drafts_btn)

        self.caption_max_lines_spin = QSpinBox()
        self.caption_max_lines_spin.setRange(1, 8)
        self.caption_max_lines_spin.setValue(settings.caption_max_lines)
        self.caption_max_lines_spin.setToolTip(
            "Caption vượt giới hạn sẽ được tách thành cue tiếp theo."
        )
        self.caption_max_characters_spin = QSpinBox()
        self.caption_max_characters_spin.setRange(1, 99)
        self.caption_max_characters_spin.setMinimumWidth(80)
        self.caption_max_characters_spin.setKeyboardTracking(False)
        self.caption_max_characters_spin.setValue(
            settings.caption_max_characters_per_line
        )
        self.caption_max_characters_spin.setToolTip(
            "Số ký tự tối đa trên mỗi dòng; chỉ xuống dòng tại khoảng trắng."
        )
        caption_layout_row = QHBoxLayout()
        caption_layout_row.addWidget(QLabel("Max lines"))
        caption_layout_row.addWidget(self.caption_max_lines_spin)
        caption_layout_row.addSpacing(16)
        caption_layout_row.addWidget(QLabel("Max characters / line"))
        caption_layout_row.addWidget(self.caption_max_characters_spin)
        caption_layout_row.addStretch(1)

        self.capcut_use_main_music_check = QCheckBox(
            "Sử dụng nhạc nền chung của Project cho CapCut"
        )
        self.capcut_use_main_music_check.setChecked(settings.capcut_use_main_music)
        self.capcut_use_main_music_check.toggled.connect(
            self._toggle_capcut_music_options
        )

        form.addRow("Template mặc định", template_row)
        self.capcut_hook_music_edit = QLineEdit(settings.capcut_hook_music)
        self.capcut_hook_music_edit.setPlaceholderText("Music file for Hook")
        self.capcut_hook_music_btn = QPushButton("Choose...")
        self.capcut_hook_music_btn.clicked.connect(
            lambda: self._choose_audio_file(self.capcut_hook_music_edit)
        )
        hook_music_row = QHBoxLayout()
        hook_music_row.addWidget(self.capcut_hook_music_edit, 1)
        hook_music_row.addWidget(self.capcut_hook_music_btn)
        self.capcut_hook_volume_spin = QDoubleSpinBox()
        self.capcut_hook_volume_spin.setRange(-60.0, 6.0)
        self.capcut_hook_volume_spin.setSingleStep(1.0)
        self.capcut_hook_volume_spin.setDecimals(1)
        self.capcut_hook_volume_spin.setSuffix(" dB")
        self.capcut_hook_volume_spin.setValue(settings.capcut_hook_volume_db)
        hook_music_row.addWidget(self.capcut_hook_volume_spin)

        self.capcut_body_music_table = QTableWidget(0, 3)
        self.capcut_body_music_table.setHorizontalHeaderLabels(
            ["Body music", "Volume", "Repeat"]
        )
        self.capcut_body_music_table.verticalHeader().setVisible(False)
        self.capcut_body_music_table.setColumnWidth(1, 100)
        self.capcut_body_music_table.setColumnWidth(2, 80)
        self.capcut_body_music_table.horizontalHeader().setStretchLastSection(False)
        self.capcut_body_music_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.capcut_body_music_table.setMinimumHeight(130)
        self.capcut_body_music_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.capcut_body_music_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.capcut_add_music_btn = QPushButton("Add...")
        self.capcut_add_music_btn.clicked.connect(self._add_body_music)
        self.capcut_remove_music_btn = QPushButton("Remove")
        self.capcut_remove_music_btn.clicked.connect(self._remove_body_music)
        self.capcut_music_up_btn = QPushButton("Up")
        self.capcut_music_up_btn.clicked.connect(lambda: self._move_body_music(-1))
        self.capcut_music_down_btn = QPushButton("Down")
        self.capcut_music_down_btn.clicked.connect(lambda: self._move_body_music(1))
        body_music_buttons = QHBoxLayout()
        body_music_buttons.addWidget(self.capcut_add_music_btn)
        body_music_buttons.addWidget(self.capcut_remove_music_btn)
        body_music_buttons.addWidget(self.capcut_music_up_btn)
        body_music_buttons.addWidget(self.capcut_music_down_btn)
        body_music_buttons.addStretch(1)
        body_music_box = QVBoxLayout()
        body_music_box.addWidget(self.capcut_body_music_table)
        body_music_box.addLayout(body_music_buttons)

        form.addRow("Draft folder", drafts_row)
        form.addRow("Caption layout", caption_layout_row)
        form.addRow("", self.capcut_use_main_music_check)
        form.addRow("Hook music", hook_music_row)
        form.addRow("Body music", body_music_box)
        note = QLabel(
            "Import template một lần, sau đó chọn template trong danh sách "
            "và bấm Lưu để dùng làm mặc định."
        )
        note.setWordWrap(True)
        note.setStyleSheet(MUTED_LABEL_STYLE)
        layout.addWidget(group)
        layout.addWidget(note)
        self.template_path_label = QLabel()
        self.template_path_label.setWordWrap(True)
        self.template_path_label.setStyleSheet(MUTED_LABEL_STYLE)
        layout.addWidget(self.template_path_label)
        self._populate_template_combo(settings.capcut_template_dir)
        self._populate_body_music_table(settings.capcut_body_music)
        self.capcut_template_combo.currentIndexChanged.connect(
            self._refresh_template_path_label
        )
        self._refresh_template_path_label()
        self._toggle_capcut_music_options(settings.capcut_use_main_music)
        layout.addStretch(1)
        return page

    def _build_model_page(self, settings: BuilderUiSettings) -> QWidget:
        page, layout = self._page(
            "AI Model",
            "Chọn model vision-language và kiểm tra cache local.",
        )
        group = QGroupBox("Model Vision-Language")
        group_layout = QVBoxLayout(group)
        form = QFormLayout()

        self.vision_model_combo = QComboBox()
        for label, model_id in VISION_MODELS.items():
            self.vision_model_combo.addItem(label, model_id)
        selected_index = self.vision_model_combo.findData(
            settings.vision_model
        )
        self.vision_model_combo.setCurrentIndex(max(0, selected_index))
        self.vision_model_combo.currentIndexChanged.connect(
            self._vision_model_changed
        )

        self.cache_path_label = QLabel(str(self.config.clip_cache_dir))
        self.cache_path_label.setWordWrap(True)
        self.cache_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.model_status_label = QLabel()
        self.model_status_label.setWordWrap(True)
        form.addRow("Model", self.vision_model_combo)
        form.addRow("Cache", self.cache_path_label)
        form.addRow("Trạng thái", self.model_status_label)
        group_layout.addLayout(form)

        self.model_help_label = QLabel()
        self.model_help_label.setWordWrap(True)
        self.model_help_label.setStyleSheet(MUTED_LABEL_STYLE)
        group_layout.addWidget(self.model_help_label)

        self.auto_download_check = QCheckBox(
            "Tự động tải model khi Cache bị thiếu hoặc chưa hoàn chỉnh"
        )
        self.auto_download_check.setChecked(settings.auto_model_download)
        group_layout.addWidget(self.auto_download_check)

        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setTextVisible(False)
        self.download_progress.hide()
        group_layout.addWidget(self.download_progress)

        actions = QHBoxLayout()
        self.check_btn = QPushButton("✓ Kiểm tra cấu hình")
        self.check_btn.clicked.connect(self.check_configuration)
        self.download_btn = QPushButton("↓ Tải model ngay")
        self.download_btn.setObjectName("PrimaryButton")
        self.download_btn.clicked.connect(self._download_model)
        actions.addWidget(self.check_btn)
        actions.addWidget(self.download_btn)
        actions.addStretch(1)
        group_layout.addLayout(actions)
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _build_runtime_page(self) -> QWidget:
        page, layout = self._page(
            "Runtime",
            "Kiểm tra Python, FFmpeg và các thư viện AI cần thiết.",
        )
        group = QGroupBox("Kiểm tra cấu hình")
        form = QFormLayout(group)
        self.python_status = QLabel()
        self.ffmpeg_status = QLabel()
        self.torch_status = QLabel()
        self.whisper_status = QLabel()
        self.sentencepiece_status = QLabel()
        form.addRow("Python", self.python_status)
        form.addRow("FFmpeg", self.ffmpeg_status)
        form.addRow("Thiết bị Torch", self.torch_status)
        form.addRow("Whisper", self.whisper_status)
        form.addRow("SentencePiece", self.sentencepiece_status)
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _selected_config(self) -> PipelineConfig:
        return replace(
            self.config,
            clip_model=str(self.vision_model_combo.currentData()),
        )

    def _vision_model_changed(self) -> None:
        selected = self.vision_model_combo.currentData()
        self._refresh_model_help()
        self.model_status_label.setText(
            f"Đang kiểm tra Cache cho {selected}..."
        )
        self.check_configuration()

    def _refresh_model_help(self) -> None:
        if not hasattr(self, "model_help_label"):
            return
        selected = str(self.vision_model_combo.currentData())
        if "siglip2" in selected.lower():
            text = (
                "Khuyến nghị khi ưu tiên chất lượng: Semantic retrieval và "
                "đa ngôn ngữ tốt hơn, nhưng phân tích chậm và dùng nhiều "
                "RAM/VRAM hơn CLIP."
            )
        else:
            text = (
                "Khuyến nghị khi ưu tiên tốc độ: nhẹ, chạy CPU tốt và tương "
                "thích Project cũ; độ chính xác Semantic thấp hơn SigLIP 2."
            )
        self.model_help_label.setText(text)

    def _duration_spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.5, 30.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSuffix(" s")
        spin.setValue(value)
        return spin

    def _choose_directory(self, edit: QLineEdit) -> None:
        current = edit.text().strip()
        start = current if current else str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục", start)
        if path:
            edit.setText(path)

    def _choose_audio_file(self, edit: QLineEdit) -> None:
        current = edit.text().strip()
        start = str(Path(current).parent) if current else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose music file",
            start,
            "Audio files (*.mp3 *.wav *.m4a *.aac *.flac);;All files (*)",
        )
        if path:
            edit.setText(path)

    def _choose_file(
        self, edit: QLineEdit, title: str, file_filter: str
    ) -> None:
        current = edit.text().strip()
        start = str(Path(current).parent) if current else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, title, start, file_filter)
        if path:
            edit.setText(path)


    def _body_music_rows(self) -> list[dict]:
        rows = []
        for row_index in range(self.capcut_body_music_table.rowCount()):
            path_item = self.capcut_body_music_table.item(row_index, 0)
            volume_spin = self.capcut_body_music_table.cellWidget(row_index, 1)
            repeat_item = self.capcut_body_music_table.item(row_index, 2)
            path = path_item.data(Qt.ItemDataRole.UserRole) if path_item else ""
            if not path:
                continue
            rows.append(
                {
                    "path": str(path),
                    "volume_db": (
                        float(volume_spin.value())
                        if isinstance(volume_spin, QDoubleSpinBox)
                        else -20.0
                    ),
                    "repeat": (
                        repeat_item.checkState() == Qt.CheckState.Checked
                        if repeat_item is not None
                        else False
                    ),
                }
            )
        return rows

    def _append_body_music_row(
        self,
        path: str,
        repeat: bool = False,
        volume_db: float = -20.0,
    ) -> None:
        row = self.capcut_body_music_table.rowCount()
        self.capcut_body_music_table.insertRow(row)
        path_item = QTableWidgetItem(Path(path).name)
        path_item.setData(Qt.ItemDataRole.UserRole, path)
        path_item.setToolTip(path)
        path_item.setFlags(path_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        volume_spin = QDoubleSpinBox()
        volume_spin.setRange(-60.0, 6.0)
        volume_spin.setSingleStep(1.0)
        volume_spin.setDecimals(1)
        volume_spin.setSuffix(" dB")
        volume_spin.setValue(volume_db)
        repeat_item = QTableWidgetItem()
        repeat_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        repeat_item.setCheckState(
            Qt.CheckState.Checked if repeat else Qt.CheckState.Unchecked
        )
        self.capcut_body_music_table.setItem(row, 0, path_item)
        self.capcut_body_music_table.setCellWidget(row, 1, volume_spin)
        self.capcut_body_music_table.setItem(row, 2, repeat_item)

    def _populate_body_music_table(self, rows: tuple[dict, ...]) -> None:
        self.capcut_body_music_table.setRowCount(0)
        for row in rows:
            path = str(row.get("path", "")).strip()
            if path:
                self._append_body_music_row(
                    path,
                    bool(row.get("repeat", False)),
                    float(row.get("volume_db", -20.0)),
                )

    def _add_body_music(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add body music",
            str(Path.home()),
            "Audio files (*.mp3 *.wav *.m4a *.aac *.flac);;All files (*)",
        )
        for path in paths:
            self._append_body_music_row(path)

    def _selected_body_music_row(self) -> int:
        selected = self.capcut_body_music_table.selectionModel().selectedRows()
        return selected[0].row() if selected else -1

    def _remove_body_music(self) -> None:
        row = self._selected_body_music_row()
        if row >= 0:
            self.capcut_body_music_table.removeRow(row)

    def _move_body_music(self, offset: int) -> None:
        row = self._selected_body_music_row()
        target = row + offset
        if row < 0 or target < 0 or target >= self.capcut_body_music_table.rowCount():
            return
        rows = self._body_music_rows()
        rows[row], rows[target] = rows[target], rows[row]
        self._populate_body_music_table(tuple(rows))
        self.capcut_body_music_table.selectRow(target)

    def _template_library_dir(self) -> Path:
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / ".footage-video-builder"
        return root / "AronVideo" / "FootageVideoBuilder" / "capcut_templates"

    def _is_template_in_library(self, path: Path) -> bool:
        library = self._template_library_dir().resolve()
        try:
            path.resolve().relative_to(library)
            return True
        except ValueError:
            return False

    def _is_deletable_template(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            library = self._template_library_dir().resolve()
        except OSError:
            return False
        return resolved.is_dir() and resolved.parent == library

    def _copy_template_to_library(self, source_path: Path) -> Path:
        source_path = source_path.resolve()
        library = self._template_library_dir()
        library.mkdir(parents=True, exist_ok=True)
        if self._is_template_in_library(source_path):
            return source_path
        safe_name = re.sub(r'[<>:"/\\|?*\s]+', "-", source_path.name).strip(" .-")
        if not safe_name:
            safe_name = "capcut-template"
        target = library / safe_name
        suffix = 2
        while target.exists():
            target = library / f"{safe_name}-{suffix}"
            suffix += 1
        shutil.copytree(source_path, target)
        return target.resolve()

    def _ensure_selected_template_in_library(self) -> str:
        template = self._selected_template_path()
        if not template:
            return ""
        source_path = Path(template).resolve()
        if not source_path.is_dir():
            return template
        if self._is_template_in_library(source_path):
            return str(source_path)
        target = self._copy_template_to_library(source_path)
        self._populate_template_combo(str(target))
        self._refresh_template_path_label()
        return str(target)

    def _selected_template_path(self) -> str:
        return str(self.capcut_template_combo.currentData() or "").strip()

    def _add_template_option(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_dir():
            return
        if not (resolved / "draft_content.json").is_file():
            return
        existing = {
            str(self.capcut_template_combo.itemData(index))
            for index in range(self.capcut_template_combo.count())
        }
        if str(resolved) in existing:
            return
        self.capcut_template_combo.addItem(resolved.name, str(resolved))

    def _populate_template_combo(self, selected: str = "") -> None:
        self.capcut_template_combo.clear()
        selected_path = Path(selected).resolve() if selected else None
        if selected_path is not None:
            self._add_template_option(selected_path)
        library = self._template_library_dir()
        if library.is_dir():
            for candidate in sorted(library.iterdir(), key=lambda item: item.name.lower()):
                self._add_template_option(candidate)
        if self.capcut_template_combo.count() == 0:
            self.capcut_template_combo.addItem("Chưa import template", "")
        if selected_path is not None:
            index = self.capcut_template_combo.findData(str(selected_path))
            if index >= 0:
                self.capcut_template_combo.setCurrentIndex(index)

    def _refresh_template_path_label(self) -> None:
        path = self._selected_template_path()
        if path:
            self.template_path_label.setText(f"Template đang chọn:\n{path}")
        else:
            self.template_path_label.setText(
                "Chưa có template. Bấm Import template để thêm Draft CapCut mẫu."
            )

        if hasattr(self, "capcut_delete_btn"):
            self.capcut_delete_btn.setEnabled(
                bool(path) and self._is_deletable_template(Path(path))
            )

    def _import_capcut_template(self) -> None:
        source = QFileDialog.getExistingDirectory(
            self,
            "Import template Draft CapCut",
            str(Path.home()),
        )
        if not source:
            return
        source_path = Path(source).resolve()
        if not (source_path / "draft_content.json").is_file():
            QMessageBox.warning(
                self,
                "Template không hợp lệ",
                f"Thư mục này thiếu draft_content.json:\n{source_path}",
            )
            return
        try:
            target = self._copy_template_to_library(source_path)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Không thể import template",
                f"Không thể copy template:\n{exc}",
            )
            return
        self._populate_template_combo(str(target))
        self._refresh_template_path_label()

    def _delete_capcut_template(self) -> None:
        template = self._selected_template_path()
        if not template:
            QMessageBox.information(
                self,
                "Chua co template",
                "Chua co template CapCut nao de xoa.",
            )
            return
        template_path = Path(template)
        if not self._is_deletable_template(template_path):
            QMessageBox.warning(
                self,
                "Khong the xoa template",
                "Chi co the xoa template da import vao thu vien cua app.\n"
                f"Template dang chon:\n{template_path}",
            )
            return
        answer = QMessageBox.question(
            self,
            "Xoa template CapCut",
            "Xoa template CapCut nay khoi thu vien cua app?\n\n"
            f"{template_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(template_path)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Khong the xoa template",
                f"Khong the xoa template:\n{exc}",
            )
            return
        self._populate_template_combo("")
        self._refresh_template_path_label()

    def accept(self) -> None:
        try:
            template = self._ensure_selected_template_in_library()
        except OSError as exc:
            QMessageBox.critical(
                self,
                "KhÃ´ng thá»ƒ copy template",
                f"KhÃ´ng thá»ƒ clone template vÃ o thÆ° viá»‡n app:\n{exc}",
            )
            return
        if template and not Path(template).is_dir():
            QMessageBox.warning(
                self,
                "Đường dẫn không hợp lệ",
                f"Template CapCut không tồn tại:\n{template}",
            )
            return
        draft_root = self.capcut_drafts_edit.text().strip()
        if draft_root and not Path(draft_root).is_dir():
            QMessageBox.warning(
                self,
                "Đường dẫn không hợp lệ",
                f"Draft folder CapCut không tồn tại:\n{draft_root}",
            )
            return
        hook_music = self.capcut_hook_music_edit.text().strip()
        if hook_music and not Path(hook_music).is_file():
            QMessageBox.warning(
                self,
                "Music file is invalid",
                f"Hook music does not exist:\n{hook_music}",
            )
            return
        missing_music = [
            row["path"]
            for row in self._body_music_rows()
            if not Path(str(row["path"])).is_file()
        ]
        if missing_music:
            QMessageBox.warning(
                self,
                "Music file is invalid",
                "Body music does not exist:\n" + "\n".join(missing_music),
            )
            return
        if not (
            self.min_cut_spin.value()
            <= self.target_cut_spin.value()
            <= self.max_cut_spin.value()
        ):
            QMessageBox.warning(
                self,
                "Cấu hình không hợp lệ",
                "Thời lượng Cut phải thỏa mãn Min ≤ Target ≤ Max.",
            )
            return
        super().accept()

    def check_configuration(self) -> ModelCacheStatus:
        self.python_status.setText(
            self._status_html(True, sys.version.split()[0])
        )
        ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
        self.ffmpeg_status.setText(
            self._status_html(
                ffmpeg_path.is_file(),
                str(ffmpeg_path) if ffmpeg_path.is_file()
                else "Không tìm thấy",
            )
        )
        try:
            import torch

            device = (
                f"CUDA - {torch.cuda.get_device_name(0)}"
                if torch.cuda.is_available()
                else "CPU"
            )
            self.torch_status.setText(self._status_html(True, device))
        except ImportError:
            self.torch_status.setText(
                self._status_html(False, "Chưa cài đặt torch")
            )
        whisper_ready = importlib.util.find_spec("whisper") is not None
        self.whisper_status.setText(
            self._status_html(
                whisper_ready,
                "Đã cài đặt"
                if whisper_ready else "Chưa cài đặt openai-whisper",
            )
        )
        sentencepiece_ready = (
            importlib.util.find_spec("sentencepiece") is not None
        )
        self.sentencepiece_status.setText(
            self._status_html(
                sentencepiece_ready,
                "Đã cài đặt" if sentencepiece_ready else "Chưa cài đặt",
            )
        )
        status = check_clip_cache(self._selected_config())
        self.model_status_label.setText(
            self._status_html(status.ready, status.summary)
        )
        self.download_btn.setEnabled(not status.ready)
        return status

    def _download_model(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.download_progress.show()
        self.download_progress.setRange(0, 0)
        self.download_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.button_box.setEnabled(False)
        self.model_status_label.setText(
            self._status_html(True, "Đang tải model từ Hugging Face...")
        )
        self.worker = ModelDownloadWorker(self._selected_config(), self)
        self.worker.completed.connect(self._download_completed)
        self.worker.failed.connect(self._download_failed)
        self.worker.start()

    def _download_completed(self, status: ModelCacheStatus) -> None:
        self._finish_download_ui()
        self.model_status_label.setText(
            self._status_html(True, status.summary)
        )
        self.download_btn.setEnabled(False)

    def _download_failed(self, message: str) -> None:
        self._finish_download_ui()
        self.model_status_label.setText(
            self._status_html(False, "Tải model thất bại")
        )
        self.download_btn.setEnabled(True)
        QMessageBox.critical(self, "Không thể tải model", message)

    def _finish_download_ui(self) -> None:
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(100)
        self.download_progress.hide()
        self.check_btn.setEnabled(True)
        self.button_box.setEnabled(True)

    @staticmethod
    def _status_html(ready: bool, text: str) -> str:
        color = "#86efac" if ready else "#fca5a5"
        marker = "●" if ready else "●"
        return f'<span style="color:{color}; font-weight:700">{marker}</span> {text}'

    @staticmethod
    def _dialog_style() -> str:
        return """
        QDialog {
            background: #0e1624;
            color: #d6deee;
            font-family: "Segoe UI", "Roboto", Arial;
            font-size: 13px;
        }
        QFrame#SettingsBody {
            background: #0e1624;
        }
        QFrame#SettingsFooter {
            background: #0e1624;
            border-top: 1px solid #27364d;
        }
        QListWidget#SettingsNav {
            background: #0b1320;
            border: 0;
            border-right: 1px solid #27364d;
            padding: 12px 10px;
            outline: 0;
        }
        QListWidget#SettingsNav::item {
            color: #d6deee;
            min-height: 40px;
            padding: 8px 12px;
            border-radius: 6px;
        }
        QListWidget#SettingsNav::item:selected {
            background: #26314d;
            color: #f7f9ff;
            border-left: 3px solid #8b5cf6;
        }
        QListWidget#SettingsNav::item:hover {
            background: #18243a;
        }
        QStackedWidget#SettingsPages {
            background: #0e1624;
        }
        QLabel#SettingsTitle {
            color: #8b5cf6;
            font-size: 15px;
            font-weight: 800;
        }
        QLabel {
            background: transparent;
            color: #d6deee;
        }
        QGroupBox {
            background: #162235;
            border: 1px solid #27364d;
            border-radius: 8px;
            margin-top: 14px;
            padding: 14px 12px 12px 12px;
            color: #8b5cf6;
            font-weight: 800;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
        }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background: #0f1726;
            border: 1px solid #34445e;
            border-radius: 6px;
            color: #d6deee;
            padding: 7px;
            min-height: 18px;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border: 1px solid #7c3aed;
        }
        QPushButton {
            background: #1d2a3d;
            border: 1px solid #34445e;
            border-radius: 7px;
            color: #f7f9ff;
            padding: 8px 12px;
            font-weight: 600;
        }
        QPushButton:hover {
            background: #26364e;
        }
        QPushButton#PrimaryButton {
            background: #6d42e8;
            border: 1px solid #8b5cf6;
            font-weight: 800;
        }
        QPushButton:disabled {
            background: #243044;
            color: #6f7c91;
            border-color: #34445e;
        }
        QCheckBox {
            background: transparent;
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 17px;
            height: 17px;
            border: 1px solid #52627b;
            border-radius: 4px;
            background: #0f1726;
        }
        QCheckBox::indicator:checked {
            background: #6d42e8;
            border-color: #8b5cf6;
        }
        QProgressBar {
            background: #1b2740;
            border: 1px solid #33445f;
            border-radius: 6px;
            height: 12px;
        }
        QProgressBar::chunk {
            background: #7c3aed;
            border-radius: 5px;
        }
        """

    def reject(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(
                self,
                "Đang tải model",
                "Vui lòng đợi quá trình tải model hoàn tất.",
            )
            return
        super().reject()
