from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from core.database.connection import DatabaseManager


class BaseRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def _fetch_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        with self._db.transaction() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def _fetch_all(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self._db.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(sql, params)
            return int(cursor.lastrowid or cursor.rowcount)

    @staticmethod
    def _upsert_fts(
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: int,
        title: str,
        content: str,
    ) -> None:
        """Оновлює запис у FTS5 в межах транзакції виклику репозиторію."""
        conn.execute(
            "DELETE FROM fts_documents WHERE doc_type = ? AND ref_id = ?",
            (entity_type, entity_id),
        )
        conn.execute(
            "INSERT INTO fts_documents(doc_type, ref_id, title, body) VALUES (?, ?, ?, ?)",
            (entity_type, entity_id, title, content),
        )
