from __future__ import annotations

import pytest

from config.defaults import get_transit_minutes
from core.database import DatabaseManager
from core.repositories import SyncAndFileRepository


def test_campus_transit_uses_configured_values_and_reverse_routes() -> None:
    assert get_transit_minutes("1", "2") == 6
    assert get_transit_minutes("2", "1") == 6
    assert get_transit_minutes("1", "1") == 0
    assert get_transit_minutes("", "2") == 0
    assert get_transit_minutes("unknown-a", "unknown-b") == 10


def test_agent_change_insert_is_idempotent_and_keeps_confidence(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "sync.sqlite3")
    try:
        db.apply_migrations()
        repo = SyncAndFileRepository(db)

        assert repo.enqueue_agent_change(
            source="test",
            external_id="same-event",
            entity_type="task",
            title="Перша пропозиція",
            payload={"title": "Завдання"},
            confidence=0.72,
        )
        assert not repo.enqueue_agent_change(
            source="test",
            external_id="same-event",
            entity_type="task",
            title="Дубль",
            payload={"title": "Дубль"},
            confidence=0.99,
        )

        rows = db.fetch_all(
            "SELECT title, confidence FROM agent_changes WHERE source = ? AND external_id = ?",
            ("test", "same-event"),
        )
        assert rows == [{"title": "Перша пропозиція", "confidence": 0.72}]
    finally:
        db.close()


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_agent_change_rejects_invalid_confidence(tmp_path, confidence: float) -> None:
    db = DatabaseManager(tmp_path / "sync.sqlite3")
    try:
        db.apply_migrations()
        repo = SyncAndFileRepository(db)
        with pytest.raises(ValueError):
            repo.enqueue_agent_change(
                source="test",
                external_id="invalid-confidence",
                entity_type="task",
                title="Некоректна впевненість",
                payload={},
                confidence=confidence,
            )
    finally:
        db.close()
