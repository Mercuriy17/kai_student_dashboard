from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.domain.academic_rules import RsoSummary


class RsoProgressCard(QFrame):
    """Картка відображення рейтингу РСО дисципліни з порогом допуску."""

    def __init__(self, summary: RsoSummary, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title_lbl = QLabel(summary.subject_name)
        title_lbl.setProperty("class", "CardTitle")
        header.addWidget(title_lbl, 1)

        badge = QLabel()
        if summary.is_passed:
            badge.setText("Зараховано (≥60)")
            badge.setProperty("class", "BadgeSuccess")
        elif summary.is_admitted:
            badge.setText("Допуск є")
            badge.setProperty("class", "Badge")
        elif summary.risk_level == "critical":
            badge.setText(f"Ризик недопуску (-{summary.points_needed_for_admission} б.)")
            badge.setProperty("class", "BadgeDanger")
        else:
            badge.setText(f"До допуску: {summary.points_needed_for_admission} б.")
            badge.setProperty("class", "BadgeWarning")
        header.addWidget(badge)
        layout.addLayout(header)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(min(100, round(summary.total_earned))))
        bar.setFormat(f"{summary.total_earned:.1f} / 100 балів")
        layout.addWidget(bar)

        meta = QLabel(
            f"Семестр: {summary.earned_semester:.1f} б. | Іспит: {summary.earned_exam:.1f} б. | "
            f"Макс. прогноз: {summary.projected_max:.1f} б."
        )
        meta.setProperty("class", "MutedText")
        layout.addWidget(meta)


class KanbanCardWidget(QFrame):
    """Картка завдання для Канбан-дошки зі швидким переміщенням між колонками."""

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
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        subj_lbl = QLabel(task.get("subject_name") or "Загальне")
        subj_lbl.setProperty("class", "Badge")
        top.addWidget(subj_lbl)
        top.addStretch()

        prio = int(task.get("priority", 2))
        prio_lbl = QLabel(f"P{prio}")
        prio_lbl.setProperty("class", "BadgeDanger" if prio == 1 else "MutedText")
        top.addWidget(prio_lbl)
        layout.addLayout(top)

        title_lbl = QLabel(str(task["title"]))
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet("font-weight: 600;")
        layout.addWidget(title_lbl)

        bottom = QHBoxLayout()
        due_txt = f"До: {task['due_date'][:10]}" if task.get("due_date") else "Без дедлайну"
        due_lbl = QLabel(due_txt)
        due_lbl.setProperty("class", "MutedText")
        bottom.addWidget(due_lbl)
        bottom.addStretch()

        current_status = str(task.get("status", "todo"))
        next_status, btn_label = self.STATUS_FLOW.get(current_status, ("done", "✓ Готово"))
        move_btn = QPushButton(btn_label)
        move_btn.setProperty("class", "SecondaryBtn")
        move_btn.clicked.connect(lambda: self.status_changed.emit(int(task["id"]), next_status))
        bottom.addWidget(move_btn)

        layout.addLayout(bottom)


