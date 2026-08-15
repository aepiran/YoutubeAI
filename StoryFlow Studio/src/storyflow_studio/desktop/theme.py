"""StoryFlow visual language, based on the Footage Video Builder shell."""

APP_STYLE_SHEET = """
QMainWindow, QWidget {
    background: #0e1624;
    color: #d6deee;
    font-family: "Segoe UI", "Roboto", Arial;
    font-size: 13px;
}
QLabel { background: transparent; }
QFrame#Header { background: #101827; border-bottom: 1px solid #27364d; }
QFrame#HeroCard, QFrame#StageCard, QFrame#ConsoleCard {
    background: #111a2a;
    border: 1px solid #27364d;
    border-radius: 12px;
}
QLabel#HeaderTitle { color: #f7f9ff; font-size: 22px; font-weight: 800; }
QLabel#HeaderSubtitle, QLabel#Muted { color: #9aa7bd; }
QLabel#VersionBadge {
    background: #18243a;
    border: 1px solid #3d4f6b;
    border-radius: 7px;
    color: #b69cff;
    font-size: 11px;
    font-weight: 800;
    padding: 3px 8px;
}
QLabel#HeroTitle { color: #f7f9ff; font-size: 20px; font-weight: 800; }
QLabel#ProjectIcon {
    background: #18243a;
    border: 1px solid #34445e;
    border-radius: 9px;
}
QLabel#ProjectStatusBadge {
    background: #171b24;
    border: 1px solid #30394a;
    border-radius: 6px;
    color: #7e8a9e;
    font-size: 10px;
    font-weight: 800;
    padding: 3px 7px;
}
QLabel#ProjectStatusBadge[active="true"] {
    background: #102a25;
    border-color: #2c7565;
    color: #78ddb7;
}
QLabel#SectionTitle { color: #8b5cf6; font-size: 15px; font-weight: 800; }
QLabel#StageStatus {
    background: #172337;
    border: 1px solid #34445e;
    border-radius: 6px;
    color: #9aa7bd;
    font-size: 11px;
    font-weight: 800;
    padding: 4px 7px;
}
QLabel#StageStatus[state="ready"] {
    background: #241b46;
    border-color: #6d42e8;
    color: #b69cff;
}
QLabel#StageStatus[state="disabled"] {
    background: #171b24;
    border-color: #30394a;
    color: #6f7b8e;
}
QLabel#StageStatus[state="running"] {
    background: #342a12;
    border-color: #806b2c;
    color: #f2cd67;
}
QLabel#StageStatus[state="completed"] {
    background: #102a25;
    border-color: #2c7565;
    color: #78ddb7;
}
QLabel#StageStatus[state="failed"] {
    background: #351c26;
    border-color: #88445c;
    color: #ff91a8;
}
QLabel#StageDetail {
    color: #8390a5;
    font-size: 11px;
    min-height: 28px;
}
QLabel#StageMetric {
    color: #b69cff;
    font-size: 12px;
    font-weight: 750;
    padding: 2px 0;
}
QLabel#SettingsTitle { color: #9b6cff; font-size: 24px; font-weight: 850; }
QLabel#SettingsDescription { color: #a6b1c4; font-size: 14px; padding-bottom: 5px; }
QLabel#FieldLabel { color: #c8d1e1; font-size: 12px; font-weight: 650; }
QLabel#PermissionValue, QLabel#InputSummary {
    background: #0f1726;
    border: 1px solid #34445e;
    border-radius: 6px;
    color: #aab5c5;
    min-height: 20px;
    padding: 7px;
}
QLabel#SidebarTitle {
    color: #6f7c91;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 0 10px;
}
QLabel#PathPreview {
    background: #0f1726;
    border: 1px solid #27364d;
    border-radius: 7px;
    color: #9aa7bd;
    padding: 10px;
}
QLabel#StatusBadge {
    background: #18243a;
    border: 1px solid #33445e;
    border-radius: 7px;
    color: #aab5c5;
    padding: 7px 10px;
    font-weight: 700;
}
QLabel#StatusBadge[authenticated="true"] {
    background: #102a25;
    border-color: #2c7565;
    color: #78ddb7;
}
QPushButton {
    background: #1d2a3d;
    border: 1px solid #34445e;
    border-radius: 7px;
    color: #f7f9ff;
    padding: 8px 12px;
    font-weight: 650;
}
QPushButton:hover { background: #26364e; border-color: #a78bfa; }
QPushButton:pressed { background: #35266b; }
QPushButton#HeaderButton { padding: 6px 11px; min-height: 22px; }
QPushButton#CodexButton[authenticated="true"] {
    background: #102a25;
    border-color: #2c7565;
    color: #78ddb7;
}
QPushButton#PrimaryButton {
    background: #6d42e8;
    border-color: #8b5cf6;
    font-weight: 800;
}
QPushButton#PrimaryButton:hover { background: #7c3aed; }
QPushButton#StageActionButton {
    background: #35266b;
    border-color: #6d42e8;
    color: #f7f9ff;
    font-size: 11px;
    font-weight: 800;
    min-height: 18px;
    padding: 4px 10px;
}
QPushButton#StageActionButton:hover {
    background: #6d42e8;
    border-color: #a78bfa;
}
QPushButton#ExportChoiceButton {
    background: #18243a;
    border: 1px solid #40516c;
    color: #f7f9ff;
    font-size: 15px;
    font-weight: 800;
    min-height: 44px;
    padding: 10px 16px;
    text-align: left;
}
QPushButton#ExportChoiceButton:hover {
    background: #35266b;
    border-color: #8b5cf6;
}
QPushButton#StageActionButton:disabled {
    background: #202c40;
    border-color: #34445e;
    color: #6f7c91;
}
QPushButton#OpenFolderButton {
    background: #18243a;
    border-color: #40516c;
    padding-left: 15px;
    padding-right: 15px;
}
QPushButton#OpenFolderButton:hover { border-color: #8b5cf6; }
QToolButton#ProjectMoreButton {
    background: #18243a;
    border: 1px solid #40516c;
    border-radius: 7px;
    color: #d6deee;
    font-weight: 800;
    min-width: 34px;
    min-height: 32px;
}
QToolButton#ProjectMoreButton:hover {
    background: #26364e;
    border-color: #8b5cf6;
}
QToolButton#ProjectMoreButton::menu-indicator {
    image: none;
    width: 0px;
    height: 0px;
}
QToolButton#ProjectIconButton {
    background: #18243a;
    border: 1px solid #40516c;
    border-radius: 7px;
    padding: 7px;
}
QToolButton#ProjectIconButton:hover {
    background: #26364e;
    border-color: #8b5cf6;
}
QToolButton#ProjectIconButton:disabled {
    background: #202c40;
    border-color: #34445e;
}
QMenu {
    background: #172337;
    border: 1px solid #40516c;
    color: #d6deee;
    padding: 5px;
}
QMenu::item { border-radius: 5px; padding: 7px 22px 7px 10px; }
QMenu::item:selected { background: #35266b; color: #ffffff; }
QMenu::item:disabled { color: #667287; }
QPushButton#ConsoleButton { padding: 5px 11px; min-height: 18px; }
QPushButton#DangerButton {
    background: #351c26;
    border-color: #88445c;
    color: #ff91a8;
    padding: 5px 11px;
    min-height: 18px;
}
QPushButton#DangerButton:hover { background: #492332; border-color: #d66a88; }
QPushButton#DangerButton:disabled {
    background: #243044;
    border-color: #34445e;
    color: #6f7c91;
}
QPushButton:disabled { background: #243044; color: #6f7c91; }
QDialog { background: #0e1624; }
QWidget#SettingsSidebar {
    background: #0a1321;
    border-right: 1px solid #27364d;
}
QWidget#SettingsFooter {
    background: #0e1624;
    border-top: 1px solid #27364d;
}
QWidget#FormField, QWidget#InlineRow { background: transparent; }
QStackedWidget#SettingsPages { background: #0e1624; }
QListWidget#SettingsNavigation {
    background: transparent;
    border: 0;
    outline: 0;
    color: #c9d3e5;
    padding: 0;
}
QListWidget#SettingsNavigation::item {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 0 14px;
    font-size: 14px;
    font-weight: 650;
}
QListWidget#SettingsNavigation::item:hover {
    background: #131e31;
    color: #f7f9ff;
}
QListWidget#SettingsNavigation::item:selected {
    background: #27324f;
    border-left: 4px solid #8b5cf6;
    color: #f7f9ff;
}
QGroupBox {
    background: #162235;
    border: 1px solid #27364d;
    border-radius: 10px;
    margin-top: 18px;
    padding: 15px 12px 12px 12px;
    font-weight: 700;
    color: #8b5cf6;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
    background: #0f1726;
    border: 1px solid #34445e;
    border-radius: 6px;
    color: #d6deee;
    padding: 7px;
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: #7c3aed; }
QTextEdit { padding: 8px; }
QPlainTextEdit#ActivityConsole {
    background: #090f1a;
    border: 1px solid #26364e;
    color: #aebbd0;
    font-family: Menlo, Consolas, monospace;
    font-size: 11px;
    padding: 9px;
}
QTableWidget#TimelineTable {
    background-color: #0b1422;
    alternate-background-color: #121f31;
    color: #dbe5f5;
    border: 1px solid #31415a;
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: #5930d8;
    selection-color: #ffffff;
    outline: 0;
    font-size: 12px;
}
QTableWidget#TimelineTable::item {
    border-bottom: 1px solid #26364c;
    padding: 7px 8px;
}
QTableWidget#TimelineTable::item:hover {
    background-color: #20304a;
}
QTableWidget#TimelineTable::item:selected {
    background-color: #5930d8;
    color: #ffffff;
}
QTableWidget#TimelineTable QHeaderView::section {
    background-color: #18263a;
    color: #f5f7ff;
    border: 0;
    border-right: 1px solid #344761;
    border-bottom: 2px solid #7047e8;
    padding: 10px 8px;
    font-size: 12px;
    font-weight: 800;
}
QTableWidget#TimelineTable QTableCornerButton::section {
    background-color: #18263a;
    border: 0;
}
QProgressBar#StageProgress {
    background: #202c40;
    border: 0;
    border-radius: 2px;
}
QProgressBar#StageProgress::chunk { background: #53627a; border-radius: 2px; }
QProgressBar#StageProgress[state="disabled"]::chunk { background: #30394a; }
QProgressBar#StageProgress[state="ready"]::chunk { background: #8b5cf6; }
QProgressBar#StageProgress[state="running"]::chunk { background: #e4b94e; }
QProgressBar#StageProgress[state="completed"]::chunk { background: #52c49d; }
QProgressBar#StageProgress[state="failed"]::chunk { background: #e36b88; }
QTabWidget::pane { border: 1px solid #27364d; border-radius: 8px; }
QTabBar::tab {
    background: #111a2a;
    border: 1px solid #27364d;
    color: #9aa7bd;
    padding: 9px 14px;
}
QTabBar::tab:selected { background: #35266b; color: #f7f9ff; }
QScrollArea { border: 0; }
QScrollArea > QWidget > QWidget { background: #0e1624; }
QCheckBox { background: transparent; spacing: 8px; }
QDialogButtonBox QPushButton { min-width: 92px; min-height: 22px; }
QToolTip { background: #162235; color: #f7f9ff; border: 1px solid #34445e; }
"""
