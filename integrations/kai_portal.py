from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from icalendar import Calendar, Event

from core.repositories import AcademicRepository, SyncAndFileRepository


class KaiPortalAdapter:
    """
    Адаптер розкладу КАІ / Digital University та стандартного формату iCalendar (.ics).
    Усі імпортовані зміни проходять через чергу підтвердження AgentChange.
    """

    def __init__(self, academic_repo: AcademicRepository, sync_repo: SyncAndFileRepository) -> None:
        self.academic_repo = academic_repo
        self.sync_repo = sync_repo

    def export_schedule_to_ics(self, output_path: Path, weeks_ahead: int = 2) -> Path:
        """Експортує поточний розклад КАІ у стандартний .ics календар."""
        cal = Calendar()
        cal.add("prodid", "-//KAI Student Command Center//UA")
        cal.add("version", "2.0")

        entries = self.academic_repo.list_schedule()
        today = date.today()
        monday = today - timedelta(days=today.weekday())

        for week_offset in range(weeks_ahead):
            for entry in entries:
                dow = int(entry["day_of_week"])
                lesson_date = monday + timedelta(days=(week_offset * 7 + dow - 1))
                sh, sm = map(int, entry["start_time"].split(":"))
                eh, em = map(int, entry["end_time"].split(":"))

                ev = Event()
                ev.add(
                    "summary",
                    f"[{entry['lesson_type'].upper()}] {entry['subject_name']} (корп. {entry['building']}, ауд. {entry['room']})",
                )
                ev.add("dtstart", datetime(lesson_date.year, lesson_date.month, lesson_date.day, sh, sm))
                ev.add("dtend", datetime(lesson_date.year, lesson_date.month, lesson_date.day, eh, em))
                ev.add("location", f"КАІ, корпус {entry['building']}, ауд. {entry['room']}")
                cal.add_component(ev)

        output_path.write_bytes(cal.to_ical())
        return output_path

    def import_ics_into_approval_queue(self, ics_path: Path, default_subject_id: int) -> int:
        """Імпортує події з .ics файлу (напр. розклад КАІ) у чергу підтвердження."""
        raw = ics_path.read_bytes()
        cal = Calendar.from_ical(raw)
        queued = 0

        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            summary = str(component.get("summary", "Заняття з ICS"))
            dtstart = component.get("dtstart").dt
            dtend = component.get("dtend").dt if component.get("dtend") else None
            location = str(component.get("location", "1"))

            if not isinstance(dtstart, datetime):
                continue
            end_dt = dtend if isinstance(dtend, datetime) else (dtstart + timedelta(minutes=95))
            ext_id = f"ics_{ics_path.name}_{dtstart.isoformat()}_{summary[:24]}"

            added = self.sync_repo.enqueue_agent_change(
                source="ics_import",
                external_id=ext_id,
                entity_type="schedule",
                title=f"Імпорт розкладу: {summary}",
                payload={
                    "subject_id": default_subject_id,
                    "day_of_week": dtstart.isoweekday(),
                    "pair_number": 1,
                    "start_time": dtstart.strftime("%H:%M"),
                    "end_time": end_dt.strftime("%H:%M"),
                    "parity": "both",
                    "lesson_type": "lecture",
                    "building": location[:10],
                    "room": "",
                },
                diff_summary=f"День тижня: {dtstart.isoweekday()}, час: {dtstart.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}",
            )
            if added:
                queued += 1
        return queued

    def fetch_demo_portal_updates(self) -> int:
        """Імітує перевірку оновлень із електронного журналу / розкладу КАІ."""
        subjects = self.academic_repo.list_subjects()
        if not subjects:
            return 0
        first_subj = subjects[0]
        added = self.sync_repo.enqueue_agent_change(
            source="kai_portal",
            external_id=f"kai_consult_{date.today().isoformat()}_{first_subj['id']}",
            entity_type="schedule",
            title=f"Консультація кафедри: {first_subj['name']}",
            payload={
                "subject_id": int(first_subj["id"]),
                "day_of_week": 5,
                "pair_number": 5,
                "start_time": "15:20",
                "end_time": "16:30",
                "parity": "both",
                "lesson_type": "consultation",
                "building": "1",
                "room": first_subj.get("teacher_room") or "1-312",
            },
            diff_summary="П'ятниця 15:20, корпус 1 — відкрита консультація перед модулем",
        )
        return 1 if added else 0