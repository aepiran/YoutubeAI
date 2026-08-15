"""Desktop branding resources."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap

LOGO_RESOURCE = "storyflow-logo.png"
# The generated master includes presentation space around the icon. This crop
# isolates the navy tile; the rounded clip keeps every desktop placement clean.
LOGO_CROP = (102, 72, 1048, 1100)


@lru_cache(maxsize=8)
def logo_pixmap(size: int | None = None) -> QPixmap:
    """Load the packaged logo, optionally scaled for a UI placement."""

    data = files("storyflow_studio.assets").joinpath(LOGO_RESOURCE).read_bytes()
    master = QPixmap()
    master.loadFromData(data, "PNG")
    cropped = master.copy(*LOGO_CROP)
    target_size = size or 512
    canvas = QPixmap(target_size, target_size)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    clip = QPainterPath()
    clip.addRoundedRect(
        QRectF(0, 0, target_size, target_size),
        target_size * 0.21,
        target_size * 0.21,
    )
    painter.setClipPath(clip)
    painter.drawPixmap(canvas.rect(), cropped)
    painter.end()
    return canvas


def application_icon() -> QIcon:
    """Create the shared application/window icon from the packaged logo."""

    return QIcon(logo_pixmap())
