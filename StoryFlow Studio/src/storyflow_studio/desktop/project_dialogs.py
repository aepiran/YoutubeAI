"""New Project dialog for Workspace-root projects."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..modules.workspace import ProjectError, WorkspaceService, slugify_project_name


class NewProjectDialog(QDialog):
    def __init__(self, workspace_root: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project · StoryFlow Studio")
        self.setMinimumWidth(620)
        self._folder_edited = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(14)
        title = QLabel("Create New Project")
        title.setObjectName("HeroTitle")
        subtitle = QLabel("The project will be created inside your Workspace Root.")
        subtitle.setObjectName("Muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("Morning Prayer 001")
        self.project_description = QPlainTextEdit()
        self.project_description.setPlaceholderText(
            "Describe the story, audience, tone, or production goal…"
        )
        self.project_description.setMaximumHeight(96)
        self.folder_name = QLineEdit()
        self.folder_name.setPlaceholderText("morning-prayer-001")
        self.workspace_root = QLineEdit(workspace_root)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_workspace)
        root_row = QWidget()
        root_layout = QHBoxLayout(root_row)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.workspace_root, 1)
        root_layout.addWidget(browse)
        form.addRow("Project Name", self.project_name)
        form.addRow("Description", self.project_description)
        form.addRow("Folder Name", self.folder_name)
        form.addRow("Workspace Root", root_row)
        layout.addLayout(form)

        self.preview = QLabel()
        self.preview.setObjectName("PathPreview")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        create = buttons.button(QDialogButtonBox.StandardButton.Ok)
        create.setText("Create Project")
        create.setObjectName("PrimaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.project_name.textChanged.connect(self._name_changed)
        self.folder_name.textEdited.connect(self._folder_changed)
        self.folder_name.textChanged.connect(self._update_preview)
        self.workspace_root.textChanged.connect(self._update_preview)
        self._update_preview()

    def _name_changed(self, value: str) -> None:
        if not self._folder_edited:
            self.folder_name.setText(slugify_project_name(value))

    def _folder_changed(self, _value: str) -> None:
        self._folder_edited = True

    def _browse_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Select Workspace Root", self.workspace_root.text()
        )
        if selected:
            self.workspace_root.setText(selected)

    def _update_preview(self) -> None:
        root = self.workspace_root.text().strip() or "<Workspace Root>"
        folder = self.folder_name.text().strip() or "<project-folder>"
        self.preview.setText(f"Project Path  ·  {Path(root) / folder}")

    def values(self) -> tuple[str, str, str, str]:
        return (
            self.workspace_root.text().strip(),
            self.project_name.text().strip(),
            self.folder_name.text().strip(),
            self.project_description.toPlainText().strip(),
        )

    def accept(self) -> None:
        root, name, folder, description = self.values()
        if not root or not name:
            QMessageBox.warning(self, "Invalid Project", "Workspace Root và Project Name là bắt buộc.")
            return
        if len(description) > 2000:
            QMessageBox.warning(
                self,
                "Invalid Project",
                "Project Description không được dài quá 2.000 ký tự.",
            )
            return
        try:
            WorkspaceService.validate_folder_name(folder)
        except ProjectError as exc:
            QMessageBox.warning(self, "Invalid Project", str(exc))
            return
        super().accept()


class ExportChoiceDialog(QDialog):
    """Choose one output workflow without crowding the Video Builder card."""

    def __init__(self, parent=None, *, capcut_draft_name: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Export · StoryFlow Studio")
        self.setMinimumWidth(540)
        self._choice = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)
        title = QLabel("Export Video Builder Output")
        title.setObjectName("HeroTitle")
        description = QLabel(
            "Choose the output format. Both options reuse the saved timeline "
            "without running Analyze Again."
        )
        description.setObjectName("Muted")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)

        capcut_name_label = QLabel("CapCut Project Name")
        capcut_name_label.setObjectName("SectionTitle")
        layout.addWidget(capcut_name_label)
        self.capcut_name = QLineEdit(capcut_draft_name.strip())
        self.capcut_name.setPlaceholderText("Enter the project name shown in CapCut")
        self.capcut_name.setAccessibleName("CapCut Project Name")
        self.capcut_name.setToolTip(
            "Used for the CapCut Draft folder and the project name shown in CapCut"
        )
        layout.addWidget(self.capcut_name)

        self.render_button = QPushButton("Final MP4")
        self.render_button.setObjectName("ExportChoiceButton")
        self.render_button.setAccessibleName("Render Final Video")
        self.render_button.setToolTip(
            "Create output/final_video.mp4 with narration and optional music"
        )
        self.render_button.clicked.connect(lambda: self._select("render"))
        layout.addWidget(self.render_button)

        self.capcut_button = QPushButton("CapCut Draft")
        self.capcut_button.setObjectName("ExportChoiceButton")
        self.capcut_button.setAccessibleName("Export CapCut Draft")
        self.capcut_button.setToolTip(
            "Create a portable package and, when configured, an editable CapCut Draft"
        )
        self.capcut_button.clicked.connect(lambda: self._select("capcut"))
        layout.addWidget(self.capcut_button)

        cancel = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel.rejected.connect(self.reject)
        layout.addWidget(cancel)

    def _select(self, choice: str) -> None:
        if choice == "capcut" and not self.capcut_name.text().strip():
            QMessageBox.warning(
                self,
                "CapCut Project Name",
                "Hãy nhập tên dự án CapCut trước khi Export.",
            )
            self.capcut_name.setFocus()
            return
        self._choice = choice
        self.accept()

    def choice(self) -> str:
        return self._choice

    def draft_name(self) -> str:
        return self.capcut_name.text().strip()
