from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

_PRIORITY = {
    1: ("Критичний", "TagHigh"),
    2: ("Високий", "TagMed"),
    3: ("Середній", "TagMuted"),
    4: ("Низький", "TagLow"),
}


def _tag(text: str, cls: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("class", cls)
    return lbl


class KanbanCardWidget(QFrame):
    """Картка завдання у стилі цільового дизайну: теги, ID, опис, дедлайн, прогрес мікрокроків."""

    status_changed = Signal(int, str)

    STATUS_FLOW = {
        "backlog": ("todo", "→ В план"),
        "todo": ("in_progress", "→ В роботу"),
        "in_progress": ("review", "→ На захист"),
        "review": ("done", "✓ Здано"),
        "done": ("todo", "↺ Повернути"),
    }

    def __init__(self, task: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.task = task
        self.setProperty("class", "Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        prio_text, prio_cls = _PRIORITY.get(int(task.get("priority", 2)), _PRIORITY[2])
        tags = QHBoxLayout()
        tags.setSpacing(6)
        tags.addWidget(_tag(f"⚑ {prio_text}", prio_cls))
        tags.addWidget(_tag(task.get("subject_name") or "Загальне", "TagSubject"))
        tags.addStretch()
        code = (task.get("subject_code") or "TASK").upper()
        tags.addWidget(_tag(f"{code}-{task['id']}", "TagId"))
        layout.addLayout(tags)

        title = QLabel(str(task["title"]))
        title.setWordWrap(True)
        title.setProperty("class", "CardTitle")
        layout.addWidget(title)

        desc = str(task.get("description") or "").strip()
        if desc:
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setMaximumHeight(34)
            d.setProperty("class", "MutedText")
            layout.addWidget(d)

        due = task.get("due_date")
        if due:
            overdue = str(due)[:10] < date.today().isoformat() and task.get("status") != "done"
            layout.addWidget(_tag(f"📅 {str(due)[:10]}", "ChipDanger" if overdue else "Chip"))

        total = int(task.get("steps_total") or 0)
        if total:
            done = int(task.get("steps_done") or 0)
            pct = round(done * 100 / total)
            row = QHBoxLayout()
            cap = QLabel("Прогрес")
            cap.setProperty("class", "MutedText")
            row.addWidget(cap)
            row.addStretch()
            val = QLabel(f"{pct}%")
            val.setProperty("class", "MutedText")
            row.addWidget(val)
            layout.addLayout(row)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(pct)
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            layout.addWidget(bar)

        status = str(task.get("status", "todo"))
        next_status, label = self.STATUS_FLOW.get(status, ("done", "✓ Готово"))
        move = QPushButton(label)
        move.setProperty("class", "SecondaryBtn")
        move.clicked.connect(lambda: self.status_changed.emit(int(task["id"]), next_status))
        layout.addWidget(move)
