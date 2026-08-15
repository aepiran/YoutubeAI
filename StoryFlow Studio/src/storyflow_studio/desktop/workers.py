"""Qt-safe background task helpers."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot


class TaskWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation

    @Slot()
    def execute(self) -> None:
        try:
            self.succeeded.emit(self.operation())
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class ProgressTaskWorker(QObject):
    """Run an operation that reports typed progress through a queued Qt signal."""

    succeeded = Signal(object)
    progress = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        operation: Callable[[Callable[[object], None]], object],
    ) -> None:
        super().__init__()
        self.operation = operation

    @Slot()
    def execute(self) -> None:
        try:
            self.succeeded.emit(self.operation(self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
