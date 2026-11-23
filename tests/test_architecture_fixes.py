from __future__ import annotations

import pytest

from core.database.connection import DatabaseManager
from core.exceptions import DatabaseTransactionError
from core.repositories import SyncAndFileRepository
from core.services import SyncApprovalService


@pytest.fixture()
def db(tmp_path):
    manager = DatabaseManager(tmp_path / "dashboard.sqlite3")
    manager.apply_migrations()
    yield manager
    manager.close()


def test_migrations_include_connector_schema_and_are_idempotent(db):
    db.apply_migrations()
    tables = {
        row["name"]
        for row in db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"schema_migrations", "agent_changes", "sync_connectors"} <= tables
    columns = {row["name"] for row in db.fetch_all("PRAGMA table_info(agent_changes)")}
    assert "confidence" in columns
    versions = db.fetch_all("SELECT version FROM schema_migrations ORDER BY version")
    assert [row["version"] for row in versions] == [1, 2]


def test_nested_transaction_rolls_back_as_one_unit(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO user_settings(key, value) VALUES ('outer', 'value')"
            )
            with db.transaction() as nested:
                nested.execute(
                    "INSERT INTO user_settings(key, value) VALUES ('inner', 'value')"
                )
            raise RuntimeError("force rollback")

    assert db.fetch_one("SELECT 1 FROM user_settings WHERE key = 'outer'") is None
    assert db.fetch_one("SELECT 1 FROM user_settings WHERE key = 'inner'") is None


def test_fts_repository_uses_schema_table(db):
    db.upsert_fts_document("test", 7, "Квантова фізика", "лекція про квантову фізику")
    results = db.search_fts("квантова")
    assert results
    assert results[0]["doc_type"] == "test"
    assert int(results[0]["ref_id"]) == 7


def test_sync_enqueue_is_idempotent(db):
    repo = SyncAndFileRepository(db)
    payload = {"title": "Перевірка"}
    assert repo.enqueue_agent_change("test", "external-1", "task", "Тест", payload)
    assert not repo.enqueue_agent_change("test", "external-1", "task", "Тест", payload)
    assert len(repo.list_agent_changes()) == 1


def test_failed_approval_does_not_mark_change_approved(db):
    repo = SyncAndFileRepository(db)
    repo.enqueue_agent_change(
        "test",
        "invalid-task",
        "task",
        "Завдання з неіснуючою дисципліною",
        {"title": "Некоректне завдання", "subject_id": 999999},
    )
    change = repo.list_agent_changes()[0]
    service = SyncApprovalService(db)

    with pytest.raises(DatabaseTransactionError):
        service.approve_change(int(change["id"]))

    saved = db.fetch_one(
        "SELECT status FROM agent_changes WHERE id = ?", (int(change["id"]),)
    )
    assert saved["status"] == "pending"
    assert db.fetch_one("SELECT 1 FROM tasks WHERE title = 'Некоректне завдання'") is None
