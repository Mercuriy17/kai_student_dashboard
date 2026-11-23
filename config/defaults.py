from infrastructure.system.paths import AppPaths

PATHS = AppPaths.resolve()
DB_PATH = PATHS.db_path
LOGS_DIR = PATHS.logs_dir
BACKUPS_DIR = PATHS.backups_dir

RSO_MAX_TOTAL_SCORE = 100.0
DEFAULT_ADMISSION_THRESHOLD = 35.0
SQLITE_BUSY_TIMEOUT_MS = 5000

# Стандартний розклад дзвінків КАІ (початок та кінець пари).
KAI_BELL_SCHEDULE = {
    1: ("08:00", "09:35"),
    2: ("09:50", "11:25"),
    3: ("11:40", "13:15"),
    4: ("13:30", "15:05"),
    5: ("15:20", "16:55"),
    6: ("17:10", "18:45"),
}

# Орієнтовний час переходу між корпусами, хвилини.
CAMPUS_TRANSIT_MINUTES = {
    ("1", "2"): 6, ("1", "3"): 7, ("1", "4"): 8, ("1", "5"): 10,
    ("1", "7"): 11, ("1", "8"): 12, ("1", "11"): 15,
    ("5", "8"): 6, ("5", "11"): 8, ("8", "11"): 7,
    ("ННБ", "1"): 8, ("ННБ", "5"): 7, ("ННБ", "8"): 6,
}

APP_VERSION = "0.1.0"
DEFAULT_SETTINGS = {
    "theme": "dark",
    "student_name": "Студент КАІ",
    "student_group": "",
    "parity_anchor_date": "2026-09-01",
    "min_productive_window_minutes": 35,
    "default_class_reminder_minutes": 15,
    "focus_work_minutes": 45,
    "focus_break_minutes": 15,
    "kai_labs": (
        "KAI-Ajax Lab",
        "AVIA Lab",
        "KAI Huawei Excellence Center",
        "Ukraine Innovation and Engineering Lab (MIT)",
        "Кафедральний науковий гурток",
        "Інший інженерний проєкт",
    ),
}


def get_transit_minutes(from_building: str, to_building: str) -> int:
    """Повертає орієнтовний час переходу між корпусами КАІ у хвилинах."""
    b1 = str(from_building).strip()
    b2 = str(to_building).strip()
    if not b1 or not b2 or b1 == b2:
        return 0
    return 10