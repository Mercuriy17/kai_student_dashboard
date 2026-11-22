from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from config.defaults import BACKUP_DIR, DB_PATH, ensure_app_directories

BACKUP_KEEP = 14  # ротація поколінь резервних копій (специфікація §11.3)


class DatabaseManager:
    """Керує підключенням до SQLite, міграціями, FTS5-індексом та безпечним бекапом.

    Одне з'єднання використовується з кількох потоків (UI, watchdog, фонові воркери),
    тому всі звернення серіалізуються через RLock.
    """

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            ensure_app_directories()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = self._create_connection()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def apply_migrations(self) -> None:
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        sql_files = sorted(migrations_dir.glob("*.sql"))
        with self._lock:
            for sql_file in sql_files:
                version = int(sql_file.stem.split("_", 1)[0])
                already_applied = False
                try:
                    cur = self._conn.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                    )
                    already_applied = cur.fetchone() is not None
                except sqlite3.OperationalError:
                    already_applied = False

                if not already_applied:
                    script = sql_file.read_text(encoding="utf-8")
                    with self.transaction() as conn:
                        conn.executescript(script)
                        conn.execute(
                            "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
                            (version, sql_file.name),
                        )

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self.transaction() as conn:
            return conn.execute(sql, params)

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def upsert_fts_document(self, doc_type: str, ref_id: int, title: str, body: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM fts_documents WHERE doc_type = ? AND ref_id = ?",
                (doc_type, ref_id),
            )
            conn.execute(
                "INSERT INTO fts_documents (doc_type, ref_id, title, body) VALUES (?, ?, ?, ?)",
                (doc_type, ref_id, title, body),
            )

    def delete_fts_document(self, doc_type: str, ref_id: int) -> None:
        self.execute(
            "DELETE FROM fts_documents WHERE doc_type = ? AND ref_id = ?",
            (doc_type, ref_id),
        )

    def search_fts(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        cleaned = " ".join(
            token.strip("\"'*():") for token in query.split() if token.strip("\"'*():")
        )
        if not cleaned:
            return []
        match_expr = " ".join(f'"{t}"*' for t in cleaned.split())
        sql = """
            SELECT
                doc_type,
                ref_id,
                title,
                snippet(fts_documents, 3, '[', ']', '...', 18) AS snippet,
                bm25(fts_documents) AS rank
            FROM fts_documents
            WHERE fts_documents MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        try:
            return self.fetch_all(sql, (match_expr, limit))
        except sqlite3.OperationalError:
            like_pattern = f"%{query.strip()}%"
            return self.fetch_all(
                """
                SELECT doc_type, ref_id, title, substr(body, 1, 140) AS snippet, 0.0 AS rank
                FROM fts_documents
                WHERE title LIKE ? OR body LIKE ?
                LIMIT ?
                """,
                (like_pattern, like_pattern, limit),
            )

    def integrity_check(self) -> bool:
        row = self.fetch_one("PRAGMA integrity_check")
        return bool(row) and list(row.values())[0] == "ok"

    def create_backup(self, target_dir: Path | str = BACKUP_DIR, keep: int = BACKUP_KEEP) -> Path:
        """Гарячий консистентний бекап через SQLite Backup API + ротація останніх `keep` копій."""
        backup_folder = Path(target_dir)
        backup_folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = backup_folder / f"kai_dashboard_backup_{stamp}.sqlite3"

        dest_conn = sqlite3.connect(str(backup_path))
        try:
            with self._lock, dest_conn:
                self._conn.backup(dest_conn)
        finally:
            dest_conn.close()

        size = backup_path.stat().st_size if backup_path.exists() else 0
        self.execute(
            "INSERT INTO backup_history (backup_type, file_path, size_bytes) VALUES (?, ?, ?)",
            ("sqlite_backup", str(backup_path), size),
        )
        self._prune_backups(backup_folder, keep)
        return backup_path

    @staticmethod
    def _prune_backups(folder: Path, keep: int) -> None:
        files = sorted(folder.glob("kai_dashboard_backup_*.sqlite3"))
        for old in files[: max(0, len(files) - keep)]:
            try:
                old.unlink()
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            self._conn.close()
