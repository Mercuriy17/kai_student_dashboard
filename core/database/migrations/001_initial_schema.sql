-- Міграція 001: Повна схема даних для КАІ Student Command Center
PRAGMA foreign_keys = ON;

-- 1. Метадані профілю та системні налаштування
CREATE TABLE IF NOT EXISTS user_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. Навчальні періоди (семестри)
CREATE TABLE IF NOT EXISTS semesters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    parity_anchor_date TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- 3. Дисципліни та параметри РСО
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    semester_id INTEGER NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    teacher_name TEXT NOT NULL DEFAULT '',
    teacher_email TEXT NOT NULL DEFAULT '',
    teacher_room TEXT NOT NULL DEFAULT '',
    rso_model TEXT NOT NULL DEFAULT '100_accum', -- '100_accum' або '60_40'
    max_points REAL NOT NULL DEFAULT 100.0,
    exam_max_points REAL NOT NULL DEFAULT 0.0,
    admission_threshold REAL NOT NULL DEFAULT 36.0,
    pass_threshold REAL NOT NULL DEFAULT 60.0,
    ai_policy TEXT NOT NULL DEFAULT 'forbidden', -- 'green', 'yellow', 'forbidden'
    ai_policy_notes TEXT NOT NULL DEFAULT '',
    syllabus_file_id INTEGER,
    color_hex TEXT NOT NULL DEFAULT '#3B82F6',
    FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE CASCADE
);

-- 4. Компоненти РСО (модулі, лабораторні, РГР, іспит)
CREATE TABLE IF NOT EXISTS rso_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    component_type TEXT NOT NULL DEFAULT 'lab', -- 'lab', 'module', 'rgr', 'practice', 'exam', 'bonus'
    max_score REAL NOT NULL DEFAULT 10.0,
    earned_score REAL, -- NULL якщо ще не оцінено
    is_mandatory INTEGER NOT NULL DEFAULT 1,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'submitted', 'graded', 'overdue'
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

-- 5. Розклад занять (чисельник/знаменник + корпуси КАІ)
CREATE TABLE IF NOT EXISTS schedule_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
    pair_number INTEGER NOT NULL DEFAULT 1,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    parity TEXT NOT NULL DEFAULT 'both', -- 'both', 'odd' (чисельник), 'even' (знаменник)
    lesson_type TEXT NOT NULL DEFAULT 'lecture', -- 'lecture', 'practice', 'lab', 'consultation'
    building TEXT NOT NULL DEFAULT '1',
    room TEXT NOT NULL DEFAULT '',
    online_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

-- 6. Разові зміни розкладу, консультації та вікна дедлайнів
CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER,
    title TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'consultation', -- 'consultation', 'exam', 'deadline', 'replacement', 'personal'
    event_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    is_completed INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL
);

-- 7. Завдання (Канбан, дедлайни, правило «лаба за 24 год»)
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER,
    rso_component_id INTEGER,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL DEFAULT 'lab', -- 'lab', 'rgr', 'module_prep', 'homework', 'rd', 'admin'
    status TEXT NOT NULL DEFAULT 'todo', -- 'backlog', 'todo', 'in_progress', 'review', 'done'
    priority INTEGER NOT NULL DEFAULT 2, -- 1 (критичний), 2 (високий), 3 (середній), 4 (низький)
    due_date TEXT,
    estimated_minutes INTEGER NOT NULL DEFAULT 60,
    lab_conducted_at TEXT, -- для відстеження правила 24 годин
    is_blackout_ready INTEGER NOT NULL DEFAULT 0, -- входить у мінімальний пакет Алг. 6
    is_top_priority_48h INTEGER NOT NULL DEFAULT 0, -- вибрано Алг. 6
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
    FOREIGN KEY (rso_component_id) REFERENCES rso_components(id) ON DELETE SET NULL
);

-- 8. Мікрокроки завдання (чек-лист розбиття на 20-хвилинні кроки)
CREATE TABLE IF NOT EXISTS task_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    step_order INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    is_done INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- 9. Журнал аудиту балів та змін оцінок
CREATE TABLE IF NOT EXISTS grade_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rso_component_id INTEGER NOT NULL,
    old_score REAL,
    new_score REAL,
    source TEXT NOT NULL DEFAULT 'manual', -- 'manual', 'classroom_sync', 'kai_portal'
    note TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (rso_component_id) REFERENCES rso_components(id) ON DELETE CASCADE
);

-- 10. Сесії Pomodoro / глибокого фокусу
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    subject_id INTEGER,
    mode TEXT NOT NULL DEFAULT '45_15', -- '25_5', '45_15', '50_10'
    planned_minutes INTEGER NOT NULL DEFAULT 45,
    actual_minutes INTEGER NOT NULL DEFAULT 0,
    interruptions_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL
);

-- 11. Конспекти лекцій за методом Корнелла (Алг. 2)
CREATE TABLE IF NOT EXISTS cornell_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    lecture_number INTEGER NOT NULL DEFAULT 1,
    topic TEXT NOT NULL,
    lecture_date TEXT NOT NULL,
    cues_column TEXT NOT NULL DEFAULT '',    -- Ліва колонка: запитання, терміни, формули
    notes_column TEXT NOT NULL DEFAULT '',   -- Права колонка: каркас лекції
    summary_block TEXT NOT NULL DEFAULT '',  -- Нижній блок: резюме 2-3 реченнями
    review_stage INTEGER NOT NULL DEFAULT 0, -- 0 (на парі), 24 (через добу), 7 (тиждень), 21 (перед сесією)
    next_review_date TEXT,
    hand_stuck_flag INTEGER NOT NULL DEFAULT 0, -- 1 якщо «зависла рука» -> повтор через 3 дні
    is_exam_deck INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

