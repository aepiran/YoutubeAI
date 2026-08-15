"""Workspace paths, project discovery, and project-state services."""

from .metrics import ProjectMetrics, ProjectMetricsService, format_duration
from .service import (
    Project,
    ProjectError,
    ProjectManifest,
    ProjectPaths,
    WorkspaceService,
    slugify_project_name,
)

__all__ = [
    "Project",
    "ProjectMetrics",
    "ProjectMetricsService",
    "ProjectError",
    "ProjectManifest",
    "ProjectPaths",
    "WorkspaceService",
    "format_duration",
    "slugify_project_name",
]
