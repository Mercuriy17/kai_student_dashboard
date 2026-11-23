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
            return [dict(r) for r in rows]

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._db.transaction() as conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or cur.rowcount)

    def _upsert_fts(self, conn: sqlite3.Connection, entity_type: str, entity_id: int, title: str, content: str) -> None:
        if hasattr(self._db, "upsert_fts_document"):
            self._db.upsert_fts_document(entity_type, entity_id, title, content)
            return
        conn.execute("DELETE FROM global_fts WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id))
        conn.execute(
            "INSERT INTO global_fts (entity_type, entity_id, title, content) VALUES (?, ?, ?, ?)",
            (entity_type, entity_id, title, content),
        )