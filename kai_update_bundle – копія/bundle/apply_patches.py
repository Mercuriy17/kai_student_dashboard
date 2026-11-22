"""Застосовує пакет змін до репозиторію KAI Student Command Center.

Використання (з кореня репозиторію):
    python <шлях_до_пакета>/apply_patches.py            # застосувати
    python <шлях_до_пакета>/apply_patches.py --dry-run  # лише перевірити

Скрипт атомарний: якщо хоч один якір не знайдено рівно один раз, НІЧОГО не змінюється.
Для кожного змінюваного файлу створюється копія *.bak.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (старий текст, новий текст) — кожен «старий» фрагмент має зустрічатися у файлі рівно один раз
PATCHES: dict[str, list[tuple[str, str]]] = {
    "core/services.py": [
        (
            '        elif entity_type == "schedule":\n',
            '''        elif entity_type == "calendar_event":
            self.academic_repo.add_calendar_event(
                title=str(payload["title"]),
                event_date=str(payload["event_date"]),
                start_time=str(payload["start_time"]),
                end_time=str(payload["end_time"]),
                event_type=str(payload.get("event_type", "replacement")),
                subject_id=self._resolve_subject_id(payload),
                location=str(payload.get("location", "")),
                description=str(payload.get("description", "")),
            )
            msg = f"Разову подію «{row['title']}» додано до календаря."

        elif entity_type == "setting":
            if payload.get("key") not in self.ALLOWED_SETTING_KEYS:
                return "Цей параметр не можна змінити зовнішньою пропозицією."
            self.academic_repo.set_setting(str(payload["key"]), str(payload["value"]))
            msg = f"Параметр «{payload['key']}» оновлено."

        elif entity_type == "schedule":
''',
        ),
        (
            '                subject_id=int(payload["subject_id"]),\n',
            '                subject_id=self._resolve_subject_id(payload),\n',
        ),
        (
            '                room=str(payload.get("room", "")),\n',
            '''                room=str(payload.get("room", "")),
                online_url=str(payload.get("online_url", "")),
                notes=str(payload.get("notes", "")),
''',
        ),
        (
            "    def reject_change(self, change_id: int) -> None:\n",
            '''    ALLOWED_SETTING_KEYS = frozenset({"parity_anchor_date"})

    def _resolve_subject_id(self, payload: Dict[str, Any]) -> int:
        """Дисципліна за ID або назвою з порталу; якщо такої немає — створюється в активному семестрі."""
        if payload.get("subject_id") is not None:
            return int(payload["subject_id"])
        name = str(payload.get("subject_name", "")).strip()
        if not name:
            raise ValueError("У пропозиції не вказано дисципліну.")
        low = name.lower()
        subjects = self.academic_repo.list_subjects()
        for subj in subjects:
            if str(subj["name"]).lower() == low:
                return int(subj["id"])
        for subj in subjects:
            existing = str(subj["name"]).lower()
            if len(existing) >= 5 and (low in existing or existing in low):
                return int(subj["id"])
        sem = self.academic_repo.get_active_semester()
        if sem is None:
            raise ValueError("Немає активного семестру для створення дисципліни.")
        return self.academic_repo.create_subject(semester_id=int(sem["id"]), name=name)

    def reject_change(self, change_id: int) -> None:
''',
        ),
    ],
    "core/repositories.py": [
        (
            "SELECT t.*, s.name AS subject_name, s.code AS subject_code, s.color_hex\n",
            "SELECT t.*, s.name AS subject_name, s.code AS subject_code, s.color_hex,\n"
            "                (SELECT COUNT(*) FROM task_steps ts WHERE ts.task_id = t.id) AS steps_total,\n"
            "                (SELECT COUNT(*) FROM task_steps ts WHERE ts.task_id = t.id AND ts.is_done = 1) AS steps_done\n",
        ),
    ],
    "ui/pages_academic.py": [
        (
            "from ui.widgets import FocusTimerBar, KanbanCardWidget, RsoProgressCard\n",
            "from ui.kanban_card import KanbanCardWidget\n"
            "from ui.layout_utils import clear_layout\n"
            "from ui.widgets import FocusTimerBar, RsoProgressCard\n",
        ),
        (
            "        while self.main_layout.count():\n"
            "            item = self.main_layout.takeAt(0)\n"
            "            if item.widget():\n"
            "                item.widget().deleteLater()\n",
            "        clear_layout(self.main_layout)\n",
        ),
        (
            "        while self.win_layout.count():\n"
            "            w_item = self.win_layout.takeAt(0)\n"
            "            if w_item.widget():\n"
            "                w_item.widget().deleteLater()\n",
            "        clear_layout(self.win_layout)\n",
        ),
        (
            '            hdr = QLabel(f"{col_title} ({len(col_tasks)})")\n',
            '            hdr = QLabel(f"{col_title} ({len(col_tasks)})")\n'
            '            hdr.setProperty("tone", status_key)\n',
        ),
    ],
    "ui/pages_cognitive_and_tools.py": [
        ("    QHeaderView,\n", "    QHeaderView,\n    QInputDialog,\n"),
        (
            "from integrations.google_classroom import GoogleClassroomConnector\n",
            "from core.connector_state import ConnectorStateRepository\n"
            "from core.credential_vault import CredentialVault\n"
            "from integrations.digital_university import DigitalUniversityConnector\n"
            "from integrations.google_classroom import GoogleClassroomConnector\n"
            "from ui.connections_dialog import ConnectionsDialog\n"
            "from ui.workers import TaskWorker\n",
        ),
        (
            "        self.portal = KaiPortalAdapter(self.academic_repo, self.sync_repo)\n",
            "        self.portal = KaiPortalAdapter(self.academic_repo, self.sync_repo)\n"
            "        self.vault = CredentialVault()\n"
            "        self.conn_state = ConnectorStateRepository(db)\n"
            "        self.du = DigitalUniversityConnector(self.academic_repo, self.sync_repo, self.vault, self.conn_state)\n"
            "        self._workers: List[TaskWorker] = []\n",
        ),
        (
            "        top.addWidget(kai_btn)\n",
            '''        top.addWidget(kai_btn)

        du_btn = QPushButton("🎓 Digital University")
        du_btn.setProperty("class", "PrimaryBtn")
        du_btn.clicked.connect(self._sync_du)
        top.addWidget(du_btn)

        du_html_btn = QPushButton("📄 Імпорт розкладу (HTML)")
        du_html_btn.setProperty("class", "SecondaryBtn")
        du_html_btn.clicked.connect(self._import_du_html)
        top.addWidget(du_html_btn)

        conn_btn = QPushButton("🔑 Підключення")
        conn_btn.setProperty("class", "SecondaryBtn")
        conn_btn.clicked.connect(self._open_connections)
        top.addWidget(conn_btn)
''',
        ),
        (
            "    def _sync_classroom(self) -> None:\n"
            "        res = self.classroom.sync_to_approval_queue()\n"
            '        QMessageBox.information(self, "Google Classroom", res["message"])\n'
            "        self.on_data_changed()\n",
            '''    def _run_async(self, fn, on_ok) -> None:
        """Довга операція виконується у фоновому потоці — вікно не зависає."""
        worker = TaskWorker(fn, self)
        worker.succeeded.connect(on_ok)
        worker.failed.connect(lambda msg: QMessageBox.warning(self, "Синхронізація", msg))
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _sync_classroom(self) -> None:
        self._run_async(self.classroom.sync_to_approval_queue, self._after_classroom)

    def _after_classroom(self, res) -> None:
        QMessageBox.information(self, "Google Classroom", res["message"])
        self.on_data_changed()

    def _sync_du(self) -> None:
        self._run_async(self.du.sync_to_approval_queue, self._after_du)

    def _import_du_html(self) -> None:
        file_str, _ = QFileDialog.getOpenFileName(
            self, "Збережена сторінка «Розклад»", "", "HTML (*.html *.htm)"
        )
        if file_str:
            self._run_async(lambda: self.du.import_from_html_file(Path(file_str)), self._after_du)

    def _after_du(self, res) -> None:
        QMessageBox.information(self, "Digital University", res["message"])
        self.on_data_changed()

    def _open_connections(self) -> None:
        ConnectionsDialog(self.vault, self.conn_state, self.du, self).exec()
''',
        ),
        (
            "        msg = self.approval_service.approve_change(change_id)\n",
            "        try:\n"
            "            msg = self.approval_service.approve_change(change_id)\n"
            "        except (ValueError, KeyError) as exc:\n"
            '            QMessageBox.warning(self, "Не застосовано", f"Зміну не вдалося застосувати: {exc}")\n'
            "            return\n",
        ),
        (
            "        target_subj = subjects[0]\n",
            "        names = [s[\"name\"] for s in subjects]\n"
            "        chosen, ok = QInputDialog.getItem(\n"
            '            self, "Дисципліна", "Для якої дисципліни цей силабус?", names, 0, False\n'
            "        )\n"
            "        if not ok:\n"
            "            return\n"
            "        target_subj = subjects[names.index(chosen)]\n",
        ),
    ],
    "ui/main_window.py": [
        (
            "    NAV_ITEMS = [\n",
            "    # Заголовки груп у бічній панелі (ключ — індекс першої сторінки групи)\n"
            '    NAV_SECTIONS = {0: "НАВЧАННЯ", 4: "ЗНАННЯ", 6: "КАР\'ЄРА ТА ДАНІ", 9: "СИСТЕМА"}\n\n'
            "    NAV_ITEMS = [\n",
        ),
        (
            "        for label, page_idx in self.NAV_ITEMS:\n",
            "        for label, page_idx in self.NAV_ITEMS:\n"
            "            section = self.NAV_SECTIONS.get(page_idx)\n"
            "            if section:\n"
            "                sec_lbl = QLabel(section)\n"
            '                sec_lbl.setProperty("class", "NavSection")\n'
            "                sb_layout.addWidget(sec_lbl)\n",
        ),
    ],
    "main.py": [
        (
            "from ui.main_window import MainWindow\n",
            "from core.logging_setup import setup_logging\nfrom ui.main_window import MainWindow\n",
        ),
        ("    app = QApplication(sys.argv)\n", "    setup_logging()\n    app = QApplication(sys.argv)\n"),
    ],
}

APPEND_IF_MISSING = {"requirements.txt": ["beautifulsoup4>=4.12.0"]}


def find_root() -> Path:
    """Іде вгору від теки скрипта й поточної теки, поки не знайде main.py + теку core/."""
    for start in (HERE, Path.cwd().resolve()):
        for cand in (start, *start.parents):
            if (cand / "main.py").exists() and (cand / "core").is_dir():
                return cand
    print("Не знайдено корінь проєкту (потрібні main.py і тека core/). Вкажіть --root <шлях>.")
    sys.exit(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="корінь репозиторію (за замовчуванням шукається автоматично)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*", help="обмежити патчі файлами, що містять ці підрядки (для тестів)")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else find_root()
    print(f"Корінь проєкту: {root}")

    new_contents: dict[Path, str] = {}
    errors: list[str] = []
    for rel, edits in PATCHES.items():
        if args.only and not any(o in rel for o in args.only):
            continue
        path = root / rel
        if not path.exists():
            errors.append(f"{rel}: файл не знайдено")
            continue
        text = path.read_text(encoding="utf-8")
        for i, (old, new) in enumerate(edits, 1):
            n = text.count(old)
            if n == 1:
                text = text.replace(old, new)
            elif n == 0 and new in text:
                print(f"  = {rel} #{i}: уже застосовано")
            else:
                errors.append(f"{rel} #{i}: якір знайдено {n} разів (очікувалось 1): {old.strip()[:70]!r}")
        new_contents[path] = text

    if errors:
        print("ПОМИЛКА — нічого не змінено:")
        for e in errors:
            print("  -", e)
        return 1

    for rel, lines in APPEND_IF_MISSING.items():
        path = root / rel
        if args.only and not any(o in rel for o in args.only):
            continue
        if path.exists():
            text = path.read_text(encoding="utf-8")
            for line in lines:
                if line.split(">=")[0] not in text:
                    text = text.rstrip("\n") + "\n" + line + "\n"
            new_contents[path] = text

    files_dir = HERE / "files"
    copies = [(src, root / src.relative_to(files_dir)) for src in files_dir.rglob("*") if src.is_file()]
    if args.only:
        copies = [(s, d) for s, d in copies if any(o in str(d) for o in args.only) or "tests" in str(d)]

    if args.dry_run:
        print(f"OK (dry-run): {len(new_contents)} файлів буде змінено, {len(copies)} додано/замінено.")
        return 0

    for path, text in new_contents.items():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        path.write_text(text, encoding="utf-8")
        print(f"  ~ {path.relative_to(root)}")
    for src, dst in copies:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.read_bytes() != src.read_bytes():
            shutil.copy2(dst, dst.with_suffix(dst.suffix + ".bak"))
        shutil.copy2(src, dst)
        print(f"  + {dst.relative_to(root)}")
    print("Готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())