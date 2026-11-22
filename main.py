from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

from PySide6.QtWidgets import QApplication

from config.defaults import DEFAULT_SETTINGS
from core.database import DatabaseManager
from core.repositories import (
    AcademicRepository,
    CognitiveRepository,
    PortfolioRepository,
    SyncAndFileRepository,
    TaskRepository,
)
from ui.main_window import MainWindow


def seed_initial_kai_data(db: DatabaseManager) -> None:
    """
    Заповнює базу реалістичним стартовим профілем студента КАІ (1 курс)
    при першому запуску застосунку, якщо таблиця семестрів порожня.
    """
    academic = AcademicRepository(db)
    if academic.get_active_semester() is not None:
        return

    tasks = TaskRepository(db)
    cognitive = CognitiveRepository(db)
    portfolio = PortfolioRepository(db)
    sync_repo = SyncAndFileRepository(db)

    # Базові налаштування профілю
    academic.set_setting("student_name", DEFAULT_SETTINGS.student_name)
    academic.set_setting("student_group", DEFAULT_SETTINGS.student_group)
    academic.set_setting("parity_anchor_date", DEFAULT_SETTINGS.parity_anchor_date)
    academic.set_setting("theme", DEFAULT_SETTINGS.theme)

    cur = db.execute(
        """
        INSERT INTO semesters (name, start_date, end_date, parity_anchor_date, is_active)
        VALUES (?, '2026-09-01', '2026-12-31', ?, 1)
        """,
        (DEFAULT_SETTINGS.semester_label, DEFAULT_SETTINGS.parity_anchor_date),
    )
    sem_id = int(cur.lastrowid)

    # Дисципліни КАІ із налаштованим РСО та політикою використання ШІ
    phys_id = academic.create_subject(
        semester_id=sem_id,
        code="PHYS-101",
        name="Загальна фізика (Механіка та молекулярна фізика)",
        teacher_name="проф. Коваленко О.В.",
        teacher_room="1-214",
        rso_model="60_40",
        admission_threshold=36.0,
        pass_threshold=60.0,
        ai_policy="yellow",
        ai_policy_notes="Дозволено пояснення теорії з обов'язковою декларацією; заборонено генерацію розрахунків.",
    )
    math_id = academic.create_subject(
        semester_id=sem_id,
        code="MATH-101",
        name="Вища математика (Лінійна алгебра та матаналіз)",
        teacher_name="доц. Мельник І.С.",
        teacher_room="8-405",
        rso_model="60_40",
        admission_threshold=35.0,
        pass_threshold=60.0,
        ai_policy="forbidden",
        ai_policy_notes="Політика КАІ: без прямого дозволу викладача завдання виконуються повністю самостійно.",
    )
    prog_id = academic.create_subject(
        semester_id=sem_id,
        code="CS-102",
        name="Алгоритмізація та програмування (Python / C++)",
        teacher_name="ст. викл. Бондаренко Д.М.",
        teacher_room="11-308",
        rso_model="100_accum",
        admission_threshold=40.0,
        pass_threshold=60.0,
        ai_policy="green",
        ai_policy_notes="Дозволено дебагінг та рев'ю коду зі збереженням історії промптів.",
    )
    stud_id = academic.create_subject(
        semester_id=sem_id,
        code="KAI-100",
        name="Університетські студії та академічна доброчесність",
        teacher_name="ст. викл. Гірчук О.В.",
        teacher_room="1-310",
        rso_model="100_accum",
        admission_threshold=45.0,
        pass_threshold=60.0,
        ai_policy="green",
        ai_policy_notes="Обов'язкове декларування ролі ШІ згідно із Законом № 4742-IX.",
    )

    # Компоненти РСО (частина вже оцінена, частина очікує здачі)
    academic.add_rso_component(phys_id, "Модульна контрольна №1", "module", 20.0, 17.0, status="graded")
    academic.add_rso_component(phys_id, "Лабораторна робота №1", "lab", 5.0, 5.0, status="graded")
    academic.add_rso_component(phys_id, "Лабораторна робота №2", "lab", 5.0, 4.5, status="graded")
    academic.add_rso_component(phys_id, "Лабораторна робота №3", "lab", 5.0, None, status="pending")
    academic.add_rso_component(phys_id, "Модульна контрольна №2", "module", 25.0, None, status="pending")
    academic.add_rso_component(phys_id, "Підсумковий іспит", "exam", 40.0, None, status="pending")

    academic.add_rso_component(math_id, "Модульна контрольна №1", "module", 25.0, 19.0, status="graded")
    academic.add_rso_component(math_id, "Розрахункова робота (Інтеграли)", "rgr", 15.0, None, status="pending")
    academic.add_rso_component(math_id, "Модульна контрольна №2", "module", 20.0, None, status="pending")
    academic.add_rso_component(math_id, "Підсумковий іспит", "exam", 40.0, None, status="pending")

    academic.add_rso_component(prog_id, "Лабораторні №1–4 (Базові структури)", "lab", 40.0, 36.0, status="graded")
    academic.add_rso_component(prog_id, "Лабораторна №5 (Файли та SQLite)", "lab", 20.0, None, status="pending")
    academic.add_rso_component(prog_id, "Курсовий міні-проєкт", "module", 40.0, None, status="pending")

    academic.add_rso_component(stud_id, "Доповідь: Міжнародні партнери КАІ", "practice", 30.0, 29.0, status="graded")
    academic.add_rso_component(stud_id, "Доповідь: Академічна доброчесність", "practice", 35.0, 34.0, status="graded")
    academic.add_rso_component(stud_id, "Підсумковий проєкт: Алгоритми КАІ", "module", 35.0, None, status="pending")

    # Розклад занять із чисельником/знаменником та переходами між корпусами КАІ (1, 8, 11)
    today_dow = date.today().isoweekday()
    active_dow = today_dow if today_dow <= 5 else 1

    academic.add_schedule_entry(
        subject_id=phys_id,
        day_of_week=active_dow,
        pair_number=1,
        start_time="08:00",
        end_time="09:35",
        parity="both",
        lesson_type="lecture",
        building="1",
        room="1-201",
    )
    academic.add_schedule_entry(
        subject_id=math_id,
        day_of_week=active_dow,
        pair_number=3,
        start_time="11:40",
        end_time="13:15",
        parity="both",
        lesson_type="practice",
        building="8",
        room="8-405",
    )
    academic.add_schedule_entry(
        subject_id=prog_id,
        day_of_week=active_dow,
        pair_number=4,
        start_time="13:30",
        end_time="15:05",
        parity="odd",
        lesson_type="lab",
        building="11",
        room="11-308",
    )
    academic.add_schedule_entry(
        subject_id=stud_id,
        day_of_week=(active_dow % 5) + 1,
        pair_number=2,
        start_time="09:50",
        end_time="11:25",
        parity="even",
        lesson_type="lecture",
        building="1",
        room="1-310",
    )

    # Початкові завдання для Канбан-дошки та Алгоритму 6
    tomorrow_iso = (date.today() + timedelta(days=1)).isoformat()
    in_3_days = (date.today() + timedelta(days=3)).isoformat()

    tasks.create_task(
        title="Оформити протокол Лабораторної №3 (Правило 24 годин)",
        subject_id=phys_id,
        description="Порахувати похибки непрямих вимірювань та побудувати графік.",
        task_type="lab",
        status="in_progress",
        priority=1,
        due_date=tomorrow_iso,
        lab_conducted_at=datetime.now().isoformat(timespec="minutes"),
        is_blackout_ready=1,
    )
    tasks.create_task(
        title="Реалізувати модуль парсингу даних для Лабораторної №5",
        subject_id=prog_id,
        description="Покрити базовими unit-тестами pytest та підготувати до захисту.",
        task_type="lab",
        status="todo",
        priority=2,
        due_date=in_3_days,
        is_blackout_ready=1,
    )
    tasks.create_task(
        title="Розв'язати 6 інтегралів із типового розрахунку без підглядання",
        subject_id=math_id,
        task_type="rgr",
        status="backlog",
        priority=2,
        due_date=(date.today() + timedelta(days=6)).isoformat(),
    )

    # Зразковий конспект Корнелла (Фаза 24 год) та картки для сесії «21 день»
    note_id = cognitive.save_cornell_note(
        subject_id=phys_id,
        lecture_number=4,
        topic="Закони збереження імпульсу та механічної енергії",
        lecture_date=(date.today() - timedelta(days=1)).isoformat(),
        cues_column="1. Коли система вважається замкненою?\n2. Умова застосування ЗЗІ?\n3. Різниця пружного та непружного удару?",
        notes_column="Імпульс тіла p = m*v.\nЗакон збереження імпульсу: сума векторів імпульсів замкненої системи постійна (F_зовн = 0).\nУ задачах на зіткнення обов'язково переходити до проєкцій на осі OX та OY.",
        summary_block="Імпульс зберігається у замкнених системах навіть при непружних ударах, де механічна енергія переходить у теплову.",
        review_stage=24,
        next_review_date=date.today().isoformat(),
    )

    cognitive.create_flashcard(
        subject_id=phys_id,
        note_id=note_id,
        question="За якої умови виконується закон збереження імпульсу системи тіл?",
        answer="Коли векторна сума всіх зовнішніх сил, що діють на систему, дорівнює нулю (замкнена система) або її проєкція на обрану вісь дорівнює нулю.",
    )
    cognitive.create_flashcard(
        subject_id=stud_id,
        question="Яка головна вимога Закону України № 4742-IX та Політики КАІ щодо використання ШІ?",
        answer="ШІ дозволено лише як допоміжний інструмент у дозволених викладачем межах; студент зобов'язаний перевіряти факти за першоджерелами, зберігати промпти та декларувати роль ШІ в роботі.",
    )

    # Стартовий запис у R&D Портфоліо КАІ
    portfolio.create_rd_item(
        lab_name="KAI-Ajax Lab",
        project_title="Телеметричний модуль моніторингу живлення",
        role_description="Проєктування архітектури збору даних із датчиків напруги та Python-клієнта візуалізації",
        tech_stack="Python, STM32, UART, PySide6",
        status="active",
        linkedin_draft="Працюю над прототипом системи телеметрії у KAI-Ajax Lab (Національний університет «Київський авіаційний інститут»). #KAI #AjaxNext #Embedded",
    )

    # Одна демонстраційна подія в черзі підтвердження (Human-in-the-loop)
    sync_repo.enqueue_agent_change(
        source="kai_portal",
        external_id="welcome_sync_check_1",
        entity_type="task",
        title="Підтвердити індивідуальний план семестру КАІ",
        payload={
            "title": "Перевірити пороги допуску по всіх 4 дисциплінах (Алгоритм 1)",
            "subject_id": stud_id,
            "task_type": "admin",
            "priority": 2,
            "due_date": tomorrow_iso,
        },
        diff_summary="Рекомендація стартового аудиту семестру (Алгоритм 1, Крок 1)",
    )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("KAI Student Command Center")

    db = DatabaseManager()
    db.apply_migrations()
    seed_initial_kai_data(db)

    window = MainWindow(db)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
