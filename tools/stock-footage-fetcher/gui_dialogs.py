"""Settings and help dialogs for Stock Footage Finder."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui_settings import GuiSettings
from gui_theme import APP_STYLE_SHEET, MUTED_LABEL_STYLE


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: GuiSettings,
        pexels_key: str,
        pixabay_key: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = replace(settings)
        self.setWindowTitle("Settings - Stock Footage Finder")
        self.setMinimumSize(720, 610)
        self.setStyleSheet(APP_STYLE_SHEET)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Cấu hình nguồn footage, API key và mức tìm kiếm. API key được lưu "
            "trong file .env cạnh ứng dụng."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(MUTED_LABEL_STYLE)
        root.addWidget(intro)

        tabs = QTabWidget()
        tabs.addTab(self._build_sources_tab(pexels_key, pixabay_key), "Nguồn & API")
        tabs.addTab(self._build_search_tab(settings), "Tìm kiếm")
        tabs.addTab(self._build_quality_tab(settings), "Chất lượng")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.recommended_btn = buttons.addButton(
            "Recommended cho DWG",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.recommended_btn.setToolTip(
            "Áp dụng cấu hình tìm footage thiên nhiên cân bằng giữa độ chính xác và số kết quả."
        )
        self.recommended_btn.clicked.connect(self._apply_dwg_recommended)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _apply_dwg_recommended(self) -> None:
        """Fill DWG-safe search defaults without saving the dialog."""
        self.pexels_check.setChecked(True)
        self.pixabay_check.setChecked(True)
        self.max_queries_spin.setValue(3)
        self.max_pages_spin.setValue(3)
        self.per_page_spin.setValue(40)
        self.workers_spin.setValue(2)
        self.clips_spin.setValue(2)
        self.pool_spin.setValue(40)
        self.shortlist_spin.setValue(12)
        self.pixabay_cap_spin.setValue(50)
        self.min_duration_spin.setValue(8.0)
        self.min_score_spin.setValue(0.16)
        self.min_width_spin.setValue(1920)
        self.min_height_spin.setValue(1080)

    def _build_sources_tab(
        self, pexels_key: str, pixabay_key: str
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        source_box = QGroupBox("Nguồn footage")
        source_layout = QVBoxLayout(source_box)
        self.pexels_check = QCheckBox("Pexels")
        self.pexels_check.setChecked(self._settings.use_pexels)
        self.pixabay_check = QCheckBox("Pixabay")
        self.pixabay_check.setChecked(self._settings.use_pixabay)
        source_layout.addWidget(self.pexels_check)
        source_layout.addWidget(self.pixabay_check)
        layout.addWidget(source_box)

        key_box = QGroupBox("API key")
        key_form = QFormLayout(key_box)
        self.pexels_key_edit = QLineEdit(pexels_key)
        self.pexels_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pexels_key_edit.setPlaceholderText("PEXELS_API_KEY")
        self.pixabay_key_edit = QLineEdit(pixabay_key)
        self.pixabay_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pixabay_key_edit.setPlaceholderText("PIXABAY_API_KEY")
        key_form.addRow("Pexels key", self.pexels_key_edit)
        key_form.addRow("Pixabay key", self.pixabay_key_edit)
        layout.addWidget(key_box)

        note = QLabel(
            "Pixabay được giới hạn mặc định 20 file mỗi project. Kết quả API "
            "được cache tối thiểu 24 giờ."
        )
        note.setWordWrap(True)
        note.setStyleSheet(MUTED_LABEL_STYLE)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_search_tab(self, settings: GuiSettings) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.max_queries_spin = self._spin(1, 5, settings.max_queries)
        self.max_pages_spin = self._spin(1, 10, settings.max_pages)
        self.per_page_spin = self._spin(3, 80, settings.per_page)
        self.workers_spin = self._spin(1, 8, settings.workers)
        self.clips_spin = self._spin(1, 4, settings.clips_per_beat)
        self.pool_spin = self._spin(4, 100, settings.candidate_pool)
        self.shortlist_spin = self._spin(1, 30, settings.shortlist)
        self.pixabay_cap_spin = self._spin(
            0, 500, settings.max_pixabay_downloads
        )

        form.addRow("Truy vấn mỗi Beat", self.max_queries_spin)
        form.addRow("Trang mỗi truy vấn", self.max_pages_spin)
        form.addRow("Kết quả mỗi trang", self.per_page_spin)
        form.addRow("Beat chạy đồng thời", self.workers_spin)
        form.addRow("Footage mỗi Beat", self.clips_spin)
        form.addRow("Ứng viên chấm AI", self.pool_spin)
        form.addRow("Shortlist chống trùng", self.shortlist_spin)
        form.addRow("Giới hạn Pixabay/project", self.pixabay_cap_spin)
        return page

    def _build_quality_tab(self, settings: GuiSettings) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.min_duration_spin = QDoubleSpinBox()
        self.min_duration_spin.setRange(1.0, 120.0)
        self.min_duration_spin.setDecimals(1)
        self.min_duration_spin.setSuffix(" giây")
        self.min_duration_spin.setValue(settings.min_duration)

        self.min_score_spin = QDoubleSpinBox()
        self.min_score_spin.setRange(-1.0, 1.0)
        self.min_score_spin.setDecimals(3)
        self.min_score_spin.setSingleStep(0.01)
        self.min_score_spin.setValue(settings.min_score)

        self.min_width_spin = self._spin(640, 7680, settings.min_width)
        self.min_height_spin = self._spin(360, 4320, settings.min_height)
        self.dry_run_check = QCheckBox("Chỉ tìm và lập kế hoạch, không tải MP4")
        self.dry_run_check.setChecked(settings.dry_run)

        form.addRow("Thời lượng tối thiểu", self.min_duration_spin)
        form.addRow("Điểm semantic tối thiểu", self.min_score_spin)
        form.addRow("Chiều rộng tối thiểu", self.min_width_spin)
        form.addRow("Chiều cao tối thiểu", self.min_height_spin)
        form.addRow("Dry run", self.dry_run_check)
        return page

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    def values(self) -> tuple[GuiSettings, str, str]:
        settings = replace(
            self._settings,
            use_pexels=self.pexels_check.isChecked(),
            use_pixabay=self.pixabay_check.isChecked(),
            max_queries=self.max_queries_spin.value(),
            max_pages=self.max_pages_spin.value(),
            per_page=self.per_page_spin.value(),
            workers=self.workers_spin.value(),
            clips_per_beat=self.clips_spin.value(),
            candidate_pool=self.pool_spin.value(),
            shortlist=self.shortlist_spin.value(),
            min_duration=self.min_duration_spin.value(),
            min_score=self.min_score_spin.value(),
            min_width=self.min_width_spin.value(),
            min_height=self.min_height_spin.value(),
            max_pixabay_downloads=self.pixabay_cap_spin.value(),
            dry_run=self.dry_run_check.isChecked(),
        )
        return (
            settings,
            self.pexels_key_edit.text().strip(),
            self.pixabay_key_edit.text().strip(),
        )

    def accept(self) -> None:
        settings, pexels, pixabay = self.values()
        if not settings.use_pexels and not settings.use_pixabay:
            QMessageBox.warning(self, "Thiếu nguồn", "Hãy bật Pexels hoặc Pixabay.")
            return
        if settings.use_pexels and not pexels:
            QMessageBox.warning(self, "Thiếu API key", "Hãy nhập Pexels API key.")
            return
        if settings.use_pixabay and not pixabay:
            QMessageBox.warning(self, "Thiếu API key", "Hãy nhập Pixabay API key.")
            return
        super().accept()


class GuideDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hướng dẫn nhanh")
        self.setMinimumSize(660, 470)
        self.setStyleSheet(APP_STYLE_SHEET)
        layout = QVBoxLayout(self)
        text = QLabel(
            "<h2>Stock Footage Finder</h2>"
            "<p><b>1.</b> Chuẩn bị project có file <code>script_beat.csv</code>.</p>"
            "<p><b>2.</b> Chọn project hoặc chọn trực tiếp CSV.</p>"
            "<p><b>3.</b> Mở Settings, bật nguồn và nhập API key.</p>"
            "<p><b>4.</b> Dùng Dry Run để kiểm tra lựa chọn trước khi tải.</p>"
            "<p><b>5.</b> Bấm Start Search. Video được lưu trong thư mục "
            "<code>video</code> cạnh CSV.</p>"
            "<p><b>6.</b> Kết quả và nguồn bản quyền nằm trong "
            "<code>selected-footage.json</code>.</p>"
            "<p>Từ khóa thay thế trong cột <code>tu_khoa</code> nên phân cách "
            "bằng dấu <code>|</code>.</p>"
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)
