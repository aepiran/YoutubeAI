"""Dark navy/purple theme shared with Footage Finder AI."""

APP_STYLE_SHEET = """
QMainWindow, QWidget {
    background: #0e1624;
    color: #d6deee;
    font-family: "Segoe UI", "Roboto", Arial;
    font-size: 13px;
}
QLabel { background: transparent; }
QFrame#Header, QFrame#RunMonitor { background: #101827; }
QFrame#WorkflowBar {
    background: #101827;
    border-bottom: 1px solid #27364d;
}
QFrame#JobPanel {
    background: #111a2a;
    border-left: 1px solid #27364d;
}
QFrame#Toolbar, QFrame#SidePanel { background: #111a2a; }
QGroupBox {
    background: #162235;
    border: 1px solid #27364d;
    border-radius: 10px;
    margin-top: 18px;
    padding: 14px 10px 10px 10px;
    font-weight: 700;
    color: #8b5cf6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
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
QPushButton:hover { background: #26364e; }
QPushButton#PrimaryButton {
    background: #6d42e8;
    border: 1px solid #8b5cf6;
    font-weight: 800;
}
QPushButton#PrimaryButton:hover { background: #7c3aed; }
QPushButton#DangerButton {
    background: #dc2626;
    border: 1px solid #ef4444;
    font-weight: 800;
}
QPushButton#DangerButton:hover { background: #ef4444; }
QPushButton:disabled {
    background: #243044;
    color: #6f7c91;
    border-color: #34445e;
}
QCheckBox { background: transparent; spacing: 8px; }
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
QTableWidget {
    background: #0f1726;
    alternate-background-color: #121d2e;
    border: 1px solid #27364d;
    border-radius: 8px;
    gridline-color: #27364d;
}
QHeaderView::section {
    background: #162235;
    color: #aab5c5;
    border: 0;
    border-right: 1px solid #27364d;
    padding: 8px;
    font-weight: 700;
}
QTextEdit {
    background: #0f1726;
    border: 1px solid #27364d;
    border-radius: 8px;
    color: #d6deee;
}
QProgressBar {
    background: #1b2740;
    border: 1px solid #33445f;
    border-radius: 6px;
    height: 12px;
    text-align: center;
}
QProgressBar::chunk {
    background: #7c3aed;
    border-radius: 5px;
}
QScrollArea { border: 0; }
QSplitter::handle { background: #27364d; }
QToolTip {
    background: #162235;
    color: #f7f9ff;
    border: 1px solid #34445e;
}
"""

SECTION_TITLE_STYLE = (
    "background:transparent; color:#8b5cf6; "
    "font-size:15px; font-weight:800;"
)
HEADER_TITLE_STYLE = (
    "background:transparent; font-size:22px; "
    "font-weight:800; color:#f7f9ff;"
)
HEADER_SUBTITLE_STYLE = "background:transparent; color:#9aa7bd;"
MUTED_LABEL_STYLE = "background:transparent; color:#9aa7bd;"
