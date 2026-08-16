"""StoryFlow Studio shell with project workflow and application settings."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import time

from PySide6.QtCore import QTimer, Qt, QThread, QUrl, Slot
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import SettingsStore
from ..core.script_text import extract_script_body
from ..core.version import version_badge
from ..modules.ai.service import AIService, AISnapshot, AuthStatus
from ..modules.beat import (
    BeatProgress,
    BeatWorkflowError,
    BeatWorkflowResult,
    BeatWorkflowService,
)
from ..modules.music import (
    CCMIXTER_TERMS_URL,
    CCMixterCatalogService,
    CatalogDownloadResult,
    CatalogProgress,
    MIXKIT_CATALOG_URL,
    MusicLibraryError,
    MusicLibraryService,
    MusicProgress,
    MusicWorkflowResult,
    MusicWorkflowService,
    default_downloads_folder,
    music_analysis_path,
    music_recommendations_path,
)
from ..modules.footage import (
    FootageProgress,
    FootageWorkflowError,
    FootageWorkflowResult,
    FootageWorkflowService,
)
from ..modules.video_builder import (
    CapCutExportProgress,
    CapCutExportResult,
    TimelineAnalysisResult,
    VideoBuilderProgress,
    VideoBuilderService,
    VideoBuilderWorkflowError,
    VideoRenderProgress,
    VideoRenderResult,
)
from ..modules.tts import (
    CancellationToken,
    TTSProgress,
    TTSScriptImportService,
    TTSWorkflowError,
    TTSWorkflowResult,
    TTSWorkflowService,
    VoiceImportService,
    VoiceResult,
)
from ..modules.workspace import (
    Project,
    ProjectError,
    ProjectMetricsService,
    WorkspaceService,
    format_duration,
)
from .branding import application_icon, logo_pixmap
from .project_dialogs import ExportChoiceDialog, NewProjectDialog
from .music_review_dialog import MusicReviewDialog, MusicReviewError
from .settings_dialog import SettingsDialog
from .subtitle_review_dialog import SubtitleReviewDialog
from .timeline_review_dialog import TimelineReviewDialog
from .workers import ProgressTaskWorker, TaskWorker


class CopyableErrorLabel(QLabel):
    """Stage detail that copies its full error message with one click."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._copy_text = ""

    def set_error_copy_text(self, text: str | None) -> None:
        self._copy_text = text or ""
        if self._copy_text:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Click to copy the complete error log")
            self.setAccessibleDescription(
                "Error log. Click once to copy the complete message."
            )
        else:
            self.unsetCursor()
            self.setToolTip("")
            self.setAccessibleDescription("")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._copy_text:
            QApplication.clipboard().setText(self._copy_text)
            self.setToolTip("Copied error log")
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CopyablePathLabel(QLabel):
    """Middle-elided project path that copies its absolute path when clicked."""

    def __init__(self, empty_text: str) -> None:
        super().__init__(empty_text)
        self._empty_text = empty_text
        self._full_path = ""

    def set_path(self, path: str | None) -> None:
        self._full_path = path or ""
        if self._full_path:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(f"{self._full_path}\n\nClick to copy project path")
            self.setAccessibleDescription("Project path. Click once to copy.")
        else:
            self.unsetCursor()
            self.setToolTip("")
            self.setAccessibleDescription("")
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        source = self._full_path or self._empty_text
        self.setText(
            self.fontMetrics().elidedText(
                source, Qt.TextElideMode.ElideMiddle, max(80, self.width())
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_elided_text()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._full_path:
            QApplication.clipboard().setText(self._full_path)
            self.setToolTip(f"{self._full_path}\n\nCopied project path")
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(
        self,
        ai_service: AIService,
        settings_store: SettingsStore,
        workspace_service: WorkspaceService | None = None,
        tts_workflow_service: TTSWorkflowService | None = None,
        beat_workflow_service: BeatWorkflowService | None = None,
        music_workflow_service: MusicWorkflowService | None = None,
        footage_workflow_service: FootageWorkflowService | None = None,
        video_builder_service: VideoBuilderService | None = None,
        metrics_service: ProjectMetricsService | None = None,
        voice_import_service: VoiceImportService | None = None,
        tts_script_import_service: TTSScriptImportService | None = None,
        music_library_service: MusicLibraryService | None = None,
        music_catalog_service: CCMixterCatalogService | None = None,
    ) -> None:
        super().__init__()
        self.ai_service = ai_service
        self.settings_store = settings_store
        self.workspace_service = workspace_service or WorkspaceService()
        self.tts_workflow_service = tts_workflow_service or TTSWorkflowService(
            ai_service
        )
        self.voice_import_service = voice_import_service or VoiceImportService()
        self.tts_script_import_service = (
            tts_script_import_service or TTSScriptImportService()
        )
        self.beat_workflow_service = beat_workflow_service or BeatWorkflowService(
            ai_service
        )
        self.music_workflow_service = music_workflow_service or MusicWorkflowService(
            ai_service
        )
        self.music_library_service = music_library_service or MusicLibraryService()
        self.music_catalog_service = music_catalog_service or CCMixterCatalogService(
            library_service=self.music_library_service
        )
        self._skip_music_confirmation_once = False
        self._regenerate_music_after_download = False
        self.footage_workflow_service = (
            footage_workflow_service or FootageWorkflowService()
        )
        self.video_builder_service = video_builder_service or VideoBuilderService()
        self.metrics_service = metrics_service or ProjectMetricsService()
        self.settings = settings_store.load()
        self.ai_settings = self.settings.ai
        self.current_project: Project | None = None
        self.snapshot = AISnapshot(AuthStatus(False, "Checking Codex…"))
        self.jobs: dict[QThread, TaskWorker | ProgressTaskWorker] = {}
        self.settings_dialog: SettingsDialog | None = None
        self.tts_cancellation: CancellationToken | None = None
        self.tts_running = False
        self.active_tts_stage = "tts_script"
        self.beat_cancellation: CancellationToken | None = None
        self.beat_running = False
        self.music_cancellation: CancellationToken | None = None
        self.music_running = False
        self.footage_cancellation: CancellationToken | None = None
        self.footage_running = False
        self.video_builder_cancellation: CancellationToken | None = None
        self.video_builder_running = False
        self._retry_video_analysis_after_model_download = False
        self._skip_video_analysis_confirmation = False
        self._pending_supplemental_footage = False
        self._supplemental_footage_active = False
        self._resume_video_analysis_after_footage = False
        self.auto_workflow_running = False
        self.auto_export_choice = ""
        self.capcut_draft_name = ""
        self.stage_started_at: dict[str, float] = {}
        self.stage_initial_eta: dict[str, float] = {}
        self.stage_remaining_eta: dict[str, float] = {}
        self.stage_progress_percent: dict[str, int | None] = {}
        self.stage_default_eta: dict[str, float] = {
            "tts_script": 75.0,
            "voice": 120.0,
            "beat": 90.0,
            "music": 120.0,
            "footage": 240.0,
            "video_plan": 120.0,
        }
        self.estimated_audio_duration = 0.0
        self.estimated_cut_count = 0

        self.setWindowTitle("StoryFlow Studio")
        self.setWindowIcon(application_icon())
        self.resize(1160, 760)
        self.setMinimumSize(940, 640)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)
        self.eta_timer = QTimer(self)
        self.eta_timer.setInterval(1000)
        self.eta_timer.timeout.connect(self._refresh_eta_labels)
        self.eta_timer.start()
        self.append_log("StoryFlow Studio started.")
        self._refresh_recent_projects()
        self._restore_last_project()
        self.refresh_codex()

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(72)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 9, 16, 9)
        layout.setSpacing(12)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("HeaderLogo")
        self.logo_label.setPixmap(logo_pixmap(48))
        self.logo_label.setFixedSize(48, 48)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setAccessibleName("StoryFlow Studio logo")
        layout.addWidget(self.logo_label)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title_row = QHBoxLayout()
        title_row.setSpacing(9)
        title = QLabel("StoryFlow Studio")
        title.setObjectName("HeaderTitle")
        title_row.addWidget(title)
        self.version_label = QLabel(version_badge())
        self.version_label.setObjectName("VersionBadge")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setAccessibleName("Application version")
        title_row.addWidget(self.version_label)
        title_row.addStretch(1)
        subtitle = QLabel("Script to Sound to Scene")
        subtitle.setObjectName("HeaderSubtitle")
        titles.addLayout(title_row)
        titles.addWidget(subtitle)
        layout.addLayout(titles)
        layout.addStretch(1)
        self.codex_button = QPushButton("○ Codex")
        self.codex_button.setObjectName("CodexButton")
        self.codex_button.setAccessibleName("Codex status")
        self.codex_button.clicked.connect(self.codex_button_clicked)
        layout.addWidget(self.codex_button)
        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("HeaderButton")
        self.settings_button.setFixedSize(40, 36)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)
        return header

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(14)

        hero = QFrame()
        self.project_bar = hero
        hero.setObjectName("HeroCard")
        hero.setFixedHeight(92)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 10, 14, 10)
        hero_layout.setSpacing(12)

        self.project_icon = QLabel()
        self.project_icon.setObjectName("ProjectIcon")
        self.project_icon.setFixedSize(38, 38)
        self.project_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.project_icon.setPixmap(
            self.style()
            .standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            .pixmap(30, 30)
        )
        hero_layout.addWidget(self.project_icon)

        project_info = QVBoxLayout()
        project_info.setSpacing(3)
        identity_row = QHBoxLayout()
        identity_row.setSpacing(9)
        self.project_title = QLabel("No project selected")
        self.project_title.setObjectName("HeroTitle")
        identity_row.addWidget(self.project_title)
        self.project_status_badge = QLabel("No project")
        self.project_status_badge.setObjectName("ProjectStatusBadge")
        self.project_status_badge.setProperty("active", False)
        identity_row.addWidget(self.project_status_badge)
        identity_row.addStretch(1)
        project_info.addLayout(identity_row)
        self.project_path = CopyablePathLabel(
            "Create a new project inside your Workspace Root, or open an existing one."
        )
        self.project_path.setObjectName("Muted")
        project_info.addWidget(self.project_path)
        hero_layout.addLayout(project_info, 1)

        project_actions = QHBoxLayout()
        project_actions.setSpacing(7)
        self.open_folder_button = QPushButton("Open Project…")
        self.open_folder_button.setObjectName("OpenFolderButton")
        self.open_folder_button.setAccessibleName("Open Project")
        self.open_folder_button.setToolTip("Open an existing StoryFlow project")
        self.open_folder_button.clicked.connect(self._project_primary_action)
        project_actions.addWidget(self.open_folder_button)
        self.new_project_button = QPushButton("＋ New")
        self.new_project_button.setObjectName("PrimaryButton")
        self.new_project_button.setToolTip("Create a new project")
        self.new_project_button.clicked.connect(self.new_project)
        project_actions.addWidget(self.new_project_button)
        self.refresh_status_button = QToolButton()
        self.refresh_status_button.setObjectName("ProjectIconButton")
        self.refresh_status_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_status_button.setFixedSize(38, 36)
        self.refresh_status_button.setToolTip(
            "Refresh Status — scan project files and update every workflow stage"
        )
        self.refresh_status_button.setAccessibleName("Refresh Project Status")
        self.refresh_status_button.setEnabled(False)
        self.refresh_status_button.clicked.connect(self.refresh_project_status)
        project_actions.addWidget(self.refresh_status_button)

        self.project_menu = QMenu(self)
        self.switch_project_menu = self.project_menu.addMenu("Switch Project")
        self.switch_project_menu.setEnabled(False)
        self.project_menu.addSeparator()
        self.open_existing_project_action = QAction("Open Existing Project…", self)
        self.open_existing_project_action.triggered.connect(self.open_project_dialog)
        self.project_menu.addAction(self.open_existing_project_action)
        self.copy_project_path_action = QAction("Copy Project Path", self)
        self.copy_project_path_action.setEnabled(False)
        self.copy_project_path_action.triggered.connect(self.copy_project_path)
        self.project_menu.addAction(self.copy_project_path_action)
        self.project_more_button = QToolButton()
        self.project_more_button.setObjectName("ProjectMoreButton")
        self.project_more_button.setText("•••")
        self.project_more_button.setToolTip("More project actions")
        self.project_more_button.setAccessibleName("More Project Actions")
        self.project_more_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.project_more_button.setMenu(self.project_menu)
        project_actions.addWidget(self.project_more_button)
        hero_layout.addLayout(project_actions)
        layout.addWidget(hero)

        stage_row = QGridLayout()
        self.stage_grid = stage_row
        stage_row.setSpacing(14)
        stages = (
            ("01", "Script & TTS DNA", "tts_script"),
            ("02", "Voice MP3 / SRT", "voice"),
            ("03", "Beat DNA", "beat"),
            ("04", "Background Music", "music"),
            ("05", "Footage Finder", "footage"),
            ("06", "Video Builder", "video_plan"),
        )
        self.stage_labels: dict[str, QLabel] = {}
        self.stage_details: dict[str, CopyableErrorLabel] = {}
        self.stage_progress: dict[str, QProgressBar] = {}
        self.stage_metrics: dict[str, QLabel] = {}
        self.stage_eta_labels: dict[str, QLabel] = {}
        metric_defaults = {
            "tts_script": "0 words · 0 characters",
            "voice": "Audio · —",
            "beat": "0 beats",
            "music": "0 cues",
            "footage": "0 clips",
            "video_plan": "0 cuts · 0 warnings",
        }
        for number, name, key in stages:
            card = QFrame()
            card.setObjectName("StageCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            number_label = QLabel(number)
            number_label.setObjectName("SectionTitle")
            card_header = QHBoxLayout()
            card_header.setSpacing(8)
            card_header.addWidget(number_label)
            card_header.addStretch(1)
            name_label = QLabel(name)
            name_label.setStyleSheet("font-size:14px; font-weight:750; color:#f7f9ff;")
            if key == "tts_script":
                self.import_tts_button = QPushButton("Import")
                self.import_tts_button.setObjectName("StageActionButton")
                self.import_tts_button.setAccessibleName("Import TTS Script")
                self.import_tts_button.setToolTip(
                    "Import an existing UTF-8 TTS text file"
                )
                self.import_tts_button.setEnabled(False)
                self.import_tts_button.clicked.connect(self.import_tts_script)
                card_header.addWidget(self.import_tts_button)
                self.run_tts_button = QPushButton("Generate")
                self.run_tts_button.setObjectName("StageActionButton")
                self.run_tts_button.setAccessibleName("Generate TTS Script")
                self.run_tts_button.setToolTip(
                    "Apply TTS DNA and create script_tts.txt"
                )
                self.run_tts_button.setEnabled(False)
                self.run_tts_button.clicked.connect(self.run_tts_script_generation)
                card_header.addWidget(self.run_tts_button)
            elif key == "voice":
                self.import_voice_button = QPushButton("Import")
                self.import_voice_button.setObjectName("StageActionButton")
                self.import_voice_button.setAccessibleName("Import Voice Audio and SRT")
                self.import_voice_button.setToolTip(
                    "Import an existing narration audio file and matching SRT"
                )
                self.import_voice_button.setEnabled(False)
                self.import_voice_button.clicked.connect(self.import_voice_files)
                card_header.addWidget(self.import_voice_button)
                self.review_subtitles_button = QPushButton("Review SRT")
                self.review_subtitles_button.setObjectName("StageActionButton")
                self.review_subtitles_button.setAccessibleName(
                    "Review Narration and Screen Subtitles"
                )
                self.review_subtitles_button.setToolTip(
                    "Compare narration.srt and screen.srt by timeline"
                )
                self.review_subtitles_button.setEnabled(False)
                self.review_subtitles_button.clicked.connect(
                    self.open_subtitle_review
                )
                card_header.addWidget(self.review_subtitles_button)
                self.run_voice_button = QPushButton("Generate")
                self.run_voice_button.setObjectName("StageActionButton")
                self.run_voice_button.setAccessibleName("Generate Voice MP3 and SRT")
                self.run_voice_button.setToolTip(
                    "Generate narration MP3 and SRT from script_tts.txt"
                )
                self.run_voice_button.setEnabled(False)
                self.run_voice_button.clicked.connect(self.run_voice_generation)
                card_header.addWidget(self.run_voice_button)
            elif key == "beat":
                self.run_beat_button = QPushButton("Generate")
                self.run_beat_button.setObjectName("StageActionButton")
                self.run_beat_button.setAccessibleName("Generate Beat CSV")
                self.run_beat_button.setToolTip(
                    "Apply Beat DNA to script_tts.txt and narration SRT"
                )
                self.run_beat_button.setEnabled(False)
                self.run_beat_button.clicked.connect(self.run_beat_pipeline)
                card_header.addWidget(self.run_beat_button)
            elif key == "music":
                self.review_music_button = QPushButton("Review")
                self.review_music_button.setObjectName("StageActionButton")
                self.review_music_button.setAccessibleName(
                    "Review Background Music Analysis"
                )
                self.review_music_button.setToolTip(
                    "Review script sections, selected tracks and search recommendations"
                )
                self.review_music_button.setEnabled(False)
                self.review_music_button.clicked.connect(self.open_music_review)
                card_header.addWidget(self.review_music_button)
                self.run_music_button = QPushButton("Generate")
                self.run_music_button.setObjectName("StageActionButton")
                self.run_music_button.setAccessibleName("Generate Background Music")
                self.run_music_button.setToolTip(
                    "Create the legacy cue sheet and render one background music MP3"
                )
                self.run_music_button.setEnabled(False)
                self.run_music_button.clicked.connect(self.run_music_pipeline)
                card_header.addWidget(self.run_music_button)
            elif key == "footage":
                self.run_footage_button = QPushButton("Search")
                self.run_footage_button.setObjectName("StageActionButton")
                self.run_footage_button.setAccessibleName("Search Stock Footage")
                self.run_footage_button.setToolTip(
                    "Search and download Pexels/Pixabay clips for footage.csv"
                )
                self.run_footage_button.setEnabled(False)
                self.run_footage_button.clicked.connect(self.run_footage_pipeline)
                card_header.addWidget(self.run_footage_button)
            elif key == "video_plan":
                self.review_timeline_button = QPushButton("Review")
                self.review_timeline_button.setObjectName("StageActionButton")
                self.review_timeline_button.setAccessibleName("Review Video Timeline")
                self.review_timeline_button.setToolTip(
                    "Inspect Cuts, technical scores, warnings and missing Beats"
                )
                self.review_timeline_button.setEnabled(False)
                self.review_timeline_button.clicked.connect(self.open_timeline_review)
                card_header.addWidget(self.review_timeline_button)
                self.export_video_button = QPushButton("Export")
                self.export_video_button.setObjectName("StageActionButton")
                self.export_video_button.setAccessibleName("Export Video Builder Output")
                self.export_video_button.setToolTip(
                    "Choose Render Video or Export CapCut Draft"
                )
                self.export_video_button.setEnabled(False)
                self.export_video_button.clicked.connect(self.open_export_dialog)
                card_header.addWidget(self.export_video_button)
                self.run_video_builder_button = QPushButton("Analyze")
                self.run_video_builder_button.setObjectName("StageActionButton")
                self.run_video_builder_button.setAccessibleName(
                    "Analyze Video Timeline"
                )
                self.run_video_builder_button.setToolTip(
                    "Reuse Beat/SRT timing and Footage Finder outputs to create a draft timeline"
                )
                self.run_video_builder_button.setEnabled(False)
                self.run_video_builder_button.clicked.connect(
                    self.run_video_builder_analysis
                )
                card_header.addWidget(self.run_video_builder_button)
            status_label = QLabel("Waiting")
            status_label.setObjectName("StageStatus")
            status_label.setProperty("state", "waiting")
            eta_label = QLabel("")
            eta_label.setObjectName("StageMetric")
            eta_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            status_row = QHBoxLayout()
            status_row.setSpacing(8)
            status_row.addWidget(status_label)
            status_row.addStretch(1)
            status_row.addWidget(eta_label)
            detail_label = CopyableErrorLabel("Open a project to begin")
            detail_label.setObjectName("StageDetail")
            detail_label.setWordWrap(True)
            metric_label = None
            if key in metric_defaults:
                metric_label = QLabel(metric_defaults[key])
                metric_label.setObjectName("StageMetric")
                metric_label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                self.stage_metrics[key] = metric_label
            progress = QProgressBar()
            progress.setObjectName("StageProgress")
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setTextVisible(False)
            progress.setFixedHeight(5)
            self.stage_labels[key] = status_label
            self.stage_eta_labels[key] = eta_label
            self.stage_details[key] = detail_label
            self.stage_progress[key] = progress
            card_layout.addLayout(card_header)
            card_layout.addWidget(name_label)
            if metric_label is not None:
                card_layout.addWidget(metric_label)
            card_layout.addLayout(status_row)
            card_layout.addWidget(detail_label)
            card_layout.addWidget(progress)
            index = len(self.stage_labels) - 1
            stage_row.addWidget(card, index // 3, index % 3)
        for column in range(3):
            stage_row.setColumnStretch(column, 1)
        layout.addLayout(stage_row)

        console = QFrame()
        console.setObjectName("ConsoleCard")
        console_layout = QVBoxLayout(console)
        console_layout.setContentsMargins(16, 14, 16, 14)
        console_layout.setSpacing(9)
        console_header = QHBoxLayout()
        console_title = QLabel("ACTIVITY CONSOLE")
        console_title.setObjectName("SectionTitle")
        console_header.addWidget(console_title)
        console_header.addStretch(1)
        self.auto_workflow_button = QPushButton("Auto")
        self.auto_workflow_button.setObjectName("PrimaryButton")
        self.auto_workflow_button.setAccessibleName("Run Auto Workflow")
        self.auto_workflow_button.setToolTip(
            "Choose Final MP4 or CapCut Draft, then run all workflow steps"
        )
        self.auto_workflow_button.setEnabled(False)
        self.auto_workflow_button.clicked.connect(self.run_auto_workflow)
        console_header.addWidget(self.auto_workflow_button)
        self.auto_eta_label = QLabel("Total ETA —")
        self.auto_eta_label.setObjectName("StageMetric")
        self.auto_eta_label.setMinimumWidth(112)
        self.auto_eta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        console_header.addWidget(self.auto_eta_label)
        self.cancel_tts_button = QPushButton("Stop Active Job")
        self.cancel_tts_button.setObjectName("DangerButton")
        self.cancel_tts_button.setEnabled(False)
        self.cancel_tts_button.clicked.connect(self.cancel_tts_pipeline)
        console_header.addWidget(self.cancel_tts_button)
        clear_console = QPushButton("Clear")
        clear_console.setObjectName("ConsoleButton")
        clear_console.clicked.connect(self.clear_console)
        console_header.addWidget(clear_console)
        console_layout.addLayout(console_header)
        self.activity_console = QPlainTextEdit()
        self.activity_console.setObjectName("ActivityConsole")
        self.activity_console.setReadOnly(True)
        self.activity_console.setMaximumBlockCount(1000)
        self.activity_console.setPlaceholderText("Workflow activity will appear here…")
        console_layout.addWidget(self.activity_console, 1)
        layout.addWidget(console, 1)
        return content

    def start_job(
        self,
        operation: Callable[[], object],
        on_success: Callable[[object], None],
    ) -> None:
        thread = QThread(self)
        worker = TaskWorker(operation)
        worker.moveToThread(thread)
        self.jobs[thread] = worker
        thread.started.connect(worker.execute)
        worker.succeeded.connect(on_success, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self.show_error, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self.jobs.pop(thread, None))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def start_progress_job(
        self,
        operation: Callable[[Callable[[object], None]], object],
        on_success: Callable[[object], None],
        on_progress: Callable[[object], None],
        on_failed: Callable[[str], None],
        on_finished: Callable[[], None],
    ) -> None:
        thread = QThread(self)
        worker = ProgressTaskWorker(operation)
        worker.moveToThread(thread)
        self.jobs[thread] = worker
        thread.started.connect(worker.execute)
        worker.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)
        worker.succeeded.connect(on_success, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(on_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(on_finished, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self.jobs.pop(thread, None))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @Slot()
    def refresh_codex(self) -> None:
        self.append_log("Checking Codex ChatGPT session…", "CODEX")
        self.set_auth_busy("Checking Codex…")
        self.start_job(self.ai_service.snapshot, self.apply_snapshot)

    @Slot()
    def sign_in_chatgpt(self) -> None:
        self.append_log("Starting ChatGPT sign-in flow…", "CODEX")
        self.set_auth_busy("Waiting for ChatGPT sign-in…")
        self.start_job(self.ai_service.login_chatgpt, self.apply_snapshot)

    @Slot()
    def codex_button_clicked(self) -> None:
        if self.snapshot.auth.authenticated:
            self.refresh_codex()
        else:
            self.sign_in_chatgpt()

    def set_auth_busy(self, message: str) -> None:
        self.codex_button.setEnabled(False)
        self.codex_button.setText("○ Checking…")
        self.codex_button.setToolTip(message)
        if self.settings_dialog:
            self.settings_dialog.set_busy(True, message)

    @Slot(object)
    def apply_snapshot(self, result: object) -> None:
        if not isinstance(result, AISnapshot):
            self.show_error("Codex service trả về trạng thái không hợp lệ.")
            return
        self.snapshot = result
        auth = result.auth
        self.codex_button.setEnabled(True)
        self.codex_button.setText(f"{'●' if auth.authenticated else '○'} Codex")
        self.codex_button.setProperty("authenticated", auth.authenticated)
        self.codex_button.style().unpolish(self.codex_button)
        self.codex_button.style().polish(self.codex_button)
        self.codex_button.setToolTip(
            " · ".join(part for part in (auth.label, auth.detail) if part)
        )
        self.append_log(
            auth.label or ("Codex connected" if auth.authenticated else "Codex disconnected"),
            "CODEX",
        )
        if self.settings_dialog:
            self.settings_dialog.set_snapshot(result)

    @Slot()
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.snapshot, self)
        self.settings_dialog = dialog
        dialog.refresh_requested.connect(self.refresh_codex)
        dialog.login_requested.connect(self.sign_in_chatgpt)
        accepted = dialog.exec()
        self.settings_dialog = None
        if not accepted:
            return
        try:
            updated = dialog.app_settings()
            self.settings_store.save(updated)
        except Exception as exc:
            self.show_error(f"Không lưu được Settings: {exc}")
            return
        self.settings = updated
        self.ai_settings = updated.ai
        self._refresh_recent_projects()
        if self.current_project is not None:
            self._apply_project_stage_states(self.current_project)
        else:
            self._update_pipeline_actions()
        self.append_log("Application settings saved.")

    @Slot()
    def new_project(self) -> None:
        dialog = NewProjectDialog(self.settings.workspace.workspace_root, self)
        if not dialog.exec():
            return
        root, name, folder, description = dialog.values()
        try:
            project = self.workspace_service.create_project(
                root, name, folder, self.settings, description=description
            )
        except (ProjectError, OSError) as exc:
            self.show_error(str(exc))
            return
        self.settings.workspace.workspace_root = root
        self.append_log(f"Created project: {project.root}", "PROJECT")
        self.set_project(project)

    @Slot()
    def open_project_dialog(self) -> None:
        start = self.settings.workspace.workspace_root or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Open StoryFlow Project", start)
        if selected:
            self.open_project(selected)

    def open_project(self, path: str | Path) -> bool:
        try:
            project = self.workspace_service.open_project(path)
        except (ProjectError, OSError) as exc:
            self.show_error(str(exc))
            return False
        self.set_project(project)
        return True

    def set_project(self, project: Project) -> None:
        self.current_project = project
        self.project_title.setText(project.manifest.name)
        self.project_title.setToolTip(project.manifest.description)
        self.project_path.set_path(str(project.root))
        self.project_status_badge.setText("Active")
        self.project_status_badge.setProperty("active", True)
        self.project_status_badge.style().unpolish(self.project_status_badge)
        self.project_status_badge.style().polish(self.project_status_badge)
        self.open_folder_button.setText("Open Folder")
        self.open_folder_button.setAccessibleName("Open Project Folder")
        self.open_folder_button.setToolTip(
            "Open the current project in the system file manager"
        )
        self.open_folder_button.setEnabled(True)
        self.refresh_status_button.setEnabled(True)
        self.copy_project_path_action.setEnabled(True)
        self._apply_project_stage_states(project)
        self._remember_project(project.root)
        self.append_log(f"Active project: {project.manifest.name}", "PROJECT")
        if project.manifest.description:
            self.append_log(
                f"Description: {project.manifest.description}", "PROJECT"
            )
        self.append_log(
            f"Input script: {project.path_for('raw_script')}", "PROJECT"
        )

    @Slot()
    def _project_primary_action(self) -> None:
        if self.current_project is None:
            self.open_project_dialog()
        else:
            self.open_project_folder()

    @Slot()
    def copy_project_path(self) -> None:
        if self.current_project is None:
            return
        value = str(self.current_project.root)
        QApplication.clipboard().setText(value)
        self.project_path.setToolTip(f"{value}\n\nCopied project path")
        self.append_log("Project path copied to clipboard.", "PROJECT")

    @Slot()
    def open_project_folder(self) -> None:
        if self.current_project is None:
            return
        project_root = self.current_project.root
        if not project_root.is_dir():
            self.show_error(f"Project folder không còn tồn tại: {project_root}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(project_root))):
            self.show_error(f"Không mở được project folder: {project_root}")
            return
        self.append_log(f"Opened project folder: {project_root}", "PROJECT")

    @Slot()
    def refresh_project_status(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        try:
            project = self.workspace_service.open_project(self.current_project.root)
        except (ProjectError, OSError) as exc:
            self.show_error(f"Không refresh được project: {exc}")
            return
        self.current_project = project
        self._apply_project_stage_states(project)
        self.append_log("Project files scanned; stage status refreshed.", "PROJECT")

    def _choose_auto_export(self) -> bool:
        default_name = (
            self.current_project.manifest.name if self.current_project else ""
        )
        dialog = ExportChoiceDialog(self, capcut_draft_name=default_name)
        if not dialog.exec():
            return False
        choice = dialog.choice()
        if choice not in {"render", "capcut"}:
            return False
        self.auto_export_choice = choice
        self.capcut_draft_name = (
            dialog.draft_name() if choice == "capcut" else ""
        )
        label = "Final MP4" if choice == "render" else "CapCut Draft"
        self.append_log(f"Auto export selected: {label}", "AUTO")
        self._refresh_auto_eta()
        return True

    @Slot()
    def run_auto_workflow(self) -> None:
        if self.current_project is None or self.auto_workflow_running:
            return
        if any(
            (
                self.tts_running,
                self.beat_running,
                self.music_running,
                self.footage_running,
                self.video_builder_running,
            )
        ):
            return
        self.auto_export_choice = ""
        if not self._choose_auto_export():
            self.append_log("Auto workflow cancelled: no export option selected.", "AUTO")
            return
        if not self.snapshot.auth.authenticated:
            self.show_error(
                "Hãy đăng nhập Codex bằng ChatGPT trước khi chạy Auto workflow."
            )
            return
        self.auto_workflow_running = True
        self.append_log(
            "Auto workflow started: TTS Script → Voice → Beat → Music → "
            "Footage → Video Analyze.",
            "AUTO",
        )
        self._update_pipeline_actions()
        QTimer.singleShot(0, self._continue_auto_workflow)

    def _continue_auto_workflow(self) -> None:
        if not self.auto_workflow_running or self.current_project is None:
            return
        if any(
            (
                self.tts_running,
                self.beat_running,
                self.music_running,
                self.footage_running,
                self.video_builder_running,
            )
        ):
            return
        try:
            self.current_project = self.workspace_service.open_project(
                self.current_project.root
            )
        except (ProjectError, OSError) as exc:
            self._stop_auto_workflow(f"Could not refresh project: {exc}")
            return
        project = self.current_project
        stages = project.manifest.stages
        self._apply_project_stage_states(project)
        if not self._has_script_content(project.path_for("raw_script")):
            self._stop_auto_workflow("Auto stopped: project is missing script.txt.")
        elif stages.get("tts_script") != "completed":
            self.run_tts_script_generation()
        elif stages.get("voice") != "completed":
            self.run_voice_generation()
        elif stages.get("beat") != "completed":
            self.run_beat_pipeline()
        elif self.settings.music.enabled and stages.get("music") != "completed":
            self.run_music_pipeline()
        elif stages.get("footage") != "completed":
            if self.settings.footage.dry_run and project.path_for(
                "footage_manifest"
            ).is_file():
                self._stop_auto_workflow(
                    "Auto stopped after Footage Dry Run; disable Dry Run and resume."
                )
            else:
                self.run_footage_pipeline()
        elif stages.get("video_plan") != "completed":
            self._skip_video_analysis_confirmation = True
            self.run_video_builder_analysis()
        else:
            export_choice = self.auto_export_choice
            self.auto_export_choice = ""
            self.auto_workflow_running = False
            self.append_log(
                "Auto workflow completed through Video Analyze; starting the "
                "selected export.",
                "AUTO",
            )
            self._update_pipeline_actions()
            if export_choice == "render":
                QTimer.singleShot(0, self.run_video_render)
            elif export_choice == "capcut":
                QTimer.singleShot(0, self.run_capcut_export)
            else:
                QTimer.singleShot(0, self.open_export_dialog)

    def _stop_auto_workflow(self, message: str) -> None:
        if self.auto_workflow_running:
            self.auto_workflow_running = False
            self.append_log(message, "AUTO")
            self._update_pipeline_actions()

    def _schedule_auto_continue(self) -> None:
        if self.auto_workflow_running:
            QTimer.singleShot(0, self._continue_auto_workflow)

    @Slot()
    def run_tts_script_generation(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        if not self.snapshot.auth.authenticated:
            self.show_error(
                "Hãy đăng nhập Codex bằng ChatGPT trước khi tạo TTS Script."
            )
            return
        project = self.current_project
        output_exists = project.path_for("tts_script").exists()
        if output_exists and not self.auto_workflow_running:
            answer = QMessageBox.question(
                self,
                "Generate TTS Script Again",
                "Replace the current TTS Script? Existing Voice and downstream "
                "outputs may need to be generated again.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        settings = self.settings.normalized()
        cancellation = CancellationToken()
        self.tts_cancellation = cancellation
        self.tts_running = True
        self.active_tts_stage = "tts_script"
        self._update_pipeline_actions()
        self.start_stage("tts_script", "Preparing TTS DNA transformation…")
        self.append_log("Starting Raw Script → TTS DNA → script_tts.txt.", "TTS_SCRIPT")

        def operation(report: Callable[[object], None]) -> object:
            return self.tts_workflow_service.generate_script(
                project,
                settings,
                lambda update: report(update),
                cancellation,
                replace_existing=output_exists,
            )

        self.start_progress_job(
            operation,
            self._tts_script_generation_succeeded,
            self._tts_pipeline_progress,
            self._tts_pipeline_failed,
            self._tts_pipeline_finished,
        )

    @Slot()
    def import_tts_script(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
            or self.auto_workflow_running
        ):
            return
        project = self.current_project
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Import TTS Script",
            str(project.root),
            "Text Files (*.txt);;All Files (*)",
        )
        if not source:
            return
        output_exists = project.path_for("tts_script").exists()
        if output_exists:
            answer = QMessageBox.question(
                self,
                "Replace TTS Script",
                "Replace the current TTS Script with the selected file?\n\n"
                "Voice and downstream outputs already created may need to be "
                "generated again.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            result = self.tts_script_import_service.run(
                source,
                project,
                replace_existing=output_exists,
            )
            self.current_project = self.workspace_service.open_project(project.root)
            self._apply_project_stage_states(self.current_project)
            self.append_log(f"Imported TTS Script: {result}", "TTS_SCRIPT")
        except (TTSWorkflowError, ProjectError, OSError) as exc:
            self.show_error(str(exc))

    @Slot(object)
    def _tts_script_generation_succeeded(self, result: object) -> None:
        if not isinstance(result, Path):
            self._tts_pipeline_failed("TTS Script service returned an invalid result.")
            return
        self.append_log(f"TTS Script: {result}", "TTS_SCRIPT")
        if self.current_project is not None:
            self.current_project = self.workspace_service.open_project(
                self.current_project.root
            )
            self._apply_project_stage_states(self.current_project)

    @Slot()
    def run_voice_generation(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        if not self.snapshot.auth.authenticated:
            self.show_error(
                "Hãy đăng nhập Codex bằng ChatGPT để tạo screen.srt sau Voice."
            )
            return
        project = self.current_project
        screen_only = (
            project.path_for("audio_file").is_file()
            and project.path_for("subtitle_file").is_file()
            and not project.path_for("screen_subtitle_file").is_file()
        )
        outputs_exist = (
            project.path_for("audio_file").exists()
            or project.path_for("subtitle_file").exists()
        )
        if outputs_exist and not screen_only and not self.auto_workflow_running:
            answer = QMessageBox.question(
                self,
                "Generate Voice Again",
                "Replace the current narration MP3 and SRT?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        settings = self.settings.normalized()
        if outputs_exist and not screen_only:
            settings.tts.overwrite_existing = True
        cancellation = CancellationToken()
        self.tts_cancellation = cancellation
        self.tts_running = True
        self.active_tts_stage = "voice"
        self._update_pipeline_actions()
        self.start_stage("voice", "Preparing Voice API generation…")
        self.append_log("Starting TTS Script → Voice MP3/SRT.", "VOICE")

        def operation(report: Callable[[object], None]) -> object:
            return self.tts_workflow_service.generate_voice(
                project,
                settings,
                lambda update: report(update),
                cancellation,
            )

        self.start_progress_job(
            operation,
            self._voice_generation_succeeded,
            self._tts_pipeline_progress,
            self._tts_pipeline_failed,
            self._tts_pipeline_finished,
        )

    @Slot()
    def import_voice_files(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
            or self.auto_workflow_running
        ):
            return
        if not self.snapshot.auth.authenticated:
            self.show_error(
                "Hãy đăng nhập Codex bằng ChatGPT để tạo screen.srt từ Audio/SRT import."
            )
            return
        project = self.current_project
        if not project.path_for("tts_script").is_file():
            self.show_error(
                "Hãy Generate hoặc Import TTS Script trước khi Import Audio/SRT."
            )
            return
        start = str(project.root)
        audio_source, _ = QFileDialog.getOpenFileName(
            self,
            "Import TTS Audio",
            start,
            "Audio Files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus);;All Files (*)",
        )
        if not audio_source:
            return
        subtitle_source, _ = QFileDialog.getOpenFileName(
            self,
            "Import Narration SRT",
            str(Path(audio_source).parent),
            "SubRip Subtitle (*.srt);;All Files (*)",
        )
        if not subtitle_source:
            return
        outputs_exist = (
            project.path_for("audio_file").exists()
            or project.path_for("subtitle_file").exists()
        )
        if outputs_exist:
            answer = QMessageBox.question(
                self,
                "Replace Voice Audio/SRT",
                "Replace the current narration Audio and SRT with the selected files?\n\n"
                "Beat, music, footage and video outputs already created may need "
                "to be generated again.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        cancellation = CancellationToken()
        self.tts_cancellation = cancellation
        self.tts_running = True
        self.active_tts_stage = "voice"
        self._update_pipeline_actions()
        self.start_stage("voice", "Validating imported Audio/SRT…")
        self.append_log(f"Import audio selected: {audio_source}", "VOICE")
        self.append_log(f"Import SRT selected: {subtitle_source}", "VOICE")

        def operation(report: Callable[[object], None]) -> object:
            voice = self.voice_import_service.run(
                audio_source,
                subtitle_source,
                project,
                lambda update: report(update),
                cancellation,
                replace_existing=outputs_exist,
            )
            screen = self.tts_workflow_service.generate_screen_subtitles(
                project,
                self.settings.normalized(),
                lambda update: report(update),
                cancellation,
                replace_existing=project.path_for("screen_subtitle_file").exists(),
            )
            return VoiceResult(
                voice.job_id,
                voice.audio_file,
                voice.subtitle_file,
                screen,
            )

        self.start_progress_job(
            operation,
            self._voice_generation_succeeded,
            self._tts_pipeline_progress,
            self._tts_pipeline_failed,
            self._tts_pipeline_finished,
        )

    @Slot()
    def open_subtitle_review(self) -> None:
        if self.current_project is None or self.tts_running:
            return
        narration_path = self.current_project.path_for("subtitle_file")
        screen_path = self.current_project.path_for("screen_subtitle_file")
        if not narration_path.is_file() or not screen_path.is_file():
            QMessageBox.information(
                self,
                "Screen Subtitle Review",
                "Cần có cả narration.srt và screen.srt để mở Review.",
            )
            return
        try:
            dialog = SubtitleReviewDialog(narration_path, screen_path, self)
        except (OSError, ValueError, BeatWorkflowError) as exc:
            QMessageBox.critical(self, "Screen Subtitle Review", str(exc))
            return
        dialog.saved.connect(
            lambda path: self.append_log(f"Screen SRT edited: {path}", "VOICE")
        )
        dialog.exec()

    @Slot(object)
    def _voice_generation_succeeded(self, result: object) -> None:
        if not isinstance(result, VoiceResult):
            self._tts_pipeline_failed("Voice service returned an invalid result.")
            return
        self.append_log(f"Narration MP3: {result.audio_file}", "VOICE")
        self.append_log(f"Narration SRT: {result.subtitle_file}", "VOICE")
        if result.screen_subtitle_file is not None:
            self.append_log(
                f"Screen SRT: {result.screen_subtitle_file}", "VOICE"
            )
        if self.current_project is not None:
            self.current_project = self.workspace_service.open_project(
                self.current_project.root
            )
            self._apply_project_stage_states(self.current_project)

    @Slot()
    def run_tts_pipeline(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        if not self.snapshot.auth.authenticated:
            self.show_error("Hãy đăng nhập Codex bằng ChatGPT trước khi chạy TTS DNA.")
            return
        project = self.current_project
        settings = self.settings.normalized()
        cancellation = CancellationToken()
        self.tts_cancellation = cancellation
        self.tts_running = True
        self.active_tts_stage = "tts_script"
        self._update_pipeline_actions()
        self.start_stage("tts_script", "Preparing TTS DNA transformation…")
        self.append_log("Starting DNA → TTS Script → Voice API pipeline.", "TTS")

        def operation(report: Callable[[object], None]) -> object:
            return self.tts_workflow_service.run(
                project,
                settings,
                lambda update: report(update),
                cancellation,
            )

        self.start_progress_job(
            operation,
            self._tts_pipeline_succeeded,
            self._tts_pipeline_progress,
            self._tts_pipeline_failed,
            self._tts_pipeline_finished,
        )

    @Slot()
    def cancel_tts_pipeline(self) -> None:
        cancellation = self.tts_cancellation
        stage = "TTS"
        if self.beat_running:
            cancellation = self.beat_cancellation
            stage = "BEAT"
        elif self.music_running:
            cancellation = self.music_cancellation
            stage = "MUSIC"
        elif self.footage_running:
            cancellation = self.footage_cancellation
            stage = "FOOTAGE"
        elif self.video_builder_running:
            cancellation = self.video_builder_cancellation
            stage = "VIDEO"
        if cancellation is None:
            return
        cancellation.cancel()
        self._stop_auto_workflow(f"Auto workflow cancellation requested at {stage}.")
        self.cancel_tts_button.setEnabled(False)
        self.append_log("Cancellation requested; waiting for the active call…", stage)

    @Slot(object)
    def _tts_pipeline_progress(self, result: object) -> None:
        if not isinstance(result, TTSProgress):
            return
        self.active_tts_stage = result.stage
        self.set_stage_state(
            result.stage, result.state, result.message, result.percent
        )
        self.append_log(result.message, result.stage.upper())

    @Slot(object)
    def _tts_pipeline_succeeded(self, result: object) -> None:
        if not isinstance(result, TTSWorkflowResult):
            self._tts_pipeline_failed("TTS service trả về kết quả không hợp lệ.")
            return
        self.append_log(f"TTS Script: {result.tts_script}", "TTS_SCRIPT")
        self.append_log(f"Narration MP3: {result.voice.audio_file}", "VOICE")
        self.append_log(f"Narration SRT: {result.voice.subtitle_file}", "VOICE")
        if self.current_project is not None:
            try:
                self.current_project = self.workspace_service.open_project(
                    self.current_project.root
                )
                self._apply_project_stage_states(self.current_project)
            except (ProjectError, OSError) as exc:
                self.append_log(f"Không refresh được manifest: {exc}", "ERROR")

    @Slot(str)
    def _tts_pipeline_failed(self, message: str) -> None:
        if self.tts_cancellation and self.tts_cancellation.cancelled:
            self._stop_auto_workflow("Auto stopped: TTS operation was cancelled.")
            self.append_log("TTS pipeline cancelled.", "TTS")
            if self.current_project is not None:
                self._apply_project_stage_states(self.current_project)
            return
        self._stop_auto_workflow(
            f"Auto stopped at {self.active_tts_stage}: {message}"
        )
        self.fail_stage(self.active_tts_stage, message)
        QMessageBox.critical(self, "TTS Pipeline", message)

    @Slot()
    def _tts_pipeline_finished(self) -> None:
        self.tts_running = False
        self.tts_cancellation = None
        self._update_pipeline_actions()
        self._schedule_auto_continue()

    @Slot()
    def run_beat_pipeline(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        if not self.snapshot.auth.authenticated:
            self.show_error("Hãy đăng nhập Codex bằng ChatGPT trước khi chạy Beat DNA.")
            return
        project = self.current_project
        beat_outputs_exist = (
            project.path_for("beat_file").exists()
            or project.path_for("beat_timing_file").exists()
        )
        if beat_outputs_exist and not self.auto_workflow_running:
            answer = QMessageBox.question(
                self,
                "Generate Beat DNA Again",
                "Tạo lại footage.csv và .storyflow/beat_timing.json?\n\n"
                "Footage và Video Timeline đã tạo trước đó có thể không còn khớp "
                "với Beat mới. Các file đó sẽ được giữ nguyên để anh kiểm tra hoặc "
                "chạy lại ở bước tương ứng.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        settings = self.settings.normalized()
        cancellation = CancellationToken()
        self.beat_cancellation = cancellation
        self.beat_running = True
        self._update_pipeline_actions()
        self.start_stage("beat", "Preparing Beat DNA transformation…")
        self.append_log(
            "Starting TTS Script + SRT timing → Beat DNA → footage.csv.",
            "BEAT",
        )

        def operation(report: Callable[[object], None]) -> object:
            return self.beat_workflow_service.run(
                project,
                settings,
                lambda update: report(update),
                cancellation,
                replace_existing=beat_outputs_exist,
            )

        self.start_progress_job(
            operation,
            self._beat_pipeline_succeeded,
            self._beat_pipeline_progress,
            self._beat_pipeline_failed,
            self._beat_pipeline_finished,
        )

    @Slot(object)
    def _beat_pipeline_progress(self, result: object) -> None:
        if not isinstance(result, BeatProgress):
            return
        self.set_stage_state(
            result.stage, result.state, result.message, result.percent
        )
        self.append_log(result.message, "BEAT")

    @Slot(object)
    def _beat_pipeline_succeeded(self, result: object) -> None:
        if not isinstance(result, BeatWorkflowResult):
            self._beat_pipeline_failed("Beat service trả về kết quả không hợp lệ.")
            return
        self.append_log(f"Footage CSV: {result.beat_file}", "BEAT")
        self.append_log(
            f"Validated {result.beat_count} beats across "
            f"{result.duration_seconds:.1f}s narration.",
            "BEAT",
        )
        if self.current_project is not None:
            try:
                self.current_project = self.workspace_service.open_project(
                    self.current_project.root
                )
                self._apply_project_stage_states(self.current_project)
            except (ProjectError, OSError) as exc:
                self.append_log(f"Không refresh được manifest: {exc}", "ERROR")

    @Slot(str)
    def _beat_pipeline_failed(self, message: str) -> None:
        if self.beat_cancellation and self.beat_cancellation.cancelled:
            self._stop_auto_workflow("Auto stopped: Beat generation was cancelled.")
            self.append_log("Beat pipeline cancelled.", "BEAT")
            if self.current_project is not None:
                self._apply_project_stage_states(self.current_project)
            return
        self._stop_auto_workflow(f"Auto stopped at Beat DNA: {message}")
        self.fail_stage("beat", message)
        QMessageBox.critical(self, "Beat DNA", message)

    @Slot()
    def _beat_pipeline_finished(self) -> None:
        self.beat_running = False
        self.beat_cancellation = None
        self._update_pipeline_actions()
        self._schedule_auto_continue()

    @Slot()
    def run_music_pipeline(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        if not self.snapshot.auth.authenticated:
            self.show_error(
                "Hãy đăng nhập Codex bằng ChatGPT trước khi chạy Background Music DNA."
            )
            return
        if not self.settings.music.enabled:
            self.show_error(
                "Hãy bật Use Background Music trong Settings trước khi chạy."
            )
            return
        project = self.current_project
        music_exists = (
            project.path_for("music_cue_file").exists()
            or project.path_for("background_music_file").exists()
            or music_analysis_path(project).exists()
        )
        skip_confirmation = self._skip_music_confirmation_once
        self._skip_music_confirmation_once = False
        if music_exists and not self.auto_workflow_running and not skip_confirmation:
            answer = QMessageBox.question(
                self,
                "Generate Background Music Again",
                "Replace the current music analysis, cue sheet and MP3?\n\n"
                "The existing outputs remain intact unless the new result is valid. "
                "Final MP4 and CapCut Draft should be exported again afterward.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        settings = self.settings.normalized()
        cancellation = CancellationToken()
        self.music_cancellation = cancellation
        self.music_running = True
        self._update_pipeline_actions()
        self.start_stage("music", "Preparing Background Music DNA…")
        self.append_log(
            "Starting TTS Script + SRT → Music DNA → cue_music.csv → MP3.",
            "MUSIC",
        )

        def operation(report: Callable[[object], None]) -> object:
            return self.music_workflow_service.run(
                project,
                settings,
                lambda update: report(update),
                cancellation,
                replace_existing=music_exists,
            )

        self.start_progress_job(
            operation,
            self._music_pipeline_succeeded,
            self._music_pipeline_progress,
            self._music_pipeline_failed,
            self._music_pipeline_finished,
        )

    @Slot(object)
    def _music_pipeline_progress(self, result: object) -> None:
        if not isinstance(result, MusicProgress):
            return
        self.set_stage_state(
            result.stage, result.state, result.message, result.percent
        )
        self.append_log(result.message, "MUSIC")

    @Slot(object)
    def _music_pipeline_succeeded(self, result: object) -> None:
        if not isinstance(result, MusicWorkflowResult):
            self._music_pipeline_failed("Music service trả về kết quả không hợp lệ.")
            return
        self.append_log(f"Music Cue Sheet: {result.cue_file}", "MUSIC")
        self.append_log(f"Background Music MP3: {result.audio_file}", "MUSIC")
        if result.analysis_file is not None:
            self.append_log(f"Music Analysis: {result.analysis_file}", "MUSIC")
        if result.recommendations_file is not None:
            self.append_log(
                f"Music Recommendations: {result.recommendations_file}", "MUSIC"
            )
        self.append_log(
            f"Validated and rendered {result.cue_count} cues across "
            f"{result.duration_seconds:.1f}s narration.",
            "MUSIC",
        )
        if result.recommendation_count:
            self.append_log(
                f"{result.recommendation_count} section(s) may benefit from "
                "additional music. Open Review in step 04.",
                "MUSIC",
            )
        if self.current_project is not None:
            try:
                self.current_project = self.workspace_service.open_project(
                    self.current_project.root
                )
                self._apply_project_stage_states(self.current_project)
            except (ProjectError, OSError) as exc:
                self.append_log(f"Không refresh được manifest: {exc}", "ERROR")

    @Slot(str)
    def _music_pipeline_failed(self, message: str) -> None:
        if self.music_cancellation and self.music_cancellation.cancelled:
            self._stop_auto_workflow("Auto stopped: Music generation was cancelled.")
            self.append_log("Background Music pipeline cancelled.", "MUSIC")
            if self.current_project is not None:
                self._apply_project_stage_states(self.current_project)
            return
        self._stop_auto_workflow(f"Auto stopped at Background Music: {message}")
        self.fail_stage("music", message)
        QMessageBox.critical(self, "Background Music", message)

    @Slot()
    def _music_pipeline_finished(self) -> None:
        self.music_running = False
        self.music_cancellation = None
        self._update_pipeline_actions()
        self._schedule_auto_continue()

    @Slot()
    def open_music_review(self) -> None:
        if self.current_project is None or self.music_running:
            return
        analysis_file = music_analysis_path(self.current_project)
        if not analysis_file.is_file():
            QMessageBox.information(
                self,
                "Background Music Review",
                "Hãy Generate Background Music trước khi mở Review.",
            )
            return
        try:
            dialog = MusicReviewDialog(analysis_file, self)
        except (MusicReviewError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Background Music Review", str(exc))
            return
        dialog.browse_catalog_requested.connect(
            lambda: QDesktopServices.openUrl(QUrl(MIXKIT_CATALOG_URL))
        )
        dialog.import_requested.connect(self.import_more_music)
        dialog.download_requested.connect(self.download_recommended_music)
        dialog.generate_again_requested.connect(
            lambda: QTimer.singleShot(0, self.run_music_pipeline)
        )
        dialog.exec()

    @Slot()
    def download_recommended_music(self) -> None:
        if self.current_project is None or self.music_running:
            return
        library = self.settings.music.library_folder.strip()
        recommendations = music_recommendations_path(self.current_project)
        if not library:
            QMessageBox.warning(
                self,
                "Find & Download Music",
                "Hãy cấu hình Music Library Folder trong Settings trước.",
            )
            return
        if not recommendations.is_file():
            QMessageBox.information(
                self,
                "Find & Download Music",
                "Chưa có music recommendations. Hãy Generate Background Music trước.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Download from ccMixter",
            "StoryFlow sẽ tìm và tải tối đa 3 track từ API công khai của "
            "ccMixter. Chỉ Public Domain hoặc CC BY được chấp nhận.\n\n"
            "Track CC BY bắt buộc ghi credit; StoryFlow sẽ tạo "
            "audio/music_attribution.txt. Bạn vẫn phải kiểm tra attribution và "
            "license trước khi xuất bản.\n\n"
            f"Terms: {CCMIXTER_TERMS_URL}\n\nTiếp tục?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        project = self.current_project
        self.music_running = True
        self._regenerate_music_after_download = False
        self._update_pipeline_actions()
        self.start_stage("music", "Searching ccMixter recommendations…")
        self.append_log(
            "Searching ccMixter for CC BY/Public Domain recommendation matches.",
            "MUSIC",
        )

        def operation(report: Callable[[object], None]) -> object:
            return self.music_catalog_service.find_and_download(
                recommendations,
                library,
                lambda update: report(update),
            )

        self.start_progress_job(
            operation,
            self._music_download_succeeded,
            self._music_download_progress,
            self._music_download_failed,
            self._music_download_finished,
        )

    @Slot(object)
    def _music_download_progress(self, result: object) -> None:
        if not isinstance(result, CatalogProgress):
            return
        self.set_stage_state("music", "running", result.message, result.percent)
        self.append_log(result.message, "MUSIC")

    @Slot(object)
    def _music_download_succeeded(self, result: object) -> None:
        if not isinstance(result, CatalogDownloadResult):
            self._music_download_failed("Music catalog returned an invalid result.")
            return
        self.append_log(
            f"Downloaded {len(result.imported)} track(s). Attribution: "
            f"{result.attribution_file}",
            "MUSIC",
        )
        for track in result.selected_tracks:
            self.append_log(
                f"{track.title} · {track.artist} · {track.license_name}", "MUSIC"
            )
        self._regenerate_music_after_download = True
        QMessageBox.information(
            self,
            "Music Downloaded",
            f"Đã tải và import {len(result.imported)} track(s).\n\n"
            f"Attribution:\n{result.attribution_file}\n\n"
            "StoryFlow sẽ chạy Generate Again để đánh giá thư viện mới.",
        )

    @Slot(str)
    def _music_download_failed(self, message: str) -> None:
        self._regenerate_music_after_download = False
        self.append_log(message, "ERROR")
        QMessageBox.critical(self, "Find & Download Music", message)
        if self.current_project is not None:
            self._apply_project_stage_states(self.current_project)

    @Slot()
    def _music_download_finished(self) -> None:
        regenerate = self._regenerate_music_after_download
        self._regenerate_music_after_download = False
        self.music_running = False
        self._update_pipeline_actions()
        if regenerate:
            self._skip_music_confirmation_once = True
            QTimer.singleShot(0, self.run_music_pipeline)

    @Slot()
    def import_more_music(self) -> None:
        library = self.settings.music.library_folder.strip()
        if not library:
            QMessageBox.warning(
                self,
                "Import More Music",
                "Hãy cấu hình Music Library Folder trong Settings trước.",
            )
            return
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Recommended Background Music",
            str(default_downloads_folder()),
            "Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;All Files (*)",
        )
        if not selected:
            return
        try:
            result = self.music_library_service.import_files(selected, library)
        except (MusicLibraryError, OSError) as exc:
            QMessageBox.critical(self, "Import More Music", str(exc))
            return
        self.append_log(
            f"Music Library updated · {len(result.imported)} imported · "
            f"{len(result.skipped)} duplicates. Use Generate Again to re-evaluate.",
            "MUSIC",
        )
        QMessageBox.information(
            self,
            "Music Library Updated",
            f"Imported {len(result.imported)} track(s).\n"
            "Choose Generate Again so Codex can evaluate the updated library.",
        )

    @Slot()
    def run_footage_pipeline(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        project = self.current_project
        settings = self.settings.normalized()
        cancellation = CancellationToken()
        self.footage_cancellation = cancellation
        self.footage_running = True
        self._update_pipeline_actions()
        self.start_stage("footage", "Preparing stock-footage search…")
        self.append_log(
            "Starting footage.csv → Pexels/Pixabay search → project video folder.",
            "FOOTAGE",
        )

        def operation(report: Callable[[object], None]) -> object:
            return self.footage_workflow_service.run(
                project,
                settings,
                lambda update: report(update),
                cancellation,
            )

        self.start_progress_job(
            operation,
            self._footage_pipeline_succeeded,
            self._footage_pipeline_progress,
            self._footage_pipeline_failed,
            self._footage_pipeline_finished,
        )

    @Slot(object)
    def _footage_pipeline_progress(self, result: object) -> None:
        if not isinstance(result, FootageProgress):
            return
        self.set_stage_state(
            result.stage, result.state, result.message, result.percent
        )
        self.append_log(result.message, "FOOTAGE")

    @Slot(object)
    def _footage_pipeline_succeeded(self, result: object) -> None:
        if not isinstance(result, FootageWorkflowResult):
            self._footage_pipeline_failed(
                "Footage Finder service trả về kết quả không hợp lệ."
            )
            return
        self.append_log(f"Footage Folder: {result.output_dir}", "FOOTAGE")
        self.append_log(f"Selection Manifest: {result.manifest_file}", "FOOTAGE")
        if result.planned_count:
            self.append_log(
                f"Dry Run planned {result.planned_count} clips; no MP4 downloaded.",
                "FOOTAGE",
            )
        else:
            self.append_log(
                f"Downloaded {result.downloaded_count} clips for "
                f"{result.beat_count} beats.",
                "FOOTAGE",
            )
        if self.current_project is not None:
            try:
                self.current_project = self.workspace_service.open_project(
                    self.current_project.root
                )
                self._apply_project_stage_states(self.current_project)
            except (ProjectError, OSError) as exc:
                self.append_log(f"Không refresh được manifest: {exc}", "ERROR")

        if self._supplemental_footage_active:
            if result.planned_count:
                self._stop_auto_workflow(
                    "Auto stopped: Footage Dry Run did not download supplemental clips."
                )
                QMessageBox.information(
                    self,
                    "Supplemental Footage",
                    "Dry Run chỉ tạo kế hoạch, chưa tải footage bổ sung. "
                    "Hãy tắt Dry Run rồi chạy lại.",
                )
                return
            answer = QMessageBox.question(
                self,
                "Supplemental Footage Ready",
                "Đã tìm và tải footage bổ sung. Tiếp tục Video Analyze?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._resume_video_analysis_after_footage = True
            else:
                self._stop_auto_workflow(
                    "Auto stopped after supplemental footage download."
                )

    @Slot(str)
    def _footage_pipeline_failed(self, message: str) -> None:
        if self.footage_cancellation and self.footage_cancellation.cancelled:
            self._stop_auto_workflow("Auto stopped: Footage Finder was cancelled.")
            self.append_log("Footage Finder cancelled.", "FOOTAGE")
            if self.current_project is not None:
                self._apply_project_stage_states(self.current_project)
            return
        self._stop_auto_workflow(f"Auto stopped at Footage Finder: {message}")
        self.fail_stage("footage", message)
        QMessageBox.critical(self, "Footage Finder", message)

    @Slot()
    def _footage_pipeline_finished(self) -> None:
        supplemental = self._supplemental_footage_active
        resume_analysis = self._resume_video_analysis_after_footage
        self._supplemental_footage_active = False
        self._resume_video_analysis_after_footage = False
        self.footage_running = False
        self.footage_cancellation = None
        self._update_pipeline_actions()
        if supplemental:
            if resume_analysis and self.current_project is not None:
                self._skip_video_analysis_confirmation = True
                QTimer.singleShot(0, self.run_video_builder_analysis)
            return
        self._schedule_auto_continue()

    @Slot()
    def run_video_builder_analysis(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        project = self.current_project
        timeline_outputs_exist = (
            project.path_for("video_timeline_file").exists()
            or project.path_for("video_timeline_csv").exists()
        )
        skip_confirmation = self._skip_video_analysis_confirmation
        self._skip_video_analysis_confirmation = False
        if timeline_outputs_exist and not skip_confirmation:
            answer = QMessageBox.question(
                self,
                "Analyze Timeline Again",
                "Run timeline analysis again and replace the current JSON/CSV plan?\n\n"
                "The current plan is restored automatically if analysis fails.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        settings = self.settings.normalized()
        cancellation = CancellationToken()
        self.video_builder_cancellation = cancellation
        self.video_builder_running = True
        self._update_pipeline_actions()
        self.start_stage("video_plan", "Preparing reusable timeline inputs…")
        self.append_log(
            "Starting SRT/Beat timing + Footage Finder outputs → draft timeline.",
            "VIDEO",
        )

        def operation(report: Callable[[object], None]) -> object:
            return self.video_builder_service.analyze(
                project,
                settings,
                lambda update: report(update),
                cancellation,
                replace_existing=timeline_outputs_exist,
            )

        self.start_progress_job(
            operation,
            self._video_builder_succeeded,
            self._video_builder_progress,
            self._video_builder_failed,
            self._video_builder_finished,
        )

    @Slot()
    def open_timeline_review(self) -> None:
        if self.current_project is None or self.video_builder_running:
            return
        try:
            review = self.video_builder_service.review(
                self.current_project, self.settings
            )
        except (OSError, ValueError, VideoBuilderWorkflowError) as exc:
            QMessageBox.critical(self, "Timeline Review", str(exc))
            return
        dialog = TimelineReviewDialog(review, self)
        self.active_timeline_review_dialog = dialog
        dialog.retry_missing_requested.connect(self._retry_missing_footage)
        dialog.preview_requested.connect(self._preview_timeline_footage)
        dialog.replace_requested.connect(self._replace_timeline_footage)
        dialog.exec()
        self.active_timeline_review_dialog = None

    @Slot()
    def _retry_missing_footage(self) -> None:
        self.append_log(
            "Timeline Review requested Retry Missing via Footage Finder.", "VIDEO"
        )
        self.run_footage_pipeline()

    @Slot(str)
    def _preview_timeline_footage(self, relative_path: str) -> None:
        if self.current_project is None:
            return
        try:
            path = (self.current_project.root / relative_path).resolve(strict=True)
            path.relative_to(self.current_project.root)
        except (OSError, ValueError):
            QMessageBox.critical(self, "Preview Clip", "Footage path không hợp lệ.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @Slot(int)
    def _replace_timeline_footage(self, cut_number: int) -> None:
        if self.current_project is None:
            return
        footage_dir = self.current_project.path_for("footage_dir")
        filename, _ = QFileDialog.getOpenFileName(
            self,
            f"Replace Footage for Cut {cut_number}",
            str(footage_dir),
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)",
        )
        if not filename:
            return
        try:
            self.video_builder_service.replace_clip(
                self.current_project,
                self.settings,
                cut_number,
                Path(filename),
            )
        except (OSError, ValueError, VideoBuilderWorkflowError) as exc:
            QMessageBox.critical(self, "Replace Clip", str(exc))
            return
        self.append_log(
            f"Cut {cut_number} manually replaced with {Path(filename).name}.",
            "VIDEO",
        )
        dialog = getattr(self, "active_timeline_review_dialog", None)
        if dialog is not None:
            dialog.accept()
        QMessageBox.information(
            self,
            "Replace Clip",
            "Clip đã được thay thế. Mở Review lại để xem timeline mới.",
        )

    @Slot()
    def open_export_dialog(self) -> None:
        if self.current_project is None or self.video_builder_running:
            return
        dialog = ExportChoiceDialog(
            self,
            capcut_draft_name=self.current_project.manifest.name,
        )
        if not dialog.exec():
            return
        if dialog.choice() == "render":
            self.run_video_render()
        elif dialog.choice() == "capcut":
            self.run_capcut_export(dialog.draft_name())

    @Slot()
    def run_video_render(self) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        project = self.current_project
        try:
            review = self.video_builder_service.review(project, self.settings)
        except (OSError, ValueError, VideoBuilderWorkflowError) as exc:
            QMessageBox.critical(self, "Final Render", str(exc))
            return
        if review.stale:
            self.append_log(
                "Timeline inputs changed after analysis; rendering the saved "
                "timeline without Analyze Again.",
                "VIDEO",
            )
        if review.missing_beats:
            QMessageBox.critical(
                self,
                "Final Render",
                "Timeline còn thiếu footage: " + ", ".join(review.missing_beats),
            )
            return
        if review.warning_count:
            answer = QMessageBox.question(
                self,
                "Render with Warnings",
                f"Timeline còn {review.warning_count} warning. Continue Final Render?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        final_exists = project.path_for("final_video_file").is_file()
        if final_exists:
            answer = QMessageBox.question(
                self,
                "Render Final Video Again",
                "Replace the current final video? The existing MP4 remains intact "
                "until the new render passes media validation.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        cancellation = CancellationToken()
        self.video_builder_cancellation = cancellation
        self.video_builder_running = True
        self._update_pipeline_actions()
        self.start_stage("video_plan", "Preparing low-memory Final Render…")
        self.append_log(
            "Starting timeline → normalized Cuts → narration/music mix → final MP4.",
            "VIDEO",
        )

        def operation(report: Callable[[object], None]) -> object:
            return self.video_builder_service.render(
                project,
                self.settings.normalized(),
                report,
                cancellation,
                replace_existing=final_exists,
            )

        self.start_progress_job(
            operation,
            self._video_render_succeeded,
            self._video_render_progress,
            self._video_render_failed,
            self._video_builder_finished,
        )

    @Slot()
    def run_capcut_export(self, draft_name: str | None = None) -> None:
        if (
            self.current_project is None
            or self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        ):
            return
        project = self.current_project
        selected_draft_name = str(
            draft_name or self.capcut_draft_name or project.manifest.name
        ).strip()
        if not selected_draft_name:
            QMessageBox.warning(
                self,
                "CapCut Project Name",
                "Hãy nhập tên dự án CapCut trước khi Export.",
            )
            return
        self.capcut_draft_name = ""
        package_exists = project.path_for("capcut_package_dir").is_dir()
        if package_exists:
            answer = QMessageBox.question(
                self,
                "Export CapCut Again",
                "Replace the current CapCut Package? The existing package remains "
                "intact until the new export is complete.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        settings = self.settings.normalized()
        cancellation = CancellationToken()
        self.video_builder_cancellation = cancellation
        self.video_builder_running = True
        self._update_pipeline_actions()
        self.start_stage("video_plan", "Preparing CapCut Package and Draft…")
        self.append_log(
            f"Exporting CapCut project: {selected_draft_name}",
            "VIDEO",
        )

        def operation(report: Callable[[object], None]) -> object:
            return self.video_builder_service.export_capcut(
                project,
                settings,
                lambda update: report(update),
                cancellation,
                replace_existing=package_exists,
                draft_name=selected_draft_name,
            )

        self.start_progress_job(
            operation,
            self._capcut_export_succeeded,
            self._capcut_export_progress,
            self._capcut_export_failed,
            self._video_builder_finished,
        )

    @Slot(object)
    def _capcut_export_progress(self, result: object) -> None:
        if not isinstance(result, CapCutExportProgress):
            return
        if result.state == "completed":
            self.complete_stage("video_plan", result.message)
        else:
            self.update_stage_progress(
                "video_plan", int(result.percent or 0), result.message
            )

    @Slot(object)
    def _capcut_export_succeeded(self, result: object) -> None:
        if not isinstance(result, CapCutExportResult):
            self._capcut_export_failed("CapCut exporter trả về kết quả không hợp lệ.")
            return
        self.append_log(f"CapCut Package: {result.package_dir}", "VIDEO")
        if result.draft_dir is not None:
            self.append_log(f"CapCut Draft: {result.draft_dir}", "VIDEO")
        else:
            self.append_log(
                "CapCut Draft was not created because no Template Draft is configured.",
                "VIDEO",
            )
        self.append_log(
            f"Exported {result.scene_count} editable scenes · "
            f"{format_duration(result.duration_seconds)}",
            "VIDEO",
        )
        if self.current_project is not None:
            self._apply_project_stage_states(self.current_project)

    @Slot(str)
    def _capcut_export_failed(self, message: str) -> None:
        if self.video_builder_cancellation and self.video_builder_cancellation.cancelled:
            self.append_log("CapCut Export cancelled; previous package was preserved.", "VIDEO")
            if self.current_project is not None:
                self._apply_project_stage_states(self.current_project)
            return
        self.fail_stage("video_plan", message)
        QMessageBox.critical(self, "CapCut Export", message)

    @Slot(object)
    def _video_render_progress(self, result: object) -> None:
        if not isinstance(result, VideoRenderProgress):
            return
        self.set_stage_state(result.stage, result.state, result.message, result.percent)
        self.append_log(result.message, "VIDEO")

    @Slot(object)
    def _video_render_succeeded(self, result: object) -> None:
        if not isinstance(result, VideoRenderResult):
            self._video_render_failed("Renderer trả về kết quả không hợp lệ.")
            return
        self.append_log(f"Final Video: {result.final_file}", "VIDEO")
        self.append_log(f"Attribution: {result.attribution_file}", "VIDEO")
        self.append_log(
            f"Rendered {result.cut_count} cuts · {format_duration(result.duration_seconds)} "
            f"· {result.size_bytes / (1024 * 1024):.1f} MB",
            "VIDEO",
        )
        if self.current_project is not None:
            try:
                self.current_project = self.workspace_service.open_project(
                    self.current_project.root
                )
                self._apply_project_stage_states(self.current_project)
            except (ProjectError, OSError) as exc:
                self.append_log(f"Không refresh được manifest: {exc}", "ERROR")

    @Slot(str)
    def _video_render_failed(self, message: str) -> None:
        if self.video_builder_cancellation and self.video_builder_cancellation.cancelled:
            self.append_log("Final Render cancelled; previous output was preserved.", "VIDEO")
            if self.current_project is not None:
                self._apply_project_stage_states(self.current_project)
            return
        self.fail_stage("video_plan", message)
        QMessageBox.critical(self, "Final Render", message)

    @Slot(object)
    def _video_builder_progress(self, result: object) -> None:
        if not isinstance(result, VideoBuilderProgress):
            return
        self.set_stage_state(
            result.stage, result.state, result.message, result.percent
        )
        self.append_log(result.message, "VIDEO")

    @Slot(object)
    def _video_builder_succeeded(self, result: object) -> None:
        if not isinstance(result, TimelineAnalysisResult):
            self._video_builder_failed(
                "Video Builder service trả về kết quả không hợp lệ."
            )
            return
        self.append_log(f"Timeline JSON: {result.timeline_file}", "VIDEO")
        self.append_log(f"Timeline CSV: {result.timeline_csv}", "VIDEO")
        self.append_log(
            f"Draft timeline: {result.cut_count} cuts · "
            f"{result.warning_count} warnings · "
            f"{format_duration(result.duration_seconds)}",
            "VIDEO",
        )
        if self.current_project is not None:
            try:
                self.current_project = self.workspace_service.open_project(
                    self.current_project.root
                )
                self._apply_project_stage_states(self.current_project)
            except (ProjectError, OSError) as exc:
                self.append_log(f"Không refresh được manifest: {exc}", "ERROR")
        self._offer_missing_footage_recovery()

    def _offer_missing_footage_recovery(self) -> None:
        if self.current_project is None:
            return
        try:
            review = self.video_builder_service.review(
                self.current_project, self.settings
            )
        except (OSError, ValueError, VideoBuilderWorkflowError) as exc:
            self._stop_auto_workflow(
                f"Auto stopped while checking missing footage: {exc}"
            )
            self.append_log(f"Could not inspect missing footage: {exc}", "ERROR")
            return
        if not review.missing_beats:
            return
        try:
            supplement_file = self.footage_workflow_service.write_supplement_request(
                self.current_project, review.missing_beats
            )
        except (OSError, ValueError, FootageWorkflowError) as exc:
            self._stop_auto_workflow(
                f"Auto stopped while creating supplemental footage file: {exc}"
            )
            QMessageBox.critical(self, "Missing Footage", str(exc))
            return
        beats = ", ".join(review.missing_beats)
        self.append_log(
            f"Missing footage: {beats}. Supplement file: {supplement_file}",
            "VIDEO",
        )
        answer = QMessageBox.question(
            self,
            "Missing Footage",
            f"Video Analyze còn thiếu footage cho: {beats}.\n\n"
            f"Đã tạo file bổ sung:\n{supplement_file}\n\n"
            "Tìm và tải thêm footage ngay?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._pending_supplemental_footage = True
        else:
            self._stop_auto_workflow(
                "Auto stopped: supplemental footage was not requested."
            )

    def _run_supplemental_footage(self) -> None:
        if self.current_project is None:
            return
        self._supplemental_footage_active = True
        self.append_log(
            "Resuming Footage Finder for the missing Beats only.", "FOOTAGE"
        )
        self.run_footage_pipeline()

    @Slot(str)
    def _video_builder_failed(self, message: str) -> None:
        if (
            self.video_builder_cancellation
            and self.video_builder_cancellation.cancelled
        ):
            self._stop_auto_workflow("Auto stopped: Video Analyze was cancelled.")
            self.append_log("Video Builder analysis cancelled.", "VIDEO")
            if self.current_project is not None:
                self._apply_project_stage_states(self.current_project)
            return
        self.fail_stage("video_plan", message)
        if message.startswith("Visual Model chưa có trong local cache."):
            answer = QMessageBox.question(
                self,
                "Download Visual Model",
                f"{message}\n\n"
                "Model chỉ được tải một lần và sẽ được lưu trong project cache. "
                "Cho phép tải và tự động Analyze Again?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.settings.video_builder.local_models_only = False
                try:
                    self.settings_store.save(self.settings)
                except Exception as exc:
                    save_error = f"Không lưu được quyền tải Visual Model: {exc}"
                    self._stop_auto_workflow(
                        f"Auto stopped at Video Analyze: {save_error}"
                    )
                    self.fail_stage("video_plan", save_error)
                    QMessageBox.critical(self, "Video Builder", save_error)
                    return
                self._retry_video_analysis_after_model_download = True
                self.append_log(
                    "Visual Model download enabled; analysis will restart automatically.",
                    "VIDEO",
                )
            else:
                self._stop_auto_workflow(
                    "Auto stopped: Visual Model download was not allowed."
                )
            return
        self._stop_auto_workflow(f"Auto stopped at Video Analyze: {message}")
        QMessageBox.critical(self, "Video Builder", message)

    @Slot()
    def _video_builder_finished(self) -> None:
        retry = self._retry_video_analysis_after_model_download
        supplemental = self._pending_supplemental_footage
        self._retry_video_analysis_after_model_download = False
        self._pending_supplemental_footage = False
        self.video_builder_running = False
        self.video_builder_cancellation = None
        self._update_pipeline_actions()
        if supplemental and self.current_project is not None:
            QTimer.singleShot(0, self._run_supplemental_footage)
        elif retry and self.current_project is not None:
            self._skip_video_analysis_confirmation = True
            QTimer.singleShot(0, self.run_video_builder_analysis)
        else:
            self._schedule_auto_continue()

    def _update_pipeline_actions(self) -> None:
        project = self.current_project
        has_script = bool(
            project and self._has_script_content(project.path_for("raw_script"))
        )
        tts_script_exists = bool(
            project and self._has_content(project.path_for("tts_script"))
        )
        voice_outputs_exist = bool(
            project
            and (
                project.path_for("audio_file").exists()
                or project.path_for("subtitle_file").exists()
            )
        )
        stage_busy = (
            self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        )
        ui_busy = stage_busy or self.auto_workflow_running
        self.auto_workflow_button.setEnabled(
            project is not None
            and not stage_busy
            and not self.auto_workflow_running
        )
        self.auto_workflow_button.setText(
            "Auto Running…" if self.auto_workflow_running else "Auto"
        )
        self.run_tts_button.setText(
            "Generate Again" if tts_script_exists else "Generate"
        )
        self.run_tts_button.setEnabled(has_script and not ui_busy)
        self.import_tts_button.setEnabled(project is not None and not ui_busy)
        self.run_voice_button.setText(
            "Generate Again" if voice_outputs_exist else "Generate"
        )
        self.run_voice_button.setEnabled(
            tts_script_exists and not ui_busy
        )
        self.import_voice_button.setEnabled(tts_script_exists and not ui_busy)
        subtitle_review_ready = bool(
            project
            and project.path_for("subtitle_file").is_file()
            and project.path_for("screen_subtitle_file").is_file()
        )
        self.review_subtitles_button.setEnabled(
            subtitle_review_ready and not ui_busy
        )
        beat_inputs_ready = bool(
            project
            and tts_script_exists
            and self._has_content(project.path_for("audio_file"))
            and self._has_content(project.path_for("subtitle_file"))
        )
        beat_exists = bool(
            project
            and (
                project.path_for("beat_file").exists()
                or project.path_for("beat_timing_file").exists()
            )
        )
        self.run_beat_button.setText("Generate Again" if beat_exists else "Generate")
        self.run_beat_button.setEnabled(beat_inputs_ready and not ui_busy)
        music_inputs_ready = beat_inputs_ready
        music_exists = bool(
            project
            and (
                project.path_for("music_cue_file").exists()
                or project.path_for("background_music_file").exists()
                or music_analysis_path(project).exists()
            )
        )
        self.run_music_button.setText(
            "Generate Again" if music_exists else "Generate"
        )
        self.run_music_button.setEnabled(
            self.settings.music.enabled
            and music_inputs_ready
            and not ui_busy
        )
        self.review_music_button.setEnabled(
            bool(project and music_analysis_path(project).is_file()) and not ui_busy
        )
        footage = self.settings.footage
        footage_sources_ready = (
            (footage.use_pexels or footage.use_pixabay)
            and (not footage.use_pexels or bool(footage.pexels_api_key))
            and (not footage.use_pixabay or bool(footage.pixabay_api_key))
        )
        footage_complete = bool(
            project and project.manifest.stages.get("footage") == "completed"
        )
        self.run_footage_button.setEnabled(
            bool(project and self._has_content(project.path_for("beat_file")))
            and footage_sources_ready
            and not footage_complete
            and not ui_busy
        )
        video_plan_exists = bool(
            project
            and (
                project.path_for("video_timeline_file").exists()
                or project.path_for("video_timeline_csv").exists()
            )
        )
        video_inputs_ready = bool(
            project
            and self._has_content(project.path_for("tts_script"))
            and self._has_content(project.path_for("audio_file"))
            and self._has_content(project.path_for("subtitle_file"))
            and self._has_content(project.path_for("beat_file"))
            and self._has_content(project.path_for("beat_timing_file"))
        )
        self.run_video_builder_button.setText(
            "Analyze Again" if video_plan_exists else "Analyze"
        )
        self.run_video_builder_button.setEnabled(video_inputs_ready and not ui_busy)
        self.review_timeline_button.setEnabled(video_plan_exists and not ui_busy)
        final_video_exists = bool(
            project and project.path_for("final_video_file").is_file()
        )
        self.export_video_button.setEnabled(video_plan_exists and not ui_busy)
        self.refresh_status_button.setEnabled(project is not None and not ui_busy)
        self.copy_project_path_action.setEnabled(project is not None)
        self.open_folder_button.setEnabled(not ui_busy)
        self.open_folder_button.setText(
            "Open Folder" if project is not None else "Open Project…"
        )
        self.open_folder_button.setAccessibleName(
            "Open Project Folder" if project is not None else "Open Project"
        )
        self.new_project_button.setEnabled(not ui_busy)
        self.open_existing_project_action.setEnabled(not ui_busy)
        self.switch_project_menu.setEnabled(
            not ui_busy
            and any(action.isEnabled() for action in self.switch_project_menu.actions())
        )
        self.cancel_tts_button.setEnabled(stage_busy)

    def current_ai_workdir(self) -> Path:
        if self.current_project is None:
            raise ProjectError("Hãy mở Project trước khi chạy Codex.")
        return self.current_project.root

    def _apply_project_stage_states(self, project: Project) -> None:
        raw_script = project.path_for("raw_script")
        tts_script = project.path_for("tts_script")
        audio_file = project.path_for("audio_file")
        subtitle_file = project.path_for("subtitle_file")
        screen_subtitle_file = project.path_for("screen_subtitle_file")
        beat_file = project.path_for("beat_file")
        music_cue_file = project.path_for("music_cue_file")
        background_music_file = project.path_for("background_music_file")

        if tts_script.is_file():
            self.set_stage_state(
                "tts_script", "completed", f"Created {tts_script.name}", 100
            )
        elif self._has_script_content(raw_script):
            self.set_stage_state(
                "tts_script", "ready", f"Ready from {raw_script.name}", 0
            )
        elif raw_script.is_file():
            self.set_stage_state(
                "tts_script", "waiting", f"{raw_script.name} is empty", 0
            )
        else:
            self.set_stage_state(
                "tts_script", "waiting", f"Add {raw_script.name} to project", 0
            )

        if (
            audio_file.is_file()
            and subtitle_file.is_file()
            and screen_subtitle_file.is_file()
        ):
            self.set_stage_state(
                "voice", "completed", "Narration Audio, SRT and screen.srt are ready", 100
            )
        elif audio_file.is_file() and subtitle_file.is_file():
            self.set_stage_state(
                "voice",
                "ready",
                "Narration is ready · Generate screen.srt with Codex",
                0,
            )
        elif tts_script.is_file():
            self.set_stage_state(
                "voice", "ready", f"Ready from {tts_script.name}", 0
            )
        else:
            self.set_stage_state(
                "voice", "waiting", f"Waiting for {tts_script.name}", 0
            )

        if beat_file.is_file():
            self.set_stage_state(
                "beat", "completed", f"Created {beat_file.name}", 100
            )
        elif (
            tts_script.is_file()
            and audio_file.is_file()
            and subtitle_file.is_file()
        ):
            self.set_stage_state(
                "beat", "ready", "TTS Script and narration timing are ready", 0
            )
        else:
            self.set_stage_state(
                "beat", "waiting", "Waiting for TTS Script, MP3 and SRT", 0
            )

        if not self.settings.music.enabled:
            self.set_stage_state(
                "music",
                "disabled",
                "Enable Use Background Music in Settings to run this stage",
                0,
            )
        elif music_cue_file.is_file() and background_music_file.is_file():
            self.set_stage_state(
                "music",
                "completed",
                "Created cue_music.csv and background_music.mp3",
                100,
            )
        elif music_cue_file.exists() or background_music_file.exists():
            self.set_stage_state(
                "music",
                "failed",
                "Music output is incomplete; remove it before regenerating",
                0,
            )
        elif (
            tts_script.is_file()
            and audio_file.is_file()
            and subtitle_file.is_file()
        ):
            self.set_stage_state(
                "music", "ready", "TTS Script and narration timing are ready", 0
            )
        else:
            self.set_stage_state(
                "music", "waiting", "Waiting for TTS Script, MP3 and SRT", 0
            )

        footage_manifest = project.path_for("footage_manifest")
        footage_settings = self.settings.footage
        footage_configured = (
            (footage_settings.use_pexels or footage_settings.use_pixabay)
            and (
                not footage_settings.use_pexels
                or bool(footage_settings.pexels_api_key)
            )
            and (
                not footage_settings.use_pixabay
                or bool(footage_settings.pixabay_api_key)
            )
        )
        if project.manifest.stages.get("footage") == "completed":
            self.set_stage_state(
                "footage", "completed", "Stock footage downloaded and indexed", 100
            )
        elif beat_file.is_file() and footage_configured:
            detail = (
                "Resume search from selected-footage.json"
                if footage_manifest.is_file()
                else "Ready from footage.csv"
            )
            self.set_stage_state("footage", "ready", detail, 0)
        elif beat_file.is_file():
            self.set_stage_state(
                "footage",
                "waiting",
                "Configure a Pexels/Pixabay API key in Settings",
                0,
            )
        else:
            self.set_stage_state(
                "footage", "waiting", "Waiting for footage.csv from Beat DNA", 0
            )

        timeline_file = project.path_for("video_timeline_file")
        timeline_csv = project.path_for("video_timeline_csv")
        final_video = project.path_for("final_video_file")
        beat_timing = project.path_for("beat_timing_file")
        if final_video.is_file():
            self.set_stage_state(
                "video_plan", "completed", "Final video is ready", 100
            )
        elif timeline_file.is_file() and timeline_csv.is_file():
            self.set_stage_state(
                "video_plan",
                "completed",
                "Draft timeline ready · Review/Render is the next milestone",
                100,
            )
        elif (
            tts_script.is_file()
            and audio_file.is_file()
            and subtitle_file.is_file()
            and beat_file.is_file()
            and beat_timing.is_file()
        ):
            self.set_stage_state(
                "video_plan",
                "ready",
                "Ready from validated Beat/SRT timing and Footage inventory",
                0,
            )
        elif beat_file.is_file() and not beat_timing.is_file():
            self.set_stage_state(
                "video_plan",
                "waiting",
                "Beat timing is missing · regenerate Beat DNA for Video Builder",
                0,
            )
        else:
            self.set_stage_state(
                "video_plan", "waiting", "Waiting for Voice and Beat DNA outputs", 0
            )
        self._apply_project_metrics(project)
        self._update_pipeline_actions()

    def _apply_project_metrics(self, project: Project) -> None:
        metrics = self.metrics_service.snapshot(project)
        narration_duration = float(
            metrics.audio_duration_seconds
            or max(30.0, metrics.character_count / 14.0)
        )
        estimated_beats = max(
            metrics.beat_count,
            1 if metrics.character_count else 0,
            round(narration_duration / 24.0),
        )
        desired_clips = estimated_beats * self.settings.footage.clips_per_beat
        missing_clips = max(0, desired_clips - metrics.footage_count)
        self.estimated_audio_duration = narration_duration
        self.estimated_cut_count = max(
            metrics.video_cut_count,
            estimated_beats,
        )
        self.stage_default_eta.update(
            {
                "tts_script": max(30.0, 30.0 + metrics.character_count / 90.0),
                "voice": max(45.0, narration_duration * 0.55),
                "beat": max(45.0, 40.0 + narration_duration * 0.10),
                "music": max(60.0, 40.0 + narration_duration * 0.25),
                "footage": max(
                    30.0,
                    estimated_beats * 4.0 + missing_clips * 20.0,
                ),
                "video_plan": max(
                    30.0,
                    20.0 + estimated_beats * 2.0 + metrics.footage_count * 2.0,
                ),
            }
        )
        script_metric = self.stage_metrics["tts_script"]
        word_label = "word" if metrics.word_count == 1 else "words"
        character_label = (
            "character" if metrics.character_count == 1 else "characters"
        )
        script_metric.setText(
            f"{metrics.word_count:,} {word_label} · "
            f"{metrics.character_count:,} {character_label}"
        )
        script_metric.setToolTip(
            f"Counted from {metrics.script_source}"
            if metrics.script_source
            else "No script content available"
        )
        self.stage_metrics["voice"].setText(
            f"Audio · {format_duration(metrics.audio_duration_seconds)}"
        )
        beat_label = "beat" if metrics.beat_count == 1 else "beats"
        self.stage_metrics["beat"].setText(
            f"{metrics.beat_count:,} {beat_label}"
        )
        cue_label = "cue" if metrics.music_cue_count == 1 else "cues"
        self.stage_metrics["music"].setText(
            f"{metrics.music_cue_count:,} {cue_label}"
        )
        clip_label = "clip" if metrics.footage_count == 1 else "clips"
        self.stage_metrics["footage"].setText(
            f"{metrics.footage_count:,} {clip_label}"
        )
        cut_label = "cut" if metrics.video_cut_count == 1 else "cuts"
        warning_label = "warning" if metrics.video_warning_count == 1 else "warnings"
        self.stage_metrics["video_plan"].setText(
            f"{metrics.video_cut_count:,} {cut_label} · "
            f"{metrics.video_warning_count:,} {warning_label}"
        )
        self._refresh_eta_labels()

    @staticmethod
    def _has_content(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def _has_script_content(path: Path) -> bool:
        try:
            if not path.is_file():
                return False
            document = path.read_text(encoding="utf-8-sig")
            return bool(extract_script_body(document).strip())
        except OSError:
            return False

    def set_stage_state(
        self,
        key: str,
        state: str,
        detail: str = "",
        progress: int | None = None,
    ) -> None:
        if key not in self.stage_labels:
            raise KeyError(key)
        normalized = state.strip().lower()
        if normalized not in {
            "waiting",
            "disabled",
            "ready",
            "running",
            "completed",
            "failed",
            "planned",
        }:
            raise ValueError(f"Unsupported stage state: {state}")
        label = self.stage_labels[key]
        previous_state = str(label.property("state") or "").lower()
        label.setText(normalized.title())
        label.setProperty("state", normalized)
        label.style().unpolish(label)
        label.style().polish(label)
        detail_label = self.stage_details[key]
        detail_label.setText(detail)
        detail_label.set_error_copy_text(detail if normalized == "failed" else None)
        bar = self.stage_progress[key]
        if normalized == "running" and progress is None:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            resolved = 100 if normalized == "completed" else int(progress or 0)
            bar.setValue(max(0, min(100, resolved)))
        bar.setProperty("state", normalized)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        if normalized == "running":
            if previous_state != "running" or key not in self.stage_started_at:
                self.stage_started_at[key] = time.monotonic()
                self.stage_initial_eta[key] = self._estimate_stage_seconds(
                    key, detail
                )
            self.stage_progress_percent[key] = progress
            self._update_stage_eta(key)
        else:
            self.stage_started_at.pop(key, None)
            self.stage_initial_eta.pop(key, None)
            self.stage_remaining_eta.pop(key, None)
            self.stage_progress_percent.pop(key, None)
            self.stage_eta_labels[key].setText("")
        self._refresh_auto_eta()

    def _estimate_stage_seconds(self, key: str, detail: str = "") -> float:
        if key != "video_plan":
            return self.stage_default_eta.get(key, 90.0)
        lowered = detail.casefold()
        duration = max(30.0, self.estimated_audio_duration)
        cuts = max(1, self.estimated_cut_count)
        if "capcut" in lowered:
            return max(45.0, duration * 0.65 + cuts * 2.0)
        if any(word in lowered for word in ("render", "mux", "final video")):
            return max(60.0, duration * 0.85 + cuts * 2.5)
        return self.stage_default_eta.get(key, 120.0)

    def _update_stage_eta(self, key: str) -> None:
        started = self.stage_started_at.get(key)
        if started is None:
            return
        elapsed = max(0.0, time.monotonic() - started)
        initial = max(10.0, self.stage_initial_eta.get(key, 90.0))
        baseline_remaining = max(5.0, initial - elapsed)
        percent = self.stage_progress_percent.get(key)
        remaining = baseline_remaining
        if percent is not None and 5 <= percent < 100 and elapsed >= 1.0:
            observed_remaining = elapsed * (100.0 - percent) / percent
            observed_weight = min(0.8, max(0.2, percent / 100.0))
            remaining = (
                baseline_remaining * (1.0 - observed_weight)
                + observed_remaining * observed_weight
            )
        self.stage_remaining_eta[key] = max(5.0, remaining)
        self.stage_eta_labels[key].setText(
            f"ETA ~{self._format_eta(self.stage_remaining_eta[key])}"
        )

    @Slot()
    def _refresh_eta_labels(self) -> None:
        for key in tuple(self.stage_started_at):
            self._update_stage_eta(key)
        self._refresh_auto_eta()

    def _refresh_auto_eta(self) -> None:
        if not hasattr(self, "auto_eta_label"):
            return
        if self.current_project is None:
            self.auto_eta_label.setText("Total ETA —")
            return
        total = 0.0
        for key in (
            "tts_script",
            "voice",
            "beat",
            "music",
            "footage",
            "video_plan",
        ):
            if key == "music" and not self.settings.music.enabled:
                continue
            state = str(self.stage_labels[key].property("state") or "").lower()
            if state == "running":
                total += self.stage_remaining_eta.get(
                    key, self.stage_default_eta.get(key, 90.0)
                )
            elif state != "completed":
                total += self.stage_default_eta.get(key, 90.0)
        video_state = str(
            self.stage_labels["video_plan"].property("state") or ""
        ).lower()
        video_detail = self.stage_details["video_plan"].text().casefold()
        export_running = video_state == "running" and any(
            word in video_detail for word in ("render", "mux", "capcut")
        )
        if not export_running:
            export_detail = (
                "CapCut" if self.auto_export_choice == "capcut" else "Final Render"
            )
            total += self._estimate_stage_seconds("video_plan", export_detail)
        self.auto_eta_label.setText(f"Total ~{self._format_eta(total)}")

    @staticmethod
    def _format_eta(seconds: float) -> str:
        value = max(0, int(round(seconds)))
        if value < 60:
            return f"{max(1, value)}s"
        minutes, remaining_seconds = divmod(value, 60)
        if minutes < 60:
            return f"{minutes}m {remaining_seconds:02d}s"
        hours, remaining_minutes = divmod(minutes, 60)
        return f"{hours}h {remaining_minutes:02d}m"

    def start_stage(self, key: str, detail: str) -> None:
        self.set_stage_state(key, "running", detail)
        self.append_log(detail, key.upper())

    def update_stage_progress(self, key: str, progress: int, detail: str) -> None:
        self.set_stage_state(key, "running", detail, progress)
        self.append_log(f"{progress}% · {detail}", key.upper())

    def complete_stage(self, key: str, detail: str) -> None:
        self.set_stage_state(key, "completed", detail, 100)
        self.append_log(detail, key.upper())

    def fail_stage(self, key: str, detail: str) -> None:
        self.set_stage_state(key, "failed", detail, 0)
        self.append_log(detail, "ERROR")

    @Slot()
    def clear_console(self) -> None:
        self.activity_console.clear()

    def append_log(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.activity_console.appendPlainText(
            f"[{timestamp}] [{level.strip().upper() or 'INFO'}] {message}"
        )
        scrollbar = self.activity_console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _remember_project(self, path: Path) -> None:
        value = str(path.resolve())
        recent = [item for item in self.settings.workspace.recent_projects if item != value]
        self.settings.workspace.recent_projects = [value, *recent][:12]
        self.settings.workspace.last_project = value
        if not self.settings.workspace.workspace_root:
            self.settings.workspace.workspace_root = str(path.parent)
        try:
            self.settings_store.save(self.settings)
        except Exception as exc:
            self.show_error(f"Không lưu được Recent Projects: {exc}")
        self._refresh_recent_projects()

    def _refresh_recent_projects(self) -> None:
        self.switch_project_menu.clear()
        current = (
            str(self.current_project.root.resolve())
            if self.current_project is not None
            else ""
        )
        has_switch_target = False
        for value in self.settings.workspace.recent_projects:
            path = Path(value)
            resolved = str(path.resolve())
            is_current = resolved == current
            label = f"{path.name}  ·  Current" if is_current else path.name
            action = self.switch_project_menu.addAction(label)
            action.setToolTip(resolved)
            action.setEnabled(not is_current)
            if not is_current:
                has_switch_target = True
            action.triggered.connect(
                lambda checked=False, project_path=resolved: (
                    self._confirm_switch_project(project_path)
                )
            )
        busy = (
            self.tts_running
            or self.beat_running
            or self.music_running
            or self.footage_running
            or self.video_builder_running
        )
        self.switch_project_menu.setEnabled(has_switch_target and not busy)

    def _confirm_switch_project(self, value: str) -> None:
        target = Path(value)
        current_name = (
            self.current_project.manifest.name
            if self.current_project is not None
            else "No project"
        )
        answer = QMessageBox.question(
            self,
            "Switch Project",
            f'Switch from "{current_name}" to "{target.name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            # Defer until the QAction finishes emitting; set_project rebuilds this menu.
            QTimer.singleShot(0, lambda path=value: self.open_project(path))

    def _restore_last_project(self) -> None:
        value = self.settings.workspace.last_project
        if not value:
            return
        try:
            project = self.workspace_service.open_project(value)
        except (ProjectError, OSError):
            return
        self.set_project(project)

    @Slot(str)
    def show_error(self, message: str) -> None:
        self.codex_button.setEnabled(True)
        if self.settings_dialog:
            self.settings_dialog.set_busy(False)
        self.append_log(message, "ERROR")
        QMessageBox.critical(self, "StoryFlow Studio", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if any(thread.isRunning() for thread in self.jobs):
            QMessageBox.information(
                self,
                "Task in progress",
                "Please wait for the current Codex task to finish.",
            )
            event.ignore()
            return
        event.accept()
