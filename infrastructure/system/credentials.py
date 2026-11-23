import keyring
from core.exceptions import IntegrationSyncError

SERVICE_NAME = "KAIStudentDashboard"


class CredentialVault:
    @staticmethod
    def save_token(account: str, token_json: str) -> None:
        try:
            keyring.set_password(SERVICE_NAME, account, token_json)
        except Exception as exc:
            raise IntegrationSyncError(f"Не вдалося зберегти токен у системне сховище: {exc}") from exc

    @staticmethod
    def load_token(account: str) -> str | None:
        return keyring.get_password(SERVICE_NAME, account)

    @staticmethod
    def delete_token(account: str) -> None:
        if CredentialVault.load_token(account):
            keyring.delete_password(SERVICE_NAME, account)