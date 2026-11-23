from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.repositories.base import BaseRepository


class FileRepository(BaseRepository):
    def upsert_indexed_file(
        self,
        file_path: str,
        file_name: str,
        extension: str,
        sha256_hash: str,
        file_size_bytes: int,
        doc_category: str,
        extracted_text: str,
        subject_id: Optional[int] = None,
    ) -> int:
        existing = self._fetch_one(
            "SELECT id, sha256_hash FROM indexed_files WHERE file_path = ?", (file_path,)
        )
        if existing and existing["sha256_hash"] == sha256_hash:
            return int(existing["id"])

        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO indexed_files (
                    subject_id, file_path, file_name, extension, sha256_hash,
                    file_size_bytes, doc_category, extracted_text, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(file_path) DO UPDATE SET
                    subject_id = COALESCE(excluded.subject_id, indexed_files.subject_id),
                    sha256_hash = excluded.sha256_hash,
                    file_size_bytes = excluded.file_size_bytes,
                    doc_category = excluded.doc_category,
                    extracted_text = excluded.extracted_text,
                    indexed_at = excluded.indexed_at
                """,
                (subject_id, file_path, file_name, extension, sha256_hash, file_size_bytes, doc_category, extracted_text),
            )
            row = conn.execute("SELECT id FROM indexed_files WHERE file_path = ?", (file_path,)).fetchone()
            file_id = int(row["id"])
            self._upsert_fts(conn, "indexed_file", file_id, file_name, extracted_text[:40000])
            return file_id

    def list_indexed_files(self) -> List[Dict[str, Any]]:
        return self._fetch_all(
            """
            SELECT f.*, s.name AS subject_name
            FROM indexed_files f
            LEFT JOIN subjects s ON s.id = f.subject_id
            ORDER BY f.indexed_at DESC
            """
        )

    def list_watched_folders(self) -> List[Dict[str, Any]]:
        return self._fetch_all(
            """
            SELECT wf.*, s.name AS subject_name
            FROM watched_folders wf
            LEFT JOIN subjects s ON s.id = wf.default_subject_id
            ORDER BY wf.id
            """
        )

    def add_watched_folder(self, folder_path: str, default_subject_id: Optional[int] = None) -> int:
        return self._execute(
            """
            INSERT INTO watched_folders (folder_path, default_subject_id, is_enabled)
            VALUES (?, ?, 1)
            ON CONFLICT(folder_path) DO UPDATE SET
                default_subject_id = excluded.default_subject_id,
                is_enabled = 1
            """,
            (folder_path, default_subject_id),
        )