from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.database import DatabaseManager
from core.domain.academic_rules import ParityResolver, RsoCalculator, WindowAnalyzer
from core.repositories import AcademicRepository, CognitiveRepository, TaskRepository
from core.services import AcademicService, BlackoutExportService
from integrations.kai_portal import KaiPortalAdapter
from core.repositories import SyncAndFileRepository
from ui.kanban_card import KanbanCardWidget
from ui.layout_utils import clear_layout
from ui.widgets import FocusTimerBar, RsoProgressCard


def _wrap_in_scroll(content_widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content_widget)
    return scroll


class DashboardPage(QWidget):
    """Сторінка 1: Командний центр дня (Алгоритми 1, 2 та 6 у реальному часі)."""

    def __init__(
        self,
        db: DatabaseManager,
        on_data_changed: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.on_data_changed = on_data_changed
        self.service = AcademicService(db)
        self.academic_repo = AcademicRepository(db)
        self.task_repo = TaskRepository(db)
        self.blackout_service = BlackoutExportService(db)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QWidget()
        self.main_layout = QVBoxLayout(self.container)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(16)
        outer.addWidget(_wrap_in_scroll(self.container))

        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.main_layout)

        ctx = self.service.get_today_context()
        today_str = ctx["date"]

        # Заголовок та швидка кнопка режиму збою (Алгоритм 6)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(f"Командний центр дня — {today_str}")
        title.setProperty("class", "SectionTitle")
        subtitle = QLabel(f"{ctx['parity_label']} • Національний університет «Київський авіаційний інститут»")
        subtitle.setProperty("class", "MutedText")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        pack_btn = QPushButton("📦 Зібрати пакет блекауту (ZIP)")
        pack_btn.setProperty("class", "SecondaryBtn")
        pack_btn.clicked.connect(self._export_blackout_pack)
        header.addWidget(pack_btn)

        emerg_btn = QPushButton(
            "🔴 Режим збою АКТИВНИЙ (Алг. 6)"
            if ctx["emergency_mode"]
            else "⚡ Увімкнути режим збою / блекауту"
        )
        emerg_btn.setProperty("class", "DangerBtn" if ctx["emergency_mode"] else "SecondaryBtn")
        emerg_btn.clicked.connect(lambda: self._toggle_emergency(not ctx["emergency_mode"]))
        header.addWidget(emerg_btn)
        self.main_layout.addLayout(header)

        # Банер аварійного протоколу Алгоритму 6
        if ctx["emergency_mode"]:
            alert_card = QFrame()
            alert_card.setProperty("class", "CardDanger")
            al = QVBoxLayout(alert_card)
            lbl = QLabel(
                "АКТИВОВАНО РЕЗЕРВНИЙ ПРОТОКОЛ (Алгоритм 6): другорядні завдання приховано. "
                "Фокус лише на 2 критичних пріоритетах на 48 год або 25 хв самоперевірки без екрана."
            )
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-weight: 700;")
            al.addWidget(lbl)
            self.main_layout.addWidget(alert_card)

        # Верхня сітка: 2 пріоритети на 48 год + Щоденний чек-ін ресурсу
        grid = QGridLayout()
        grid.setSpacing(14)

        prio_card = QFrame()
        prio_card.setProperty("class", "CardAccent")
        pl = QVBoxLayout(prio_card)
        pl.setContentsMargins(16, 14, 16, 14)
        pl_title = QLabel("🎯 Топ-2 критичні пріоритети на 48 годин (Алгоритм 6)")
        pl_title.setProperty("class", "CardTitle")
        pl.addWidget(pl_title)

        top2 = ctx["top_priorities"]
        if not top2:
            empty_p = QLabel("Усі актуальні дедлайни закрито! Можна попрацювати над R&D портфоліо КАІ.")
            empty_p.setProperty("class", "MutedText")
            pl.addWidget(empty_p)
        else:
            for idx, pt in enumerate(top2, start=1):
                t = pt.task
                row_frame = QFrame()
                row_frame.setProperty("class", "Card")
                rl = QHBoxLayout(row_frame)
                info = QLabel(
                    f"<b>{idx}. {t['title']}</b> ({t.get('subject_name') or 'Загальне'})<br>"
                    f"<span style='color:#94A3B8;'>Критерій: {pt.rationale} | Дедлайн: {t.get('due_date') or '—'}</span>"
                )
                info.setWordWrap(True)
                rl.addWidget(info, 1)

                done_btn = QPushButton("✓ Готово")
                done_btn.setProperty("class", "PrimaryBtn")
                done_btn.clicked.connect(lambda _, tid=int(t["id"]): self._complete_task(tid))
                rl.addWidget(done_btn)
                pl.addWidget(row_frame)
        pl.addStretch()
        grid.addWidget(prio_card, 0, 0)

        # Картка саморегуляції та ресурсу (Алгоритм 6)
        wb_card = QFrame()
        wb_card.setProperty("class", "Card")
        wl = QVBoxLayout(wb_card)
        wl.setContentsMargins(16, 14, 16, 14)
        wl_title = QLabel("🔋 Біологічний ресурс і саморегуляція сьогодні")
        wl_title.setProperty("class", "CardTitle")
        wl.addWidget(wl_title)

        existing_wb = self.task_repo.get_wellbeing_log(today_str) or {}
        form = QFormLayout()
        self.sleep_spin = QDoubleSpinBox()
        self.sleep_spin.setRange(0.0, 16.0)
        self.sleep_spin.setSingleStep(0.5)
        self.sleep_spin.setValue(float(existing_wb.get("sleep_hours", 7.5)))

        self.energy_spin = QSpinBox()
        self.energy_spin.setRange(1, 5)
        self.energy_spin.setValue(int(existing_wb.get("energy_level", 4)))

        self.stress_spin = QSpinBox()
        self.stress_spin.setRange(1, 5)
        self.stress_spin.setValue(int(existing_wb.get("stress_level", 2)))

        form.addRow("Сон (год, норма ≥7.0):", self.sleep_spin)
        form.addRow("Рівень енергії (1–5):", self.energy_spin)
        form.addRow("Рівень стресу (1–5):", self.stress_spin)
        wl.addLayout(form)

        save_wb_btn = QPushButton("Зберегти чек-ін дня")
        save_wb_btn.setProperty("class", "SecondaryBtn")
        save_wb_btn.clicked.connect(lambda: self._save_wellbeing(ctx["emergency_mode"]))
        wl.addWidget(save_wb_btn)
        grid.addWidget(wb_card, 0, 1)

        # Пари сьогодні та вікна між корпусами КАІ
        sched_card = QFrame()
        sched_card.setProperty("class", "Card")
        sl = QVBoxLayout(sched_card)
        sl.setContentsMargins(16, 14, 16, 14)
        sl_title = QLabel("📅 Розклад на сьогодні та навігація корпусами КАІ")
        sl_title.setProperty("class", "CardTitle")
        sl.addWidget(sl_title)

        if not ctx["today_classes"]:
            no_cls = QLabel("Сьогодні за розкладом пар немає — день самопідготовки або R&D лабораторії.")
            no_cls.setProperty("class", "MutedText")
            sl.addWidget(no_cls)
        else:
            for rem in ctx["smart_reminders"]:
                lbl = QLabel(f"• {rem}")
                lbl.setWordWrap(True)
                sl.addWidget(lbl)

        if ctx["windows"]:
            win_hdr = QLabel("⏱ Виявлені продуктивні «вікна» між парами:")
            win_hdr.setStyleSheet("font-weight: 600; margin-top: 6px; color: #38BDF8;")
            sl.addWidget(win_hdr)
            for w in ctx["windows"]:
                wl_item = QLabel(
                    f"  {w.start_time}–{w.end_time}: чистих {w.net_productive_minutes} хв "
                    f"(перехід корп. {w.from_building}→{w.to_building} ~{w.transit_minutes} хв) — {w.recommendation}"
                )
                wl_item.setWordWrap(True)
                wl_item.setProperty("class", "MutedText")
                sl.addWidget(wl_item)
        sl.addStretch()
        grid.addWidget(sched_card, 1, 0)

        # Черга повторення конспектів Корнелла (Алгоритм 2)
        rev_card = QFrame()
        rev_card.setProperty("class", "Card")
        rvl = QVBoxLayout(rev_card)
        rvl.setContentsMargins(16, 14, 16, 14)
        rv_title = QLabel("🧠 Черга інтервального повторення (0 → 24 → 7 → 21)")
        rv_title.setProperty("class", "CardTitle")
        rvl.addWidget(rv_title)

        due_notes = ctx["due_notes"]
        if not due_notes:
            ok_lbl = QLabel("На сьогодні запланованих повторень конспектів немає.")
            ok_lbl.setProperty("class", "MutedText")
            rvl.addWidget(ok_lbl)
        else:
            for note in due_notes[:4]:
                n_lbl = QLabel(
                    f"• [{note['subject_name']}] Лекція №{note['lecture_number']}: {note['topic']} "
                    f"(поточна фаза: {note['review_stage']})"
                )
                n_lbl.setWordWrap(True)
                rvl.addWidget(n_lbl)
        rvl.addStretch()
        grid.addWidget(rev_card, 1, 1)

        self.main_layout.addLayout(grid)

        # Секція зведеного рейтингу РСО по всіх дисциплінах
        rso_hdr = QLabel("📊 Оперативний моніторинг РСО та порогів допуску до сесії")
        rso_hdr.setProperty("class", "CardTitle")
        self.main_layout.addWidget(rso_hdr)

        rso_grid = QGridLayout()
        rso_grid.setSpacing(12)
        summaries = self.academic_repo.get_all_rso_summaries()
        for idx, summary in enumerate(summaries):
            rso_grid.addWidget(RsoProgressCard(summary), idx // 2, idx % 2)
        self.main_layout.addLayout(rso_grid)
        self.main_layout.addStretch()

    def _complete_task(self, task_id: int) -> None:
        self.task_repo.update_task_status(task_id, "done")
        self.on_data_changed()

    def _toggle_emergency(self, active: bool) -> None:
        today_str = date.today().isoformat()
        existing = self.task_repo.get_wellbeing_log(today_str) or {}
        self.task_repo.save_wellbeing_log(
            log_date=today_str,
            sleep_hours=float(existing.get("sleep_hours", 7.0)),
            energy_level=int(existing.get("energy_level", 3)),
            stress_level=int(existing.get("stress_level", 4 if active else 2)),
            disruption_type="blackout" if active else "none",
            emergency_mode_active=active,
        )
        self.on_data_changed()

    def _save_wellbeing(self, current_emergency: bool) -> None:
        today_str = date.today().isoformat()
        sleep_val = self.sleep_spin.value()
        stress_val = self.stress_spin.value()
        auto_emerg = current_emergency or (sleep_val < 5.0 and stress_val >= 4)
        self.task_repo.save_wellbeing_log(
            log_date=today_str,
            sleep_hours=sleep_val,
            energy_level=self.energy_spin.value(),
            stress_level=stress_val,
            disruption_type="sleep_deficit" if sleep_val < 5.0 else "none",
            emergency_mode_active=auto_emerg,
        )
        QMessageBox.information(self, "Збережено", "Показники саморегуляції на сьогодні оновлено.")
        self.on_data_changed()

    def _export_blackout_pack(self) -> None:
        zip_path = self.blackout_service.export_blackout_bundle()
        QMessageBox.information(
            self,
            "Пакет блекауту сформовано",
            f"Автономний архів для роботи без світла та інтернету збережено:\n{zip_path}",
        )
        self.on_data_changed()


class SchedulePage(QWidget):
    """Сторінка 2: Розклад КАІ (Чисельник/Знаменник), аналізатор вікон та експорт ICS."""

    DAYS_UA = {
        1: "Понеділок",
        2: "Вівторок",
        3: "Середа",
        4: "Четвер",
        5: "П'ятниця",
        6: "Субота",
    }

    def __init__(
        self,
        db: DatabaseManager,
        on_data_changed: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.on_data_changed = on_data_changed
        self.academic_repo = AcademicRepository(db)
        self.portal_adapter = KaiPortalAdapter(self.academic_repo, SyncAndFileRepository(db))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Розклад занять КАІ (Чисельник / Знаменник) та вікна")
        title.setProperty("class", "SectionTitle")
        top.addWidget(title, 1)

        self.parity_filter = QComboBox()
        self.parity_filter.addItems(
            ["Усі тижні (Повний)", "1-й тиждень (Чисельник)", "2-й тиждень (Знаменник)"]
        )
        self.parity_filter.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.parity_filter)

        export_btn = QPushButton("📤 Експортувати в .ICS")
        export_btn.setProperty("class", "SecondaryBtn")
        export_btn.clicked.connect(self._export_ics)
        top.addWidget(export_btn)
        layout.addLayout(top)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["День", "Пара", "Час", "Тиждень", "Дисципліна", "Тип", "Корпус / Ауд."]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        self.windows_box = QFrame()
        self.windows_box.setProperty("class", "CardAccent")
        self.win_layout = QVBoxLayout(self.windows_box)
        layout.addWidget(self.windows_box)

        self.refresh()

    def refresh(self) -> None:
        entries = self.academic_repo.list_schedule()
        f_idx = self.parity_filter.currentIndex()
        filtered: List[Dict[str, Any]] = []
        for e in entries:
            p = e.get("parity", "both")
            if f_idx == 1 and p == "even":
                continue
            if f_idx == 2 and p == "odd":
                continue
            filtered.append(e)

        self.table.setRowCount(len(filtered))
        parity_names = {"both": "Щотижня", "odd": "Чисельник (1)", "even": "Знаменник (2)"}
        type_names = {
            "lecture": "Лекція",
            "practice": "Практика",
            "lab": "Лабораторна",
            "consultation": "Консультація",
        }

        for row_idx, item in enumerate(filtered):
            dow = int(item["day_of_week"])
            self.table.setItem(row_idx, 0, QTableWidgetItem(self.DAYS_UA.get(dow, str(dow))))
            self.table.setItem(row_idx, 1, QTableWidgetItem(f"{item['pair_number']}-а пара"))
            self.table.setItem(
                row_idx, 2, QTableWidgetItem(f"{item['start_time']}–{item['end_time']}")
            )
            self.table.setItem(
                row_idx, 3, QTableWidgetItem(parity_names.get(item["parity"], item["parity"]))
            )
            self.table.setItem(row_idx, 4, QTableWidgetItem(str(item["subject_name"])))
            self.table.setItem(
                row_idx, 5, QTableWidgetItem(type_names.get(item["lesson_type"], item["lesson_type"]))
            )
            self.table.setItem(
                row_idx,
                6,
                QTableWidgetItem(f"Корп. {item['building']}, ауд. {item['room']}"),
            )

        # Оновлення блоку аналізу вікон по днях
        clear_layout(self.win_layout)

        hdr = QLabel("🧭 Аналіз вільних «вікон» між парами з урахуванням переходів корпусами КАІ:")
        hdr.setProperty("class", "CardTitle")
        self.win_layout.addWidget(hdr)

        found_any = False
        for dow in range(1, 7):
            day_cls = [c for c in filtered if int(c["day_of_week"]) == dow]
            wins = WindowAnalyzer.find_productive_windows(day_cls)
            for w in wins:
                found_any = True
                lbl = QLabel(
                    f"• <b>{self.DAYS_UA[dow]}</b> ({w.start_time}–{w.end_time}): "
                    f"вікно {w.total_gap_minutes} хв − перехід корп. {w.from_building}→{w.to_building} "
                    f"({w.transit_minutes} хв) = <b>{w.net_productive_minutes} хв чистого часу</b> → {w.recommendation}"
                )
                lbl.setWordWrap(True)
                self.win_layout.addWidget(lbl)

        if not found_any:
            none_lbl = QLabel("Для вибраного фільтра тижня довгих «вікон» (>35 хв) між парами немає.")
            none_lbl.setProperty("class", "MutedText")
            self.win_layout.addWidget(none_lbl)

    def _export_ics(self) -> None:
        file_str, _ = QFileDialog.getSaveFileName(
            self, "Зберегти розклад КАІ (.ics)", "kai_schedule.ics", "iCalendar (*.ics)"
        )
        if file_str:
            out = self.portal_adapter.export_schedule_to_ics(Path(file_str))
            QMessageBox.information(self, "Експорт завершено", f"Файл календаря збережено:\n{out}")


class SubjectsAndRsoPage(QWidget):
    """Сторінка 3: Дисципліни, Симулятор РСО, Політика ШІ КАІ та Конструктор консультацій (Алг. 4)."""

    def __init__(
        self,
        db: DatabaseManager,
        on_data_changed: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.on_data_changed = on_data_changed
        self.academic_repo = AcademicRepository(db)
        self.cognitive_repo = CognitiveRepository(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Дисципліни, журнал і симулятор РСО, консультації (Алгоритм 4)")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_rso_tab(), "📊 Журнал та симулятор РСО")
        tabs.addTab(self._build_consultation_tab(), "💬 Конструктор консультації (4 пункти)")
        layout.addWidget(tabs, 1)

        self.refresh()

    def _build_rso_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Оберіть дисципліну:"))
        self.subj_combo = QComboBox()
        self.subj_combo.currentIndexChanged.connect(self._load_subject_components)
        top.addWidget(self.subj_combo, 1)

        self.ai_policy_badge = QLabel("Політика ШІ: —")
        self.ai_policy_badge.setProperty("class", "Badge")
        top.addWidget(self.ai_policy_badge)
        l.addLayout(top)

        self.comp_table = QTableWidget(0, 5)
        self.comp_table.setHorizontalHeaderLabels(
            ["Компонент РСО", "Тип", "Макс. балів", "Отримано / Прогноз", "Статус"]
        )
        self.comp_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        l.addWidget(self.comp_table, 1)

        btn_row = QHBoxLayout()
        sim_btn = QPushButton("🧮 Порахувати симуляцію «Що буде, якщо...»")
        sim_btn.setProperty("class", "SecondaryBtn")
        sim_btn.clicked.connect(self._run_rso_simulation)
        btn_row.addWidget(sim_btn)

        save_btn = QPushButton("💾 Зберегти введені бали в журнал РСО")
        save_btn.setProperty("class", "PrimaryBtn")
        save_btn.clicked.connect(self._save_rso_scores)
        btn_row.addWidget(save_btn)
        l.addLayout(btn_row)

        self.sim_result_label = QLabel("")
        self.sim_result_label.setProperty("class", "CardTitle")
        l.addWidget(self.sim_result_label)
        return w

    def _build_consultation_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        info = QLabel(
            "Алгоритм 4: сформулюйте запит за 4 пунктами перед візитом до викладача або на кафедру КАІ, "
            "щоб отримати вичерпну відповідь за 10 хвилин."
        )
        info.setWordWrap(True)
        info.setProperty("class", "MutedText")
        l.addWidget(info)

        form = QFormLayout()
        self.cons_subj = QComboBox()
        self.p1_edit = QLineEdit()
        self.p1_edit.setPlaceholderText("Напр.: Розрахунок похибки непрямих вимірювань у Лабораторній №2")
        self.p2_edit = QLineEdit()
        self.p2_edit.setPlaceholderText("Напр.: Вивів частинні похідні за методичкою КАІ, підставив дані")
        self.p3_edit = QLineEdit()
        self.p3_edit.setPlaceholderText("Напр.: Отримав 14%, хоча контрольний прилад дає похибку < 2%")
        self.p4_edit = QLineEdit()
        self.p4_edit.setPlaceholderText("Напр.: Чи потрібно переводити кут у радіани перед диференціюванням?")

        form.addRow("Дисципліна:", self.cons_subj)
        form.addRow("1. Задача (що вирішую):", self.p1_edit)
        form.addRow("2. Що вже зроблено:", self.p2_edit)
        form.addRow("3. Де розбіжність:", self.p3_edit)
        form.addRow("4. Одне конкретне питання:", self.p4_edit)
        l.addLayout(form)

        add_cons_btn = QPushButton("Зберегти картку консультації")
        add_cons_btn.setProperty("class", "PrimaryBtn")
        add_cons_btn.clicked.connect(self._save_consultation)
        l.addWidget(add_cons_btn)

        self.cons_list_box = QTextEdit()
        self.cons_list_box.setReadOnly(True)
        l.addWidget(self.cons_list_box, 1)
        return w

    def refresh(self) -> None:
        subjects = self.academic_repo.list_subjects()
        self.subj_combo.blockSignals(True)
        self.subj_combo.clear()
        self.cons_subj.clear()
        for s in subjects:
            self.subj_combo.addItem(f"{s['name']} ({s['teacher_name']})", int(s["id"]))
            self.cons_subj.addItem(s["name"], int(s["id"]))
        self.subj_combo.blockSignals(False)

        self._load_subject_components()
        self._refresh_consultations_history()

    def _load_subject_components(self) -> None:
        subj_id = self.subj_combo.currentData()
        if subj_id is None:
            return
        subj = self.academic_repo.get_subject(int(subj_id))
        if subj:
            pol = subj.get("ai_policy", "forbidden")
            pol_map = {
                "green": ("Політика ШІ: ЗЕЛЕНА (дозволено з декларацією)", "BadgeSuccess"),
                "yellow": ("Політика ШІ: ЖОВТА (за погодженням викладача)", "BadgeWarning"),
                "forbidden": ("Політика ШІ: ЗАБОРОНЕНО без прямого дозволу", "BadgeDanger"),
            }
            txt, cls = pol_map.get(pol, ("Політика ШІ: перевірити силабус", "Badge"))
            self.ai_policy_badge.setText(txt)
            self.ai_policy_badge.setProperty("class", cls)
            self.ai_policy_badge.style().unpolish(self.ai_policy_badge)
            self.ai_policy_badge.style().polish(self.ai_policy_badge)

        comps = self.academic_repo.list_rso_components(int(subj_id))
        self._current_components = comps
        self.comp_table.setRowCount(len(comps))

        for r, c in enumerate(comps):
            self.comp_table.setItem(r, 0, QTableWidgetItem(str(c["title"])))
            self.comp_table.setItem(r, 1, QTableWidgetItem(str(c["component_type"])))
            self.comp_table.setItem(r, 2, QTableWidgetItem(f"{float(c['max_score']):.1f}"))

            spin = QDoubleSpinBox()
            spin.setRange(-1.0, float(c["max_score"]))
            spin.setSpecialValueText("— (не оцінено)")
            spin.setValue(float(c["earned_score"]) if c["earned_score"] is not None else -1.0)
            self.comp_table.setCellWidget(r, 3, spin)

            self.comp_table.setItem(r, 4, QTableWidgetItem(str(c["status"])))

        if subj:
            summary = RsoCalculator.calculate_subject_rso(subj, comps)
            self.sim_result_label.setText(
                f"Поточний рейтинг: {summary.total_earned:.1f} б. | "
                f"Поріг допуску: {summary.admission_threshold:.1f} б. "
                f"({'ДОПУЩЕНО' if summary.is_admitted else f'ще {summary.points_needed_for_admission:.1f} б.'})"
            )

    def _collect_table_scores(self) -> Dict[int, Optional[float]]:
        result: Dict[int, Optional[float]] = {}
        for r, comp in enumerate(getattr(self, "_current_components", [])):
            widget = self.comp_table.cellWidget(r, 3)
            if isinstance(widget, QDoubleSpinBox):
                val = widget.value()
                result[int(comp["id"])] = None if val < 0 else round(val, 2)
        return result

    def _run_rso_simulation(self) -> None:
        subj_id = self.subj_combo.currentData()
        if subj_id is None:
            return
        subj = self.academic_repo.get_subject(int(subj_id))
        if not subj:
            return
        scores = self._collect_table_scores()
        hypo = {cid: val for cid, val in scores.items() if val is not None}
        sim = RsoCalculator.simulate_what_if(subj, self._current_components, hypo)
        self.sim_result_label.setText(
            f"🧮 СИМУЛЯЦІЯ: Семестр = {sim.earned_semester:.1f} б., Іспит = {sim.earned_exam:.1f} б., "
            f"Разом = {sim.total_earned:.1f} б. → "
            f"{'ЗАРАХОВАНО (≥60)' if sim.is_passed else ('ДОПУСК Є, потрібно ще ' + str(sim.points_needed_for_pass) + ' б. до 60' if sim.is_admitted else 'НЕДОПУСК (менше ' + str(sim.admission_threshold) + ' б.)')}"
        )

    def _save_rso_scores(self) -> None:
        scores = self._collect_table_scores()
        for cid, val in scores.items():
            self.academic_repo.update_component_score(cid, val, source="manual")
        QMessageBox.information(self, "Збережено", "Бали РСО оновлено та зафіксовано в журналі аудиту.")
        self.on_data_changed()

    def _save_consultation(self) -> None:
        subj_id = self.cons_subj.currentData()
        if subj_id is None or not self.p1_edit.text().strip() or not self.p4_edit.text().strip():
            QMessageBox.warning(self, "Неповні дані", "Заповніть принаймні пункти 1 (Задача) та 4 (Запитання).")
            return
        self.cognitive_repo.create_consultation(
            subject_id=int(subj_id),
            p1_goal=self.p1_edit.text().strip(),
            p2_done=self.p2_edit.text().strip(),
            p3_discrepancy=self.p3_edit.text().strip(),
            p4_question=self.p4_edit.text().strip(),
        )
        self.p1_edit.clear()
        self.p2_edit.clear()
        self.p3_edit.clear()
        self.p4_edit.clear()
        self._refresh_consultations_history()

    def _refresh_consultations_history(self) -> None:
        items = self.cognitive_repo.list_consultations()
        lines: List[str] = []
        for it in items:
            lines.append(
                f"=== [{it['subject_name']}] Викладач: {it['teacher_name']} ({it['created_at'][:16]}) ===\n"
                f"1. Задача: {it['p1_goal']}\n"
                f"2. Зроблено: {it['p2_done']}\n"
                f"3. Розбіжність: {it['p3_discrepancy']}\n"
                f"4. Питання: {it['p4_question']}\n"
            )
        self.cons_list_box.setPlainText("\n".join(lines) if lines else "Карток консультацій ще немає.")


class TasksAndFocusPage(QWidget):
    """Сторінка 4: Канбан-дошка завдань (Правило лаби за 24 год) та Фокус-таймер Pomodoro."""

    COLUMNS = [
        ("backlog", "Беклог"),
        ("todo", "До виконання"),
        ("in_progress", "У роботі"),
        ("review", "На захист"),
        ("done", "Здано ✓"),
    ]

    def __init__(
        self,
        db: DatabaseManager,
        on_data_changed: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.on_data_changed = on_data_changed
        self.task_repo = TaskRepository(db)
        self.service = AcademicService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Завдання, дедлайни та Фокус-таймер Pomodoro")
        title.setProperty("class", "SectionTitle")
        top.addWidget(title, 1)

        self.quick_input = QLineEdit()
        self.quick_input.setPlaceholderText("Швидко додати: Лаба №2 #фізика завтра !критично")
        self.quick_input.setMinimumWidth(340)
        self.quick_input.returnPressed.connect(self._quick_create)
        top.addWidget(self.quick_input)

        add_btn = QPushButton("+ Додати")
        add_btn.setProperty("class", "PrimaryBtn")
        add_btn.clicked.connect(self._quick_create)
        top.addWidget(add_btn)
        layout.addLayout(top)

        self.focus_bar = FocusTimerBar()
        self.focus_bar.session_completed.connect(self._on_focus_finished)
        layout.addWidget(self.focus_bar)

        self.board_container = QWidget()
        self.board_layout = QHBoxLayout(self.board_container)
        self.board_layout.setSpacing(10)
        layout.addWidget(self.board_container, 1)

        self.refresh()

    def refresh(self) -> None:
        while self.board_layout.count():
            item = self.board_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tasks = self.task_repo.list_tasks()
        for status_key, col_title in self.COLUMNS:
            col_frame = QFrame()
            col_frame.setProperty("class", "Card")
            col_layout = QVBoxLayout(col_frame)
            col_layout.setContentsMargins(8, 8, 8, 8)
            col_layout.setSpacing(8)

            col_tasks = [t for t in tasks if t.get("status") == status_key]
            hdr = QLabel(f"{col_title} ({len(col_tasks)})")
            hdr.setProperty("tone", status_key)
            hdr.setProperty("tone", status_key)
            hdr.setProperty("class", "CardTitle")
            col_layout.addWidget(hdr)

            cards_holder = QWidget()
            cards_v = QVBoxLayout(cards_holder)
            cards_v.setContentsMargins(0, 0, 0, 0)
            cards_v.setSpacing(8)

            for t in col_tasks:
                card = KanbanCardWidget(t)
                card.status_changed.connect(self._change_status)
                cards_v.addWidget(card)
            cards_v.addStretch()

            col_layout.addWidget(_wrap_in_scroll(cards_holder), 1)
            self.board_layout.addWidget(col_frame, 1)

    def _quick_create(self) -> None:
        raw = self.quick_input.text().strip()
        if not raw:
            return
        self.service.quick_add_task(raw)
        self.quick_input.clear()
        self.on_data_changed()

    def _change_status(self, task_id: int, new_status: str) -> None:
        self.task_repo.update_task_status(task_id, new_status)
        self.on_data_changed()

    def _on_focus_finished(
        self, mode: str, planned: int, actual: int, interruptions: int
    ) -> None:
        self.task_repo.log_focus_session(
            mode=mode,
            planned_minutes=planned,
            actual_minutes=actual,
            interruptions_count=interruptions,
        )
        QMessageBox.information(
            self,
            "Фокус-сесію завершено!",
            f"Зараховано {actual} хв глибокої роботи (відволікань: {interruptions}). Час на безекранну перерву!",
        )
        self.on_data_changed()