from __future__ import annotations

import json
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.defaults import DEFAULT_SETTINGS, PATHS
from core.database.connection import DatabaseManager
from core.domain.academic_rules import ParityResolver, ScheduleWindow, WindowAnalyzer
from core.domain.cognitive_and_priority import (
    PrioritizedTask,
    PriorityEngine,
    ReviewScheduler,
    SmartTextParser,
)
from core.repositories import (
    AcademicRepository,
    CognitiveRepository,
    PortfolioRepository,
    SyncAndFileRepository,
    TaskRepository,
)


class AcademicService:
    """Координує навчальний контур, розклад, вікна та правило «лаба за 24 години»."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self.academic_repo = AcademicRepository(db)
        self.task_repo = TaskRepository(db)
        self.cognitive_repo = CognitiveRepository(db)

    def get_today_context(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        today = target_date or date.today()
        default_anchor = str(DEFAULT_SETTINGS.get("parity_anchor_date", "2026-09-01"))
        anchor_str = self.academic_repo.get_setting("parity_anchor_date", default_anchor)
        anchor_date = date.fromisoformat(anchor_str)

        parity = ParityResolver.get_week_parity(today, anchor_date)
        parity_label = ParityResolver.format_parity_ua(parity)

        weekday = today.isoweekday()  # 1=Пн .. 7=Нд
        raw_entries = self.academic_repo.list_schedule(day_of_week=weekday)
        today_classes = [
            e
            for e in raw_entries
            if ParityResolver.is_entry_active_on_parity(e.get("parity", "both"), parity)
        ]

        default_min_win = int(DEFAULT_SETTINGS.get("min_productive_window_minutes", 45))
        min_win = int(
            self.academic_repo.get_setting(
                "min_productive_window_minutes",
                str(default_min_win),
            )
        )
        windows: List[ScheduleWindow] = WindowAnalyzer.find_productive_windows(
            today_classes, min_productive_minutes=min_win
        )

        # Нагадування про переходи між корпусами КАІ
        default_lead = int(DEFAULT_SETTINGS.get("default_class_reminder_minutes", 15))
        smart_reminders: List[str] = []
        for idx, cls in enumerate(today_classes):
            prev_cls = today_classes[idx - 1] if idx > 0 else None
            _, msg = WindowAnalyzer.calculate_smart_reminder_lead(
                prev_cls, cls, default_lead
            )
            smart_reminders.append(f"{cls['start_time']} {cls['subject_name']}: {msg}")

        wellbeing = self.task_repo.get_wellbeing_log(today.isoformat())
        emergency_mode = bool(wellbeing and int(wellbeing.get("emergency_mode_active", 0)) == 1)

        all_tasks = self.task_repo.list_tasks()
        top_priorities: List[PrioritizedTask] = PriorityEngine.rank_top_priorities(
            all_tasks, today=today, limit=2, emergency_mode=emergency_mode
        )

        due_notes = [
            n
            for n in self.cognitive_repo.list_cornell_notes()
            if n.get("next_review_date") and str(n["next_review_date"]) <= today.isoformat()
        ]

        return {
            "date": today.isoformat(),
            "weekday": weekday,
            "parity": parity,
            "parity_label": parity_label,
            "today_classes": today_classes,
            "windows": windows,
            "smart_reminders": smart_reminders,
            "top_priorities": top_priorities,
            "due_notes": due_notes,
            "emergency_mode": emergency_mode,
        }

    def quick_add_task(self, raw_input: str) -> int:
        parsed = SmartTextParser.parse_quick_input(raw_input)
        subject_id: Optional[int] = None
        if parsed.subject_hint:
            hint = parsed.subject_hint.lower()
            for subj in self.academic_repo.list_subjects():
                if hint in subj["name"].lower() or hint in subj.get("code", "").lower():
                    subject_id = int(subj["id"])
                    break

        lab_ts = datetime.now().isoformat(timespec="minutes") if parsed.task_type == "lab" else None
        return self.task_repo.create_task(
            title=parsed.title,
            subject_id=subject_id,
            task_type=parsed.task_type,
            priority=parsed.priority,
            due_date=parsed.due_date,
            lab_conducted_at=lab_ts,
        )

    def advance_cornell_review(
        self, note: Dict[str, Any], hand_stuck: bool = False
    ) -> tuple[int, str]:
        current_stage = int(note.get("review_stage", 0))
        next_stage, next_date = ReviewScheduler.compute_next_review(
            current_stage=current_stage,
            base_date=date.today(),
            hand_stuck=hand_stuck,
        )
        next_iso = next_date.isoformat()
        self.cognitive_repo.save_cornell_note(
            subject_id=int(note["subject_id"]),
            lecture_number=int(note["lecture_number"]),
            topic=str(note["topic"]),
            lecture_date=str(note["lecture_date"]),
            cues_column=str(note.get("cues_column", "")),
            notes_column=str(note.get("notes_column", "")),
            summary_block=str(note.get("summary_block", "")),
            review_stage=next_stage,
            next_review_date=next_iso,
            hand_stuck_flag=1 if hand_stuck else 0,
            note_id=int(note["id"]),
        )
        return next_stage, next_iso

    @staticmethod
    def generate_ai_declaration_text(
        tool_name: str,
        purpose: str,
        verified_sources: bool = True,
    ) -> str:
        """Генерує офіційний текст декларації ШІ згідно з Законом № 4742-IX та Політикою КАІ."""
        verification_note = (
            "Джерела, формули та фактичні дані перевірено автором за оригінальними першоджерелами."
            if verified_sources
            else "Фактичні твердження потребують додаткової звірки з першоджерелами."
        )
        return (
            f"Під час підготовки цієї роботи використано {tool_name} виключно як допоміжний "
            f"інструмент для: {purpose}. {verification_note} "
            "Аналіз, розрахунки, програмний код, висновки та остаточний текст роботи виконано автором самостійно. "
            "Історію запитів (промптів) і відповідей збережено та може бути надано на вимогу викладача."
        )


class SyncApprovalService:
    """Реалізує принцип Human-in-the-loop: зовнішні зміни потрапляють у БД лише після підтвердження."""

    ALLOWED_SETTING_KEYS = frozenset({"parity_anchor_date"})

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self.sync_repo = SyncAndFileRepository(db)
        self.academic_repo = AcademicRepository(db)
        self.task_repo = TaskRepository(db)

    def approve_change(self, change_id: int) -> str:
        """Застосовує пропозицію та змінює її статус в одній транзакції."""
        with self.db.transaction() as conn:
            raw_row = conn.execute(
                "SELECT * FROM agent_changes WHERE id = ? AND status = 'pending'",
                (change_id,),
            ).fetchone()
            if raw_row is None:
                return "Зміна вже оброблена або не знайдена."

            row = dict(raw_row)
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Пропозиція #{change_id} містить некоректний JSON.") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Пропозиція #{change_id} має некоректний формат.")

            entity_type = row["entity_type"]
            source = row["source"]

            if entity_type == "task":
                self.task_repo.create_task(
                    title=str(payload.get("title", row["title"])),
                    subject_id=payload.get("subject_id"),
                    description=str(payload.get("description", "")),
                    task_type=str(payload.get("task_type", "homework")),
                    priority=int(payload.get("priority", 2)),
                    due_date=payload.get("due_date"),
                )
                msg = f"Завдання «{row['title']}» додано до робочого плану."

            elif entity_type == "grade":
                comp_id = payload.get("rso_component_id")
                score = payload.get("score")
                if comp_id is None or score is None:
                    raise ValueError("Пропозиція оцінки не містить компонента РСО або бала.")
                self.academic_repo.update_component_score(
                    int(comp_id),
                    float(score),
                    source=source,
                    note=f"Підтверджено зі зміни #{change_id}",
                )
                msg = f"Оцінку за «{row['title']}» оновлено в журналі РСО."

            elif entity_type == "rso_draft":
                subject_id = int(payload["subject_id"])
                components = payload.get("components", [])
                if not isinstance(components, list):
                    raise ValueError("Список компонентів РСО має бути масивом.")
                for component in components:
                    self.academic_repo.add_rso_component(
                        subject_id=subject_id,
                        title=str(component["title"]),
                        component_type=str(component.get("component_type", "lab")),
                        max_score=float(component.get("max_score", 10.0)),
                    )
                msg = f"Структуру РСО ({len(components)} компонентів) застосовано."

            elif entity_type == "calendar_event":
                self.academic_repo.add_calendar_event(
                    title=str(payload["title"]),
                    event_date=str(payload["event_date"]),
                    start_time=str(payload["start_time"]),
                    end_time=str(payload["end_time"]),
                    event_type=str(payload.get("event_type", "replacement")),
                    subject_id=self._resolve_subject_id(payload),
                    location=str(payload.get("location", "")),
                    description=str(payload.get("description", "")),
                )
                msg = f"Разову подію «{row['title']}» додано до календаря."

            elif entity_type == "setting":
                key = payload.get("key")
                if key not in self.ALLOWED_SETTING_KEYS:
                    raise ValueError("Цей параметр не можна змінити зовнішньою пропозицією.")
                self.academic_repo.set_setting(str(key), str(payload["value"]))
                msg = f"Параметр «{key}» оновлено."

            elif entity_type == "schedule":
                self.academic_repo.add_schedule_entry(
                    subject_id=self._resolve_subject_id(payload),
                    day_of_week=int(payload["day_of_week"]),
                    pair_number=int(payload.get("pair_number", 1)),
                    start_time=str(payload["start_time"]),
                    end_time=str(payload["end_time"]),
                    parity=str(payload.get("parity", "both")),
                    lesson_type=str(payload.get("lesson_type", "lecture")),
                    building=str(payload.get("building", "1")),
                    room=str(payload.get("room", "")),
                    online_url=str(payload.get("online_url", "")),
                    notes=str(payload.get("notes", "")),
                )
                msg = f"Заняття «{row['title']}» додано до розкладу."

            else:
                raise ValueError(f"Невідомий тип пропозиції: {entity_type!r}")

            updated = conn.execute(
                """
                UPDATE agent_changes
                SET status = 'approved', reviewed_at = datetime('now')
                WHERE id = ? AND status = 'pending'
                """,
                (change_id,),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Статус пропозиції змінився під час підтвердження.")
            return msg

    def _resolve_subject_id(self, payload: Dict[str, Any]) -> int:
        """Дисципліна за ID або назвою з порталу; якщо такої немає — створюється в активному семестрі."""
        if payload.get("subject_id") is not None:
            return int(payload["subject_id"])
        name = str(payload.get("subject_name", "")).strip()
        if not name:
            raise ValueError("У пропозиції не вказано дисципліну.")
        low = name.lower()
        subjects = self.academic_repo.list_subjects()
        for subj in subjects:
            if str(subj["name"]).lower() == low:
                return int(subj["id"])
        for subj in subjects:
            existing = str(subj["name"]).lower()
            if len(existing) >= 5 and (low in existing or existing in low):
                return int(subj["id"])
        sem = self.academic_repo.get_active_semester()
        if sem is None:
            raise ValueError("Немає активного семестру для створення дисципліни.")
        return self.academic_repo.create_subject(semester_id=int(sem["id"]), name=name)

    def reject_change(self, change_id: int) -> None:
        self.sync_repo.mark_agent_change(change_id, "rejected")


class BlackoutExportService:
    """Алгоритм 6: Формує автономний ZIP-пакет для роботи під час блекауту / відсутності зв'язку."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self.academic_repo = AcademicRepository(db)
        self.task_repo = TaskRepository(db)
        self.cognitive_repo = CognitiveRepository(db)
        self.portfolio_repo = PortfolioRepository(db)

    def export_blackout_bundle(self, target_dir: Path | str | None = None) -> Path:
        out_folder = Path(target_dir) if target_dir is not None else (PATHS.base_dir / "blackout_packs")
        out_folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = out_folder / f"KAI_Blackout_Pack_{stamp}.zip"

        today = date.today()
        tasks = self.task_repo.list_tasks()
        top2 = PriorityEngine.rank_top_priorities(tasks, today=today, limit=2, emergency_mode=True)
        notes = self.cognitive_repo.list_cornell_notes()
        cards = self.cognitive_repo.list_flashcards()
        summaries = self.academic_repo.get_all_rso_summaries()

        plan_lines = [
            f"# Автономний пакет КАІ (Алгоритм 6 — Режим блекауту)\n"
            f"Сформовано: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
            "## 1. Два критичні пріоритети на найближчі 48 годин",
        ]
        for idx, pt in enumerate(top2, start=1):
            t = pt.task
            plan_lines.append(
                f"{idx}. **{t['title']}** ({t.get('subject_name') or 'Загальне'}) — "
                f"дедлайн: `{t.get('due_date') or 'не задано'}` | критерій: _{pt.rationale}_"
            )

        plan_lines.append("\n## 2. Поточний рейтинг РСО та пороги допуску")
        for s in summaries:
            status_txt = (
                "ДОПУЩЕНО"
                if s.is_admitted
                else f"не вистачає {s.points_needed_for_admission} б. до допуску"
            )
            plan_lines.append(
                f"- **{s.subject_name}**: {s.total_earned} / 100 балів ({status_txt})"
            )

        deck_lines = ["# Колода активного пригадування (25 хвилин без інтернету)\n"]
        for c in cards:
            deck_lines.append(f"### Запитання ({c['subject_name']}):\n{c['question']}\n")
            deck_lines.append(f"**Відповідь для самоперевірки:** {c['answer']}\n---\n")

        for n in notes:
            deck_lines.append(
                f"## Конспект: {n['subject_name']} — Лекція №{n['lecture_number']}: {n['topic']}\n"
                f"**Запитання (ліва колонка):**\n{n['cues_column']}\n\n"
                f"**Резюме:** {n['summary_block']}\n---\n"
            )

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("01_PRIORITY_48H_AND_RSO.md", "\n".join(plan_lines))
            zf.writestr("02_ACTIVE_RECALL_DECK_25MIN.md", "\n".join(deck_lines))

        size = zip_path.stat().st_size if zip_path.exists() else 0
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO backup_history (backup_type, file_path, size_bytes) VALUES (?, ?, ?)",
                ("blackout_pack", str(zip_path), size),
            )
        return zip_path