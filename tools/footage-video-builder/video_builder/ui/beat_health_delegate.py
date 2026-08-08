from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QToolTip
from PySide6.QtGui import QPainter, QColor, QPalette
from PySide6.QtCore import Qt, QModelIndex

from enum import Enum

# Giả định BeatHealth và BeatHealthResult được định nghĩa ở một nơi chung,
# ví dụ: video_builder.core.models.
# Để ví dụ này đầy đủ, tôi sẽ định nghĩa lại chúng ở đây.
# Trong ứng dụng thực tế, bạn nên import chúng từ module chung.
class BeatHealth(Enum):
    NORMAL = 0
    WARNING = 1
    CRITICAL = 2
    MISSING_FOOTAGE = 3
    FORCED_LOW_SEMANTIC = 4
    FORCED_EARLY_REUSE = 5
    TIMELINE_GAP = 6
    TIMELINE_OVERLAP = 7
    SHORT_CANDIDATE = 8
    LOW_QUALITY = 9
    LOW_SEMANTIC = 10
    REUSED_VISUAL_REGION = 11
    JUMP_CUT = 12
    MISSING_FILE = 13
    OTHER_BEAT_FOOTAGE = 14
    FALLBACK_LOW_SEMANTIC = 15
    COOLDOWN_VIOLATION = 16

class BeatHealthResult:
    def __init__(self, health_status: BeatHealth, messages: list[str]):
        self.health_status = health_status
        self.messages = messages

class BeatHealthDelegate(QStyledItemDelegate):
    def __init__(self, beat_results: dict[str, BeatHealthResult], parent=None):
        super().__init__(parent)
        self._beat_results = beat_results

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        # Lấy Beat ID từ cột đầu tiên của hàng hiện tại
        # Giả định Beat ID nằm ở cột 0
        beat_id_item = index.model().index(index.row(), 0)
        beat_id = beat_id_item.data(Qt.DisplayRole)

        color = QColor(Qt.white) # Màu mặc định

        if beat_id in self._beat_results:
            beat_health_result = self._beat_results[beat_id]
            health_status = beat_health_result.health_status

            if health_status == BeatHealth.CRITICAL:
                color = QColor("#FFCCCC")  # Đỏ nhạt
            elif health_status == BeatHealth.WARNING:
                color = QColor("#FFFFCC")  # Vàng nhạt
            elif health_status == BeatHealth.NORMAL:
                color = QColor("#CCFFCC")  # Xanh lá nhạt
            elif health_status == BeatHealth.MISSING_FOOTAGE:
                color = QColor("#FF9999")  # Đỏ hơn
            elif health_status in [BeatHealth.FORCED_LOW_SEMANTIC, BeatHealth.FORCED_EARLY_REUSE,
                                   BeatHealth.SHORT_CANDIDATE, BeatHealth.LOW_QUALITY,
                                   BeatHealth.LOW_SEMANTIC, BeatHealth.REUSED_VISUAL_REGION,
                                   BeatHealth.FALLBACK_LOW_SEMANTIC, BeatHealth.COOLDOWN_VIOLATION]:
                color = QColor("#FFCC99")  # Cam nhạt
            elif health_status in [BeatHealth.TIMELINE_GAP, BeatHealth.TIMELINE_OVERLAP, BeatHealth.JUMP_CUT]:
                color = QColor("#FF6666")  # Đỏ
            elif health_status == BeatHealth.MISSING_FILE:
                color = QColor("#FF9999")  # Đỏ hơn
            elif health_status == BeatHealth.OTHER_BEAT_FOOTAGE:
                color = QColor("#FFFF99")  # Vàng

        # Tô màu nền
        painter.save()
        painter.fillRect(option.rect, color)
        painter.restore()

        # Đảm bảo văn bản và các yếu tố khác được vẽ đúng cách trên nền tùy chỉnh
        option.backgroundBrush = color
        super().paint(painter, option, index)

    def helpEvent(self, event, view, option, index):
        # Phương thức này được gọi khi yêu cầu tooltip
        beat_id_item = index.model().index(index.row(), 0)
        beat_id = beat_id_item.data(Qt.DisplayRole)
        if beat_id in self._beat_results:
            messages = self._beat_results[beat_id].messages
            if messages:
                QToolTip.showText(event.globalPos(), "\n".join(messages), view)
                return True
        return super().helpEvent(event, view, option, index)