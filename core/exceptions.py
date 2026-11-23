class DashboardError(Exception):
    """Базовий виняток застосунку."""


class DomainValidationError(DashboardError):
    """Помилка валідації бізнес-правил (РСО, розклад, дедлайни)."""


class DatabaseTransactionError(DashboardError):
    """Помилка цілісності або блокування БД."""


class IntegrationSyncError(DashboardError):
    """Помилка зовнішнього API (Google Classroom / портал КАІ)."""