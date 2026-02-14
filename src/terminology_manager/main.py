from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from terminology_manager.config import AppConfig
from terminology_manager.persistence.database import (
    create_sqlite_engine,
    ensure_data_dir,
    initialize_database,
    make_session_factory,
)
from terminology_manager.services.terminology_service import TerminologyService
from terminology_manager.ui.main_window import MainWindow


def main() -> int:
    config = AppConfig()
    ensure_data_dir(config.database_path)
    engine = create_sqlite_engine(config.database_url)
    initialize_database(engine)
    session_factory = make_session_factory(engine)

    app = QApplication(sys.argv)
    app.setApplicationName(config.app_name)
    app.setStyleSheet(
        """
        QWidget { font-family: 'Segoe UI'; font-size: 12px; }
        QMainWindow { background: #15171A; }
        QLineEdit, QTextEdit, QTreeWidget, QTableWidget, QListWidget, QTextBrowser {
            background: #1F242B; color: #E6EAF0; border: 1px solid #2C3440; border-radius: 6px;
        }
        QPushButton { background: #2563EB; color: #FFFFFF; border-radius: 6px; padding: 6px 10px; }
        QPushButton:hover { background: #1D4ED8; }
        QPushButton:disabled {
            background: #4B5563;
            color: #A3AAB4;
            border: 1px solid #374151;
        }
        QToolBar { background: #111827; color: #E6EAF0; spacing: 6px; }
        QLabel { color: #D1D5DB; }
        QHeaderView::section { background: #111827; color: #E5E7EB; padding: 4px; }
        """
    )

    window = MainWindow(TerminologyService(session_factory))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
