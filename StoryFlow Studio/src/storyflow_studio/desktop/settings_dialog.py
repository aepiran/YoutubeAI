"""StoryFlow application settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import (
    AISettings,
    AppSettings,
    BeatSettings,
    FootageSettings,
    MusicSettings,
    REASONING_EFFORTS,
    TTSSettings,
    VideoBuilderSettings,
    WorkspaceSettings,
)
from ..modules.ai.service import AISnapshot
from ..modules.music import (
    MIXKIT_CATALOG_URL,
    MIXKIT_LICENSE_NAME,
    MIXKIT_LICENSE_URL,
    MusicLibraryError,
    MusicLibraryService,
    default_downloads_folder,
)


FALLBACK_MODELS = (
    ("Codex Default (Recommended)", ""),
    ("GPT-5.6", "gpt-5.6"),
    ("GPT-5.6 Sol", "gpt-5.6-sol"),
    ("GPT-5.6 Terra", "gpt-5.6-terra"),
    ("GPT-5.6 Luna", "gpt-5.6-luna"),
    ("GPT-5.3 Codex Spark", "gpt-5.3-codex-spark"),
)

TTS_MODEL_OPTIONS = (
    ("Speech 2.8 HD", "speech-2.8-hd"),
    ("Speech 2.8 Turbo", "speech-2.8-turbo"),
    ("Speech 2.6 HD", "speech-2.6-hd"),
    ("Speech 2.6 Turbo", "speech-2.6-turbo"),
    ("Speech 2.5 HD Preview", "speech-2.5-hd-preview"),
    ("Speech 2.5 Turbo Preview", "speech-2.5-turbo-preview"),
    ("Speech 02 HD", "speech-02-hd"),
    ("Speech 02 Turbo", "speech-02-turbo"),
    ("Speech 01 HD", "speech-01-hd"),
    ("Speech 01 Turbo", "speech-01-turbo"),
)

TTS_LANGUAGE_OPTIONS = (
    "Auto Detect",
    "Chinese (Mandarin)",
    "Cantonese",
    "English",
    "Spanish",
    "French",
    "Russian",
    "German",
    "Portuguese",
    "Arabic",
    "Italian",
    "Japanese",
    "Korean",
    "Indonesian",
    "Vietnamese",
    "Turkish",
    "Dutch",
    "Ukrainian",
    "Thai",
    "Polish",
    "Romanian",
    "Greek",
    "Czech",
    "Finnish",
    "Hindi",
    "Bulgarian",
    "Danish",
    "Hebrew",
    "Malay",
    "Persian",
    "Slovak",
    "Swedish",
    "Croatian",
    "Filipino",
    "Hungarian",
    "Norwegian",
    "Slovenian",
    "Catalan",
    "Nynorsk",
    "Tamil",
    "Afrikaans",
)

PEXELS_API_URL = "https://www.pexels.com/api/"
PIXABAY_API_DOCS_URL = "https://pixabay.com/api/docs/"

class SettingsDialog(QDialog):
    refresh_requested = Signal()
    login_requested = Signal()

    def __init__(
        self,
        settings: AppSettings,
        snapshot: AISnapshot,
        parent=None,
        music_library_service: MusicLibraryService | None = None,
    ) -> None:
        super().__init__(parent)
        self.original = settings
        self.music_library_service = music_library_service or MusicLibraryService()
        self.setWindowTitle("Settings · StoryFlow Studio")
        self.resize(1120, 760)
        self.setMinimumSize(920, 650)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("SettingsSidebar")
        sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 24, 20, 20)
        sidebar_layout.setSpacing(16)
        sidebar_title = QLabel("CONFIGURATION")
        sidebar_title.setObjectName("SidebarTitle")
        sidebar_layout.addWidget(sidebar_title)

        self.section_names = (
            "ChatGPT / AI",
            "Workspace & Role",
            "TTS & Voice",
            "Background Music",
            "Beat DNA",
            "Footage Finder",
            "Video Builder",
        )
        self.navigation = QListWidget()
        self.navigation.setObjectName("SettingsNavigation")
        self.navigation.setSpacing(7)
        self.navigation.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.navigation.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        icons = (
            QStyle.StandardPixmap.SP_ComputerIcon,
            QStyle.StandardPixmap.SP_DirIcon,
            QStyle.StandardPixmap.SP_MediaVolume,
            QStyle.StandardPixmap.SP_DriveHDIcon,
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            QStyle.StandardPixmap.SP_DialogSaveButton,
            QStyle.StandardPixmap.SP_MediaPlay,
        )
        for label, icon in zip(self.section_names, icons, strict=True):
            item = QListWidgetItem(self.style().standardIcon(icon), label)
            item.setSizeHint(QSize(204, 54))
            self.navigation.addItem(item)
        sidebar_layout.addWidget(self.navigation, 1)
        content_layout.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("SettingsPages")
        self.pages.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self.pages.addWidget(self._build_ai_tab(settings.ai, snapshot))
        self.pages.addWidget(self._build_workspace_tab(settings.workspace))
        self.pages.addWidget(self._build_tts_tab(settings.tts))
        self.pages.addWidget(self._build_music_tab(settings.music))
        self.pages.addWidget(self._build_beat_tab(settings.beat))
        self.pages.addWidget(self._build_footage_tab(settings.footage))
        self.pages.addWidget(self._build_video_builder_tab(settings.video_builder))
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        content_layout.addWidget(self.pages, 1)
        layout.addWidget(content, 1)

        footer = QWidget()
        footer.setObjectName("SettingsFooter")
        footer.setFixedHeight(68)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(22, 14, 22, 14)
        footer_layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setObjectName("PrimaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer_layout.addWidget(buttons)
        layout.addWidget(footer)

    def _build_ai_tab(self, settings: AISettings, snapshot: AISnapshot) -> QWidget:
        page, layout = self._page()
        self._section_header(
            layout,
            "ChatGPT and AI",
            "Manage the Codex account, model, reasoning effort and project permission.",
        )
        account_box = QGroupBox("ChatGPT Account")
        account_layout = QVBoxLayout(account_box)
        status_row = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("StatusBadge")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.login_button = QPushButton("Sign in with ChatGPT")
        self.login_button.setObjectName("PrimaryButton")
        self.login_button.clicked.connect(self.login_requested)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.refresh_button)
        status_row.addWidget(self.login_button)
        account_layout.addLayout(status_row)
        self.account_detail = QLabel()
        self.account_detail.setObjectName("Muted")
        account_layout.addWidget(self.account_detail)
        layout.addWidget(account_box)

        preferences = QGroupBox("AI Preferences")
        preferences_grid = QGridLayout(preferences)
        self._configure_grid(preferences_grid, 2)
        self.model = QComboBox()
        self.reasoning = QComboBox()
        for effort in REASONING_EFFORTS:
            self.reasoning.addItem(
                "Model default" if effort == "default" else effort.capitalize(), effort
            )
        preferences_grid.addWidget(self._field("Model", self.model), 0, 0)
        preferences_grid.addWidget(
            self._field("Reasoning Effort", self.reasoning), 0, 1
        )
        permission = QLabel("Workspace Write · current project only")
        permission.setObjectName("Muted")
        permission.setObjectName("PermissionValue")
        preferences_grid.addWidget(
            self._field("Default Permission", permission), 1, 0, 1, 2
        )
        layout.addWidget(preferences)
        note = QLabel(
            "Uses the saved Codex ChatGPT session. StoryFlow does not use an "
            "OpenAI API key."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self._requested_model = settings.model
        self.set_snapshot(snapshot)
        reasoning_index = self.reasoning.findData(settings.reasoning_effort)
        self.reasoning.setCurrentIndex(max(0, reasoning_index))
        return self._scroll_page(page)

    def _build_workspace_tab(self, settings: WorkspaceSettings) -> QWidget:
        page, layout = self._page()
        self._section_header(
            layout,
            "Workspace and Role",
            "Choose where projects live and define the working role used by Codex.",
        )
        group = QGroupBox("Workspace Root")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(10)
        self.workspace_root = QLineEdit(settings.workspace_root)
        group_layout.addWidget(
            self._field(
                "Workspace Root",
                self._browse_row(
                    self.workspace_root, self._browse_workspace, "Browse…"
                ),
            )
        )
        hint = QLabel("New projects are created as direct child folders of this location.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        group_layout.addWidget(hint)
        layout.addWidget(group)

        role = QGroupBox("Role / Instructions")
        role_layout = QVBoxLayout(role)
        role_layout.setSpacing(12)
        self.role_file = QLineEdit(settings.role_file)
        role_layout.addWidget(
            self._field(
                "Role File",
                self._browse_row(
                    self.role_file, self._browse_role_file, "Choose…"
                ),
            )
        )
        self.role_instructions = QTextEdit(settings.role_instructions)
        self.role_instructions.setPlaceholderText(
            "Optional application-level instructions for Codex…"
        )
        self.role_instructions.setFixedHeight(150)
        role_layout.addWidget(self._field("Instructions", self.role_instructions))
        layout.addWidget(role)
        layout.addStretch(1)
        return self._scroll_page(page)

    def _build_tts_tab(self, settings: TTSSettings) -> QWidget:
        content, layout = self._page()
        self._section_header(
            layout,
            "TTS and Voice",
            "Configure TTS DNA, voice provider, runtime behavior and default outputs.",
        )
        dna = QGroupBox("TTS DNA")
        dna_layout = QVBoxLayout(dna)
        self.tts_dna = QLineEdit(settings.dna_path)
        dna_layout.addWidget(
            self._field(
                "DNA File",
                self._browse_row(self.tts_dna, self._browse_tts_dna, "Choose…"),
            )
        )
        layout.addWidget(dna)

        api = QGroupBox("Voice API")
        api_grid = QGridLayout(api)
        api_grid.setHorizontalSpacing(16)
        api_grid.setVerticalSpacing(12)
        api_grid.setColumnStretch(0, 1)
        api_grid.setColumnStretch(1, 1)
        self.tts_provider = QLineEdit(settings.provider)
        self.tts_base_url = QLineEdit(settings.api_base_url)
        self.tts_api_key = QLineEdit(settings.api_key)
        self.tts_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        show_key = QCheckBox("Show")
        show_key.toggled.connect(
            lambda checked: self.tts_api_key.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        api_grid.addWidget(self._field("Provider", self.tts_provider), 0, 0)
        api_grid.addWidget(self._field("API Base URL", self.tts_base_url), 0, 1)
        api_grid.addWidget(
            self._field("API Key", self._inline_row(self.tts_api_key, show_key)),
            1,
            0,
            1,
            2,
        )
        layout.addWidget(api)

        voice = QGroupBox("Voice")
        voice_grid = QGridLayout(voice)
        voice_grid.setHorizontalSpacing(16)
        voice_grid.setVerticalSpacing(12)
        voice_grid.setColumnStretch(0, 1)
        voice_grid.setColumnStretch(1, 1)
        self.voice_id = QLineEdit(settings.voice_id)
        self.voice_id.setPlaceholderText("Enter MiniMax voice_id")
        self.voice_model = QComboBox()
        for label, model_id in TTS_MODEL_OPTIONS:
            self.voice_model.addItem(label, model_id)
        model_index = self.voice_model.findData(settings.voice_model)
        if model_index < 0 and settings.voice_model:
            self.voice_model.addItem(
                f"{settings.voice_model} · Custom", settings.voice_model
            )
            model_index = self.voice_model.count() - 1
        self.voice_model.setCurrentIndex(max(0, model_index))
        self.language = QComboBox()
        self.language.addItems(TTS_LANGUAGE_OPTIONS)
        self.language.setCurrentText(settings.language)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.05)
        self.speed.setValue(settings.speed)
        self.pitch = QSpinBox()
        self.pitch.setRange(-12, 12)
        self.pitch.setValue(settings.pitch)
        self.volume = QDoubleSpinBox()
        self.volume.setRange(0.01, 10.0)
        self.volume.setSingleStep(0.1)
        self.volume.setValue(settings.volume)
        for row, left, right in (
            (0, ("Voice ID", self.voice_id), ("Voice Model", self.voice_model)),
            (1, ("Language", self.language), ("Speed", self.speed)),
            (2, ("Pitch", self.pitch), ("Volume", self.volume)),
        ):
            voice_grid.addWidget(self._field(*left), row, 0)
            voice_grid.addWidget(self._field(*right), row, 1)
        layout.addWidget(voice)

        runtime = QGroupBox("Runtime")
        runtime_grid = QGridLayout(runtime)
        runtime_grid.setHorizontalSpacing(16)
        runtime_grid.setVerticalSpacing(12)
        runtime_grid.setColumnStretch(0, 1)
        runtime_grid.setColumnStretch(1, 1)
        self.enable_srt = QCheckBox("Require subtitle output")
        self.enable_srt.setChecked(settings.enable_srt)
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 86400)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(settings.timeout_seconds)
        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(1, 300)
        self.poll_interval.setSuffix(" s")
        self.poll_interval.setValue(settings.poll_interval_seconds)
        self.max_retry = QSpinBox()
        self.max_retry.setRange(1, 20)
        self.max_retry.setValue(settings.max_retry)
        runtime_grid.addWidget(self._field("SRT", self.enable_srt), 0, 0)
        runtime_grid.addWidget(self._field("Timeout", self.timeout), 0, 1)
        runtime_grid.addWidget(
            self._field("Polling Interval", self.poll_interval), 1, 0
        )
        runtime_grid.addWidget(
            self._field("Maximum Attempts", self.max_retry), 1, 1
        )
        layout.addWidget(runtime)

        files = QGroupBox("Default Files")
        files_grid = QGridLayout(files)
        files_grid.setHorizontalSpacing(16)
        files_grid.setVerticalSpacing(12)
        files_grid.setColumnStretch(0, 1)
        files_grid.setColumnStretch(1, 1)
        self.tts_script_filename = QLineEdit(settings.script_filename)
        self.output_folder = QLineEdit(settings.output_folder)
        self.audio_filename = QLineEdit(settings.audio_filename)
        self.subtitle_filename = QLineEdit(settings.subtitle_filename)
        self.overwrite = QCheckBox("Allow replacing existing outputs")
        self.overwrite.setChecked(settings.overwrite_existing)
        files_grid.addWidget(
            self._field("TTS Script", self.tts_script_filename), 0, 0
        )
        files_grid.addWidget(
            self._field("Output Folder", self.output_folder), 0, 1
        )
        files_grid.addWidget(
            self._field("Audio Filename", self.audio_filename), 1, 0
        )
        files_grid.addWidget(
            self._field("Subtitle Filename", self.subtitle_filename), 1, 1
        )
        files_grid.addWidget(self._field("Overwrite", self.overwrite), 2, 0, 1, 2)
        layout.addWidget(files)
        layout.addStretch(1)

        return self._scroll_page(content)

    def _build_beat_tab(self, settings: BeatSettings) -> QWidget:
        page, layout = self._page()
        self._section_header(
            layout,
            "Beat DNA",
            "Configure how narration timing is transformed into the footage beat file.",
        )
        group = QGroupBox("Beat DNA")
        beat_grid = QGridLayout(group)
        self._configure_grid(beat_grid, 2)
        self.beat_dna = QLineEdit(settings.dna_path)
        self.beat_filename = QLineEdit(settings.output_filename)
        beat_grid.addWidget(
            self._field(
                "DNA File",
                self._browse_row(self.beat_dna, self._browse_beat_dna, "Choose…"),
            ),
            0,
            0,
        )
        beat_grid.addWidget(
            self._field("Output Filename", self.beat_filename), 0, 1
        )
        layout.addWidget(group)
        inputs = QGroupBox("Pipeline Inputs")
        input_grid = QGridLayout(inputs)
        self._configure_grid(input_grid, 3)
        for column, (label, value) in enumerate((
            ("Content", "TTS Script from project manifest"),
            ("Timing", "Narration SRT from project manifest"),
            ("Duration", "Narration MP3 from project manifest"),
        )):
            text = QLabel(value)
            text.setObjectName("InputSummary")
            text.setWordWrap(True)
            input_grid.addWidget(self._field(label, text), 0, column)
        layout.addWidget(inputs)
        layout.addStretch(1)
        return self._scroll_page(page)

    def _build_music_tab(self, settings: MusicSettings) -> QWidget:
        page, layout = self._page()
        self._section_header(
            layout,
            "Background Music",
            "Configure Background Music DNA and the local Music Library. Outputs "
            "are always saved as audio/cue_music.csv and "
            "audio/background_music.mp3.",
        )

        usage = QGroupBox("Workflow")
        usage_layout = QVBoxLayout(usage)
        self.enable_music = QCheckBox("Use Background Music")
        self.enable_music.setChecked(settings.enabled)
        self.enable_music.setToolTip(
            "Enable the Background Music stage for StoryFlow projects"
        )
        usage_layout.addWidget(self.enable_music)
        usage_hint = QLabel(
            "When disabled, StoryFlow skips this stage and does not generate "
            "cue_music.csv or background_music.mp3."
        )
        usage_hint.setObjectName("SettingsDescription")
        usage_hint.setWordWrap(True)
        usage_layout.addWidget(usage_hint)
        layout.addWidget(usage)

        source = QGroupBox("Music Source")
        source_grid = QGridLayout(source)
        self._configure_grid(source_grid, 2)
        self.music_dna = QLineEdit(settings.dna_path)
        self.music_dna.setPlaceholderText(
            "Leave empty to use the built-in Background Music DNA"
        )
        self.music_library = QLineEdit(settings.library_folder)
        self.music_library.setPlaceholderText("Folder containing downloaded music tracks")
        source_grid.addWidget(
            self._field(
                "DNA File (Optional)",
                self._browse_row(self.music_dna, self._browse_music_dna, "Choose…"),
            ),
            0,
            0,
        )
        source_grid.addWidget(
            self._field(
                "Music Library Folder",
                self._browse_row(
                    self.music_library, self._browse_music_library, "Choose…"
                ),
            ),
            0,
            1,
        )
        library_actions = QHBoxLayout()
        self.music_import_button = QPushButton("Import Downloaded Music…")
        self.music_import_button.setObjectName("PrimaryButton")
        self.music_import_button.setAccessibleName("Import Downloaded Music")
        self.music_import_button.setToolTip(
            "Review audio files from Downloads and import them into Music Library"
        )
        self.music_import_button.clicked.connect(self._import_downloaded_music)
        self.music_open_library_button = QPushButton("Open Music Library")
        self.music_open_library_button.clicked.connect(self._open_music_library)
        library_actions.addWidget(self.music_import_button)
        library_actions.addWidget(self.music_open_library_button)
        library_actions.addStretch(1)
        source_grid.addLayout(library_actions, 1, 0, 1, 2)
        layout.addWidget(source)

        license_group = QGroupBox("Download Music · Mixkit")
        license_layout = QVBoxLayout(license_group)
        license_layout.setSpacing(10)
        license_info = QLabel(
            f"License: {MIXKIT_LICENSE_NAME}\n"
            f"License URL: {MIXKIT_LICENSE_URL}\n"
            f"Catalog URL: {MIXKIT_CATALOG_URL}"
        )
        license_info.setObjectName("InputSummary")
        license_info.setWordWrap(True)
        license_info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        license_layout.addWidget(license_info)
        download_hint = QLabel(
            "Open the Mixkit catalog in your browser, download suitable tracks, "
            "then choose Import Downloaded Music to validate and add them to the "
            "configured Music Library."
        )
        download_hint.setObjectName("SettingsDescription")
        download_hint.setWordWrap(True)
        license_layout.addWidget(download_hint)
        actions = QHBoxLayout()
        self.music_license_button = QPushButton("View License")
        self.music_license_button.setAccessibleName("View Mixkit Music License")
        self.music_license_button.clicked.connect(
            lambda: self._open_external_url(MIXKIT_LICENSE_URL)
        )
        self.music_catalog_button = QPushButton("Browse & Download Music")
        self.music_catalog_button.setObjectName("PrimaryButton")
        self.music_catalog_button.setAccessibleName("Open Mixkit Music Catalog")
        self.music_catalog_button.clicked.connect(
            lambda: self._open_external_url(MIXKIT_CATALOG_URL)
        )
        actions.addWidget(self.music_license_button)
        actions.addWidget(self.music_catalog_button)
        actions.addStretch(1)
        license_layout.addLayout(actions)
        layout.addWidget(license_group)
        layout.addStretch(1)
        return self._scroll_page(page)

    def _build_footage_tab(self, settings: FootageSettings) -> QWidget:
        page, layout = self._page()
        self._section_header(
            layout,
            "Footage Finder",
            "Search and download stock footage for footage.csv. Video Builder "
            "is not executed in this phase.",
        )

        sources = QGroupBox("Sources and API")
        sources_grid = QGridLayout(sources)
        self._configure_grid(sources_grid, 2)
        self.footage_use_pexels = QCheckBox("Use Pexels")
        self.footage_use_pexels.setChecked(settings.use_pexels)
        self.footage_use_pixabay = QCheckBox("Use Pixabay")
        self.footage_use_pixabay.setChecked(settings.use_pixabay)
        self.pexels_api_key = QLineEdit(settings.pexels_api_key)
        self.pexels_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.pexels_api_key.setPlaceholderText("PEXELS_API_KEY")
        self.pixabay_api_key = QLineEdit(settings.pixabay_api_key)
        self.pixabay_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.pixabay_api_key.setPlaceholderText("PIXABAY_API_KEY")
        sources_grid.addWidget(
            self._field(
                "Pexels",
                self._inline_row(self.pexels_api_key, self.footage_use_pexels),
            ),
            0,
            0,
        )
        sources_grid.addWidget(
            self._field(
                "Pixabay",
                self._inline_row(self.pixabay_api_key, self.footage_use_pixabay),
            ),
            0,
            1,
        )
        source_note = QLabel(
            "API keys are stored in the operating-system keyring and never in "
            "settings.json or the project manifest."
        )
        source_note.setObjectName("SettingsDescription")
        source_note.setWordWrap(True)
        sources_grid.addWidget(source_note, 1, 0, 1, 2)
        provider_links = QHBoxLayout()
        self.pexels_api_button = QPushButton("Pexels API")
        self.pexels_api_button.clicked.connect(
            lambda: self._open_external_url(PEXELS_API_URL)
        )
        self.pixabay_api_button = QPushButton("Pixabay API")
        self.pixabay_api_button.clicked.connect(
            lambda: self._open_external_url(PIXABAY_API_DOCS_URL)
        )
        provider_links.addWidget(self.pexels_api_button)
        provider_links.addWidget(self.pixabay_api_button)
        provider_links.addStretch(1)
        sources_grid.addLayout(provider_links, 2, 0, 1, 2)
        layout.addWidget(sources)

        search = QGroupBox("Search and Downloads")
        search_grid = QGridLayout(search)
        self._configure_grid(search_grid, 2)
        self.footage_max_queries = QSpinBox()
        self.footage_max_queries.setRange(1, 5)
        self.footage_max_queries.setValue(settings.max_queries)
        self.footage_max_pages = QSpinBox()
        self.footage_max_pages.setRange(1, 10)
        self.footage_max_pages.setValue(settings.max_pages)
        self.footage_per_page = QSpinBox()
        self.footage_per_page.setRange(3, 80)
        self.footage_per_page.setValue(settings.per_page)
        self.footage_clips_per_beat = QSpinBox()
        self.footage_clips_per_beat.setRange(1, 4)
        self.footage_clips_per_beat.setValue(settings.clips_per_beat)
        self.footage_pixabay_cap = QSpinBox()
        self.footage_pixabay_cap.setRange(0, 500)
        self.footage_pixabay_cap.setValue(settings.max_pixabay_downloads)
        for index, (label, widget) in enumerate(
            (
                ("Queries per Beat", self.footage_max_queries),
                ("Pages per Query", self.footage_max_pages),
                ("Results per Page", self.footage_per_page),
                ("Clips per Beat", self.footage_clips_per_beat),
                ("Pixabay Download Cap", self.footage_pixabay_cap),
            )
        ):
            search_grid.addWidget(self._field(label, widget), index // 2, index % 2)
        layout.addWidget(search)

        quality = QGroupBox("Quality")
        quality_grid = QGridLayout(quality)
        self._configure_grid(quality_grid, 2)
        self.footage_min_duration = QDoubleSpinBox()
        self.footage_min_duration.setRange(1.0, 120.0)
        self.footage_min_duration.setDecimals(1)
        self.footage_min_duration.setSuffix(" s")
        self.footage_min_duration.setValue(settings.min_duration)
        self.footage_min_width = QSpinBox()
        self.footage_min_width.setRange(640, 7680)
        self.footage_min_width.setValue(settings.min_width)
        self.footage_min_height = QSpinBox()
        self.footage_min_height.setRange(360, 4320)
        self.footage_min_height.setValue(settings.min_height)
        self.footage_dry_run = QCheckBox(
            "Dry Run · create selection manifest without downloading MP4"
        )
        self.footage_dry_run.setChecked(settings.dry_run)
        quality_grid.addWidget(
            self._field("Minimum Duration", self.footage_min_duration), 0, 0
        )
        quality_grid.addWidget(
            self._field("Minimum Width", self.footage_min_width), 0, 1
        )
        quality_grid.addWidget(
            self._field("Minimum Height", self.footage_min_height), 1, 0
        )
        quality_grid.addWidget(self.footage_dry_run, 1, 1)
        layout.addWidget(quality)
        layout.addStretch(1)
        return self._scroll_page(page)

    def _build_video_builder_tab(
        self, settings: VideoBuilderSettings
    ) -> QWidget:
        page, layout = self._page()
        self._section_header(
            layout,
            "Video Builder",
            "Create a reviewable draft timeline from validated Beat timing and "
            "downloaded footage. Final MP4 rendering is a later milestone.",
        )

        video_group = QGroupBox("Video and Runtime")
        video_grid = QGridLayout(video_group)
        self._configure_grid(video_grid, 2)
        self.builder_resolution = QComboBox()
        self.builder_resolution.addItems(["1080p", "720p"])
        self.builder_resolution.setCurrentText(settings.resolution)
        self.builder_fps = QSpinBox()
        self.builder_fps.setRange(24, 60)
        self.builder_fps.setSuffix(" fps")
        self.builder_fps.setValue(settings.output_fps)
        self.builder_workers = QSpinBox()
        self.builder_workers.setRange(1, 16)
        self.builder_workers.setValue(settings.analysis_workers)
        self.builder_preset = QComboBox()
        for preset in (
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
        ):
            self.builder_preset.addItem(preset.capitalize(), preset)
        preset_index = self.builder_preset.findData(settings.encoder_preset)
        self.builder_preset.setCurrentIndex(max(0, preset_index))
        for index, (label, widget) in enumerate(
            (
                ("Resolution", self.builder_resolution),
                ("Output Frame Rate", self.builder_fps),
                ("Analysis Workers", self.builder_workers),
                ("Encoder Preset", self.builder_preset),
            )
        ):
            video_grid.addWidget(self._field(label, widget), index // 2, index % 2)
        layout.addWidget(video_group)

        cut_group = QGroupBox("Timeline and Cut Profile")
        cut_grid = QGridLayout(cut_group)
        self._configure_grid(cut_grid, 2)
        self.builder_min_cut = QDoubleSpinBox()
        self.builder_target_cut = QDoubleSpinBox()
        self.builder_max_cut = QDoubleSpinBox()
        for widget, value in (
            (self.builder_min_cut, settings.min_cut_seconds),
            (self.builder_target_cut, settings.target_cut_seconds),
            (self.builder_max_cut, settings.max_cut_seconds),
        ):
            widget.setRange(1.0, 60.0)
            widget.setDecimals(2)
            widget.setSuffix(" s")
            widget.setValue(value)
        self.builder_transition = QDoubleSpinBox()
        self.builder_transition.setRange(0.0, 2.0)
        self.builder_transition.setDecimals(2)
        self.builder_transition.setSuffix(" s")
        self.builder_transition.setValue(settings.transition_seconds)
        self.builder_minimum_minutes = QDoubleSpinBox()
        self.builder_minimum_minutes.setRange(0.0, 180.0)
        self.builder_minimum_minutes.setDecimals(1)
        self.builder_minimum_minutes.setSuffix(" min")
        self.builder_minimum_minutes.setSpecialValueText("Disabled")
        self.builder_minimum_minutes.setValue(settings.minimum_video_minutes)
        for index, (label, widget) in enumerate(
            (
                ("Minimum Cut", self.builder_min_cut),
                ("Target Cut", self.builder_target_cut),
                ("Maximum Cut", self.builder_max_cut),
                ("Transition", self.builder_transition),
                ("Minimum Video Duration", self.builder_minimum_minutes),
            )
        ):
            cut_grid.addWidget(self._field(label, widget), index // 2, index % 2)
        timing_note = QLabel(
            "StoryFlow reuses narration.srt and .storyflow/beat_timing.json; "
            "Whisper is not run again. Minimum Video Duration is disabled by default."
        )
        timing_note.setObjectName("SettingsDescription")
        timing_note.setWordWrap(True)
        cut_grid.addWidget(timing_note, 3, 0, 1, 2)
        layout.addWidget(cut_group)

        visual_group = QGroupBox("Visual Analysis")
        visual_grid = QGridLayout(visual_group)
        self._configure_grid(visual_grid, 2)
        self.builder_visual_model = QComboBox()
        for label, value in (
            ("Technical Only (No ML)", "disabled"),
            ("CLIP ViT-B/32", "openai/clip-vit-base-patch32"),
            ("SigLIP 2 Base", "google/siglip2-base-patch16-224"),
        ):
            self.builder_visual_model.addItem(label, value)
        visual_index = self.builder_visual_model.findData(settings.visual_model)
        self.builder_visual_model.setCurrentIndex(max(0, visual_index))
        self.builder_local_models = QCheckBox("Use local model cache only")
        self.builder_local_models.setChecked(settings.local_models_only)
        self.builder_scene_threshold = QDoubleSpinBox()
        self.builder_scene_threshold.setRange(0.05, 0.95)
        self.builder_scene_threshold.setDecimals(2)
        self.builder_scene_threshold.setSingleStep(0.05)
        self.builder_scene_threshold.setValue(settings.scene_threshold)
        self.builder_scene_min = QDoubleSpinBox()
        self.builder_scene_min.setRange(0.5, 10.0)
        self.builder_scene_min.setDecimals(1)
        self.builder_scene_min.setSuffix(" s")
        self.builder_scene_min.setValue(settings.scene_min_seconds)
        for index, (label, widget) in enumerate(
            (
                ("Semantic Model", self.builder_visual_model),
                ("Scene Threshold", self.builder_scene_threshold),
                ("Minimum Scene", self.builder_scene_min),
                ("Model Runtime", self.builder_local_models),
            )
        ):
            visual_grid.addWidget(self._field(label, widget), index // 2, index % 2)
        visual_note = QLabel(
            "CLIP/SigLIP requires the optional torch, transformers and Pillow "
            "runtime. The selected model is downloaded once and cached in the project. "
            "Enable local-only mode only after that first download."
        )
        visual_note.setObjectName("SettingsDescription")
        visual_note.setWordWrap(True)
        visual_grid.addWidget(visual_note, 2, 0, 1, 2)
        layout.addWidget(visual_group)
        layout.addStretch(1)
        return self._scroll_page(page)

    @staticmethod
    def _page() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 30, 42, 30)
        layout.setSpacing(16)
        return page, layout

    @staticmethod
    def _scroll_page(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        scroll.setWidget(content)
        return scroll

    @staticmethod
    def _section_header(layout: QVBoxLayout, title: str, description: str) -> None:
        title_label = QLabel(title)
        title_label.setObjectName("SettingsTitle")
        description_label = QLabel(description)
        description_label.setObjectName("SettingsDescription")
        description_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(description_label)

    @staticmethod
    def _configure_grid(layout: QGridLayout, columns: int) -> None:
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(12)
        for column in range(columns):
            layout.setColumnStretch(column, 1)

    @staticmethod
    def _inline_row(*widgets: QWidget) -> QWidget:
        row = QWidget()
        row.setObjectName("InlineRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, 1 if index == 0 else 0)
        return row

    @staticmethod
    def _field(label: str, widget: QWidget) -> QWidget:
        field = QWidget()
        field.setObjectName("FormField")
        layout = QVBoxLayout(field)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label_widget = QLabel(label)
        label_widget.setObjectName("FieldLabel")
        layout.addWidget(label_widget)
        layout.addWidget(widget)
        return field

    def _browse_row(self, field: QLineEdit, callback, label: str) -> QWidget:
        button = QPushButton(label)
        button.clicked.connect(callback)
        return self._inline_row(field, button)

    def _browse_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Select Workspace Root", self.workspace_root.text()
        )
        if selected:
            self.workspace_root.setText(selected)

    def _choose_file(self, title: str, field: QLineEdit, filters: str) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, title, field.text(), filters)
        if selected:
            field.setText(selected)

    def _browse_role_file(self) -> None:
        self._choose_file("Select Role File", self.role_file, "Markdown/Text (*.md *.txt);;All (*)")

    def _browse_tts_dna(self) -> None:
        self._choose_file("Select TTS DNA", self.tts_dna, "Markdown (*.md);;All (*)")

    def _browse_beat_dna(self) -> None:
        self._choose_file("Select Beat DNA", self.beat_dna, "Markdown (*.md);;All (*)")

    def _browse_music_dna(self) -> None:
        self._choose_file(
            "Select Background Music DNA",
            self.music_dna,
            "Markdown (*.md);;All (*)",
        )

    def _browse_music_library(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Music Library Folder",
            self.music_library.text(),
        )
        if selected:
            self.music_library.setText(selected)

    @Slot()
    def _import_downloaded_music(self) -> None:
        library = self.music_library.text().strip()
        if not library:
            QMessageBox.warning(
                self,
                "Background Music",
                "Hãy chọn Music Library Folder trước khi import.",
            )
            return
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Downloaded Music",
            str(default_downloads_folder()),
            "Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;All Files (*)",
        )
        if not selected:
            return
        try:
            result = self.music_library_service.import_files(selected, library)
        except (MusicLibraryError, OSError) as exc:
            QMessageBox.critical(self, "Music Library Import", str(exc))
            return
        parts = [f"Imported: {len(result.imported)} track(s)"]
        if result.skipped:
            parts.append(f"Skipped duplicates: {len(result.skipped)}")
        parts.append(f"Library manifest: {result.manifest_path.name}")
        QMessageBox.information(
            self,
            "Music Library Updated",
            "\n".join(parts),
        )

    @Slot()
    def _open_music_library(self) -> None:
        value = self.music_library.text().strip()
        if not value:
            QMessageBox.warning(
                self, "Background Music", "Hãy chọn Music Library Folder trước."
            )
            return
        library = Path(value).expanduser()
        if not library.is_dir():
            QMessageBox.warning(
                self, "Background Music", f"Music Library chưa tồn tại: {library}"
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(library.resolve()))):
            QMessageBox.warning(
                self, "Background Music", f"Không mở được Music Library: {library}"
            )

    @staticmethod
    def _open_external_url(value: str) -> None:
        QDesktopServices.openUrl(QUrl(value))

    @Slot(object)
    def set_snapshot(self, snapshot: AISnapshot) -> None:
        auth = snapshot.auth
        self.status.setText(f"{'●' if auth.authenticated else '○'} {auth.label}")
        self.status.setProperty("authenticated", auth.authenticated)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.account_detail.setText(auth.detail or "No account details available.")
        self.login_button.setVisible(not auth.authenticated)
        self.set_busy(False)
        current = self._requested_model or self.model.currentData() or ""
        self.model.clear()
        if snapshot.models:
            self.model.addItem("Codex Default (Recommended)", "")
            for option in snapshot.models:
                label = option.display_name or option.model_id
                if option.is_default:
                    label += " · Default"
                self.model.addItem(label, option.model_id)
                self.model.setItemData(self.model.count() - 1, option.description, 3)
        else:
            for label, model_id in FALLBACK_MODELS:
                self.model.addItem(label, model_id)
        index = self.model.findData(current)
        self.model.setCurrentIndex(index if index >= 0 else 0)
        self._requested_model = ""

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.refresh_button.setEnabled(not busy)
        self.login_button.setEnabled(not busy)
        if busy and message:
            self.status.setText(f"○ {message}")

    def app_settings(self) -> AppSettings:
        return AppSettings(
            ai=AISettings(
                str(self.model.currentData() or ""),
                str(self.reasoning.currentData() or "default"),
            ),
            workspace=WorkspaceSettings(
                workspace_root=self.workspace_root.text(),
                role_file=self.role_file.text(),
                role_instructions=self.role_instructions.toPlainText(),
                recent_projects=list(self.original.workspace.recent_projects),
                last_project=self.original.workspace.last_project,
            ),
            tts=TTSSettings(
                dna_path=self.tts_dna.text(),
                api_base_url=self.tts_base_url.text(),
                api_key=self.tts_api_key.text(),
                provider=self.tts_provider.text(),
                voice_id=self.voice_id.text(),
                voice_model=str(self.voice_model.currentData() or ""),
                language=self.language.currentText(),
                speed=self.speed.value(),
                pitch=self.pitch.value(),
                volume=self.volume.value(),
                enable_srt=self.enable_srt.isChecked(),
                timeout_seconds=self.timeout.value(),
                poll_interval_seconds=self.poll_interval.value(),
                max_retry=self.max_retry.value(),
                script_filename=self.tts_script_filename.text(),
                output_folder=self.output_folder.text(),
                audio_filename=self.audio_filename.text(),
                subtitle_filename=self.subtitle_filename.text(),
                overwrite_existing=self.overwrite.isChecked(),
            ),
            beat=BeatSettings(self.beat_dna.text(), self.beat_filename.text()),
            music=MusicSettings(
                dna_path=self.music_dna.text(),
                library_folder=self.music_library.text(),
                enabled=self.enable_music.isChecked(),
            ),
            footage=FootageSettings(
                use_pexels=self.footage_use_pexels.isChecked(),
                use_pixabay=self.footage_use_pixabay.isChecked(),
                pexels_api_key=self.pexels_api_key.text(),
                pixabay_api_key=self.pixabay_api_key.text(),
                max_queries=self.footage_max_queries.value(),
                max_pages=self.footage_max_pages.value(),
                per_page=self.footage_per_page.value(),
                clips_per_beat=self.footage_clips_per_beat.value(),
                min_duration=self.footage_min_duration.value(),
                min_width=self.footage_min_width.value(),
                min_height=self.footage_min_height.value(),
                max_pixabay_downloads=self.footage_pixabay_cap.value(),
                dry_run=self.footage_dry_run.isChecked(),
            ),
            video_builder=VideoBuilderSettings(
                resolution=self.builder_resolution.currentText(),
                output_fps=self.builder_fps.value(),
                analysis_workers=self.builder_workers.value(),
                min_cut_seconds=self.builder_min_cut.value(),
                target_cut_seconds=self.builder_target_cut.value(),
                max_cut_seconds=self.builder_max_cut.value(),
                minimum_video_minutes=self.builder_minimum_minutes.value(),
                transition_seconds=self.builder_transition.value(),
                encoder_preset=str(
                    self.builder_preset.currentData() or "veryfast"
                ),
                visual_model=str(
                    self.builder_visual_model.currentData() or "disabled"
                ),
                local_models_only=self.builder_local_models.isChecked(),
                scene_threshold=self.builder_scene_threshold.value(),
                scene_min_seconds=self.builder_scene_min.value(),
            ),
        ).normalized()
