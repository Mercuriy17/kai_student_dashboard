from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from core.connector_state import ConnectorStateRepository
from core.credential_vault import CredentialVault
from core.database import DatabaseManager
from core.repositories import AcademicRepository, SyncAndFileRepository
from core.services import SyncApprovalService
from integrations.digital_university import (
    CONNECTOR_ID,
    DigitalUniversityConnector,
    DigitalUniversityParser,
    PortalAuthError,
    PortalClient,
    PortalParseError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "schedule_sample.html"


class FakeKeyring:
    def __init__(self):
        self.data = {}

    def set_password(self, s, u, p):
        self.data[(s, u)] = p

    def get_password(self, s, u):
        return self.data.get((s, u))

    def delete_password(self, s, u):
        self.data.pop((s, u), None)


@pytest.fixture(scope="module")
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(html):
    return DigitalUniversityParser.parse_schedule(html, semester_year=2026)


# ------------------------------------------------------------------ парсер


def test_group_and_anchor(parsed):
    assert parsed.group == "Б-G9-26-1-МК"
    assert parsed.anchor_date == date(2026, 8, 31)  # понеділок 1-го тижня


def test_regular_entries_collapse_by_parity(parsed):
    by_key = {(e.day_of_week, e.start_time, e.subject): e for e in parsed.regular}
    # Лекція «Екологія» у вівторок 08:00 — лише непарні тижні (чисельник)
    eco = by_key[(2, "08:00", "Екологія")]
    assert eco.parity == "odd" and eco.lesson_type == "lecture"
    assert eco.building == "4" and eco.room == "Укриття"
    # Вища математика, практика у п'ятницю 08:00 — чисельник
    assert by_key[(5, "08:00", "Вища математика")].parity == "odd"
    # Загальна фізика, лаба у четвер 08:00 — знаменник
    phys = by_key[(4, "08:00", "Загальна фізика")]
    assert phys.parity == "even" and phys.lesson_type == "lab"


def test_one_offs_are_saturdays_and_extra_week(parsed):
    dates = {(o.lesson_date.isoformat(), o.start_time, o.subject) for o in parsed.one_offs}
    assert ("2026-11-21", "09:50", "Загальна фізика") in dates  # субота 12-го тижня
    assert all(o.week in (12, 13, 15) for o in parsed.one_offs)
    # ніяка регулярна пара не потрапляє в разові
    regular_keys = {(e.day_of_week, e.start_time, e.subject) for e in parsed.regular}
    assert (6, "09:50", "Загальна фізика") not in regular_keys


def test_week_badge_filters_cards(parsed):
    # «Вступ до спеціальності» має бейдж «тижні 1,3,5…»: у парних панелях її бути не може
    intro = [e for e in parsed.regular if e.subject == "Вступ до спеціальності"]
    assert intro and all(e.parity == "odd" for e in intro)


def test_online_link_extracted_and_safe(parsed):
    links = [e.online_url for e in parsed.regular if e.online_url]
    assert links and all(u.startswith("https://") for u in links)


def test_pair_numbers_follow_bell_schedule(parsed):
    e = next(x for x in parsed.regular if x.start_time == "11:40")
    assert e.pair_number == 3


def test_parse_error_on_wrong_page():
    with pytest.raises(PortalParseError):
        DigitalUniversityParser.parse_schedule("<html><body>нічого</body></html>")


# ------------------------------------------------------------------ клієнт


LOGIN_FORM = """<html><body><form action="/site/login" method="post">
<input type="hidden" name="_csrf-frontend" value="tok123">
<input type="text" name="LoginForm[username]"><input type="password" name="LoginForm[password]">
</form></body></html>"""


def _portal_transport(html: str, seen: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/student/schedule":
            if request.headers.get("cookie", "").find("sid=ok") >= 0:
                return httpx.Response(200, text=html)
            return httpx.Response(302, headers={"location": "/site/login"})
        if request.url.path == "/site/login" and request.method == "GET":
            return httpx.Response(200, text=LOGIN_FORM)
        if request.url.path == "/site/login" and request.method == "POST":
            seen["post"] = request.content.decode()
            ok = b"secret" in request.content
            return httpx.Response(302, headers={"location": "/student/schedule", "set-cookie": "sid=ok; Path=/"} if ok else {"location": "/site/login"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_client_logs_in_with_form_and_csrf(html):
    seen: dict = {}
    c = PortalClient("https://cabinet.example", transport=_portal_transport(html, seen))
    page = c.fetch_schedule_html("student", "secret")
    assert "schedule-week-pane" in page
    assert "tok123" in seen["post"] and "LoginForm%5Busername%5D=student" in seen["post"]


def test_client_wrong_password_gives_safe_error(html):
    c = PortalClient("https://cabinet.example", transport=_portal_transport(html, {}))
    with pytest.raises(PortalAuthError) as ei:
        c.fetch_schedule_html("student", "WRONGPASS")
    assert "WRONGPASS" not in str(ei.value)


def test_client_sso_without_password_form():
    def handler(request):
        return httpx.Response(200, text="<html><body><a href='/google'>Увійти через Google</a></body></html>")

    c = PortalClient("https://cabinet.example", transport=httpx.MockTransport(handler))
    with pytest.raises(PortalAuthError) as ei:
        c.fetch_schedule_html("a", "b")
    assert "SSO" in str(ei.value)


# ------------------------------------------------------------------ конектор + підтвердження


@pytest.fixture()
def env(tmp_path, html):
    db = DatabaseManager(tmp_path / "t.sqlite3")
    db.apply_migrations()
    academic, sync = AcademicRepository(db), SyncAndFileRepository(db)
    db.execute("INSERT INTO semesters (name, start_date, end_date, parity_anchor_date, is_active) VALUES ('s','2026-09-01','2026-12-31','2026-09-01',1)")
    academic.set_setting("parity_anchor_date", "2026-09-01")
    vault = CredentialVault(FakeKeyring())
    state = ConnectorStateRepository(db)
    conn = DigitalUniversityConnector(academic, sync, vault, state, transport=_portal_transport(html, {}))
    return db, academic, sync, vault, state, conn


def test_import_html_queues_and_is_idempotent(env):
    db, academic, sync, vault, state, conn = env
    r1 = conn.import_from_html_file(FIXTURE)
    assert r1["queued"] > 20 and r1["group"] == "Б-G9-26-1-МК"
    r2 = conn.import_from_html_file(FIXTURE)
    assert r2["queued"] == 0  # повторна синхронізація не створює дублікатів
    assert academic.list_schedule() == []  # основні таблиці не змінено до підтвердження
    pending = sync.list_agent_changes("pending")
    assert all(0 < float(p["confidence"]) <= 1 for p in pending)
    assert {"schedule", "calendar_event", "setting"} <= {p["entity_type"] for p in pending}
    assert state.get(CONNECTOR_ID)["last_status"] == "ok"


def test_approval_creates_subjects_schedule_events_and_anchor(env):
    db, academic, sync, vault, state, conn = env
    conn.import_from_html_file(FIXTURE)
    svc = SyncApprovalService(db)
    for ch in sync.list_agent_changes("pending"):
        svc.approve_change(int(ch["id"]))
    sched = academic.list_schedule()
    assert len(sched) == 24
    assert len({s["subject_id"] for s in sched}) == len({s["subject_name"] for s in sched})  # без дублікатів дисциплін
    ev = db.fetch_all("SELECT * FROM calendar_events")
    assert len(ev) == 6 and all(e["event_type"] == "replacement" for e in ev)
    assert academic.get_setting("parity_anchor_date") == "2026-08-31"
    # онлайн-посилання та нотатки переїхали в розклад
    assert any(s["online_url"].startswith("https://") for s in sched)


def test_existing_subject_matched_by_name_containment(env):
    db, academic, sync, vault, state, conn = env
    sem = academic.get_active_semester()
    sid = academic.create_subject(semester_id=int(sem["id"]), name="Загальна фізика (Механіка та молекулярна фізика)")
    conn.import_from_html_file(FIXTURE)
    svc = SyncApprovalService(db)
    for ch in sync.list_agent_changes("pending"):
        svc.approve_change(int(ch["id"]))
    phys = [s for s in academic.list_schedule() if "фізика" in s["subject_name"].lower()]
    assert phys and all(int(s["subject_id"]) == sid for s in phys)
    assert len([s for s in academic.list_subjects() if "фізика" in s["name"].lower()]) == 1


def test_sync_without_credentials_is_clear_error(env):
    *_, conn = env
    with pytest.raises(PortalAuthError):
        conn.sync_to_approval_queue()


def test_sync_with_credentials_end_to_end(env):
    db, academic, sync, vault, state, conn = env
    vault.save(CONNECTOR_ID, "student", "secret")
    res = conn.sync_to_approval_queue()
    assert res["queued"] > 20


def test_failed_sync_records_error_without_secret(env):
    db, academic, sync, vault, state, conn = env
    vault.save(CONNECTOR_ID, "student", "WRONGPASS")
    with pytest.raises(PortalAuthError):
        conn.sync_to_approval_queue()
    st = state.get(CONNECTOR_ID)
    assert st["last_status"] == "error" and "WRONGPASS" not in st["last_error"]
