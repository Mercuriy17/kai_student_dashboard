from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    pass
    base_dir: Path
    db_path: Path
    logs_dir: Path
    backups_dir: Path

    @classmethod
    def resolve(cls, app_name: str = "KAIStudentDashboard") -> AppPaths:
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / app_name
        logs = root / "logs"
        backups = root / "backups"
        for directory in (root, logs, backups):
            directory.mkdir(parents=True, exist_ok=True)
        return cls(
            base_dir=root,
            db_path=root / "kai_dashboard.db",
            logs_dir=logs,
            backups_dir=backups,
        )