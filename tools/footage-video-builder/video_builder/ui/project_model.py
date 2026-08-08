from PySide6.QtCore import QObject, Signal
from pathlib import Path
import json
import csv
from typing import Optional, List, Dict, Any

# Giả định BeatHealth và BeatHealthResult được định nghĩa ở một nơi chung,
# ví dụ: video_builder.core.models.
# Để ví dụ này đầy đủ, tôi sẽ định nghĩa lại chúng ở đây.
# Trong ứng dụng thực tế, bạn nên import chúng từ module chung.
from enum import Enum

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

class ProjectModel(QObject):
    project_loaded = Signal()
    project_saved = Signal()
    data_changed = Signal() # Tín hiệu chung cho bất kỳ thay đổi dữ liệu nào

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_path: Optional[Path] = None
        self._script_path: Optional[Path] = None
        self._footage_dir: Optional[Path] = None
        self._output_dir: Optional[Path] = None
        self._voice_files: List[Path] = []
        self._beats_csv_data: List[Dict[str, str]] = [] # Dữ liệu thô từ footage.csv
        self._selected_footage_json_data: Dict[str, Any] = {} # Dữ liệu đã phân tích từ selected-footage.json
        self._beat_results: Dict[str, BeatHealthResult] = {} # Kết quả health sau phân tích

    def set_project_path(self, path: Path):
        if self._project_path != path:
            self._project_path = path
            self.load_project()

    def get_project_path(self) -> Optional[Path]:
        return self._project_path

    def get_script_path(self) -> Optional[Path]:
        return self._script_path

    def get_footage_dir(self) -> Optional[Path]:
        return self._footage_dir

    def get_output_dir(self) -> Optional[Path]:
        return self._output_dir

    def get_voice_files(self) -> List[Path]:
        return self._voice_files

    def get_beats_csv_data(self) -> List[Dict[str, str]]:
        return self._beats_csv_data

    def get_selected_footage_json_data(self) -> Dict[str, Any]:
        return self._selected_footage_json_data

    def get_beat_results(self) -> Dict[str, BeatHealthResult]:
        return self._beat_results

    def update_beat_results(self, results: Dict[str, BeatHealthResult]):
        self._beat_results = results
        self.data_changed.emit() # Thông báo UI rằng kết quả beat đã thay đổi

    def load_project(self):
        if not self._project_path or not self._project_path.is_dir():
            return

        # Đặt lại dữ liệu hiện tại
        self._script_path = None
        self._footage_dir = None
        self._output_dir = None
        self._voice_files = []
        self._beats_csv_data = []
        self._selected_footage_json_data = {}
        self._beat_results = {} # Xóa kết quả cũ

        # Tải script.txt, footage.csv, selected-footage.json, v.v.
        # (Logic tải file tương tự như trong MainWindow hiện tại)
        # Ví dụ:
        script_file = self._project_path / "script.txt"
        if script_file.is_file():
            self._script_path = script_file
        # ... (thêm logic tải các file khác)

        self.project_loaded.emit()
        self.data_changed.emit()

    def save_project(self):
        if not self._project_path:
            return

        # Ví dụ: Lưu selected-footage.json (nếu nó được sửa đổi bởi UI)
        selected_footage_file = self._project_path / "selected-footage.json"
        if self._selected_footage_json_data:
            with open(selected_footage_file, 'w', encoding='utf-8') as f:
                json.dump(self._selected_footage_json_data, f, indent=4)
            self.project_saved.emit()