from dataclasses import dataclass
from pathlib import Path

from app.application import ApplicationServices
from app.events import EventBus
from config.defaults import DB_PATH
from core.credential_vault import CredentialVault
from core.database.connection import DatabaseManager


@dataclass(slots=True)
class AppContainer:
    db: DatabaseManager
    events: EventBus
    vault: CredentialVault
    services: ApplicationServices

    @classmethod
    def build(cls) -> "AppContainer":
        db = DatabaseManager(Path(DB_PATH))
        return cls(
            db=db,
            events=EventBus(),
            vault=CredentialVault(),
            services=ApplicationServices.build(db),
        )
