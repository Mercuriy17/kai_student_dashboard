from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

SERVICE_PREFIX = "KAIStudentDashboard_"
_ENTRY = "credentials"


class VaultError(Exception):
    """Сховище облікових даних Windows недоступне."""


@dataclass(frozen=True)
class StoredCredentials:
    login: str
    password: str = field(repr=False)  # ніколи не потрапляє у repr/логи


class CredentialVault:
    """Логін/пароль зберігаються лише у Windows Credential Manager (keyring) — не в SQLite, логах чи бекапах."""

    def __init__(self, backend: Optional[Any] = None) -> None:
        if backend is None:
            import keyring

            backend = keyring
        self._kr = backend

    @staticmethod
    def _service(connector_id: str) -> str:
        return f"{SERVICE_PREFIX}{connector_id}"

    def save(self, connector_id: str, login: str, password: str) -> None:
        login, password = login.strip(), password
        if not login or not password:
            raise ValueError("Логін і пароль не можуть бути порожніми.")
        try:
            self._kr.set_password(
                self._service(connector_id),
                _ENTRY,
                json.dumps({"login": login, "password": password}, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            raise VaultError("Не вдалося записати дані у Диспетчер облікових даних Windows.") from exc

    def load(self, connector_id: str) -> Optional[StoredCredentials]:
        try:
            raw = self._kr.get_password(self._service(connector_id), _ENTRY)
        except Exception as exc:  # noqa: BLE001
            raise VaultError("Не вдалося прочитати Диспетчер облікових даних Windows.") from exc
        if not raw:
            return None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or "login" not in data or "password" not in data:
                return None
            return StoredCredentials(login=str(data["login"]), password=str(data["password"]))
        except (TypeError, ValueError, KeyError):
            return None

    def has(self, connector_id: str) -> bool:
        return self.load(connector_id) is not None

    def delete(self, connector_id: str) -> None:
        service = self._service(connector_id)
        try:
            # Відсутній запис — штатний стан; помилку backend під час читання
            # або фактичного видалення не можна приховувати від користувача.
            if self._kr.get_password(service, _ENTRY) is None:
                return
            self._kr.delete_password(service, _ENTRY)
        except Exception as exc:  # noqa: BLE001
            raise VaultError("Не вдалося видалити облікові дані з Диспетчера облікових даних Windows.") from exc
