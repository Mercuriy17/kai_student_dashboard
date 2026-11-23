from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

log = logging.getLogger(__name__)


class TaskWorker(QThread):
    """Виконує довгу операцію (мережа/файли) поза UI-потоком; результат повертається сигналами."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            log.warning("background task failed: %s", exc.__class__.__name__)
            # Показуємо лише безпечний текст винятків застосунку; решту — узагальнено
            from integrations.digital_university import PortalError

            msg = str(exc) if isinstance(exc, PortalError) else f"Операція не вдалась ({exc.__class__.__name__})."
            self.failed.emit(msg)
