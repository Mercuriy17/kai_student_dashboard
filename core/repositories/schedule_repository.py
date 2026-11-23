from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.repositories.base import BaseRepository


class ScheduleRepository(BaseRepository):
    def list_schedule(self, day_of_week: Optional[int] = None) -> List[Dict[str, Any]]:
        if day_of_week is not None:
            return self._fetch_all(
                """
                SELECT se.*, s.name AS subject_name, s.code AS subject_code, s.color_hex, s.teacher_name
                FROM schedule_entries se
                JOIN subjects s ON s.id = se.subject_id
                WHERE se.day_of_week = ?
                ORDER BY se.pair_number, se.start_time
                """,
                (day_of_week,),
            )
        return self._fetch_all(
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
        return self._execute(
            """
            INSERT INTO schedule_entries (
                subject_id, day_of_week, pair_number, start_time, end_time,
                parity, lesson_type, building, room, online_url, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (subject_id, day_of_week, pair_number, start_time, end_time, parity, lesson_type, building, room, online_url, notes),
        )

    def list_calendar_events(self, from_date: Optional[str] = None) -> List[Dict[str, Any]]:
        if from_date:
            return self._fetch_all(
                """
                SELECT ce.*, s.name AS subject_name
                FROM calendar_events ce
                LEFT JOIN subjects s ON s.id = ce.subject_id
                WHERE ce.event_date >= ?
                ORDER BY ce.event_date, ce.start_time
                """,
                (from_date,),
            )
        return self._fetch_all(
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
        return self._execute(
            """
            INSERT INTO calendar_events (
                subject_id, title, event_type, event_date, start_time, end_time, location, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (subject_id, title, event_type, event_date, start_time, end_time, location, description),
        )