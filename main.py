import sys
from PySide6.QtWidgets import QApplication
from app.container import AppContainer
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("KAI Student Dashboard")

    container = AppContainer.build()
    # Ініціалізація схеми БД через міграції перед стартом UI
    with container.db.transaction() as conn:
        conn.execute("SELECT 1;")

    window = MainWindow(container=container)  # Передаємо єдиний контейнер замість набору репозиторіїв
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())