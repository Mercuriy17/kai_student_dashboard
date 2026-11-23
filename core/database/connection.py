from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from config.defaults import BACKUPS_DIR, DB_PATH, SQLITE_BUSY_TIMEOUT_MS
from core.exceptions import DatabaseTransactionError


class DatabaseManager:
    """Єдиний потокобезпечний менеджер SQLite з транзакціями та міграціями.

    Одне з'єднання серіалізоване RLock. Вкладені виклики transaction()
    використовують SAVEPOINT, тому Application Services можуть атомарно
    викликати репозиторії, які самі відкривають транзакції.
    """

    BACKUP_KEEP = 14

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._conn = self._create_connection()
        self._closed = False

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if str(self.db_path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(f"PRAGMA busy_timeout = {int(SQLITE_BUSY_TIMEOUT_MS)}")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        if self._closed:
            raise DatabaseTransactionError("З'єднання з базою даних уже закрито.")
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self._closed:
            raise DatabaseTransactionError("З'єднання з базою даних уже закрито.")
        with self._lock:
            depth = getattr(self._local, "transaction_depth", 0)
            savepoint = f"sp_{depth}"
            try:
                if depth == 0:
                    self._conn.execute("BEGIN IMMEDIATE")
                else:
                    self._conn.execute(f"SAVEPOINT {savepoint}")
                self._local.transaction_depth = depth + 1
                yield self._conn
                if depth == 0:
                    self._conn.commit()
                else:
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception as exc:
                if depth == 0:
                    self._conn.rollback()
                else:
                    self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                if isinstance(exc, sqlite3.Error):
                    raise DatabaseTransactionError(f"Помилка транзакції SQLite: {exc}") from exc
                raise
            finally:
                self._local.transaction_depth = depth

    def apply_migrations(self) -> None:
        root = Path(__file__).resolve().parent
        migration_dirs = (root / "migrations", root.parent / "migrations")
        migration_files = sorted(
            (p for folder in migration_dirs if folder.exists() for p in folder.glob("*.sql")),
            key=lambda p: (int(p.stem.split("_", 1)[0]), p.name),
        )
        for sql_file in migration_files:
            try:
                version = int(sql_file.stem.split("_", 1)[0])
            except ValueError as exc:
                raise DatabaseTransactionError(f"Некоректна назва міграції: {sql_file.name}") from exc

            with self._lock:
                has_version_table = self._conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                ).fetchone() is not None
                applied = False
                if has_version_table:
                    applied = self._conn.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                    ).fetchone() is not None
                if applied:
                    continue

                script = sql_file.read_text(encoding="utf-8")
                safe_name = sql_file.name.replace("'", "''")
                migration_script = (
                    "BEGIN IMMEDIATE;\n"
                    + script
                    + f"\nINSERT OR IGNORE INTO schema_migrations(version, name) "
                      f"VALUES ({version}, '{safe_name}');\nCOMMIT;"
                )
                try:
                    self._conn.executescript(migration_script)
                except sqlite3.Error as exc:
                    if self._conn.in_transaction:
                        self._conn.rollback()
                    raise DatabaseTransactionError(
                        f"Міграція {sql_file.name} не виконана: {exc}"
                    ) from exc

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self.transaction() as conn:
            cursor = conn.execute(sql, params)
        return cursor

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def upsert_fts_document(self, doc_type: str, ref_id: int, title: str, body: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM fts_documents WHERE doc_type = ? AND ref_id = ?",
                (doc_type, ref_id),
            )
            conn.execute(
                "INSERT INTO fts_documents(doc_type, ref_id, title, body) VALUES (?, ?, ?, ?)",
                (doc_type, ref_id, title, body),
            )

    def delete_fts_document(self, doc_type: str, ref_id: int) -> None:
        self.execute(
            "DELETE FROM fts_documents WHERE doc_type = ? AND ref_id = ?",
            (doc_type, ref_id),
        )

    def search_fts(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        cleaned = " ".join(
            token.strip("\"'*():") for token in query.split()
            if token.strip("\"'*():")
        )
        if not cleaned:
            return []
        match_expr = " ".join(f'"{token}"*' for token in cleaned.split())
        try:
            return self.fetch_all(
                """
                SELECT doc_type, ref_id, title,
                       snippet(fts_documents, 3, '[', ']', '...', 18) AS snippet,
                       bm25(fts_documents) AS rank
                FROM fts_documents
                WHERE fts_documents MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match_expr, limit),
            )
        except sqlite3.OperationalError:
            pattern = f"%{query.strip()}%"
            return self.fetch_all(
                """
                SELECT doc_type, ref_id, title,
                       substr(body, 1, 140) AS snippet, 0.0 AS rank
                FROM fts_documents
                WHERE title LIKE ? OR body LIKE ?
                LIMIT ?
                """,
                (pattern, pattern, limit),
            )

    def integrity_check(self) -> bool:
        row = self.fetch_one("PRAGMA integrity_check")
        return bool(row) and next(iter(row.values())) == "ok"

    def create_backup(
        self,
        target_dir: Path | str = BACKUPS_DIR,
        keep: int = BACKUP_KEEP,
    ) -> Path:
        if keep < 0:
            raise ValueError("Кількість резервних копій не може бути від'ємною.")
        folder = Path(target_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = folder / f"kai_dashboard_backup_{stamp}.sqlite3"
        with self._lock:
            destination = sqlite3.connect(str(target))
            try:
                self._conn.backup(destination)
            finally:
                destination.close()
            size = target.stat().st_size
            if self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backup_history'"
            ).fetchone():
                with self.transaction() as conn:
                    conn.execute(
                        "INSERT INTO backup_history(backup_type, file_path, size_bytes) "
                        "VALUES (?, ?, ?)",
                        ("sqlite_backup", str(target), size),
                    )
        self._prune_backups(folder, keep)
        return target

    @staticmethod
    def _prune_backups(folder: Path, keep: int) -> None:
        backups = sorted(folder.glob("kai_dashboard_backup_*.sqlite3"))
        for old in backups[: max(0, len(backups) - keep)]:
            try:
                old.unlink()
            except OSError:
                # Не зриваємо успішне створення нової копії через заблокований старий файл.
                continue

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True
