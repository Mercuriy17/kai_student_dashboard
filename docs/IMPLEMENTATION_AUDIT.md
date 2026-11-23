# KAI Student Dashboard — implementation audit against Specification 3.0

Audit basis: source inspection of branch `fix/systematic-audit-2026-11-23`. This is a static implementation map; it does not claim Windows runtime verification or live-provider authentication.

## 1. Twelve functional sections

| Spec section | Current entry point | Existing implementation | Status / known gap |
|---|---|---|---|
| 6.1 Dashboard | `ui/pages_academic.py::DashboardPage` | Today context, deadlines, RSO summaries, overdue tasks, wellbeing actions, blackout export | Partial: verify quick notes, configurable overdue threshold, and all four decision questions |
| 6.2 Schedule | `ui/pages_academic.py::SchedulePage`; `core/repositories/schedule_repository.py`; `core/domain/academic_rules.py` | Schedule CRUD/display, parity resolver, ICS export | Partial: month view, CSV import, recurring-series editing, cancellation and conflict dialog need verification |
| 6.3 Subjects / RSO | `SubjectsAndRsoPage`; `core/domain/academic_rules.py`; `core/repositories/subject_repository.py` | Subjects, RSO components, simulation, consultation history, syllabus parser adapter | Partial: arbitrary formulas, teacher/contact model, parser confirmation workflow and full consultation verdict-to-task workflow |
| 6.4 Tasks / focus | `TasksAndFocusPage`; `core/repositories/task_repository.py`; `ui/widgets.py` | Task status, steps, deadlines, focus sessions | Partial: task categories, kanban completeness, configurable timer modes, reminder actions and AI-use declaration linkage |
| 6.5 Lectures / Cornell | `CornellNotesPage`; `ExamSession21Page`; `core/repositories/cognitive_repository.py` | Cornell notes, flashcards, attempt recording, review dates | Partial: 0→24→7→21 history semantics and editable intervals require domain-level validation |
| 6.6 Exam / 21 days | `ExamSession21Page`; `ReviewScheduler` | Flashcard-based study session and review scheduler | Partial: exam calendar and adaptive 21-day stage planner are not evidenced as complete |
| 6.7 KAI R&D | `RdPortfolioPage`; `core/repositories/portfolio_repository.py` | Portfolio item/project storage and display | Partial: hub directory, certificates/verification periods and CV/LinkedIn draft generator |
| 6.8 Files | `FilesAndSearchPage`; `infrastructure/files/file_indexer.py`; `core/repositories/file_repository.py` | Watch folders, SHA-256 index, PDF/DOCX extraction, FTS5 search | Partial: folder-to-semester/project binding, Markdown/source extraction coverage, OCR extension point and debounce/stability tests |
| 6.9 Sync | `SyncQueuePage`; `integrations/google_classroom.py`; `integrations/digital_university.py`; `core/services.py::SyncApprovalService` | Queue, confidence, approve/reject, Google Classroom adapter, manual Digital University import | Partial: live KAI portal connector is absent; course matching and provider lifecycle need hardening |
| 6.10 Algorithms | `AlgorithmsAndAiPage`; `core/domain/cognitive_and_priority.py` | AI declaration and self-check UI | Partial: complete six checklists, custom templates, progress/history and reset are not evidenced |
| 6.11 Analytics | `AnalyticsPage` | Basic aggregates from local data | Partial: source/period provenance, PDF/CSV exports and methodology safeguards need verification |
| 6.12 Settings / backups | `SettingsAndBackupsPage`; `core/database/connection.py`; `core/credential_vault.py` | Settings, manual backup, blackout export, credential vault | Partial: first-run wizard, daily scheduled backup, one-click restore and editable campus transit matrix need completion |

## 2. Current SQLite model

Migration `core/database/migrations/001_initial_schema.sql` creates these application tables:

`user_settings`, `semesters`, `subjects`, `rso_components`, `schedule_entries`, `calendar_events`, `tasks`, `task_steps`, `grade_audit_log`, `focus_sessions`, `cornell_notes`, `flashcards`, `consultation_briefs`, `ai_declarations`, `wellbeing_logs`, `rd_portfolio_items`, `indexed_files`, `watched_folders`, `agent_changes`, `backup_history`.

Technical objects: `schema_migrations` and FTS5 `fts_documents`.

Specification 3.0 names 21 domain entities: Student, Semester, Subject, Teacher, ClassSession, Exam, Task, Subtask, GradeEntry, FocusSession, Topic, Question, TeacherConsultation, SyncSource, AgentChange, WatchedFolder, FileRecord, PortfolioProject, Note, Checklist, Reminder.

The current 20 application tables are not a one-to-one implementation of those entities. Some are merged or represented under different names (e.g. `schedule_entries` / `calendar_events`, `task_steps`, `cornell_notes` / `flashcards`); Teacher, Checklist and Reminder do not currently have clear independent tables. Do not rename or replace tables in-place: introduce additive migrations and explicit data backfills only after a field-level mapping and backup/restore test.

## 3. Layering and coupling

- Presentation: 12 page classes are wired in `ui/main_window.py`; 4 academic pages share `ui/pages_academic.py`, 8 other pages share `ui/pages_cognitive_and_tools.py`.
- Application: `app/application.py` now composes AcademicService, SyncApprovalService and BlackoutExportService; `app/container.py` owns the shared service graph. MainWindow and SyncQueuePage receive the academic and sync-approval services through dependency injection. Remaining pages still construct some repositories/services directly; migration is incremental.
- Domain: `core/domain/academic_rules.py` and `core/domain/cognitive_and_priority.py` contain current rules; the new `core/domain/models`, `rules` and `services` packages are mostly empty placeholders.
- Persistence: legacy `core/database.py` and new `core/database/connection.py` coexist. Repository facade `core/repositories/__init__.py` composes multiple repositories using inheritance.
- Integrations: Google Classroom adapter is currently an abstraction/staging adapter; Digital University has a substantial parser/import implementation; KAI portal currently supports ICS import/export and has a demo-update method that must never be treated as a live source.
- Infrastructure: file indexing exists; backup manager package is a placeholder while backup logic is in the database manager.

## 4. Safe implementation sequence

1. Preserve current schema and UI; add migration/restore tests before any data-model changes.
2. Add application use cases and inject them into UI without changing visible workflows.
3. Split page modules by feature, preserving import compatibility until callers migrate.
4. Split repository facade into explicit repositories and move callers gradually.
5. Add additive migrations for missing entities only after mapping old columns, relationships and data conversion.
6. Implement incomplete feature requirements and adapter contracts; test with fixtures, not live accounts.
7. Add Windows release smoke tests and document the remaining manual provider checks.

## 5. Verification boundaries

- CI currently runs Python compilation and pytest under GitHub Actions. Latest checked run: 35 passed (commit `ab36f8b`).
- First dependency-injection slice is implemented and covered by `tests/test_application_composition.py`.
- Passing unit/integration tests do not prove Qt UI usability on Windows, successful Google OAuth, or live KAI portal access.
- No schema-destructive migration should be merged without a tested backup and restore path.