-- 12. Картки активного пригадування (Active Recall / колода 21 день)
CREATE TABLE IF NOT EXISTS flashcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    note_id INTEGER,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'medium', -- 'easy', 'medium', 'hard'
    times_reviewed INTEGER NOT NULL DEFAULT 0,
    times_correct INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TEXT,
    next_due_date TEXT,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (note_id) REFERENCES cornell_notes(id) ON DELETE SET NULL
);

-- 13. Конструктор консультацій 4 пунктів (Алг. 4)
CREATE TABLE IF NOT EXISTS consultation_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    task_id INTEGER,
    p1_goal TEXT NOT NULL,          -- 1. Задача
    p2_done TEXT NOT NULL,          -- 2. Що зроблено
    p3_discrepancy TEXT NOT NULL,   -- 3. Де розбіжність
    p4_question TEXT NOT NULL,      -- 4. Одне конкретне запитання
    teacher_answer TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft', -- 'draft', 'asked', 'resolved'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

-- 14. Декларації доброчесного використання ШІ та журнал промптів (Алг. 3)
CREATE TABLE IF NOT EXISTS ai_declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    subject_id INTEGER,
    tool_name TEXT NOT NULL,
    zone_level TEXT NOT NULL DEFAULT 'green', -- 'green', 'yellow'
    purpose TEXT NOT NULL,
    prompts_archive TEXT NOT NULL DEFAULT '',
    sources_verified INTEGER NOT NULL DEFAULT 0,
    declaration_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL
);

-- 15. Щоденний чек-ін ресурсу та саморегуляції (Алг. 6)
CREATE TABLE IF NOT EXISTS wellbeing_logs (
    log_date TEXT PRIMARY KEY,
    sleep_hours REAL NOT NULL DEFAULT 7.5,
    energy_level INTEGER NOT NULL DEFAULT 4 CHECK (energy_level BETWEEN 1 AND 5),
    stress_level INTEGER NOT NULL DEFAULT 2 CHECK (stress_level BETWEEN 1 AND 5),
    disruption_type TEXT NOT NULL DEFAULT 'none', -- 'none', 'air_raid', 'blackout', 'illness'
    emergency_mode_active INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);

-- 16. Проєкти R&D лабораторій КАІ та портфоліо (KAI-Ajax, AVIA, MIT UIEL, Huawei)
CREATE TABLE IF NOT EXISTS rd_portfolio_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_name TEXT NOT NULL,
    project_title TEXT NOT NULL,
    role_description TEXT NOT NULL,
    tech_stack TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active', -- 'idea', 'active', 'prototype', 'published'
    artifact_url TEXT NOT NULL DEFAULT '',
    linkedin_draft TEXT NOT NULL DEFAULT '',
    start_date TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 17. Локальний індекс навчальних файлів та силабусів
CREATE TABLE IF NOT EXISTS indexed_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER,
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    sha256_hash TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    doc_category TEXT NOT NULL DEFAULT 'material', -- 'syllabus', 'lecture', 'lab_report', 'book', 'other'
    extracted_text TEXT NOT NULL DEFAULT '',
    indexed_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL
);

-- 18. Відстежувані папки для watchdog
CREATE TABLE IF NOT EXISTS watched_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT NOT NULL UNIQUE,
    default_subject_id INTEGER,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (default_subject_id) REFERENCES subjects(id) ON DELETE SET NULL
);

-- 19. Черга змін зовнішніх агентів та парсерів (Human-in-the-loop)
CREATE TABLE IF NOT EXISTS agent_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, -- 'google_classroom', 'kai_portal', 'syllabus_parser', 'ics_import'
    external_id TEXT NOT NULL,
    entity_type TEXT NOT NULL, -- 'task', 'grade', 'schedule', 'rso_draft'
    title TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    diff_summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at TEXT,
    UNIQUE(source, external_id)
);

-- 20. Журнал резервних копій та експортів блекаут-пакетів
CREATE TABLE IF NOT EXISTS backup_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_type TEXT NOT NULL, -- 'sqlite_backup', 'blackout_pack'
    file_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 21. Журнал версій міграцій схеми
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Індекси для швидких вибірок
CREATE INDEX IF NOT EXISTS idx_tasks_status_due ON tasks(status, due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_subject ON tasks(subject_id);
CREATE INDEX IF NOT EXISTS idx_schedule_day_parity ON schedule_entries(day_of_week, parity);
CREATE INDEX IF NOT EXISTS idx_cornell_review ON cornell_notes(next_review_date, review_stage);
CREATE INDEX IF NOT EXISTS idx_agent_changes_status ON agent_changes(status);

-- Віртуальна таблиця повнотекстового пошуку FTS5 по конспектах, завданнях і файлах
CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents USING fts5(
    doc_type,
    ref_id UNINDEXED,
    title,
    body,
    tokenize = 'unicode61'
);