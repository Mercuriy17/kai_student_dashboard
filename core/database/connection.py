from __future__ import annotations
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from config.defaults import SQLITE_BUSY_TIMEOUT_MS
from core.exceptions import DatabaseTransactionError


class DatabaseManager:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        except sqlite3.Error as exc:
            raise DatabaseTransactionError(f"Помилка транзакції SQLite: {exc}") from exc
        finally:
            conn.close()