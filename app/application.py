from __future__ import annotations

from dataclasses import dataclass

from core.database.connection import DatabaseManager
from core.services import AcademicService, BlackoutExportService, SyncApprovalService


@dataclass(slots=True)
class ApplicationServices:
    """Use-case/service boundary shared by the presentation layer."""

    academic: AcademicService
    sync_approval: SyncApprovalService
    blackout_export: BlackoutExportService

    @classmethod
    def build(cls, db: DatabaseManager) -> "ApplicationServices":
        return cls(
            academic=AcademicService(db),
            sync_approval=SyncApprovalService(db),
            blackout_export=BlackoutExportService(db),
        )
