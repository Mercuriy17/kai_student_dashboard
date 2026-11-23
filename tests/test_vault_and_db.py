from __future__ import annotations

import threading

import pytest

from core.credential_vault import CredentialVault
from core.database import DatabaseManager
from core.logging_setup import RedactFilter
import logging


class FakeKeyring:
    def __init__(self):
        self.data = {}

    def set_password(self, s, u, p):
        self.data[(s, u)] = p

    def get_password(self, s, u):
        return self.data.get((s, u))

    def delete_password(self, s, u):
        self.data.pop((s, u), None)


def test_vault_roundtrip_delete_and_repr_hides_password():
    v = CredentialVault(FakeKeyring())
    assert v.load("x") is None
    v.save("x", " user ", "p@ss")
    c = v.load("x")
    assert c.login == "user" and c.password == "p@ss"
    assert "p@ss" not in repr(c)
    v.delete("x")
    assert not v.has("x")


def test_vault_rejects_empty():
    with pytest.raises(ValueError):
        CredentialVault(FakeKeyring()).save("x", "", "p")


def test_secret_never_stored_in_database(tmp_path):
    db = DatabaseManager(tmp_path / "t.sqlite3")
    db.apply_migrations()
    CredentialVault(FakeKeyring()).save("digital_university", "u", "TOPSECRET")
    dump = "".join(db.connection.iterdump())
    assert "TOPSECRET" not in dump


def test_migrations_idempotent_and_confidence_column(tmp_path):
    db = DatabaseManager(tmp_path / "t.sqlite3")
    db.apply_migrations()
    db.apply_migrations()
    cols = {r["name"] for r in db.fetch_all("PRAGMA table_info(agent_changes)")}
    assert "confidence" in cols
    assert db.fetch_one("SELECT base_url FROM sync_connectors WHERE connector_id='digital_university'")["base_url"].startswith("https://")
    assert db.integrity_check()


def test_concurrent_writers_do_not_corrupt(tmp_path):
    db = DatabaseManager(tmp_path / "t.sqlite3")
    db.apply_migrations()

    def worker(n):
        for i in range(60):
            db.execute("INSERT INTO user_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f"k{n}_{i}", "v"))
            db.fetch_all("SELECT * FROM user_settings")

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert db.fetch_one("SELECT COUNT(*) AS c FROM user_settings")["c"] == 360


def test_backup_rotation_keeps_latest(tmp_path):
    db = DatabaseManager(tmp_path / "t.sqlite3")
    db.apply_migrations()
    folder = tmp_path / "bk"
    for _ in range(5):
        db.create_backup(folder, keep=3)
    assert len(list(folder.glob("*.sqlite3"))) == 3


def test_log_filter_masks_secrets():
    rec = logging.LogRecord("x", logging.INFO, "", 0, "login ok password=hunter2 csrf: abc", (), None)
    RedactFilter().filter(rec)
    assert "hunter2" not in rec.msg and "abc" not in rec.msg



def test_vault_reports_delete_backend_failure():
    from core.credential_vault import VaultError

    class BrokenDeleteKeyring(FakeKeyring):
        def delete_password(self, s, u):
            raise RuntimeError("backend unavailable")

    keyring = BrokenDeleteKeyring()
    keyring.set_password("KAIStudentDashboard_x", "credentials", '{"login":"u","password":"p"}')
    with pytest.raises(VaultError):
        CredentialVault(keyring).delete("x")


def test_vault_treats_malformed_payload_as_missing():
    keyring = FakeKeyring()
    keyring.set_password("KAIStudentDashboard_x", "credentials", '["not", "an", "object"]')
    assert CredentialVault(keyring).load("x") is None
