from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from core.database import DatabaseManager
from core.domain.academic_rules import RsoCalculator, RsoSummary


class AcademicRepository:
    """Репозиторій семестрів, дисциплін, компонентів РСО, розкладу та подій календаря."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.db.fetch_one("SELECT value FROM user_settings WHERE key = ?", (key,))
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute(
            """
            INSERT INTO user_settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value),
        )

    def get_active_semester(self) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            "SELECT * FROM semesters WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )

    def list_subjects(self, semester_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if semester_id is None:
            sem = self.get_active_semester()
            if not sem:
                return self.db.fetch_all("SELECT * FROM subjects ORDER BY name")
            semester_id = int(sem["id"])
        return self.db.fetch_all(
            "SELECT * FROM subjects WHERE semester_id = ? ORDER BY name",
            (semester_id,),
        )

    def get_subject(self, subject_id: int) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one("SELECT * FROM subjects WHERE id = ?", (subject_id,))

    def create_subject(
        self,
        semester_id: int,
        name: str,
        code: str = "",
        teacher_name: str = "",
        teacher_email: str = "",
        teacher_room: str = "",
        rso_model: str = "100_accum",
        admission_threshold: float = 36.0,
        pass_threshold: float = 60.0,
        ai_policy: str = "forbidden",
        ai_policy_notes: str = "",
        color_hex: str = "#3B82F6",
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO subjects (
                semester_id, code, name, teacher_name, teacher_email, teacher_room,
                rso_model, admission_threshold, pass_threshold, ai_policy, ai_policy_notes, color_hex
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                semester_id,
                code,
                name,
                teacher_name,
                teacher_email,
                teacher_room,
                rso_model,
                admission_threshold,
                pass_threshold,
                ai_policy,
                ai_policy_notes,
                color_hex,
            ),
        )
        return int(cur.lastrowid)

    def list_rso_components(self, subject_id: int) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM rso_components WHERE subject_id = ? ORDER BY id",
            (subject_id,),
        )

    def add_rso_component(
        self,
        subject_id: int,
        title: str,
        component_type: str,
        max_score: float,
        earned_score: Optional[float] = None,
        due_date: Optional[str] = None,
        status: str = "pending",
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO rso_components (
                subject_id, title, component_type, max_score, earned_score, due_date, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (subject_id, title, component_type, max_score, earned_score, due_date, status),
        )
        return int(cur.lastrowid)

    def update_component_score(
        self,
        component_id: int,
        new_score: Optional[float],
        source: str = "manual",
        note: str = "",
    ) -> None:
        existing = self.db.fetch_one(
            "SELECT earned_score FROM rso_components WHERE id = ?", (component_id,)
        )
        old_score = existing["earned_score"] if existing else None
        new_status = "graded" if new_score is not None else "pending"
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE rso_components SET earned_score = ?, status = ? WHERE id = ?",
                (new_score, new_status, component_id),
            )
            conn.execute(
                """
                INSERT INTO grade_audit_log (rso_component_id, old_score, new_score, source, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (component_id, old_score, new_score, source, note),
            )

    def get_all_rso_summaries(self) -> List[RsoSummary]:
        summaries: List[RsoSummary] = []
        for subj in self.list_subjects():
            comps = self.list_rso_components(int(subj["id"]))
            summaries.append(RsoCalculator.calculate_subject_rso(subj, comps))
        return summaries

    def list_schedule(self, day_of_week: Optional[int] = None) -> List[Dict[str, Any]]:
        if day_of_week is not None:
            return self.db.fetch_all(
                """
                SELECT se.*, s.name AS subject_name, s.code AS subject_code, s.color_hex, s.teacher_name
                FROM schedule_entries se
                JOIN subjects s ON s.id = se.subject_id
                WHERE se.day_of_week = ?
                ORDER BY se.pair_number, se.start_time
                """,
                (day_of_week,),
            )
        return self.db.fetch_all(
            """
            SELECT se.*, s.name AS subject_name, s.code AS subject_code, s.color_hex, s.teacher_name
            FROM schedule_entries se
            JOIN subjects s ON s.id = se.subject_id
            ORDER BY se.day_of_week, se.pair_number, se.start_time
            """
        )

    def add_schedule_entry(
        self,
        subject_id: int,
        day_of_week: int,
        pair_number: int,
        start_time: str,
        end_time: str,
        parity: str = "both",
        lesson_type: str = "lecture",
        building: str = "1",
        room: str = "",
        online_url: str = "",
        notes: str = "",
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO schedule_entries (
                subject_id, day_of_week, pair_number, start_time, end_time,
                parity, lesson_type, building, room, online_url, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject_id,
                day_of_week,
                pair_number,
                start_time,
                end_time,
                parity,
                lesson_type,
                building,
                room,
                online_url,
                notes,
            ),
        )
        return int(cur.lastrowid)

    def list_calendar_events(self, from_date: Optional[str] = None) -> List[Dict[str, Any]]:
        if from_date:
            return self.db.fetch_all(
                """
                SELECT ce.*, s.name AS subject_name
                FROM calendar_events ce
                LEFT JOIN subjects s ON s.id = ce.subject_id
                WHERE ce.event_date >= ?
                ORDER BY ce.event_date, ce.start_time
                """,
                (from_date,),
            )
        return self.db.fetch_all(
            """
            SELECT ce.*, s.name AS subject_name
            FROM calendar_events ce
            LEFT JOIN subjects s ON s.id = ce.subject_id
            ORDER BY ce.event_date, ce.start_time
            """
        )

    def add_calendar_event(
        self,
        title: str,
        event_date: str,
        start_time: str,
        end_time: str,
        event_type: str = "consultation",
        subject_id: Optional[int] = None,
        location: str = "",
        description: str = "",
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO calendar_events (
                subject_id, title, event_type, event_date, start_time, end_time, location, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (subject_id, title, event_type, event_date, start_time, end_time, location, description),
        )
        return int(cur.lastrowid)


class TaskRepository:
    """Репозиторій завдань, мікрокроків, фокус-сесій та чек-інів саморегуляції."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def list_tasks(
        self,
        status: Optional[str] = None,
        subject_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("t.status = ?")
            params.append(status)
        if subject_id is not None:
            clauses.append("t.subject_id = ?")
            params.append(subject_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.db.fetch_all(
            f"""
            SELECT t.*, s.name AS subject_name, s.code AS subject_code, s.color_hex
            FROM tasks t
            LEFT JOIN subjects s ON s.id = t.subject_id
            {where_sql}
            ORDER BY
                CASE WHEN t.status = 'done' THEN 1 ELSE 0 END,
                t.priority ASC,
                COALESCE(t.due_date, '9999-12-31') ASC
            """,
            tuple(params),
        )

    def create_task(
        self,
        title: str,
        subject_id: Optional[int] = None,
        rso_component_id: Optional[int] = None,
        description: str = "",
        task_type: str = "lab",
        status: str = "todo",
        priority: int = 2,
        due_date: Optional[str] = None,
        estimated_minutes: int = 60,
        lab_conducted_at: Optional[str] = None,
        is_blackout_ready: int = 0,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO tasks (
                subject_id, rso_component_id, title, description, task_type,
                status, priority, due_date, estimated_minutes, lab_conducted_at, is_blackout_ready
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject_id,
                rso_component_id,
                title,
                description,
                task_type,
                status,
                priority,
                due_date,
                estimated_minutes,
                lab_conducted_at,
                is_blackout_ready,
            ),
        )
        task_id = int(cur.lastrowid)
        self.db.upsert_fts_document("task", task_id, title, f"{task_type} {description}")
        return task_id

    def update_task_status(self, task_id: int, new_status: str) -> None:
        completed_expr = "datetime('now')" if new_status == "done" else "NULL"
        self.db.execute(
            f"UPDATE tasks SET status = ?, completed_at = {completed_expr} WHERE id = ?",
            (new_status, task_id),
        )

    def list_task_steps(self, task_id: int) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_order, id",
            (task_id,),
        )

    def add_task_step(self, task_id: int, title: str, step_order: int = 1) -> int:
        cur = self.db.execute(
            "INSERT INTO task_steps (task_id, step_order, title) VALUES (?, ?, ?)",
            (task_id, step_order, title),
        )
        return int(cur.lastrowid)

    def toggle_task_step(self, step_id: int, is_done: bool) -> None:
        self.db.execute(
            "UPDATE task_steps SET is_done = ? WHERE id = ?",
            (1 if is_done else 0, step_id),
        )

    def log_focus_session(
        self,
        mode: str,
        planned_minutes: int,
        actual_minutes: int,
        task_id: Optional[int] = None,
        subject_id: Optional[int] = None,
        interruptions_count: int = 0,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO focus_sessions (
                task_id, subject_id, mode, planned_minutes, actual_minutes,
                interruptions_count, ended_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (task_id, subject_id, mode, planned_minutes, actual_minutes, interruptions_count),
        )
        return int(cur.lastrowid)

    def get_focus_stats(self) -> Dict[str, Any]:
        row = self.db.fetch_one(
            """
            SELECT
                COUNT(*) AS sessions_count,
                COALESCE(SUM(actual_minutes), 0) AS total_minutes,
                COALESCE(SUM(interruptions_count), 0) AS total_interruptions
            FROM focus_sessions
            """
        )
        return row or {"sessions_count": 0, "total_minutes": 0, "total_interruptions": 0}

    def save_wellbeing_log(
        self,
        log_date: str,
        sleep_hours: float,
        energy_level: int,
        stress_level: int,
        disruption_type: str = "none",
        emergency_mode_active: bool = False,
        notes: str = "",
    ) -> None:
        self.db.execute(
            """
            INSERT INTO wellbeing_logs (
                log_date, sleep_hours, energy_level, stress_level,
                disruption_type, emergency_mode_active, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(log_date) DO UPDATE SET
                sleep_hours = excluded.sleep_hours,
                energy_level = excluded.energy_level,
                stress_level = excluded.stress_level,
                disruption_type = excluded.disruption_type,
                emergency_mode_active = excluded.emergency_mode_active,
                notes = excluded.notes
            """,
            (
                log_date,
                sleep_hours,
                energy_level,
                stress_level,
                disruption_type,
                1 if emergency_mode_active else 0,
                notes,
            ),
        )

    def get_wellbeing_log(self, log_date: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one("SELECT * FROM wellbeing_logs WHERE log_date = ?", (log_date,))


class CognitiveRepository:
    """Репозиторій конспектів Корнелла, карток 21-денної колоди, консультацій та декларацій ШІ."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def list_cornell_notes(self, subject_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if subject_id is not None:
            return self.db.fetch_all(
                """
                SELECT cn.*, s.name AS subject_name, s.code AS subject_code
                FROM cornell_notes cn
                JOIN subjects s ON s.id = cn.subject_id
                WHERE cn.subject_id = ?
                ORDER BY cn.lecture_date DESC, cn.lecture_number DESC
                """,
                (subject_id,),
            )
        return self.db.fetch_all(
            """
            SELECT cn.*, s.name AS subject_name, s.code AS subject_code
            FROM cornell_notes cn
            JOIN subjects s ON s.id = cn.subject_id
            ORDER BY cn.lecture_date DESC, cn.lecture_number DESC
            """
        )

    def save_cornell_note(
        self,
        subject_id: int,
        lecture_number: int,
        topic: str,
        lecture_date: str,
        cues_column: str,
        notes_column: str,
        summary_block: str,
        review_stage: int = 0,
        next_review_date: Optional[str] = None,
        hand_stuck_flag: int = 0,
        note_id: Optional[int] = None,
    ) -> int:
        if note_id is not None:
            self.db.execute(
                """
                UPDATE cornell_notes
                SET subject_id = ?, lecture_number = ?, topic = ?, lecture_date = ?,
                    cues_column = ?, notes_column = ?, summary_block = ?,
                    review_stage = ?, next_review_date = ?, hand_stuck_flag = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    subject_id,
                    lecture_number,
                    topic,
                    lecture_date,
                    cues_column,
                    notes_column,
                    summary_block,
                    review_stage,
                    next_review_date,
                    hand_stuck_flag,
                    note_id,
                ),
            )
            saved_id = note_id
        else:
            cur = self.db.execute(
                """
                INSERT INTO cornell_notes (
                    subject_id, lecture_number, topic, lecture_date,
                    cues_column, notes_column, summary_block, review_stage, next_review_date, hand_stuck_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subject_id,
                    lecture_number,
                    topic,
                    lecture_date,
                    cues_column,
                    notes_column,
                    summary_block,
                    review_stage,
                    next_review_date,
                    hand_stuck_flag,
                ),
            )
            saved_id = int(cur.lastrowid)

        self.db.upsert_fts_document(
            "cornell_note",
            saved_id,
            f"Лекція {lecture_number}: {topic}",
            f"{cues_column}\n{notes_column}\n{summary_block}",
        )
        return saved_id

    def list_flashcards(self, subject_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if subject_id is not None:
            return self.db.fetch_all(
                """
                SELECT fc.*, s.name AS subject_name
                FROM flashcards fc
                JOIN subjects s ON s.id = fc.subject_id
                WHERE fc.subject_id = ?
                ORDER BY COALESCE(fc.next_due_date, '2000-01-01') ASC, fc.id ASC
                """,
                (subject_id,),
            )
        return self.db.fetch_all(
            """
            SELECT fc.*, s.name AS subject_name
            FROM flashcards fc
            JOIN subjects s ON s.id = fc.subject_id
            ORDER BY COALESCE(fc.next_due_date, '2000-01-01') ASC, fc.id ASC
            """
        )

    def create_flashcard(
        self,
        subject_id: int,
        question: str,
        answer: str,
        difficulty: str = "medium",
        note_id: Optional[int] = None,
    ) -> int:
        today_iso = date.today().isoformat()
        cur = self.db.execute(
            """
            INSERT INTO flashcards (subject_id, note_id, question, answer, difficulty, next_due_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (subject_id, note_id, question, answer, difficulty, today_iso),
        )
        return int(cur.lastrowid)

    def record_flashcard_attempt(self, card_id: int, is_correct: bool, next_due_date: str) -> None:
        self.db.execute(
            """
            UPDATE flashcards
            SET times_reviewed = times_reviewed + 1,
                times_correct = times_correct + ?,
                last_reviewed_at = datetime('now'),
                next_due_date = ?
            WHERE id = ?
            """,
            (1 if is_correct else 0, next_due_date, card_id),
        )

    def list_consultations(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT cb.*, s.name AS subject_name, s.teacher_name
            FROM consultation_briefs cb
            JOIN subjects s ON s.id = cb.subject_id
            ORDER BY cb.created_at DESC
            """
        )

    def create_consultation(
        self,
        subject_id: int,
        p1_goal: str,
        p2_done: str,
        p3_discrepancy: str,
        p4_question: str,
        task_id: Optional[int] = None,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO consultation_briefs (
                subject_id, task_id, p1_goal, p2_done, p3_discrepancy, p4_question
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (subject_id, task_id, p1_goal, p2_done, p3_discrepancy, p4_question),
        )
        return int(cur.lastrowid)

    def list_ai_declarations(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT ad.*, s.name AS subject_name
            FROM ai_declarations ad
            LEFT JOIN subjects s ON s.id = ad.subject_id
            ORDER BY ad.created_at DESC
            """
        )

    def create_ai_declaration(
        self,
        tool_name: str,
        zone_level: str,
        purpose: str,
        prompts_archive: str,
        sources_verified: bool,
        declaration_text: str,
        subject_id: Optional[int] = None,
        task_id: Optional[int] = None,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO ai_declarations (
                task_id, subject_id, tool_name, zone_level, purpose,
                prompts_archive, sources_verified, declaration_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                subject_id,
                tool_name,
                zone_level,
                purpose,
                prompts_archive,
                1 if sources_verified else 0,
                declaration_text,
            ),
        )
        return int(cur.lastrowid)


class SyncAndFileRepository:
    """Репозиторій черги агентських змін (Human-in-the-loop) та індексованих файлів."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def enqueue_agent_change(
        self,
        source: str,
        external_id: str,
        entity_type: str,
        title: str,
        payload: Dict[str, Any],
        diff_summary: str = "",
    ) -> bool:
        """Ідемпотентне додавання зовнішньої зміни в чергу очікування."""
        existing = self.db.fetch_one(
            "SELECT id FROM agent_changes WHERE source = ? AND external_id = ?",
            (source, external_id),
        )
        if existing:
            return False
        self.db.execute(
            """
            INSERT INTO agent_changes (
                source, external_id, entity_type, title, payload_json, diff_summary, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (source, external_id, entity_type, title, json.dumps(payload, ensure_ascii=False), diff_summary),
        )
        return True

    def list_agent_changes(self, status: Optional[str] = "pending") -> List[Dict[str, Any]]:
        if status:
            return self.db.fetch_all(
                "SELECT * FROM agent_changes WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        return self.db.fetch_all("SELECT * FROM agent_changes ORDER BY created_at DESC")

    def mark_agent_change(self, change_id: int, status: str) -> None:
        self.db.execute(
            "UPDATE agent_changes SET status = ?, reviewed_at = datetime('now') WHERE id = ?",
            (status, change_id),
        )

    def upsert_indexed_file(
        self,
        file_path: str,
        file_name: str,
        extension: str,
        sha256_hash: str,
        file_size_bytes: int,
        doc_category: str,
        extracted_text: str,
        subject_id: Optional[int] = None,
    ) -> int:
        existing = self.db.fetch_one(
            "SELECT id, sha256_hash FROM indexed_files WHERE file_path = ?", (file_path,)
        )
        if existing and existing["sha256_hash"] == sha256_hash:
            return int(existing["id"])

        self.db.execute(
            """
            INSERT INTO indexed_files (
                subject_id, file_path, file_name, extension, sha256_hash,
                file_size_bytes, doc_category, extracted_text, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(file_path) DO UPDATE SET
                subject_id = COALESCE(excluded.subject_id, indexed_files.subject_id),
                sha256_hash = excluded.sha256_hash,
                file_size_bytes = excluded.file_size_bytes,
                doc_category = excluded.doc_category,
                extracted_text = excluded.extracted_text,
                indexed_at = excluded.indexed_at
            """,
            (
                subject_id,
                file_path,
                file_name,
                extension,
                sha256_hash,
                file_size_bytes,
                doc_category,
                extracted_text,
            ),
        )
        row = self.db.fetch_one("SELECT id FROM indexed_files WHERE file_path = ?", (file_path,))
        file_id = int(row["id"])
        self.db.upsert_fts_document("indexed_file", file_id, file_name, extracted_text[:40000])
        return file_id

    def list_indexed_files(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT f.*, s.name AS subject_name
            FROM indexed_files f
            LEFT JOIN subjects s ON s.id = f.subject_id
            ORDER BY f.indexed_at DESC
            """
        )

    def list_watched_folders(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT wf.*, s.name AS subject_name
            FROM watched_folders wf
            LEFT JOIN subjects s ON s.id = wf.default_subject_id
            ORDER BY wf.id
            """
        )

    def add_watched_folder(self, folder_path: str, default_subject_id: Optional[int] = None) -> int:
        cur = self.db.execute(
            """
            INSERT INTO watched_folders (folder_path, default_subject_id, is_enabled)
            VALUES (?, ?, 1)
            ON CONFLICT(folder_path) DO UPDATE SET
                default_subject_id = excluded.default_subject_id,
                is_enabled = 1
            """,
            (folder_path, default_subject_id),
        )
        return int(cur.lastrowid)


class PortfolioRepository:
    """Репозиторій проєктів R&D лабораторій КАІ (KAI-Ajax, AVIA, MIT UIEL, Huawei) та історії бекапів."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def list_rd_items(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM rd_portfolio_items ORDER BY updated_at DESC, id DESC")

    def create_rd_item(
        self,
        lab_name: str,
        project_title: str,
        role_description: str,
        tech_stack: str = "",
        status: str = "active",
        artifact_url: str = "",
        linkedin_draft: str = "",
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO rd_portfolio_items (
                lab_name, project_title, role_description, tech_stack,
                status, artifact_url, linkedin_draft, start_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, date('now'))
            """,
            (
                lab_name,
                project_title,
                role_description,
                tech_stack,
                status,
                artifact_url,
                linkedin_draft,
            ),
        )
        return int(cur.lastrowid)

    def list_backups(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM backup_history ORDER BY created_at DESC LIMIT 20")