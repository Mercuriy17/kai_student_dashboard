from dataclasses import dataclass
from app.events import EventBus
from config.defaults import DB_PATH
from core.database.connection import DatabaseManager
from infrastructure.system.credentials import CredentialVault


@dataclass(slots=True)
class AppContainer:
    db: DatabaseManager
    events: EventBus
    vault: CredentialVault

    @classmethod
    def build(cls) -> "AppContainer":
        return cls(
            db=DatabaseManager(DB_PATH),
            events=EventBus(),
            vault=CredentialVault(),
        )