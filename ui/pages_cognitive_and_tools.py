from __future__ import annotations

import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config.defaults import BACKUPS_DIR, DB_PATH, DEFAULT_SETTINGS
from core.connector_state import ConnectorStateRepository
from core.database.connection import DatabaseManager
from core.domain.cognitive_and_priority import ReviewScheduler
from core.repositories import (
    AcademicRepository,
    CognitiveRepository,
    PortfolioRepository,
    SyncAndFileRepository,
    TaskRepository,
)
from core.services import AcademicService, BlackoutExportService, SyncApprovalService
from infrastructure.files.file_indexer import LocalFileIndexer
from core.credential_vault import CredentialVault
from integrations.digital_university import DigitalUniversityConnector
from integrations.kai_portal import KaiPortalAdapter
from integrations.syllabus_parser import SyllabusParser
from ui.connections_dialog import ConnectionsDialog
from ui.workers import TaskWorker

try:
    from integrations.google_classroom import GoogleClassroomConnector
except ImportError:
    GoogleClassroomConnector = None  # type: ignore[assignment,misc]

DEFAULT_KAI_LABS = (
    "KAI-Ajax Lab",
    "AVIA Lab",
    "MIT UIEL (Ukraine Innovation & Engineering Lab)",
    "KAI Huawei Excellence Center",
    "Інша лабораторія / кафедра КАІ",
)