class FocusTimerBar(QFrame):
    """
    Вбудований таймер глибокого фокусу Pomodoro (25/5, 45/15, 50/10)
    із фіксацією відволікань («Зафіксуй і відклади»).
    """

    session_completed = Signal(str, int, int, int)  # mode, planned, actual, interruptions

    MODES = {
        "25/5 (Класичний старт)": (25, 5),
        "45/15 (Академічний блок КАІ)": (45, 15),
        "50/10 (Deep Work / Код)": (50, 10),
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "CardAccent")
        self._is_running = False
        self._is_break = False
        self._planned_minutes = 45
        self._break_minutes = 15
        self._remaining_seconds = 45 * 60
        self._interruptions = 0

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(self.MODES.keys()))
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        self.phase_label = QLabel("ФАЗА РОБОТИ")
        self.phase_label.setProperty("class", "Badge")
        layout.addWidget(self.phase_label)

        self.clock_label = QLabel("45:00")
        self.clock_label.setStyleSheet("font-size: 22px; font-weight: 700; color: #38BDF8;")
        layout.addWidget(self.clock_label)

        self.start_btn = QPushButton("▶ Старт")
        self.start_btn.setProperty("class", "PrimaryBtn")
        self.start_btn.clicked.connect(self._toggle_timer)
        layout.addWidget(self.start_btn)

        self.reset_btn = QPushButton("↺ Скинути")
        self.reset_btn.setProperty("class", "SecondaryBtn")
        self.reset_btn.clicked.connect(self._reset_timer)
        layout.addWidget(self.reset_btn)

        self.distract_btn = QPushButton("⚡ Відволікання (0)")
        self.distract_btn.setProperty("class", "SecondaryBtn")
        self.distract_btn.setToolTip(
            "Зафіксувати внутрішнє чи зовнішнє відволікання і повернутися до задачі"
        )
        self.distract_btn.clicked.connect(self._register_interruption)
        layout.addWidget(self.distract_btn)

        layout.addStretch()

    def _on_mode_changed(self, text: str) -> None:
        work_m, break_m = self.MODES.get(text, (45, 15))
        self._planned_minutes = work_m
        self._break_minutes = break_m
        self._reset_timer()

    def _toggle_timer(self) -> None:
        if self._is_running:
            self._timer.stop()
            self._is_running = False
            self.start_btn.setText("▶ Продовжити")
        else:
            self._timer.start()
            self._is_running = True
            self.start_btn.setText("⏸ Пауза")

    def _reset_timer(self) -> None:
        self._timer.stop()
        self._is_running = False
        self._is_break = False
        self._interruptions = 0
        self._remaining_seconds = self._planned_minutes * 60
        self.phase_label.setText("ФАЗА РОБОТИ")
        self.start_btn.setText("▶ Старт")
        self.distract_btn.setText("⚡ Відволікання (0)")
        self._update_clock_display()

    def _register_interruption(self) -> None:
        self._interruptions += 1
        self.distract_btn.setText(f"⚡ Відволікання ({self._interruptions})")

    def _on_tick(self) -> None:
        if self._remaining_seconds > 0:
            self._remaining_seconds -= 1
            self._update_clock_display()
            return

        if not self._is_break:
            # Завершено робочий інтервал — зберігаємо сесію в БД і вмикаємо перерву
            self.session_completed.emit(
                f"{self._planned_minutes}_{self._break_minutes}",
                self._planned_minutes,
                self._planned_minutes,
                self._interruptions,
            )
            self._is_break = True
            self._remaining_seconds = self._break_minutes * 60
            self.phase_label.setText("ПЕРЕРВА БЕЗ ЕКРАНА")
            self._update_clock_display()
        else:
            self._reset_timer()

    def _update_clock_display(self) -> None:
        mins = self._remaining_seconds // 60
        secs = self._remaining_seconds % 60
        self.clock_label.setText(f"{mins:02d}:{secs:02d}")


class QuickAddDialog(QDialog):
    """Модальне вікно швидкого додавання завдання (Ctrl+N) із розумним парсером."""

    def __init__(
        self,
        on_submit: Callable[[str], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.on_submit = on_submit
        self.setWindowTitle("Швидке додавання завдання (Quick Add)")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        hint = QLabel(
            "Введіть завдання у вільному форматі. Підтримуються теги дисципліни (#фізика), "
            "дати (сьогодні, завтра, 25.11) та пріоритет (!критично):"
        )
        hint.setWordWrap(True)
        hint.setProperty("class", "MutedText")
        layout.addWidget(hint)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Напр.: Оформити звіт Лаба №3 #фізика завтра !критично")
        self.input_edit.returnPressed.connect(self._handle_accept)
        layout.addWidget(self.input_edit)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Скасувати")
        cancel_btn.setProperty("class", "SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)

        save_btn = QPushButton("Додати завдання")
        save_btn.setProperty("class", "PrimaryBtn")
        save_btn.clicked.connect(self._handle_accept)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    def _handle_accept(self) -> None:
        text = self.input_edit.text().strip()
        if text:
            self.on_submit(text)
            self.accept()