from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from config.defaults import KAI_BELL_SCHEDULE
from core.connector_state import ConnectorStateRepository
from core.credential_vault import CredentialVault
from core.repositories import AcademicRepository, SyncAndFileRepository

log = logging.getLogger(__name__)

CONNECTOR_ID = "digital_university"
DEFAULT_BASE_URL = "https://cabinet.nau.edu.ua"
SCHEDULE_PATH = "/student/schedule"

_TYPE_MAP = {"лекц": "lecture", "практ": "practice", "лаб": "lab", "конс": "consultation"}
_TYPE_UA = {"lecture": "Лекція", "practice": "Практика", "lab": "Лабораторна", "consultation": "Консультація"}
_DAYS_SHORT = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Нд"}
_WEEKS_RE = re.compile(r"тиж(?:день|ні)\s+([\d,\s]+)", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})")
_BUILDING_RE = re.compile(r"Корп\.?\s*(\S+)\s*(.*)", re.IGNORECASE)
# Частка панелей одного типу тижня, за якої заняття вважається «регулярним»
REGULAR_COVERAGE = 0.75


class PortalError(Exception):
    """Базова помилка конектора порталу (текст безпечно показувати користувачу)."""


class PortalAuthError(PortalError):
    """Вхід неможливий: невірні дані, SSO, капча тощо."""


class PortalParseError(PortalError):
    """Сторінка отримана, але структура розкладу не розпізнана."""


# --------------------------------------------------------------------------- parsing


@dataclass(frozen=True)
class PortalLesson:
    week: int
    parity: str  # 'odd' | 'even'
    lesson_date: date
    day_of_week: int
    start_time: str
    end_time: str
    pair_number: int
    subject: str
    lesson_type: str
    building: str
    room: str
    teacher: str
    online_url: str


@dataclass(frozen=True)
class RegularEntry:
    day_of_week: int
    start_time: str
    end_time: str
    pair_number: int
    subject: str
    lesson_type: str
    parity: str  # 'odd' | 'even' | 'both'
    building: str
    room: str
    teacher: str
    online_url: str
    missing_weeks: Tuple[int, ...]
    confidence: float


@dataclass
class ParsedSchedule:
    group: str = ""
    anchor_date: Optional[date] = None  # понеділок 1-го тижня за даними порталу
    regular: List[RegularEntry] = field(default_factory=list)
    one_offs: List[PortalLesson] = field(default_factory=list)
    lessons_total: int = 0


def _hhmm(h: str, m: str) -> str:
    return f"{int(h):02d}:{int(m):02d}"


def _pair_number(start: str, fallback: int) -> int:
    for num, (s, _e) in KAI_BELL_SCHEDULE.items():
        if s == start:
            return num
    return fallback


def semester_year_for(today: Optional[date] = None) -> int:
    """Рік початку осіннього семестру (для дат вигляду 31.08 без року)."""
    d = today or date.today()
    return d.year if d.month >= 8 else d.year - 1


def _resolve_date(day: int, month: int, sem_year: int) -> date:
    year = sem_year if month >= 8 else sem_year + 1
    return date(year, month, day)