def _wrap_in_scroll(widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    return scroll


class CornellNotesPage(QWidget):
    """Сторінка 5: Конспекти лекцій за методом Корнелла (Алгоритм 2: 0 -> 24 -> 7 -> 21)."""

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
        self.service = AcademicService(db)
        self._selected_note: Optional[Dict[str, Any]] = None
        self._notes_cache: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Конспекти за методом Корнелла (Алгоритм 2: 0 → 24 → 7 → 21)")
        title.setProperty("class", "SectionTitle")
        top.addWidget(title, 1)

        new_btn = QPushButton("+ Новий конспект")
        new_btn.setProperty("class", "SecondaryBtn")
        new_btn.clicked.connect(self._clear_editor)
        top.addWidget(new_btn)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Ліва панель — список конспектів
        left_panel = QFrame()
        left_panel.setProperty("class", "Card")
        ll = QVBoxLayout(left_panel)
        ll.addWidget(QLabel("Збережені конспекти:"))
        self.notes_table = QTableWidget(0, 3)
        self.notes_table.setHorizontalHeaderLabels(["Дисципліна", "Тема", "Фаза / Повтор"])
        self.notes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.notes_table.cellClicked.connect(self._on_note_selected)
        ll.addWidget(self.notes_table)
        splitter.addWidget(left_panel)

        # Права панель — тризонний редактор Корнелла
        right_panel = QFrame()
        right_panel.setProperty("class", "Card")
        rl = QVBoxLayout(right_panel)

        meta_row = QHBoxLayout()
        self.subj_combo = QComboBox()
        self.lec_num = QSpinBox()
        self.lec_num.setRange(1, 60)
        self.lec_num.setPrefix("Лекція №")
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("Тема лекції...")
        meta_row.addWidget(self.subj_combo)
        meta_row.addWidget(self.lec_num)
        meta_row.addWidget(self.topic_edit, 1)
        rl.addLayout(meta_row)

        cols_row = QHBoxLayout()
        cues_box = QVBoxLayout()
        cues_box.addWidget(QLabel("Ліва колонка (30%): Запитання, терміни, умови меж"))
        self.cues_edit = QTextEdit()
        self.cues_edit.setPlaceholderText("Заповнюється у Фазі 24 год для самоперевірки...")
        cues_box.addWidget(self.cues_edit)

        notes_box = QVBoxLayout()
        notes_box.addWidget(QLabel("Права колонка (70%): Каркас лекції (Визначення → Формула → Приклад)"))
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Заповнюється під час пари (Фаза 0)...")
        notes_box.addWidget(self.notes_edit)

        cols_row.addLayout(cues_box, 3)
        cols_row.addLayout(notes_box, 7)
        rl.addLayout(cols_row, 1)

        rl.addWidget(QLabel("Нижній блок: Резюме сторінки 2–3 реченнями власними словами"))
        self.summary_edit = QTextEdit()
        self.summary_edit.setMaximumHeight(75)
        rl.addWidget(self.summary_edit)

        actions = QHBoxLayout()
        self.stage_badge = QLabel("Фаза 0 (Нова лекція)")
        self.stage_badge.setProperty("class", "Badge")
        actions.addWidget(self.stage_badge)

        self.hand_stuck_cb = QCheckBox("«Зависла рука» (повторити через 3 дні)")
        actions.addWidget(self.hand_stuck_cb)
        actions.addStretch()

        save_btn = QPushButton("💾 Зберегти конспект")
        save_btn.setProperty("class", "SecondaryBtn")
        save_btn.clicked.connect(self._save_note)
        actions.addWidget(save_btn)

        advance_btn = QPushButton("✓ Завершити повторення → Наступна фаза")
        advance_btn.setProperty("class", "PrimaryBtn")
        advance_btn.clicked.connect(self._advance_stage)
        actions.addWidget(advance_btn)
        rl.addLayout(actions)

        splitter.addWidget(right_panel)
        splitter.setSizes([340, 720])
        layout.addWidget(splitter, 1)

        self.refresh()

    def refresh(self) -> None:
        self.subj_combo.clear()
        for s in self.academic_repo.list_subjects():
            self.subj_combo.addItem(s["name"], int(s["id"]))

        self._notes_cache = self.cognitive_repo.list_cornell_notes()
        self.notes_table.setRowCount(len(self._notes_cache))
        for r, n in enumerate(self._notes_cache):
            self.notes_table.setItem(r, 0, QTableWidgetItem(str(n["subject_name"])))
            self.notes_table.setItem(r, 1, QTableWidgetItem(f"№{n['lecture_number']}: {n['topic']}"))
            self.notes_table.setItem(
                r, 2, QTableWidgetItem(f"Фаза {n['review_stage']} | {n.get('next_review_date') or '—'}")
            )

    def _clear_editor(self) -> None:
        self._selected_note = None
        self.topic_edit.clear()
        self.cues_edit.clear()
        self.notes_edit.clear()
        self.summary_edit.clear()
        self.hand_stuck_cb.setChecked(False)
        self.stage_badge.setText("Фаза 0 (Нова лекція)")

    def _on_note_selected(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._notes_cache):
            note = self._notes_cache[row]
            self._selected_note = note
            idx = self.subj_combo.findData(int(note["subject_id"]))
            if idx >= 0:
                self.subj_combo.setCurrentIndex(idx)
            self.lec_num.setValue(int(note["lecture_number"]))
            self.topic_edit.setText(str(note["topic"]))
            self.cues_edit.setText(str(note["cues_column"]))
            self.notes_edit.setText(str(note["notes_column"]))
            self.summary_edit.setText(str(note["summary_block"]))
            self.hand_stuck_cb.setChecked(bool(note.get("hand_stuck_flag", 0)))
            self.stage_badge.setText(ReviewScheduler.stage_label_ua(int(note["review_stage"])))

    def _save_note(self) -> None:
        subj_id = self.subj_combo.currentData()
        topic = self.topic_edit.text().strip()
        if subj_id is None or not topic:
            QMessageBox.warning(self, "Помилка", "Оберіть дисципліну та вкажіть тему лекції.")
            return

        current_stage = int(self._selected_note["review_stage"]) if self._selected_note else 0
        next_rev = (
            self._selected_note["next_review_date"]
            if self._selected_note
            else (date.today() + timedelta(days=1)).isoformat()
        )
        saved_id = self.cognitive_repo.save_cornell_note(
            subject_id=int(subj_id),
            lecture_number=self.lec_num.value(),
            topic=topic,
            lecture_date=date.today().isoformat(),
            cues_column=self.cues_edit.toPlainText(),
            notes_column=self.notes_edit.toPlainText(),
            summary_block=self.summary_edit.toPlainText(),
            review_stage=current_stage,
            next_review_date=next_rev,
            hand_stuck_flag=1 if self.hand_stuck_cb.isChecked() else 0,
            note_id=int(self._selected_note["id"]) if self._selected_note else None,
        )
        self.on_data_changed()
        for n in self._notes_cache:
            if int(n["id"]) == saved_id:
                self._selected_note = n
                break
        QMessageBox.information(self, "Збережено", "Конспект Корнелла збережено та проіндексовано у FTS5.")

    def _advance_stage(self) -> None:
        if not self._selected_note:
            self._save_note()
        if not self._selected_note:
            return
        new_stage, next_iso = self.service.advance_cornell_review(
            self._selected_note, hand_stuck=self.hand_stuck_cb.isChecked()
        )
        self.on_data_changed()
        self.stage_badge.setText(ReviewScheduler.stage_label_ua(new_stage))
        QMessageBox.information(
            self,
            "Етап оновлено",
            f"Наступне повторення заплановано на {next_iso} ({ReviewScheduler.stage_label_ua(new_stage)}).",
        )


class ExamSession21Page(QWidget):
    """Сторінка 6: Сесія «21 день» (Алгоритм 5) та тренажер активного пригадування (Active Recall)."""

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
        self._cards: List[Dict[str, Any]] = []
        self._card_index = 0
        self._answer_visible = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Сесія: зворотний відлік 21 день та колода активного пригадування (Алг. 5)")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        # Дорожня карта 21 дня
        roadmap = QFrame()
        roadmap.setProperty("class", "Card")
        rm_l = QHBoxLayout(roadmap)
        phases = [
            ("За 21–15 днів", "Закрити всі хвости з лаб і РГР, скласти список тем"),
            ("За 14–8 днів", "Пройти колоду карток, виявити слабкі місця"),
            ("За 7–3 дні", "Розв'язати білет на час (90 хв) без конспекту"),
            ("За 2 дні", "Легке повторення колоди та повний сон ≥7.5 год"),
        ]
        for p_title, p_desc in phases:
            box = QVBoxLayout()
            l1 = QLabel(p_title)
            l1.setProperty("class", "Badge")
            l2 = QLabel(p_desc)
            l2.setWordWrap(True)
            l2.setProperty("class", "MutedText")
            box.addWidget(l1)
            box.addWidget(l2)
            rm_l.addLayout(box, 1)
        layout.addWidget(roadmap)

        # Картка тренажера Active Recall
        trainer = QFrame()
        trainer.setProperty("class", "CardAccent")
        tl = QVBoxLayout(trainer)
        tl.setContentsMargins(20, 18, 20, 18)
        tl.setSpacing(12)

        self.card_counter = QLabel("Картка 0 / 0")
        self.card_counter.setProperty("class", "Badge")
        tl.addWidget(self.card_counter, 0, Qt.AlignmentFlag.AlignLeft)

        self.question_lbl = QLabel("Натисніть «Показати відповідь» після спроби відтворити матеріал усно чи на чернетці.")
        self.question_lbl.setWordWrap(True)
        self.question_lbl.setStyleSheet("font-size: 16px; font-weight: 700;")
        tl.addWidget(self.question_lbl)

        self.answer_lbl = QLabel("")
        self.answer_lbl.setWordWrap(True)
        self.answer_lbl.setStyleSheet("font-size: 14px; color: #6EE7B7; padding: 8px;")
        tl.addWidget(self.answer_lbl)

        btn_row = QHBoxLayout()
        self.reveal_btn = QPushButton("👁 Показати еталонну відповідь")
        self.reveal_btn.setProperty("class", "SecondaryBtn")
        self.reveal_btn.clicked.connect(self._reveal_answer)
        btn_row.addWidget(self.reveal_btn)

        self.hard_btn = QPushButton("⚠ Зависла рука (повтор через 3 дні)")
        self.hard_btn.setProperty("class", "DangerBtn")
        self.hard_btn.clicked.connect(lambda: self._rate_card(False))
        btn_row.addWidget(self.hard_btn)

        self.easy_btn = QPushButton("✓ Відтворив точно (наступний інтервал)")
        self.easy_btn.setProperty("class", "PrimaryBtn")
        self.easy_btn.clicked.connect(lambda: self._rate_card(True))
        btn_row.addWidget(self.easy_btn)
        tl.addLayout(btn_row)
        layout.addWidget(trainer)

        # Форма додавання нової картки до колоди
        add_card_box = QFrame()
        add_card_box.setProperty("class", "Card")
        acl = QHBoxLayout(add_card_box)
        self.new_card_subj = QComboBox()
        self.new_q = QLineEdit()
        self.new_q.setPlaceholderText("Запитання до колоди...")
        self.new_a = QLineEdit()
        self.new_a.setPlaceholderText("Ключова відповідь / формула / межі застосування...")
        add_btn = QPushButton("+ Додати картку")
        add_btn.setProperty("class", "PrimaryBtn")
        add_btn.clicked.connect(self._add_card)

        acl.addWidget(self.new_card_subj)
        acl.addWidget(self.new_q, 1)
        acl.addWidget(self.new_a, 1)
        acl.addWidget(add_btn)
        layout.addWidget(add_card_box)
        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        self.new_card_subj.clear()
        for s in self.academic_repo.list_subjects():
            self.new_card_subj.addItem(s["name"], int(s["id"]))

        self._cards = self.cognitive_repo.list_flashcards()
        if self._card_index >= len(self._cards):
            self._card_index = 0
        self._render_current_card()

    def _render_current_card(self) -> None:
        if not self._cards:
            self.card_counter.setText("Колода порожня")
            self.question_lbl.setText("Додайте запитання з конспектів Корнелла для підготовки до сесії.")
            self.answer_lbl.setText("")
            return

        card = self._cards[self._card_index]
        self.card_counter.setText(
            f"Картка {self._card_index + 1} із {len(self._cards)} • {card['subject_name']}"
        )
        self.question_lbl.setText(str(card["question"]))
        self.answer_lbl.setText(
            str(card["answer"])
            if self._answer_visible
            else "••• Відповідь прихована (спробуйте відповісти самостійно) •••"
        )

    def _reveal_answer(self) -> None:
        self._answer_visible = True
        self._render_current_card()

    def _rate_card(self, success: bool) -> None:
        if not self._cards:
            return
        card = self._cards[self._card_index]
        next_days = 7 if success else 3
        next_due = (date.today() + timedelta(days=next_days)).isoformat()
        self.cognitive_repo.record_flashcard_attempt(int(card["id"]), success, next_due)
        self._answer_visible = False
        self._card_index = (self._card_index + 1) % len(self._cards)
        self.refresh()

    def _add_card(self) -> None:
        subj_id = self.new_card_subj.currentData()
        q = self.new_q.text().strip()
        a = self.new_a.text().strip()
        if subj_id is None or not q or not a:
            return
        self.cognitive_repo.create_flashcard(int(subj_id), q, a)
        self.new_q.clear()
        self.new_a.clear()
        self.refresh()


class RdPortfolioPage(QWidget):
    """Сторінка 7: Проєкти R&D лабораторій КАІ (Ajax, AVIA, MIT UIEL, Huawei) та LinkedIn-чернетки."""

    def __init__(
        self,
        db: DatabaseManager,
        on_data_changed: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.on_data_changed = on_data_changed
        self.portfolio_repo = PortfolioRepository(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("КАІ R&D Портфоліо: лабораторії та інженерні проєкти")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        form_card = QFrame()
        form_card.setProperty("class", "Card")
        fl = QFormLayout(form_card)

        self.lab_combo = QComboBox()
        labs = DEFAULT_SETTINGS.get("kai_labs", DEFAULT_KAI_LABS)
        self.lab_combo.addItems(list(labs))

        self.proj_title = QLineEdit()
        self.proj_title.setPlaceholderText("Назва проєкту / прототипу...")
        self.role_edit = QLineEdit()
        self.role_edit.setPlaceholderText("Ваша конкретна інженерна роль (напр.: розробка прошивки STM32 / телеметрії)")
        self.stack_edit = QLineEdit()
        self.stack_edit.setPlaceholderText("Стек технологій: Python, C++, FreeRTOS, KiCad...")

        fl.addRow("Лабораторія / Хаб КАІ:", self.lab_combo)
        fl.addRow("Назва проєкту:", self.proj_title)
        fl.addRow("Ваш внесок:", self.role_edit)
        fl.addRow("Технології:", self.stack_edit)

        add_btn = QPushButton("+ Додати в портфоліо та згенерувати пост для LinkedIn")
        add_btn.setProperty("class", "PrimaryBtn")
        add_btn.clicked.connect(self._create_project)
        fl.addRow(add_btn)
        layout.addWidget(form_card)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Лабораторія КАІ", "Проєкт", "Роль", "Стек", "LinkedIn-чернетка"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self.refresh()

    def refresh(self) -> None:
        items = self.portfolio_repo.list_rd_items()
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            self.table.setItem(r, 0, QTableWidgetItem(str(it["lab_name"])))
            self.table.setItem(r, 1, QTableWidgetItem(str(it["project_title"])))
            self.table.setItem(r, 2, QTableWidgetItem(str(it["role_description"])))
            self.table.setItem(r, 3, QTableWidgetItem(str(it["tech_stack"])))
            self.table.setItem(r, 4, QTableWidgetItem(str(it["linkedin_draft"])))

    def _create_project(self) -> None:
        p_title = self.proj_title.text().strip()
        role = self.role_edit.text().strip()
        if not p_title or not role:
            return
        lab = self.lab_combo.currentText()
        stack = self.stack_edit.text().strip()
        linkedin = (
            f"Працюю над інженерним проєктом «{p_title}» у межах {lab} (КАІ). "
            f"Мій фокус: {role}. Стек: {stack or 'інженерний прототип'}. #KAI #Engineering #Ukraine"
        )
        self.portfolio_repo.create_rd_item(
            lab_name=lab,
            project_title=p_title,
            role_description=role,
            tech_stack=stack,
            linkedin_draft=linkedin,
        )
        self.proj_title.clear()
        self.role_edit.clear()
        self.stack_edit.clear()
        self.refresh()


class FilesAndSearchPage(QWidget):
    """Сторінка 8: Локальні файли, парсер силабусів РСО та повнотекстовий пошук FTS5."""

    def __init__(
        self,
        db: DatabaseManager,
        indexer: LocalFileIndexer,
        on_data_changed: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.indexer = indexer
        self.on_data_changed = on_data_changed
        self.sync_repo = SyncAndFileRepository(db)
        self.academic_repo = AcademicRepository(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Локальний індекс матеріалів (FTS5) та парсер силабусів КАІ")
        title.setProperty("class", "SectionTitle")
        top.addWidget(title, 1)

        add_folder_btn = QPushButton("📁 Підключити папку для автоіндексації")
        add_folder_btn.setProperty("class", "SecondaryBtn")
        add_folder_btn.clicked.connect(self._add_watch_folder)
        top.addWidget(add_folder_btn)

        parse_syl_btn = QPushButton("📄 Імпортувати силабус (PDF/DOCX) у РСО")
        parse_syl_btn.setProperty("class", "PrimaryBtn")
        parse_syl_btn.clicked.connect(self._import_syllabus)
        top.addWidget(parse_syl_btn)
        layout.addLayout(top)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Пошук по всіх конспектах Корнелла, завданнях та PDF/DOCX файлах...")
        self.search_edit.returnPressed.connect(self._run_search)
        search_btn = QPushButton("🔍 Шукати (FTS5)")
        search_btn.setProperty("class", "PrimaryBtn")
        search_btn.clicked.connect(self._run_search)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["Тип", "Назва", "Знайдений фрагмент", "ID"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.results_table, 1)

        self.refresh()

    def refresh(self) -> None:
        files = self.sync_repo.list_indexed_files()
        self.results_table.setRowCount(len(files))
        for r, f in enumerate(files):
            self.results_table.setItem(r, 0, QTableWidgetItem(str(f["doc_category"])))
            self.results_table.setItem(r, 1, QTableWidgetItem(str(f["file_name"])))
            self.results_table.setItem(r, 2, QTableWidgetItem(str(f["file_path"])))
            self.results_table.setItem(r, 3, QTableWidgetItem(str(f["id"])))

    def _search_fts(self, query: str) -> List[Dict[str, Any]]:
        if hasattr(self.db, "search_fts"):
            return self.db.search_fts(query)  # type: ignore[no-any-return]
        with self.db.transaction() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT entity_type AS doc_type, entity_id AS ref_id, title,
                           snippet(global_fts, 3, '[', ']', '...', 24) AS snippet
                    FROM global_fts
                    WHERE global_fts MATCH ?
                    LIMIT 50
                    """,
                    (query,),
                ).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.Error:
                like_q = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT 'indexed_file' AS doc_type, id AS ref_id, file_name AS title,
                           substr(extracted_text, 1, 120) AS snippet
                    FROM indexed_files
                    WHERE file_name LIKE ? OR extracted_text LIKE ?
                    LIMIT 50
                    """,
                    (like_q, like_q),
                ).fetchall()
                return [dict(r) for r in rows]

    def _run_search(self) -> None:
        q = self.search_edit.text().strip()
        if not q:
            self.refresh()
            return
        hits = self._search_fts(q)
        self.results_table.setRowCount(len(hits))
        for r, h in enumerate(hits):
            self.results_table.setItem(r, 0, QTableWidgetItem(str(h.get("doc_type", ""))))
            self.results_table.setItem(r, 1, QTableWidgetItem(str(h.get("title", ""))))
            self.results_table.setItem(r, 2, QTableWidgetItem(str(h.get("snippet", ""))))
            self.results_table.setItem(r, 3, QTableWidgetItem(str(h.get("ref_id", ""))))

    def _add_watch_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Оберіть папку з лекціями / лабораторними")
        if folder:
            p = Path(folder)
            self.sync_repo.add_watched_folder(str(p))
            count = self.indexer.scan_directory(p)
            self.indexer.start_watching()
            QMessageBox.information(self, "Папку підключено", f"Проіндексовано файлів: {count}.")
            self.refresh()

    def _import_syllabus(self) -> None:
        subjects = self.academic_repo.list_subjects()
        if not subjects:
            return
        file_str, _ = QFileDialog.getOpenFileName(
            self, "Оберіть файл силабусу КАІ", "", "Документи (*.pdf *.docx *.txt)"
        )
        if not file_str:
            return
        p = Path(file_str)
        names = [s["name"] for s in subjects]
        chosen, ok = QInputDialog.getItem(
            self, "Дисципліна", "Для якої дисципліни цей силабус?", names, 0, False
        )
        if not ok:
            return
        target_subj = subjects[names.index(chosen)]
        draft = SyllabusParser.parse_syllabus_file(p, int(target_subj["id"]))
        self.sync_repo.enqueue_agent_change(
            source="syllabus_parser",
            external_id=f"syl_{p.name}_{target_subj['id']}",
            entity_type="rso_draft",
            title=f"Чернетка РСО із силабусу «{p.name}» для {target_subj['name']}",
            payload=draft,
            diff_summary=f"Розпізнано {len(draft['components'])} компонентів оцінювання",
        )
        QMessageBox.information(
            self,
            "Силабус розпізнано",
            "Чернетку структури балів РСО додано у вкладку «Синхронізація (Human-in-the-loop)» для вашого підтвердження.",
        )
        self.on_data_changed()


class SyncQueuePage(QWidget):
    """Сторінка 9: Черга зовнішніх змін (Google Classroom, Портал КАІ, Силабуси) — Human-in-the-loop."""

    def __init__(
        self,
        db: DatabaseManager,
        on_data_changed: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.on_data_changed = on_data_changed
        self.sync_repo = SyncAndFileRepository(db)
        self.academic_repo = AcademicRepository(db)
        self.approval_service = SyncApprovalService(db)
        self.classroom = (
            GoogleClassroomConnector(self.academic_repo, self.sync_repo)
            if GoogleClassroomConnector is not None
            else None
        )
        self.portal = KaiPortalAdapter(self.academic_repo, self.sync_repo)
        self.vault = CredentialVault()
        self.conn_state = ConnectorStateRepository(db)
        self.du = DigitalUniversityConnector(self.academic_repo, self.sync_repo, self.vault, self.conn_state)
        self._workers: List[TaskWorker] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Центр синхронізації (Human-in-the-loop)")
        title.setProperty("class", "SectionTitle")
        top.addWidget(title, 1)

        gc_btn = QPushButton("🔄 Перевірити Google Classroom")
        gc_btn.setProperty("class", "PrimaryBtn")
        gc_btn.clicked.connect(self._sync_classroom)
        top.addWidget(gc_btn)

        kai_btn = QPushButton("🏛 Перевірити портал КАІ")
        kai_btn.setProperty("class", "SecondaryBtn")
        kai_btn.clicked.connect(self._sync_kai)
        top.addWidget(kai_btn)

        du_btn = QPushButton("🎓 Digital University")
        du_btn.setProperty("class", "PrimaryBtn")
        du_btn.clicked.connect(self._sync_du)
        top.addWidget(du_btn)

        du_html_btn = QPushButton("📄 Імпорт розкладу (HTML)")
        du_html_btn.setProperty("class", "SecondaryBtn")
        du_html_btn.clicked.connect(self._import_du_html)
        top.addWidget(du_html_btn)

        conn_btn = QPushButton("🔑 Підключення")
        conn_btn.setProperty("class", "SecondaryBtn")
        conn_btn.clicked.connect(self._open_connections)
        top.addWidget(conn_btn)
        layout.addLayout(top)

        hint = QLabel(
            "Жодна зовнішня зміна не змінює ваші оцінки чи дедлайни автоматично — підтвердіть або відхиліть кожен запис нижче:"
        )
        hint.setProperty("class", "MutedText")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Джерело", "Тип", "Заголовок", "Деталі (Diff)", "Дія"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self.refresh()

    def refresh(self) -> None:
        pending = self.sync_repo.list_agent_changes(status="pending")
        self.table.setRowCount(len(pending))
        for r, item in enumerate(pending):
            cid = int(item["id"])
            self.table.setItem(r, 0, QTableWidgetItem(str(item["source"])))
            self.table.setItem(r, 1, QTableWidgetItem(str(item["entity_type"])))
            self.table.setItem(r, 2, QTableWidgetItem(str(item["title"])))
            self.table.setItem(r, 3, QTableWidgetItem(str(item["diff_summary"])))

            act_w = QWidget()
            al = QHBoxLayout(act_w)
            al.setContentsMargins(2, 2, 2, 2)
            ok_b = QPushButton("✓ Підтвердити")
            ok_b.setProperty("class", "PrimaryBtn")
            ok_b.clicked.connect(lambda _, x=cid: self._approve(x))

            rej_b = QPushButton("✕ Відхилити")
            rej_b.setProperty("class", "DangerBtn")
            rej_b.clicked.connect(lambda _, x=cid: self._reject(x))
            al.addWidget(ok_b)
            al.addWidget(rej_b)
            self.table.setCellWidget(r, 4, act_w)

    def _run_async(self, fn: Callable[[], Any], on_ok: Callable[[Any], None]) -> None:
        """Довга операція виконується у фоновому потоці — вікно не зависає."""
        worker = TaskWorker(fn, self)
        worker.succeeded.connect(on_ok)
        worker.failed.connect(lambda msg: QMessageBox.warning(self, "Синхронізація", msg))
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _sync_classroom(self) -> None:
        if self.classroom is None:
            QMessageBox.information(
                self,
                "Google Classroom",
                "Конектор Classroom зараз у процесі переходу на OAuth-адаптер. Налаштуйте підключення в меню «Підключення».",
            )
            return
        self._run_async(self.classroom.sync_to_approval_queue, self._after_classroom)

    def _after_classroom(self, res: Dict[str, Any]) -> None:
        QMessageBox.information(self, "Google Classroom", res["message"])
        self.on_data_changed()

    def _sync_du(self) -> None:
        self._run_async(self.du.sync_to_approval_queue, self._after_du)

    def _import_du_html(self) -> None:
        file_str, _ = QFileDialog.getOpenFileName(
            self, "Збережена сторінка «Розклад»", "", "HTML (*.html *.htm)"
        )
        if file_str:
            self._run_async(lambda: self.du.import_from_html_file(Path(file_str)), self._after_du)

    def _after_du(self, res: Dict[str, Any]) -> None:
        QMessageBox.information(self, "Digital University", res["message"])
        self.on_data_changed()

    def _open_connections(self) -> None:
        ConnectionsDialog(self.vault, self.conn_state, self.du, self).exec()

    def _sync_kai(self) -> None:
        QMessageBox.information(
            self,
            "Портал КАІ",
            "Пряма синхронізація з порталом КАІ ще не реалізована. "
            "Щоб не додавати демонстраційні або неперевірені дані до вашого розкладу, "
            "ця дія не створює жодних записів. Для отримання реального розкладу "
            "скористайтеся підключенням Digital University або імпортом HTML.",
        )

    def _approve(self, change_id: int) -> None:
        try:
            msg = self.approval_service.approve_change(change_id)
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Не застосовано", f"Зміну не вдалося застосувати: {exc}")
            return
        QMessageBox.information(self, "Застосовано", msg)
        self.on_data_changed()

    def _reject(self, change_id: int) -> None:
        self.approval_service.reject_change(change_id)
        self.on_data_changed()


class AlgorithmsAndAiPage(QWidget):
    """Сторінка 10: Алгоритми 1–6, Чек-ап 7 запитань та Генератор декларації ШІ (Закон № 4742-IX)."""

    CHECKLIST_7 = [
        "1. Чи є в мене силабус кожної дисципліни та таблиця балів?",
        "2. Чи знаю я поріг допуску до сесії хоча б для двох головних предметів?",
        "3. Чи здані вчасно всі лабораторні та РГР за останні два тижні?",
        "4. Чи можу я без конспекту пояснити три теми минулого тижня?",
        "5. Чи перевірив я за першоджерелами все, що взяв від ШІ?",
        "6. Чи є в мене офлайн-копія матеріалів на випадок відключення світла?",
        "7. Чи був я на консультації хоча б раз за місяць, якщо щось було неясно?",
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
        self.academic_repo = AcademicRepository(db)
        self.cognitive_repo = CognitiveRepository(db)
        self.service = AcademicService(db)
        self._check_boxes: List[QCheckBox] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Алгоритми успішного навчання КАІ (1–6) та Академічна доброчесність")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_ai_declaration_tab(), "🛡 Генератор декларації ШІ (Закон № 4742-IX)")
        tabs.addTab(self._build_self_check_tab(), "✅ Самоперевірка семестру (7 критеріїв)")
        layout.addWidget(tabs, 1)

        self.refresh()

    def _build_ai_declaration_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        info = QLabel(
            "Алгоритм 3 (Закон «Про академічну доброчесність» № 4742-IX та Політика КАІ): "
            "використовуйте ШІ як помічника лише після 15–20 хв власної спроби, перевіряйте факти за двома "
            "першоджерелами та формуйте прозору примітку-декларацію."
        )
        info.setWordWrap(True)
        info.setProperty("class", "MutedText")
        l.addWidget(info)

        form = QFormLayout()
        self.decl_subj = QComboBox()
        self.tool_edit = QLineEdit()
        self.tool_edit.setPlaceholderText("Напр.: Gemini / Claude (режим пояснення та критики тексту)")
        self.purpose_edit = QLineEdit()
        self.purpose_edit.setPlaceholderText("Напр.: пояснення термінів аеродинаміки та підбір ключових слів для Google Scholar")
        self.prompts_edit = QTextEdit()
        self.prompts_edit.setMaximumHeight(80)
        self.prompts_edit.setPlaceholderText("Збережіть сюди історію промптів (на вимогу викладача КАІ)...")
        self.verified_cb = QCheckBox("Підтверджую: усі формули, факти та джерела перевірено за першоджерелами")
        self.verified_cb.setChecked(True)

        form.addRow("Дисципліна:", self.decl_subj)
        form.addRow("Інструмент / модель ШІ:", self.tool_edit)
        form.addRow("Мета допоміжного використання:", self.purpose_edit)
        form.addRow("Архів запитів (промптів):", self.prompts_edit)
        form.addRow("", self.verified_cb)
        l.addLayout(form)

        gen_btn = QPushButton("📜 Згенерувати та зберегти декларацію ШІ")
        gen_btn.setProperty("class", "PrimaryBtn")
        gen_btn.clicked.connect(self._create_declaration)
        l.addWidget(gen_btn)

        self.decl_output = QTextEdit()
        self.decl_output.setReadOnly(True)
        l.addWidget(self.decl_output, 1)
        return w

    def _build_self_check_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        self._check_boxes = []
        for q in self.CHECKLIST_7:
            cb = QCheckBox(q)
            cb.stateChanged.connect(self._evaluate_checklist)
            self._check_boxes.append(cb)
            l.addWidget(cb)

        self.check_verdict = QLabel("Позначте пункти, які виконуються станом на сьогодні.")
        self.check_verdict.setProperty("class", "CardTitle")
        l.addWidget(self.check_verdict)
        l.addStretch()
        return w

    def refresh(self) -> None:
        self.decl_subj.clear()
        for s in self.academic_repo.list_subjects():
            self.decl_subj.addItem(s["name"], int(s["id"]))

    def _create_declaration(self) -> None:
        tool = self.tool_edit.text().strip()
        purpose = self.purpose_edit.text().strip()
        if not tool or not purpose:
            QMessageBox.warning(self, "Неповні дані", "Вкажіть назву інструменту ШІ та мету використання.")
            return
        text = self.service.generate_ai_declaration_text(
            tool_name=tool,
            purpose=purpose,
            verified_sources=self.verified_cb.isChecked(),
        )
        self.cognitive_repo.create_ai_declaration(
            tool_name=tool,
            zone_level="green",
            purpose=purpose,
            prompts_archive=self.prompts_edit.toPlainText().strip(),
            sources_verified=self.verified_cb.isChecked(),
            declaration_text=text,
            subject_id=self.decl_subj.currentData(),
        )
        self.decl_output.setPlainText(text)
        QMessageBox.information(self, "Готово", "Текст декларації згенеровано та збережено в журналі.")

    def _evaluate_checklist(self) -> None:
        yes_count = sum(1 for cb in self._check_boxes if cb.isChecked())
        no_count = len(self._check_boxes) - yes_count
        if no_count >= 3:
            self.check_verdict.setText(
                f"⚠ Відповідь «Ні» на {no_count} запитань (≥3): час запускати Алгоритм 1 і двотижневий чек-ап!"
            )
        else:
            self.check_verdict.setText(
                f"✅ Відповідь «Так» на {yes_count} із 7 пунктів: система навчання в робочому тонусі."
            )


class AnalyticsPage(QWidget):
    """Сторінка 11: Аналітика продуктивності, фокус-сесій та виконання завдань."""

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.task_repo = TaskRepository(db)
        self.academic_repo = AcademicRepository(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Аналітика навчального ритму та глибокого фокусу")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        self.kpi_label = QLabel("")
        self.kpi_label.setProperty("class", "CardTitle")
        layout.addWidget(self.kpi_label)

        self.summary_table = QTableWidget(0, 5)
        self.summary_table.setHorizontalHeaderLabels(
            ["Дисципліна", "Модель РСО", "Семестр", "Іспит", "Статус допуску"]
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.summary_table, 1)

        self.refresh()

    def refresh(self) -> None:
        f_stats = self.task_repo.get_focus_stats()
        tasks = self.task_repo.list_tasks()
        done_cnt = sum(1 for t in tasks if t["status"] == "done")
        self.kpi_label.setText(
            f"Сесій Pomodoro: {f_stats['sessions_count']} ({f_stats['total_minutes']} хв) | "
            f"Відволікань зафіксовано: {f_stats['total_interruptions']} | "
            f"Виконано завдань: {done_cnt} із {len(tasks)}"
        )

        sums = self.academic_repo.get_all_rso_summaries()
        self.summary_table.setRowCount(len(sums))
        for r, s in enumerate(sums):
            self.summary_table.setItem(r, 0, QTableWidgetItem(s.subject_name))
            self.summary_table.setItem(r, 1, QTableWidgetItem(s.rso_model))
            self.summary_table.setItem(r, 2, QTableWidgetItem(f"{s.earned_semester:.1f}"))
            self.summary_table.setItem(r, 3, QTableWidgetItem(f"{s.earned_exam:.1f}"))
            self.summary_table.setItem(
                r, 4, QTableWidgetItem("Допущено" if s.is_admitted else f"Ще {s.points_needed_for_admission} б.")
            )


class SettingsAndBackupsPage(QWidget):
    """Сторінка 12: Налаштування теми, опорної дати тижня, бекапи SQLite та пакет блекауту."""

    def __init__(
        self,
        db: DatabaseManager,
        on_theme_changed: Callable[[str], None],
        on_data_changed: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.on_theme_changed = on_theme_changed
        self.on_data_changed = on_data_changed
        self.academic_repo = AcademicRepository(db)
        self.portfolio_repo = PortfolioRepository(db)
        self.blackout_service = BlackoutExportService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Налаштування системи, резервні копії та офлайн-експорт")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        card = QFrame()
        card.setProperty("class", "Card")
        fl = QFormLayout(card)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Темна тема (Командний центр)", "dark")
        self.theme_combo.addItem("Світла денна тема", "light")
        default_theme = str(DEFAULT_SETTINGS.get("theme", "dark"))
        curr_theme = self.academic_repo.get_setting("theme", default_theme)
        self.theme_combo.setCurrentIndex(1 if curr_theme == "light" else 0)

        default_anchor = str(DEFAULT_SETTINGS.get("parity_anchor_date", "2026-09-01"))
        self.anchor_edit = QLineEdit(
            self.academic_repo.get_setting("parity_anchor_date", default_anchor)
        )

        fl.addRow("Оформлення інтерфейсу:", self.theme_combo)
        fl.addRow("Опорний понеділок 1-го тижня (РРРР-ММ-ДД):", self.anchor_edit)

        save_btn = QPushButton("💾 Зберегти налаштування")
        save_btn.setProperty("class", "PrimaryBtn")
        save_btn.clicked.connect(self._save_settings)
        fl.addRow(save_btn)
        layout.addWidget(card)

        actions = QHBoxLayout()
        bkp_btn = QPushButton("🛡 Створити гарячий бекап БД (SQLite Backup API)")
        bkp_btn.setProperty("class", "SecondaryBtn")
        bkp_btn.clicked.connect(self._create_backup)
        actions.addWidget(bkp_btn)

        blk_btn = QPushButton("📦 Згенерувати ZIP-пакет блекауту (Алг. 6)")
        blk_btn.setProperty("class", "PrimaryBtn")
        blk_btn.clicked.connect(self._create_blackout)
        actions.addWidget(blk_btn)
        layout.addLayout(actions)

        self.backups_table = QTableWidget(0, 4)
        self.backups_table.setHorizontalHeaderLabels(["Тип", "Шлях до файлу", "Розмір (байт)", "Час"])
        self.backups_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.backups_table, 1)

        self.refresh()

    def refresh(self) -> None:
        rows = self.portfolio_repo.list_backups()
        self.backups_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            self.backups_table.setItem(r, 0, QTableWidgetItem(str(item["backup_type"])))
            self.backups_table.setItem(r, 1, QTableWidgetItem(str(item["file_path"])))
            self.backups_table.setItem(r, 2, QTableWidgetItem(str(item["size_bytes"])))
            self.backups_table.setItem(r, 3, QTableWidgetItem(str(item["created_at"])))

    def _save_settings(self) -> None:
        theme_val = str(self.theme_combo.currentData())
        anchor_val = self.anchor_edit.text().strip()
        try:
            date.fromisoformat(anchor_val)
        except ValueError:
            QMessageBox.warning(self, "Невірний формат дати", "Введіть дату у форматі РРРР-ММ-ДД.")
            return
        self.academic_repo.set_setting("theme", theme_val)
        self.academic_repo.set_setting("parity_anchor_date", anchor_val)
        self.on_theme_changed(theme_val)
        self.on_data_changed()

    def _create_backup(self) -> None:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUPS_DIR / f"kai_dashboard_backup_{stamp}.db"

        if hasattr(self.db, "create_backup"):
            backup_path = Path(self.db.create_backup())  # type: ignore[attr-defined]
        else:
            with self.db.transaction() as src_conn:
                dst_conn = sqlite3.connect(backup_path)
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()

        size = backup_path.stat().st_size if backup_path.exists() else 0
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO backup_history (backup_type, file_path, size_bytes) VALUES (?, ?, ?)",
                ("sqlite_hot_backup", str(backup_path), size),
            )
        QMessageBox.information(self, "Бекап створено", f"Резервну копію збережено:\n{backup_path}")
        self.refresh()

    def _create_blackout(self) -> None:
        path = self.blackout_service.export_blackout_bundle()
        QMessageBox.information(self, "Пакет блекауту", f"Офлайн-пакет збережено:\n{path}")
        self.refresh()