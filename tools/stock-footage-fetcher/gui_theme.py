"""Dark desktop theme aligned with Footage Finder AI."""

APP_STYLE_SHEET = """
QMainWindow, QWidget {
    background: #0e1624;
    color: #d6deee;
    font-family: "Segoe UI", "Roboto", Arial;
    font-size: 13px;
}
QLabel { background: transparent; }
QFrame#Header, QFrame#Footer { background: #101827; }
QFrame#Toolbar, QFrame#ControlBar {
    background: #111a2a;
    border-top: 1px solid #27364d;
    border-bottom: 1px solid #27364d;
}
QGroupBox {
    background: #162235;
    border: 1px solid #27364d;
    border-radius: 10px;
    margin-top: 18px;
    padding: 14px 10px 10px 10px;
    font-weight: 700;
    color: #8b5cf6;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #0f1726;
    border: 1px solid #34445e;
    border-radius: 6px;
    color: #d6deee;
    padding: 7px;
    min-height: 20px;
}
QComboBox QAbstractItemView {
    background: #0f1726;
    color: #d6deee;
    selection-background-color: #26364e;
    border: 1px solid #34445e;
}
QPushButton {
    background: #1d2a3d;
    border: 1px solid #34445e;
    border-radius: 7px;
    color: #f7f9ff;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover { background: #26364e; }
QPushButton#PrimaryButton { background: #6d42e8; border: 1px solid #7c3aed; }
QPushButton#PrimaryButton:hover { background: #7c3aed; }
QPushButton#DangerButton { background: #7f1d1d; border: 1px solid #dc2626; }
QPushButton#DangerButton:hover { background: #991b1b; }
QPushButton:disabled { background: #243044; color: #6f7c91; }
QTableWidget {
    background: #0f1726;
    alternate-background-color: #121d2e;
    border: 1px solid #27364d;
    border-radius: 8px;
    gridline-color: #27364d;
    selection-background-color: #2d235f;
    selection-color: #f7f9ff;
}
QHeaderView::section {
    background: #162235;
    color: #aab5c5;
    border: 0;
    border-right: 1px solid #27364d;
    padding: 8px;
    font-weight: 700;
}
QTextEdit, QPlainTextEdit {
    background: #0f1726;
    border: 1px solid #27364d;
    border-radius: 8px;
    color: #cbd5e1;
    selection-background-color: #44337a;
}
QProgressBar {
    background: #253146;
    border: 0;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: #f7f9ff;
}
QProgressBar::chunk { background: #6d42e8; border-radius: 5px; }
QSplitter::handle { background: #27364d; }
QTabWidget::pane { border: 1px solid #27364d; border-radius: 8px; }
QTabBar::tab {
    background: #111a2a; color: #9aa7bd; padding: 9px 16px;
    border: 1px solid #27364d; border-bottom: 0;
}
QTabBar::tab:selected { background: #1d2a3d; color: #f7f9ff; }
QCheckBox { background: transparent; spacing: 7px; }
QStatusBar { background: #101827; color: #9aa7bd; }
QToolTip { background: #162235; color: #f7f9ff; border: 1px solid #34445e; }
"""

HEADER_TITLE_STYLE = (
    "background:transparent; font-size:22px; font-weight:800; color:#f7f9ff;"
)
HEADER_SUBTITLE_STYLE = "background:transparent; color:#9aa7bd;"
SECTION_TITLE_STYLE = (
    "background:transparent; color:#8b5cf6; font-size:15px; font-weight:800;"
)
MUTED_LABEL_STYLE = "background:transparent; color:#9aa7bd;"


def chip_style(background: str, foreground: str, border: str) -> str:
    return (
        f"background:{background}; color:{foreground}; border:1px solid {border};"
        "border-radius:7px; padding:4px 9px; font-size:11px; font-weight:700;"
    )
