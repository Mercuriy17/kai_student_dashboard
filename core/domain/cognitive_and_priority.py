from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


class ReviewScheduler:
    """Реалізує Алгоритм 2: трифазну обробку знань 0 -> 24 год -> 7 днів -> 21 день."""

    STAGE_SEQUENCE = (0, 24, 7, 21)

    @classmethod
    def compute_next_review(
        cls,
        current_stage: int,
        base_date: date,
        hand_stuck: bool = False,
    ) -> Tuple[int, date]:
        """
        Якщо під час відтворення «зависла рука» (hand_stuck=True),
        повторення призначається через 3 дні без підвищення фінальної стадії.
        """
        if hand_stuck:
            return current_stage, base_date + timedelta(days=3)

        if current_stage == 0:
            return 24, base_date + timedelta(days=1)
        if current_stage == 24:
            return 7, base_date + timedelta(days=7)
        if current_stage == 7:
            return 21, base_date + timedelta(days=14)
        # Якщо вже на передсесійній стадії 21 — циклічне повторення раз на 5 днів
        return 21, base_date + timedelta(days=5)

    @staticmethod
    def stage_label_ua(stage: int) -> str:
        mapping = {
            0: "Фаза 0 (Свіжа лекція — заповнити ліву колонку)",
            24: "Фаза 24 год (Активне кодування та резюме)",
            7: "Фаза 7 днів (Відтворення з чистого аркуша)",
            21: "Фаза 21 день (Передсесійна колода)",
        }
        return mapping.get(stage, f"Етап {stage}")


@dataclass(frozen=True)
class PrioritizedTask:
    task: Dict[str, Any]
    score: float
    rationale: str


class PriorityEngine:
    """
    Алгоритм 6 (Резервний режим для збоїв) та щоденний ранжувальник:
    обирає до 2 найважливіших завдань на 48 годин із прозорим поясненням критерію.
    """

    @staticmethod
    def rank_top_priorities(
        tasks: List[Dict[str, Any]],
        today: date,
        limit: int = 2,
        emergency_mode: bool = False,
    ) -> List[PrioritizedTask]:
        active_tasks = [t for t in tasks if t.get("status") != "done"]
        scored: List[PrioritizedTask] = []

        for task in active_tasks:
            score = 0.0
            reasons: List[str] = []

            # 1. Терміновість дедлайну
            due_str = task.get("due_date")
            if due_str:
                try:
                    due_d = date.fromisoformat(due_str[:10])
                    days_left = (due_d - today).days
                    if days_left < 0:
                        score += 65.0
                        reasons.append(f"прострочено на {abs(days_left)} дн.")
                    elif days_left == 0:
                        score += 55.0
                        reasons.append("дедлайн сьогодні")
                    elif days_left <= 2:
                        score += 45.0
                        reasons.append(f"дедлайн через {days_left} дн.")
                    elif days_left <= 5:
                        score += 25.0
                        reasons.append(f"дедлайн через {days_left} дн.")
                except ValueError:
                    pass

            # 2. Правило «Лабораторна за 24 години» (Алгоритм 1)
            lab_at = task.get("lab_conducted_at")
            if lab_at and task.get("task_type") == "lab":
                try:
                    conducted_dt = datetime.fromisoformat(lab_at)
                    hours_passed = (datetime.now() - conducted_dt).total_seconds() / 3600.0
                    if 0 <= hours_passed <= 36:
                        score += 35.0
                        reasons.append("правило «лаба за 24 год»")
                except ValueError:
                    pass

            # 3. Базовий пріоритет (1 = критичний .. 4 = низький)
            prio = int(task.get("priority", 2))
            score += max(0, (5 - prio) * 10)
            if prio == 1:
                reasons.append("критичний пріоритет")

            # 4. У режимі збою / блекауту перевага задачам, готовим до офлайн-роботи
            if emergency_mode and int(task.get("is_blackout_ready", 0)) == 1:
                score += 20.0
                reasons.append("готово до офлайн-пакету блекауту")

            if not reasons:
                reasons.append("поточний робочий план")

            scored.append(
                PrioritizedTask(
                    task=task,
                    score=round(score, 1),
                    rationale=", ".join(reasons),
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]


@dataclass(frozen=True)
class ParsedQuickTask:
    title: str
    task_type: str
    due_date: Optional[str]
    priority: int
    subject_hint: Optional[str]


class SmartTextParser:
    """Парсить рядки швидкого додавання (напр. 'Лаба 3 з фізики до 25.11 !критично')."""

    TYPE_KEYWORDS = {
        "лаб": "lab",
        "lab": "lab",
        "ргр": "rgr",
        "модул": "module_prep",
        "мкр": "module_prep",
        "дз": "homework",
        "ajax": "rd",
        "avia": "rd",
        "mit": "rd",
    }

    @classmethod
    def parse_quick_input(cls, raw_text: str, reference_date: Optional[date] = None) -> ParsedQuickTask:
        ref = reference_date or date.today()
        text = raw_text.strip()
        lower = text.lower()

        # Тип завдання
        detected_type = "homework"
        for kw, t_type in cls.TYPE_KEYWORDS.items():
            if kw in lower:
                detected_type = t_type
                break

        # Пріоритет
        priority = 2
        if any(w in lower for w in ("!крит", "!терміново", "urgent", "!!!")):
            priority = 1
        elif any(w in lower for w in ("!низьк", "потім")):
            priority = 3

        # Дата дедлайну
        due_iso: Optional[str] = None
        if "сьогодні" in lower:
            due_iso = ref.isoformat()
        elif "завтра" in lower:
            due_iso = (ref + timedelta(days=1)).isoformat()
        elif "післязавтра" in lower:
            due_iso = (ref + timedelta(days=2)).isoformat()
        else:
            m_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
            m_ua = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", text)
            if m_iso:
                due_iso = m_iso.group(1)
            elif m_ua:
                day = int(m_ua.group(1))
                month = int(m_ua.group(2))
                year = int(m_ua.group(3)) if m_ua.group(3) else ref.year
                try:
                    due_iso = date(year, month, day).isoformat()
                except ValueError:
                    due_iso = None

        # Підказка дисципліни (#фізика або "з фізики")
        subject_hint: Optional[str] = None
        m_tag = re.search(r"#([А-Яа-яІіЇїЄєҐґA-Za-z0-9_-]+)", text)
        if m_tag:
            subject_hint = m_tag.group(1)

        cleaned_title = re.sub(r"![А-Яа-яІіЇїЄєҐґA-Za-z]+", "", text)
        cleaned_title = re.sub(r"#[А-Яа-яІіЇїЄєҐґA-Za-z0-9_-]+", "", cleaned_title).strip()

        return ParsedQuickTask(
            title=cleaned_title or text,
            task_type=detected_type,
            due_date=due_iso,
            priority=priority,
            subject_hint=subject_hint,
        )