class DigitalUniversityParser:
    """Детермінований парсер сторінки «Розклад» Digital University (/student/schedule)."""

    @classmethod
    def parse_schedule(cls, html: str, semester_year: Optional[int] = None) -> ParsedSchedule:
        soup = BeautifulSoup(html, "html.parser")
        panes = soup.select("div.schedule-week-pane")
        if not panes:
            raise PortalParseError(
                "На сторінці не знайдено тижневих панелей розкладу. "
                "Перевірте, що це сторінка «Розклад» у режимі «Таблиця»."
            )
        sem_year = semester_year or semester_year_for()
        result = ParsedSchedule()
        group_btn = soup.select_one("button.modal-education.active")
        if group_btn:
            result.group = group_btn.get_text(strip=True)

        lessons: List[PortalLesson] = []
        parity_weeks: Dict[str, set] = {"odd": set(), "even": set()}
        for pane in panes:
            lessons.extend(cls._parse_pane(pane, sem_year, parity_weeks, result))
        result.lessons_total = len(lessons)
        result.regular, result.one_offs = cls._collapse(lessons, parity_weeks)
        return result

    @classmethod
    def _parse_pane(
        cls,
        pane: Any,
        sem_year: int,
        parity_weeks: Dict[str, set],
        result: ParsedSchedule,
    ) -> List[PortalLesson]:
        m_week = re.match(r"\s*(\d+)", pane.get("data-week-name", ""))
        if not m_week:
            return []
        week = int(m_week.group(1))
        parity = "odd" if str(pane.get("data-sequence-label", "1")).strip() == "1" else "even"
        parity_weeks[parity].add(week)

        grid = pane.select_one(".schedule-grid")
        if grid is None:
            return []
        header = grid.select_one(".grid-header-row")
        day_dates: List[date] = []
        if header is not None:
            for cell in header.find_all("div", class_="grid-cell", recursive=False):
                m = _DATE_RE.search(cell.get_text(" ", strip=True))
                if not m:
                    return []
                day_dates.append(_resolve_date(int(m.group(1)), int(m.group(2)), sem_year))
        if not day_dates:
            return []
        if week == 1 and result.anchor_date is None:
            result.anchor_date = day_dates[0]

        out: List[PortalLesson] = []
        for row_idx, row in enumerate(grid.find_all("div", class_="grid-row", recursive=False), start=1):
            cells = row.find_all("div", class_="grid-cell", recursive=False)
            if len(cells) < 2:
                continue
            spans = [s.get_text(strip=True) for s in cells[0].select("span")]
            if len(spans) < 4:
                continue
            start, end = _hhmm(spans[0], spans[1]), _hhmm(spans[2], spans[3])
            pair_no = _pair_number(start, row_idx)
            for day_idx, cell in enumerate(cells[1:]):
                if day_idx >= len(day_dates):
                    break
                for card in cell.select(".pair-card"):
                    lesson = cls._parse_card(card, week, parity, day_dates[day_idx], day_idx + 1, start, end, pair_no)
                    if lesson is not None:
                        out.append(lesson)
        return out

    @classmethod
    def _parse_card(
        cls,
        card: Any,
        week: int,
        parity: str,
        lesson_date: date,
        dow: int,
        start: str,
        end: str,
        pair_no: int,
    ) -> Optional[PortalLesson]:
        title_el = card.select_one(".font-weight-bold")
        if title_el is None:
            return None
        # Бейдж «тиждень N / тижні …»: заняття діє лише в перелічені тижні
        for badge in card.select(".badge-info"):
            m = _WEEKS_RE.search(badge.get_text(" ", strip=True))
            if m:
                allowed = {int(n) for n in re.findall(r"\d+", m.group(1))}
                if week not in allowed:
                    return None
                break

        type_el = card.select_one("span.badge:not(.badge-info)")
        raw_type = (type_el.get_text(strip=True) if type_el else "").lower().rstrip(".")
        lesson_type = _TYPE_MAP.get(raw_type, "lecture")

        def icon_text(icon_cls: str) -> str:
            icon = card.select_one(f"i.{icon_cls}")
            if icon is None or icon.parent is None:
                return ""
            return icon.parent.get_text(" ", strip=True)

        building, room = "", ""
        m_b = _BUILDING_RE.match(icon_text("fa-building"))
        if m_b:
            building, room = m_b.group(1), m_b.group(2).strip()

        online_url = ""
        popover = card.select_one("[data-content]")
        if popover is not None:
            inner = BeautifulSoup(popover.get("data-content", ""), "html.parser")
            link = inner.select_one("a[href]")
            if link is not None:
                online_url = link["href"]
        if urlparse(online_url).scheme not in ("http", "https"):
            online_url = ""

        return PortalLesson(
            week=week,
            parity=parity,
            lesson_date=lesson_date,
            day_of_week=dow,
            start_time=start,
            end_time=end,
            pair_number=pair_no,
            subject=title_el.get_text(" ", strip=True),
            lesson_type=lesson_type,
            building=building,
            room=room,
            teacher=icon_text("fa-person"),
            online_url=online_url,
        )

    @classmethod
    def _collapse(
        cls, lessons: List[PortalLesson], parity_weeks: Dict[str, set]
    ) -> Tuple[List[RegularEntry], List[PortalLesson]]:
        """Згортає тижневі зрізи у регулярні записи (parity) та разові відхилення."""
        groups: Dict[Tuple[int, str, str, str], List[PortalLesson]] = {}
        for ls in lessons:
            groups.setdefault((ls.day_of_week, ls.start_time, ls.subject, ls.lesson_type), []).append(ls)

        odd_all, even_all = parity_weeks["odd"], parity_weeks["even"]
        regular: List[RegularEntry] = []
        one_offs: List[PortalLesson] = []

        for items in groups.values():
            weeks = {ls.week for ls in items}
            odd_cov = len(weeks & odd_all) / len(odd_all) if odd_all else 0.0
            even_cov = len(weeks & even_all) / len(even_all) if even_all else 0.0
            odd_ok, even_ok = odd_cov >= REGULAR_COVERAGE, even_cov >= REGULAR_COVERAGE

            if odd_ok and even_ok:
                parity, base = "both", odd_all | even_all
            elif odd_ok:
                parity, base = "odd", odd_all
            elif even_ok:
                parity, base = "even", even_all
            else:
                one_offs.extend(items)
                continue

            main = [ls for ls in items if ls.week in base]
            one_offs.extend(ls for ls in items if ls.week not in base)
            missing = tuple(sorted(base - weeks))
            first = main[0]
            regular.append(
                RegularEntry(
                    day_of_week=first.day_of_week,
                    start_time=first.start_time,
                    end_time=first.end_time,
                    pair_number=first.pair_number,
                    subject=first.subject,
                    lesson_type=first.lesson_type,
                    parity=parity,
                    building=next((x.building for x in main if x.building), ""),
                    room=next((x.room for x in main if x.room), ""),
                    teacher=next((x.teacher for x in main if x.teacher), ""),
                    online_url=next((x.online_url for x in main if x.online_url), ""),
                    missing_weeks=missing,
                    confidence=0.95 if not missing else 0.85,
                )
            )
        regular.sort(key=lambda e: (e.day_of_week, e.start_time, e.subject))
        one_offs.sort(key=lambda x: (x.lesson_date, x.start_time, x.subject))
        return regular, one_offs


