from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from config.defaults import LOGS_DIR

_SECRET_RE = re.compile(r"(password|passwd|pwd|token|csrf|secret)(\s*[=:]\s*)(\S+)", re.IGNORECASE)


class RedactFilter(logging.Filter):
    """Маскує значення паролів/токенів у будь-якому повідомленні журналу (специфікація §12.1)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET_RE.sub(r"\1\2***", str(record.getMessage()))
        record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOGS_DIR / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter())
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    # httpx логує повні URL запитів — залишаємо лише попередження
    logging.getLogger("httpx").setLevel(logging.WARNING)
