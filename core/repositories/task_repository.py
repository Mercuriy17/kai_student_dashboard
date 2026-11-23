from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.repositories.base import BaseRepository


class TaskRepository(BaseRepository):
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
        return self._fetch_all(
            f"""
            SELECT t.*, s.name AS subject_name, s.code AS subject_code, s.color_hex,
                (SELECT COUNT(*) FROM task_steps ts WHERE ts.task_id = t.id) AS steps_total,
                (SELECT COUNT(*) FROM task_steps ts WHERE ts.task_id = t.id AND ts.is_done = 1) AS steps_done
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
        with self._db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks (
                    subject_id, rso_component_id, title, description, task_type,
                    status, priority, due_date, estimated_minutes, lab_conducted_at, is_blackout_ready
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subject_id, rso_component_id, title, description, task_type,
                    status, priority, due_date, estimated_minutes, lab_conducted_at, is_blackout_ready,
                ),
            )
            task_id = int(cur.lastrowid)
            self._upsert_fts(conn, "task", task_id, title, f"{task_type} {description}")
            return task_id

    def update_task_status(self, task_id: int, new_status: str) -> None:
        completed_expr = "datetime('now')" if new_status == "done" else "NULL"
        self._execute(
            f"UPDATE tasks SET status = ?, completed_at = {completed_expr} WHERE id = ?",
            (new_status, task_id),
        )

    def list_task_steps(self, task_id: int) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_order, id", (task_id,))

    def add_task_step(self, task_id: int, title: str, step_order: int = 1) -> int:
        return self._execute(
            "INSERT INTO task_steps (task_id, step_order, title) VALUES (?, ?, ?)",
            (task_id, step_order, title),
        )

    def toggle_task_step(self, step_id: int, is_done: bool) -> None:
        self._execute("UPDATE task_steps SET is_done = ? WHERE id = ?", (1 if is_done else 0, step_id))

    def log_focus_session(
        self,
        mode: str,
        planned_minutes: int,
        actual_minutes: int,
        task_id: Optional[int] = None,
        subject_id: Optional[int] = None,
        interruptions_count: int = 0,
    ) -> int:
        return self._execute(
            """
            INSERT INTO focus_sessions (
                task_id, subject_id, mode, planned_minutes, actual_minutes,
                interruptions_count, ended_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (task_id, subject_id, mode, planned_minutes, actual_minutes, interruptions_count),
        )

    def get_focus_stats(self) -> Dict[str, Any]:
        row = self._fetch_one(
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
        self._execute(
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
            (log_date, sleep_hours, energy_level, stress_level, disruption_type, 1 if emergency_mode_active else 0, notes),
        )

    def get_wellbeing_log(self, log_date: str) -> Optional[Dict[str, Any]]:
        return self._fetch_one("SELECT * FROM wellbeing_logs WHERE log_date = ?", (log_date,))