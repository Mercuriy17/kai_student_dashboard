from __future__ import annotations

from core.database.connection import DatabaseManager
from core.repositories.base import BaseRepository
from core.repositories.cognitive_repository import CognitiveRepository
from core.repositories.file_repository import FileRepository
from core.repositories.portfolio_repository import PortfolioRepository
from core.repositories.schedule_repository import ScheduleRepository
from core.repositories.settings_repository import SettingsRepository
from core.repositories.subject_repository import SubjectRepository
from core.repositories.sync_repository import SyncRepository
from core.repositories.task_repository import TaskRepository


class AcademicRepository(SettingsRepository, SubjectRepository, ScheduleRepository):
    """Фасад зворотної сумісності для сторінок UI та існуючих сервісів."""

    def __init__(self, db: DatabaseManager) -> None:
        super().__init__(db)
        self.db = db


class SyncAndFileRepository(SyncRepository, FileRepository):
    """Фасад зворотної сумісності для черги змін та індексатора файлів."""

    def __init__(self, db: DatabaseManager) -> None:
        super().__init__(db)
        self.db = db


__all__ = [
    "BaseRepository",
    "SettingsRepository",
    "SubjectRepository",
    "ScheduleRepository",
    "TaskRepository",
    "CognitiveRepository",
    "SyncRepository",
    "FileRepository",
    "PortfolioRepository",
    "AcademicRepository",
    "SyncAndFileRepository",
]