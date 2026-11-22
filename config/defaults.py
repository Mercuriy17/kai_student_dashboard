from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Tuple

from platformdirs import user_data_dir

APP_NAME = "KAIStudentDashboard"
APP_AUTHOR = "KAI"
APP_VERSION = "1.0.0"

DATA_DIR = Path(user_data_dir(APP_NAME, APP_AUTHOR))
DB_PATH = DATA_DIR / "kai_dashboard.sqlite3"
BACKUP_DIR = DATA_DIR / "backups"
BLACKOUT_DIR = DATA_DIR / "blackout_packs"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
CREDENTIALS_DIR = DATA_DIR / "credentials"


def ensure_app_directories() -> None:
    """Створює необхідні директорії застосунку в AppData\\Local\\KAIStudentDashboard."""
    for folder in (DATA_DIR, BACKUP_DIR, BLACKOUT_DIR, ATTACHMENTS_DIR, CREDENTIALS_DIR):
        folder.mkdir(parents=True, exist_ok=True)


# Стандартний розклад дзвінків КАІ (початок та кінець пари у форматі HH:MM)
KAI_BELL_SCHEDULE: Dict[int, Tuple[str, str]] = {
    1: ("08:00", "09:35"),
    2: ("09:50", "11:25"),
    3: ("11:40", "13:15"),
    4: ("13:30", "15:05"),
    5: ("15:20", "16:55"),
    6: ("17:10", "18:45"),
}

# Матриця орієнтовного часу переходу між корпусами КАІ (у хвилинах)
CAMPUS_TRANSIT_MINUTES: Dict[Tuple[str, str], int] = {
    ("1", "1"): 2,
    ("1", "2"): 6,
    ("1", "3"): 7,
    ("1", "4"): 8,
    ("1", "5"): 10,
    ("1", "7"): 11,
    ("1", "8"): 12,
    ("1", "11"): 15,
    ("5", "8"): 6,
    ("5", "11"): 8,
    ("8", "11"): 7,
    ("ННБ", "1"): 8,
    ("ННБ", "5"): 7,
    ("ННБ", "8"): 6,
}


def get_transit_minutes(from_building: str, to_building: str) -> int:
    """Повертає оцінку часу переходу між двома корпусами КАІ."""
    b1 = (from_building or "").strip().upper()
    b2 = (to_building or "").strip().upper()
    if not b1 or not b2 or b1 == b2:
        return 3
    if (b1, b2) in CAMPUS_TRANSIT_MINUTES:
        return CAMPUS_TRANSIT_MINUTES[(b1, b2)]
    if (b2, b1) in CAMPUS_TRANSIT_MINUTES:
        return CAMPUS_TRANSIT_MINUTES[(b2, b1)]
    return 12


@dataclass(frozen=True)
class DefaultSettings:
    theme: str = "dark"
    # Опорний понеділок 1-го (непарного / чисельника) тижня семестру
    parity_anchor_date: str = "2026-09-01"
    # Тривалість робочого інтервалу та перерви (хв) за замовчуванням
    focus_work_minutes: int = 45
    focus_break_minutes: int = 15
    # Мінімальна тривалість вільного «вікна» (хв), придатного для продуктивної задачі
    min_productive_window_minutes: int = 35
    # Нагадування про пару за N хвилин (збільшується, якщо перехід в інший корпус)
    default_class_reminder_minutes: int = 15
    # Профіль студента за замовчуванням
    student_name: str = "Куцак Михайло"
    student_group: str = "Б-G9-26-1-МК"
    semester_label: str = "2026/2027 — Осінній семестр"
    # R&D лабораторії КАІ для портфоліо
    kai_labs: Tuple[str, ...] = field(
        default=(
            "KAI-Ajax Lab",
            "AVIA Lab",
            "KAI Huawei Excellence Center",
            "Ukraine Innovation and Engineering Lab (MIT)",
            "Кафедральний науковий гурток",
            "Інший інженерний проєкт",
        )
    )


DEFAULT_SETTINGS = DefaultSettings()


def get_current_semester_start() -> date:
    """Повертає опорну дату початку семестру у вигляді об'єкта date."""
    return date.fromisoformat(DEFAULT_SETTINGS.parity_anchor_date)