from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Set

from docx import Document
from pypdf import PdfReader
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from core.repositories import SyncAndFileRepository

SUPPORTED_EXTENSIONS: Set[str] = {".pdf", ".docx", ".md", ".txt", ".py", ".c", ".cpp", ".json"}


def compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_text_from_file(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            reader = PdfReader(str(file_path))
            chunks = [page.extract_text() or "" for page in reader.pages[:40]]
            return "\n".join(chunks).strip()
        if ext == ".docx":
            doc = Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
        if ext in {".md", ".txt", ".py", ".c", ".cpp", ".json"}:
            return file_path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:  # noqa: BLE001
        return ""
    return ""


def detect_doc_category(file_name: str) -> str:
    lower = file_name.lower()
    if any(w in lower for w in ("силабус", "syllabus", "рсо", "програма")):
        return "syllabus"
    if any(w in lower for w in ("лекц", "lecture", "конспект")):
        return "lecture"
    if any(w in lower for w in ("лаб", "lab", "звіт", "report", "ргр")):
        return "lab_report"
    return "material"


class _DebouncedHandler(FileSystemEventHandler):
    def __init__(
        self,
        indexer: "LocalFileIndexer",
        default_subject_id: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.indexer = indexer
        self.default_subject_id = default_subject_id

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.indexer.schedule_file(Path(str(event.src_path)), self.default_subject_id)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.indexer.schedule_file(Path(str(event.src_path)), self.default_subject_id)


class LocalFileIndexer:
    """Фоновий індексатор локальних директорій із дебаунсом та перевіркою завершення запису."""

    def __init__(
        self,
        repo: SyncAndFileRepository,
        on_indexed_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.repo = repo
        self.on_indexed_callback = on_indexed_callback
        self._observer: Optional[Any] = None
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def schedule_file(self, path: Path, subject_id: Optional[int] = None, delay: float = 1.2) -> None:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        if path.name.startswith("~$") or path.name.startswith("."):
            return
        key = str(path.resolve())
        with self._lock:
            existing = self._timers.pop(key, None)
            if existing:
                existing.cancel()
            timer = threading.Timer(delay, self._process_when_ready, args=(path, subject_id))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _process_when_ready(self, path: Path, subject_id: Optional[int]) -> None:
        if not path.exists() or not path.is_file():
            return
        # Перевірка стабільності розміру файлу (щоб не читати під час копіювання)
        try:
            s1 = path.stat().st_size
            time.sleep(0.25)
            s2 = path.stat().st_size
            if s1 != s2 or s2 == 0:
                return
        except OSError:
            return

        self.index_single_file(path, subject_id)

    def index_single_file(self, path: Path, subject_id: Optional[int] = None) -> Optional[int]:
        if not path.exists() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return None
        try:
            resolved = str(path.resolve())
            sha = compute_sha256(path)
            size = path.stat().st_size
            text = extract_text_from_file(path)
            category = detect_doc_category(path.name)
            file_id = self.repo.upsert_indexed_file(
                file_path=resolved,
                file_name=path.name,
                extension=path.suffix.lower(),
                sha256_hash=sha,
                file_size_bytes=size,
                doc_category=category,
                extracted_text=text,
                subject_id=subject_id,
            )
            if self.on_indexed_callback:
                self.on_indexed_callback(path.name)
            return file_id
        except Exception:  # noqa: BLE001
            return None

    def scan_directory(self, folder: Path, subject_id: Optional[int] = None) -> int:
        if not folder.exists() or not folder.is_dir():
            return 0
        count = 0
        for item in folder.rglob("*"):
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                if self.index_single_file(item, subject_id) is not None:
                    count += 1
        return count

    def start_watching(self) -> None:
        self.stop_watching()
        folders = self.repo.list_watched_folders()
        enabled = [f for f in folders if int(f.get("is_enabled", 1)) == 1]
        if not enabled:
            return
        observer = Observer()
        for row in enabled:
            folder_path = Path(row["folder_path"])
            if folder_path.exists() and folder_path.is_dir():
                handler = _DebouncedHandler(self, row.get("default_subject_id"))
                observer.schedule(handler, str(folder_path), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None