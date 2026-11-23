from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.connector_state import ConnectorStateRepository
from core.credential_vault import CredentialVault, VaultError
from integrations.digital_university import CONNECTOR_ID, DEFAULT_BASE_URL, DigitalUniversityConnector
from ui.workers import TaskWorker


class ConnectionsDialog(QDialog):
    """Введення облікових даних Digital University. Пароль йде лише у Windows Credential Manager."""

    def __init__(
        self,
        vault: CredentialVault,
        state: ConnectorStateRepository,
        connector: DigitalUniversityConnector,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.vault, self.state, self.connector = vault, state, connector
        self._worker: Optional[TaskWorker] = None
        self.setWindowTitle("Підключення: Digital University КАІ")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        info = QLabel(
            "Логін і пароль зберігаються лише в Диспетчері облікових даних Windows і ніколи не потрапляють "
            "у базу даних, журнали, резервні копії чи пакет блекауту. Отримані дані спершу йдуть у чергу "
            "підтвердження. Пароль Google застосунок не запитує: Classroom підключається через OAuth."
        )
        info.setWordWrap(True)
        info.setProperty("class", "MutedText")
        layout.addWidget(info)

        form = QFormLayout()
        self.url_edit = QLineEdit(self.state.get(CONNECTOR_ID).get("base_url") or DEFAULT_BASE_URL)
        self.login_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        existing = self._safe_load()
        if existing:
            self.login_edit.setText(existing.login)
            self.password_edit.setPlaceholderText("Збережено (введіть нове значення, щоб замінити)")
        form.addRow("Адреса порталу:", self.url_edit)
        form.addRow("Логін:", self.login_edit)
        form.addRow("Пароль:", self.password_edit)
        layout.addLayout(form)

        self.status = QLabel(self.state.describe(CONNECTOR_ID))
        self.status.setWordWrap(True)
        self.status.setProperty("class", "MutedText")
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.test_btn = QPushButton("Зберегти і перевірити вхід")
        self.test_btn.setProperty("class", "PrimaryBtn")
        self.test_btn.clicked.connect(self._save_and_test)
        forget_btn = QPushButton("Забути облікові дані")
        forget_btn.setProperty("class", "DangerBtn")
        forget_btn.clicked.connect(self._forget)
        close_btn = QPushButton("Закрити")
        close_btn.setProperty("class", "SecondaryBtn")
        close_btn.clicked.connect(self.accept)
        row.addWidget(self.test_btn)
        row.addWidget(forget_btn)
        row.addStretch()
        row.addWidget(close_btn)
        layout.addLayout(row)

    def _safe_load(self):
        try:
            return self.vault.load(CONNECTOR_ID)
        except VaultError:
            return None

    def _save(self) -> bool:
        login = self.login_edit.text().strip()
        password = self.password_edit.text()
        url = self.url_edit.text().strip()
        if not url.lower().startswith("https://"):
            QMessageBox.warning(self, "Адреса", "Адреса порталу має починатися з https://")
            return False
        try:
            if password:
                self.vault.save(CONNECTOR_ID, login, password)
            elif not self._safe_load():
                QMessageBox.warning(self, "Дані", "Введіть логін і пароль.")
                return False
            self.state.set_base_url(CONNECTOR_ID, url)
        except (ValueError, VaultError) as exc:
            QMessageBox.warning(self, "Не збережено", str(exc))
            return False
        self.password_edit.clear()
        return True

    def _save_and_test(self) -> None:
        if not self._save():
            return
        self.test_btn.setEnabled(False)
        self.status.setText("Перевіряю вхід…")
        self._worker = TaskWorker(self.connector.test_login, self)
        self._worker.succeeded.connect(self._on_ok)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self, res: dict) -> None:
        self.test_btn.setEnabled(True)
        self.status.setText(res["message"])

    def _on_fail(self, msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.status.setText(msg)

    def _forget(self) -> None:
        self.vault.delete(CONNECTOR_ID)
        self.login_edit.clear()
        self.password_edit.clear()
        self.password_edit.setPlaceholderText("")
        self.status.setText("Облікові дані видалено з Диспетчера облікових даних Windows.")
