-- Міграція 002: стан конекторів, впевненість парсингу в черзі змін, службовий журнал
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sync_connectors (
    connector_id TEXT PRIMARY KEY,           -- 'digital_university', 'google_classroom'
    display_name TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    is_enabled INTEGER NOT NULL DEFAULT 1,
    last_sync_at TEXT,
    last_status TEXT NOT NULL DEFAULT 'never', -- 'never', 'ok', 'error'
    last_error TEXT NOT NULL DEFAULT '',
    last_found INTEGER NOT NULL DEFAULT 0
);

-- Показник впевненості парсингу для кожної пропозиції агента (0..1)
ALTER TABLE agent_changes ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0;

INSERT OR IGNORE INTO sync_connectors (connector_id, display_name, base_url)
VALUES ('digital_university', 'Digital University КАІ', 'https://cabinet.nau.edu.ua'),
       ('google_classroom', 'Google Classroom', '');
