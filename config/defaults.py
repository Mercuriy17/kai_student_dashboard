from infrastructure.system.paths import AppPaths

PATHS = AppPaths.resolve()
DB_PATH = PATHS.db_path
LOGS_DIR = PATHS.logs_dir
BACKUPS_DIR = PATHS.backups_dir

RSO_MAX_TOTAL_SCORE = 100.0
DEFAULT_ADMISSION_THRESHOLD = 35.0
SQLITE_BUSY_TIMEOUT_MS = 5000

APP_VERSION = "0.1.0"
DEFAULT_SETTINGS = {
    "theme": "dark",
    "student_name": "Студент КАІ",
    "student_group": "",
    "parity_anchor_date": "2026-09-01",
}


def get_transit_minutes(from_building: str, to_building: str) -> int:
    """Повертає орієнтовний час переходу між корпусами КАІ у хвилинах."""
    b1 = str(from_building).strip()
    b2 = str(to_building).strip()
    if not b1 or not b2 or b1 == b2:
        return 0
    return 10