from __future__ import annotations

from typing import Any, Dict

from core.database import DatabaseManager


class ConnectorStateRepository:
    """Стан конекторів (час, статус, помилка, URL). Секретів тут немає — вони лише в keyring."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def get(self, connector_id: str) -> Dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM sync_connectors WHERE connector_id = ?", (connector_id,))
        return row or {
            "connector_id": connector_id,
            "base_url": "",
            "last_sync_at": None,
            "last_status": "never",
            "last_error": "",
            "last_found": 0,
        }

    def set_base_url(self, connector_id: str, base_url: str) -> None:
        self.db.execute(
            """
            INSERT INTO sync_connectors (connector_id, display_name, base_url)
            VALUES (?, ?, ?)
            ON CONFLICT(connector_id) DO UPDATE SET base_url = excluded.base_url
            """,
            (connector_id, connector_id, base_url.strip()),
        )

    def record_result(self, connector_id: str, status: str, found: int = 0, error: str = "") -> None:
        self.db.execute(
            """
            INSERT INTO sync_connectors (connector_id, display_name, last_sync_at, last_status, last_error, last_found)
            VALUES (?, ?, datetime('now'), ?, ?, ?)
            ON CONFLICT(connector_id) DO UPDATE SET
                last_sync_at = excluded.last_sync_at,
                last_status = excluded.last_status,
                last_error = excluded.last_error,
                last_found = excluded.last_found
            """,
            (connector_id, connector_id, status, error[:300], found),
        )

    def describe(self, connector_id: str) -> str:
        st = self.get(connector_id)
        if st["last_status"] == "never":
            return "Ще не синхронізовано."
        when = str(st.get("last_sync_at") or "—")[:16]
        if st["last_status"] == "ok":
            return f"Остання успішна синхронізація: {when} (нових змін: {st['last_found']})."
        return f"Остання спроба {when} завершилась помилкою: {st['last_error']}"
