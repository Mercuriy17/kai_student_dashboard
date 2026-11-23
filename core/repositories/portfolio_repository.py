from __future__ import annotations

from typing import Any, Dict, List

from core.repositories.base import BaseRepository


class PortfolioRepository(BaseRepository):
    def list_rd_items(self) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM rd_portfolio_items ORDER BY updated_at DESC, id DESC")

    def create_rd_item(
        self,
        lab_name: str,
        project_title: str,
        role_description: str,
        tech_stack: str = "",
        status: str = "active",
        artifact_url: str = "",
        linkedin_draft: str = "",
    ) -> int:
        return self._execute(
            """
            INSERT INTO rd_portfolio_items (
                lab_name, project_title, role_description, tech_stack,
                status, artifact_url, linkedin_draft, start_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, date('now'))
            """,
            (lab_name, project_title, role_description, tech_stack, status, artifact_url, linkedin_draft),
        )

    def list_backups(self) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM backup_history ORDER BY created_at DESC LIMIT 20")