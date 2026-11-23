from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.domain.academic_rules import RsoCalculator, RsoSummary
from core.repositories.base import BaseRepository


class SubjectRepository(BaseRepository):
    def get_active_semester(self) -> Optional[Dict[str, Any]]:
        return self._fetch_one("SELECT * FROM semesters WHERE is_active = 1 ORDER BY id DESC LIMIT 1")

    def list_subjects(self, semester_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if semester_id is None:
            sem = self.get_active_semester()
            if not sem:
                return self._fetch_all("SELECT * FROM subjects ORDER BY name")
            semester_id = int(sem["id"])
        return self._fetch_all("SELECT * FROM subjects WHERE semester_id = ? ORDER BY name", (semester_id,))

    def get_subject(self, subject_id: int) -> Optional[Dict[str, Any]]:
        return self._fetch_one("SELECT * FROM subjects WHERE id = ?", (subject_id,))

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
        return self._execute(
            """
            INSERT INTO subjects (
                semester_id, code, name, teacher_name, teacher_email, teacher_room,
                rso_model, admission_threshold, pass_threshold, ai_policy, ai_policy_notes, color_hex
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                semester_id, code, name, teacher_name, teacher_email, teacher_room,
                rso_model, admission_threshold, pass_threshold, ai_policy, ai_policy_notes, color_hex,
            ),
        )

    def list_rso_components(self, subject_id: int) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM rso_components WHERE subject_id = ? ORDER BY id", (subject_id,))

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
        return self._execute(
            """
            INSERT INTO rso_components (
                subject_id, title, component_type, max_score, earned_score, due_date, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (subject_id, title, component_type, max_score, earned_score, due_date, status),
        )

    def update_component_score(
        self,
        component_id: int,
        new_score: Optional[float],
        source: str = "manual",
        note: str = "",
    ) -> None:
        existing = self._fetch_one("SELECT earned_score FROM rso_components WHERE id = ?", (component_id,))
        old_score = existing["earned_score"] if existing else None
        new_status = "graded" if new_score is not None else "pending"
        with self._db.transaction() as conn:
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
        return [
            RsoCalculator.calculate_subject_rso(subj, self.list_rso_components(int(subj["id"])))
            for subj in self.list_subjects()
        ]