from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config.defaults import CREDENTIALS_DIR
from core.repositories import AcademicRepository, SyncAndFileRepository

# Мінімально необхідні read-only права для безпечної синхронізації
CLASSROOM_SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
]
KEYRING_SERVICE = "KAIStudentDashboard_GoogleOAuth"
KEYRING_USERNAME = "classroom_token_json"


class GoogleClassroomConnector:
    """
    Офіційний конектор Google Classroom API із OAuth 2.0 Desktop flow,
    безпечним зберіганням refresh-токена у Windows Credential Manager (keyring)
    та записом усіх вхідних даних у чергу підтвердження AgentChange.
    """

    def __init__(
        self,
        academic_repo: AcademicRepository,
        sync_repo: SyncAndFileRepository,
        client_secret_path: Optional[Path] = None,
    ) -> None:
        self.academic_repo = academic_repo
        self.sync_repo = sync_repo
        self.client_secret_path = client_secret_path or (CREDENTIALS_DIR / "credentials.json")

    def has_client_secret(self) -> bool:
        return self.client_secret_path.exists()

    def _load_credentials(self) -> Optional[Credentials]:
        try:
            raw_token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception:  # noqa: BLE001
            raw_token = None

        creds: Optional[Credentials] = None
        if raw_token:
            creds = Credentials.from_authorized_user_info(json.loads(raw_token), CLASSROOM_SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._save_credentials(creds)
            return creds

        if creds and creds.valid:
            return creds

        if not self.has_client_secret():
            return None

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secret_path), CLASSROOM_SCOPES
        )
        creds = flow.run_local_server(port=0)
        self._save_credentials(creds)
        return creds

    @staticmethod
    def _save_credentials(creds: Credentials) -> None:
        try:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, creds.to_json())
        except Exception:  # noqa: BLE001
            pass

    def sync_to_approval_queue(self) -> Dict[str, Any]:
        """
        Отримує курси та завдання з Google Classroom і складає їх у чергу підтвердження.
        Якщо credentials.json відсутній — завантажує реалістичний пакет демонстраційних подій КАІ.
        """
        creds = self._load_credentials()
        if creds is None:
            queued = self._enqueue_demo_classroom_items()
            return {
                "mode": "demo_offline",
                "queued_count": queued,
                "message": (
                    f"credentials.json не знайдено у {self.client_secret_path}. "
                    f"Додано {queued} демонстраційні зміни Classroom у чергу підтвердження."
                ),
            }

        service = build("classroom", "v1", credentials=creds, cache_discovery=False)
        courses_resp = service.courses().list(courseStates=["ACTIVE"]).execute()
        courses = courses_resp.get("courses", [])
        subjects = self.academic_repo.list_subjects()
        queued = 0

        for course in courses:
            c_id = course["id"]
            c_name = course.get("name", "Курс Classroom")
            matched_subj_id = self._match_subject_id(c_name, subjects)

            cw_resp = service.courses().courseWork().list(courseId=c_id).execute()
            for work in cw_resp.get("courseWork", []):
                w_id = work["id"]
                title = work.get("title", "Завдання Classroom")
                due_obj = work.get("dueDate")
                due_iso = None
                if due_obj:
                    due_iso = f"{due_obj['year']:04d}-{due_obj['month']:02d}-{due_obj['day']:02d}"

                added = self.sync_repo.enqueue_agent_change(
                    source="google_classroom",
                    external_id=f"cw_{c_id}_{w_id}",
                    entity_type="task",
                    title=f"[{c_name}] {title}",
                    payload={
                        "title": title,
                        "subject_id": matched_subj_id,
                        "description": work.get("description", ""),
                        "task_type": "lab" if "лаб" in title.lower() else "homework",
                        "priority": 2,
                        "due_date": due_iso,
                    },
                    diff_summary=f"Курс: {c_name} | Дедлайн: {due_iso or 'не вказано'}",
                )
                if added:
                    queued += 1

        return {
            "mode": "oauth_live",
            "queued_count": queued,
            "message": f"Синхронізацію Google Classroom завершено. Нових змін у черзі: {queued}.",
        }

    @staticmethod
    def _match_subject_id(course_name: str, subjects: List[Dict[str, Any]]) -> Optional[int]:
        lower = course_name.lower()
        for subj in subjects:
            if subj["name"].lower()[:6] in lower:
                return int(subj["id"])
        return int(subjects[0]["id"]) if subjects else None

    def _enqueue_demo_classroom_items(self) -> int:
        subjects = self.academic_repo.list_subjects()
        subj_id = int(subjects[0]["id"]) if subjects else None
        due_soon = (date.today() + timedelta(days=2)).isoformat()
        count = 0

        if self.sync_repo.enqueue_agent_change(
            source="google_classroom",
            external_id=f"demo_cw_{date.today().isoformat()}_1",
            entity_type="task",
            title="Лабораторна робота №4: Дослідження коливань маятника",
            payload={
                "title": "Лабораторна робота №4: Дослідження коливань маятника",
                "subject_id": subj_id,
                "description": "Оформити протокол вимірювань та розрахунок похибок за методичкою КАІ.",
                "task_type": "lab",
                "priority": 1,
                "due_date": due_soon,
            },
            diff_summary=f"Нове завдання з Google Classroom | Дедлайн: {due_soon}",
        ):
            count += 1

        if subjects:
            comps = self.academic_repo.list_rso_components(int(subjects[0]["id"]))
            ungraded = [c for c in comps if c.get("earned_score") is None]
            if ungraded:
                target_comp = ungraded[0]
                if self.sync_repo.enqueue_agent_change(
                    source="google_classroom",
                    external_id=f"demo_grade_{date.today().isoformat()}_{target_comp['id']}",
                    entity_type="grade",
                    title=f"Оцінка: {target_comp['title']} → {target_comp['max_score']} балів",
                    payload={
                        "rso_component_id": int(target_comp["id"]),
                        "score": float(target_comp["max_score"]),
                    },
                    diff_summary=f"Викладач виставив {target_comp['max_score']} з {target_comp['max_score']} балів",
                ):
                    count += 1
        return count