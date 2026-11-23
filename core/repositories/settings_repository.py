from core.repositories.base import BaseRepository


class SettingsRepository(BaseRepository):
    def get_setting(self, key: str, default: str = "") -> str:
        row = self._fetch_one("SELECT value FROM user_settings WHERE key = ?", (key,))
        return str(row["value"]) if row and row["value"] is not None else default

    def set_setting(self, key: str, value: str) -> None:
        self._execute(
            """
            INSERT INTO user_settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value),
        )