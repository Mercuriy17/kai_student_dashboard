# Пакет оновлення KAI Student Command Center (етапи 1–3, частково 2)

Застосування (з кореня репозиторію, спершу `git commit` поточного стану):

    python <пакет>/apply_patches.py --dry-run
    python <пакет>/apply_patches.py
    pip install -r requirements.txt
    pytest

Скрипт атомарний (при будь-якому незбігу якоря нічого не змінюється) і робить `*.bak`.
Після запуску можна видалити з `ui/widgets.py` старий клас `KanbanCardWidget` (більше не використовується).
