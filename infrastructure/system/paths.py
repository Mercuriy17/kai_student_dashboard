from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir


@dataclass(frozen=True, slots=True)
class AppPaths:
    base_dir: Path
    db_path: Path
    logs_dir: Path
    backups_dir: Path

    @classmethod
    def resolve(cls, app_name: str = "KAIStudentDashboard") -> AppPaths:
        # Зберігаємо попередній platformdirs-шлях і назву БД, щоб оновлення
        # не створювало непомітно порожній профіль замість наявних даних.
        root = Path(user_data_dir(app_name, "KAI"))
        logs = root / "logs"
        backups = root / "backups"
        for directory in (root, logs, backups):
            directory.mkdir(parents=True, exist_ok=True)
        return cls(
            base_dir=root,
            db_path=root / "kai_dashboard.sqlite3",
            logs_dir=logs,
            backups_dir=backups,
        )
