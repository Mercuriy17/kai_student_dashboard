from app.application import ApplicationServices
from core.database.connection import DatabaseManager
from core.services import AcademicService, BlackoutExportService, SyncApprovalService


def test_application_services_are_composed_around_one_database(tmp_path):
    db = DatabaseManager(tmp_path / "application.sqlite3")
    try:
        services = ApplicationServices.build(db)
        assert isinstance(services.academic, AcademicService)
        assert isinstance(services.sync_approval, SyncApprovalService)
        assert isinstance(services.blackout_export, BlackoutExportService)
        assert services.sync_approval.db is db
        assert services.academic.db is db
        assert services.blackout_export.db is db
    finally:
        db.close()
