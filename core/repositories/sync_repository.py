from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.repositories.base import BaseRepository


class SyncRepository(BaseRepository):
    def enqueue_agent_change(
        self,
        source: str,
        external_id: str,
        entity_type: str,
        title: str,
        payload: Dict[str, Any],
        diff_summary: str = "",
        confidence: float = 1.0,
    ) -> bool:
        """Атомарно додає пропозицію; UNIQUE(source, external_id) захищає від гонок."""
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Впевненість має бути в межах від 0 до 1.")
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_changes (
                    source, external_id, entity_type, title, payload_json,
                    diff_summary, status, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                ON CONFLICT(source, external_id) DO NOTHING
                """,
                (
                    source,
                    external_id,
                    entity_type,
                    title,
                    json.dumps(payload, ensure_ascii=False),
                    diff_summary,
                    confidence,
                ),
            )
            return cursor.rowcount == 1

    def list_agent_changes(self, status: Optional[str] = "pending") -> List[Dict[str, Any]]:
        if status:
            return self._fetch_all(
                "SELECT * FROM agent_changes WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        return self._fetch_all("SELECT * FROM agent_changes ORDER BY created_at DESC")

    def mark_agent_change(self, change_id: int, status: str) -> None:
        self._execute(
            "UPDATE agent_changes SET status = ?, reviewed_at = datetime('now') WHERE id = ?",
            (status, change_id),
        )
