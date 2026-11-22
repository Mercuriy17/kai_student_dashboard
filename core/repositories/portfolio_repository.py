class PortfolioRepository:
    """Репозиторій проєктів R&D лабораторій КАІ (KAI-Ajax, AVIA, MIT UIEL, Huawei) та історії бекапів."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def list_rd_items(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM rd_portfolio_items ORDER BY updated_at DESC, id DESC")

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
        cur = self.db.execute(
            """
            INSERT INTO rd_portfolio_items (
                lab_name, project_title, role_description, tech_stack,
                status, artifact_url, linkedin_draft, start_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, date('now'))
            """,
            (
                lab_name,
                project_title,
                role_description,
                tech_stack,
                status,
                artifact_url,
                linkedin_draft,
            ),
        )
        return int(cur.lastrowid)

    def list_backups(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM backup_history ORDER BY created_at DESC LIMIT 20")