import sys
from PySide6.QtWidgets import QApplication
from app.container import AppContainer
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("KAI Student Dashboard")

    container = AppContainer.build()
    # Схема БД має бути актуальною до створення будь-яких репозиторіїв та сторінок.
    container.db.apply_migrations()

    window = MainWindow(container=container)  # Передаємо єдиний контейнер замість набору репозиторіїв
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())