# --------------------------------------------------------------------------- HTTP client


def _with_retry(fn: Callable[[], Any], attempts: int = 3, base_delay: float = 0.6) -> Any:
    """Повтор із експоненційною затримкою лише для мережевих збоїв і 5xx."""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            resp = fn()
            if isinstance(resp, httpx.Response) and resp.status_code >= 500:
                raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(base_delay * (2**i))
    raise PortalError("Портал недоступний або відповідає помилкою. Спробуйте пізніше.") from last


class PortalClient:
    """Сесійний клієнт Digital University: вхід формою логін/пароль і завантаження розкладу."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "KAI-Student-Command-Center/1.0"},
        )

    def close(self) -> None:
        self._client.close()

    @property
    def schedule_url(self) -> str:
        return self.base_url + SCHEDULE_PATH

    @staticmethod
    def _is_schedule_page(html: str) -> bool:
        return 'id="schedule"' in html and "schedule-week-pane" in html

    def fetch_schedule_html(self, login: str, password: str) -> str:
        resp = _with_retry(lambda: self._client.get(self.schedule_url))
        if self._is_schedule_page(resp.text):
            return resp.text

        self._submit_login_form(resp, login, password)
        resp = _with_retry(lambda: self._client.get(self.schedule_url))
        if not self._is_schedule_page(resp.text):
            raise PortalAuthError(
                "Не вдалося відкрити розклад після входу: перевірте логін і пароль "
                "або скористайтеся імпортом збереженої HTML-сторінки."
            )
        return resp.text

    def _submit_login_form(self, resp: httpx.Response, login: str, password: str) -> None:
        page = resp.text
        if "captcha" in page.lower():
            raise PortalAuthError("Портал вимагає капчу. Автоматичний вхід неможливий — імпортуйте HTML-сторінку.")
        soup = BeautifulSoup(page, "html.parser")
        form = next((f for f in soup.find_all("form") if f.select_one("input[type=password]")), None)
        if form is None:
            host = urlparse(str(resp.url)).netloc
            raise PortalAuthError(
                f"Форму входу з паролем не знайдено (адреса: {host}). Імовірно, портал використовує "
                "зовнішній вхід (SSO). Використайте імпорт збереженої HTML-сторінки."
            )
        data: Dict[str, str] = {}
        for inp in form.select("input[name]"):
            if inp.get("type", "text").lower() in ("hidden",):
                data[inp["name"]] = inp.get("value", "")
        pw_field = form.select_one("input[type=password]")["name"]
        login_inp = form.select_one("input[type=text], input[type=email], input:not([type])")
        if login_inp is None or not login_inp.get("name"):
            raise PortalAuthError("У формі входу не знайдено поле логіна.")
        data[login_inp["name"]] = login
        data[pw_field] = password
        action = urljoin(str(resp.url), form.get("action") or str(resp.url))
        _with_retry(lambda: self._client.post(action, data=data))


# --------------------------------------------------------------------------- connector


def _slug(text: str) -> str:
    return re.sub(r"[^\w]+", "_", text.lower(), flags=re.UNICODE).strip("_")[:48]


class DigitalUniversityConnector:
    """Збирає розклад із Digital University і кладе його ЛИШЕ в чергу підтвердження (AgentChange)."""

    def __init__(
        self,
        academic_repo: AcademicRepository,
        sync_repo: SyncAndFileRepository,
        vault: CredentialVault,
        state: ConnectorStateRepository,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.academic_repo = academic_repo
        self.sync_repo = sync_repo
        self.vault = vault
        self.state = state
        self._transport = transport

    # публічне API -------------------------------------------------------------

    def test_login(self) -> Dict[str, Any]:
        html = self._download()
        parsed = DigitalUniversityParser.parse_schedule(html)
        self.state.record_result(CONNECTOR_ID, "ok", found=parsed.lessons_total)
        return {"ok": True, "message": f"Вхід успішний. Знайдено занять у тижневих панелях: {parsed.lessons_total}."}

    def sync_to_approval_queue(self) -> Dict[str, Any]:
        return self._ingest(self._download())

    def import_from_html_file(self, path: Path) -> Dict[str, Any]:
        try:
            html = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            raise PortalError(f"Не вдалося прочитати файл: {exc.strerror or exc}") from exc
        return self._ingest(html)

    # внутрішнє ----------------------------------------------------------------

    def _download(self) -> str:
        creds = self.vault.load(CONNECTOR_ID)
        if creds is None:
            raise PortalAuthError("Облікові дані не збережено. Відкрийте «Підключення» та введіть логін і пароль.")
        base = self.state.get(CONNECTOR_ID).get("base_url") or DEFAULT_BASE_URL
        client = PortalClient(base, transport=self._transport)
        try:
            return client.fetch_schedule_html(creds.login, creds.password)
        except PortalError as exc:
            self.state.record_result(CONNECTOR_ID, "error", error=str(exc))
            raise
        finally:
            client.close()

    def _ingest(self, html: str) -> Dict[str, Any]:
        try:
            parsed = DigitalUniversityParser.parse_schedule(html)
        except PortalError as exc:
            self.state.record_result(CONNECTOR_ID, "error", error=str(exc))
            raise

        existing = {
            (int(e["day_of_week"]), str(e["start_time"]), str(e["subject_name"]).lower())
            for e in self.academic_repo.list_schedule()
        }
        queued = skipped = 0

        for e in parsed.regular:
            if (e.day_of_week, e.start_time, e.subject.lower()) in existing:
                skipped += 1
                continue
            weeks_note = f"Не проводиться у тижні: {', '.join(map(str, e.missing_weeks))}." if e.missing_weeks else ""
            notes = " ".join(x for x in (f"Викладач: {e.teacher}." if e.teacher else "", weeks_note) if x)
            parity_ua = {"odd": "чисельник", "even": "знаменник", "both": "щотижня"}[e.parity]
            if self._enqueue(
                external_id=f"du:sched:{e.day_of_week}:{e.start_time}:{_slug(e.subject)}:{e.lesson_type}:{e.parity}",
                entity_type="schedule",
                title=f"Розклад: {e.subject} ({_DAYS_SHORT[e.day_of_week]} {e.start_time}, {_TYPE_UA[e.lesson_type]})",
                payload={
                    "subject_name": e.subject,
                    "day_of_week": e.day_of_week,
                    "pair_number": e.pair_number,
                    "start_time": e.start_time,
                    "end_time": e.end_time,
                    "parity": e.parity,
                    "lesson_type": e.lesson_type,
                    "building": e.building or "1",
                    "room": e.room,
                    "online_url": e.online_url,
                    "notes": notes,
                },
                diff_summary=(
                    f"{_DAYS_SHORT[e.day_of_week]} {e.start_time}–{e.end_time} • {_TYPE_UA[e.lesson_type]} • "
                    f"корп. {e.building or '—'} {e.room} • {parity_ua} • впевненість {int(e.confidence * 100)}%"
                ),
                confidence=e.confidence,
            ):
                queued += 1

        for ls in parsed.one_offs:
            if self._enqueue(
                external_id=f"du:event:{ls.lesson_date.isoformat()}:{ls.start_time}:{_slug(ls.subject)}",
                entity_type="calendar_event",
                title=f"Разова пара {ls.lesson_date.strftime('%d.%m')}: {ls.subject} ({_TYPE_UA[ls.lesson_type]})",
                payload={
                    "subject_name": ls.subject,
                    "title": f"{ls.subject} ({_TYPE_UA[ls.lesson_type]})",
                    "event_type": "replacement",
                    "event_date": ls.lesson_date.isoformat(),
                    "start_time": ls.start_time,
                    "end_time": ls.end_time,
                    "location": f"корп. {ls.building} {ls.room}".strip(),
                    "description": f"Викладач: {ls.teacher}" if ls.teacher else "",
                },
                diff_summary=(
                    f"{ls.lesson_date.strftime('%d.%m')} ({_DAYS_SHORT[ls.day_of_week]}) "
                    f"{ls.start_time}–{ls.end_time} • відхилення від регулярного розкладу • впевненість 70%"
                ),
                confidence=0.7,
            ):
                queued += 1

        if parsed.anchor_date is not None:
            anchor_iso = parsed.anchor_date.isoformat()
            current = self.academic_repo.get_setting("parity_anchor_date", "")
            if current != anchor_iso and self._enqueue(
                external_id=f"du:setting:parity_anchor:{anchor_iso}",
                entity_type="setting",
                title=f"Опорна дата 1-го тижня за порталом: {anchor_iso}",
                payload={"key": "parity_anchor_date", "value": anchor_iso},
                diff_summary=f"Було: {current or 'не задано'} → стане: {anchor_iso}",
                confidence=0.95,
            ):
                queued += 1

        self.state.record_result(CONNECTOR_ID, "ok", found=queued)
        log.info("digital_university: lessons=%s queued=%s skipped=%s", parsed.lessons_total, queued, skipped)
        return {
            "queued": queued,
            "skipped": skipped,
            "lessons": parsed.lessons_total,
            "group": parsed.group,
            "message": (
                f"Розклад розпізнано (група {parsed.group or '—'}). Нових змін у черзі: {queued}, "
                f"уже є в розкладі або в черзі: {skipped}."
            ),
        }

    def _enqueue(
        self,
        external_id: str,
        entity_type: str,
        title: str,
        payload: Dict[str, Any],
        diff_summary: str,
        confidence: float,
    ) -> bool:
        return self.sync_repo.enqueue_agent_change(
            source=CONNECTOR_ID,
            external_id=external_id,
            entity_type=entity_type,
            title=title,
            payload=payload,
            diff_summary=diff_summary,
            confidence=confidence,
        )
