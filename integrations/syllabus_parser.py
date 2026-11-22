from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from infrastructure.files.file_indexer import extract_text_from_file


class SyllabusParser:
    """
    Детермінований парсер робочих програм / силабусів КАІ (PDF / DOCX).
    Витягує компоненти оцінювання (лабораторні, модулі, РГР, іспит) у вигляді
    чернетки для черги підтвердження людиною (Human-in-the-loop).
    """

    COMPONENT_PATTERNS = [
        (r"(?:лабораторн[аіої]|lab)\s*(?:робот[аи])?\s*№?\s*(\d+)", "lab", "Лабораторна робота"),
        (r"(?:модульн[аіої]|мкр|module)\s*(?:контрольн[аіої])?\s*№?\s*(\d+)", "module", "Модульна контрольна робота"),
        (r"(?:ргр|розрахунково-графічн[аіої])\s*№?\s*(\d+)?", "rgr", "Розрахунково-графічна робота"),
        (r"(?:іспит|екзамен|exam)", "exam", "Підсумковий іспит"),
    ]

    @classmethod
    def parse_syllabus_file(cls, file_path: Path, subject_id: int) -> Dict[str, Any]:
        raw_text = extract_text_from_file(file_path)
        return cls.parse_syllabus_text(raw_text, subject_id, source_name=file_path.name)

    @classmethod
    def parse_syllabus_text(
        cls, text: str, subject_id: int, source_name: str = "syllabus"
    ) -> Dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        components: List[Dict[str, Any]] = []
        seen_titles: set[str] = set()

        for line in lines:
            lower = line.lower()
            score_match = re.search(r"(\d{1,3}(?:[.,]\d)?)\s*(?:бал|points|б\.)", lower)
            extracted_score = (
                float(score_match.group(1).replace(",", ".")) if score_match else None
            )

            for pattern, comp_type, base_label in cls.COMPONENT_PATTERNS:
                m = re.search(pattern, lower)
                if m:
                    num = m.group(1) if m.lastindex else None
                    title = f"{base_label} №{num}" if num else base_label
                    if title not in seen_titles:
                        seen_titles.add(title)
                        default_max = 40.0 if comp_type == "exam" else (20.0 if comp_type == "module" else 5.0)
                        components.append(
                            {
                                "title": title,
                                "component_type": comp_type,
                                "max_score": extracted_score or default_max,
                            }
                        )
                    break

        # Якщо структура не знайдена автоматично — пропонуємо базовий шаблон РСО КАІ
        if not components:
            components = [
                {"title": "Модульна контрольна робота №1", "component_type": "module", "max_score": 20.0},
                {"title": "Модульна контрольна робота №2", "component_type": "module", "max_score": 20.0},
                {"title": "Лабораторний практикум (сумарно)", "component_type": "lab", "max_score": 20.0},
                {"title": "Підсумковий іспит", "component_type": "exam", "max_score": 40.0},
            ]

        return {
            "subject_id": subject_id,
            "source_file": source_name,
            "components": components,
        }