from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol
from core.exceptions import IntegrationSyncError


class ChangeStagingPort(Protocol):
    def stage_change(self, source: str, entity_type: str, external_id: str, payload: dict[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class ClassroomSyncAdapter:
    service: Any  # googleapiclient.discovery.Resource
    staging: ChangeStagingPort

    def sync_courses_and_work(self) -> int:
        staged_count = 0
        try:
            for course in self._paginate(self.service.courses().list, "courses", courseStates=["ACTIVE"]):
                self.staging.stage_change("google_classroom", "subject", course["id"], course)
                staged_count += 1
                for work in self._paginate(
                    self.service.courses().courseWork().list, "courseWork", courseId=course["id"]
                ):
                    self.staging.stage_change("google_classroom", "task", work["id"], work)
                    staged_count += 1
        except Exception as exc:
            raise IntegrationSyncError(f"Збій синхронізації Google Classroom: {exc}") from exc
        return staged_count

    @staticmethod
    def _paginate(endpoint: Any, items_key: str, **kwargs: Any) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            response = endpoint(pageToken=page_token, **kwargs).execute()
            results.extend(response.get(items_key, []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return results