from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from core.repositories.base import BaseRepository


class CognitiveRepository(BaseRepository):
    def list_cornell_notes(self, subject_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if subject_id is not None:
            return self._fetch_all(
                """
                SELECT cn.*, s.name AS subject_name, s.code AS subject_code
                FROM cornell_notes cn
                JOIN subjects s ON s.id = cn.subject_id
                WHERE cn.subject_id = ?
                ORDER BY cn.lecture_date DESC, cn.lecture_number DESC
                """,
                (subject_id,),
            )
        return self._fetch_all(
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
        with self._db.transaction() as conn:
            if note_id is not None:
                conn.execute(
                    """
                    UPDATE cornell_notes
                    SET subject_id = ?, lecture_number = ?, topic = ?, lecture_date = ?,
                        cues_column = ?, notes_column = ?, summary_block = ?,
                        review_stage = ?, next_review_date = ?, hand_stuck_flag = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (
                        subject_id, lecture_number, topic, lecture_date,
                        cues_column, notes_column, summary_block,
                        review_stage, next_review_date, hand_stuck_flag, note_id,
                    ),
                )
                saved_id = note_id
            else:
                cur = conn.execute(
                    """
                    INSERT INTO cornell_notes (
                        subject_id, lecture_number, topic, lecture_date,
                        cues_column, notes_column, summary_block, review_stage, next_review_date, hand_stuck_flag
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        subject_id, lecture_number, topic, lecture_date,
                        cues_column, notes_column, summary_block, review_stage, next_review_date, hand_stuck_flag,
                    ),
                )
                saved_id = int(cur.lastrowid)

            self._upsert_fts(
                conn,
                "cornell_note",
                saved_id,
                f"Лекція {lecture_number}: {topic}",
                f"{cues_column}\n{notes_column}\n{summary_block}",
            )
            return saved_id

    def list_flashcards(self, subject_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if subject_id is not None:
            return self._fetch_all(
                """
                SELECT fc.*, s.name AS subject_name
                FROM flashcards fc
                JOIN subjects s ON s.id = fc.subject_id
                WHERE fc.subject_id = ?
                ORDER BY COALESCE(fc.next_due_date, '2000-01-01') ASC, fc.id ASC
                """,
                (subject_id,),
            )
        return self._fetch_all(
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
        return self._execute(
            """
            INSERT INTO flashcards (subject_id, note_id, question, answer, difficulty, next_due_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (subject_id, note_id, question, answer, difficulty, date.today().isoformat()),
        )

    def record_flashcard_attempt(self, card_id: int, is_correct: bool, next_due_date: str) -> None:
        self._execute(
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
        return self._fetch_all(
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
        return self._execute(
            """
            INSERT INTO consultation_briefs (
                subject_id, task_id, p1_goal, p2_done, p3_discrepancy, p4_question
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (subject_id, task_id, p1_goal, p2_done, p3_discrepancy, p4_question),
        )

    def list_ai_declarations(self) -> List[Dict[str, Any]]:
        return self._fetch_all(
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
        return self._execute(
            """
            INSERT INTO ai_declarations (
                task_id, subject_id, tool_name, zone_level, purpose,
                prompts_archive, sources_verified, declaration_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id, subject_id, tool_name, zone_level, purpose,
                prompts_archive, 1 if sources_verified else 0, declaration_text,
            ),
        )