"""Test fumée UI — construit toutes les vues en mode offscreen (sans interaction)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    import app.config as cfg
    tmp = Path(tempfile.mkdtemp(prefix="gest_ui_test_"))
    cfg.DATA_DIR = tmp
    cfg.BACKUP_DIR = tmp / "backups"
    cfg.DB_PATH = tmp / "test.db"
    cfg.EXPORT_DIR = tmp / "exports"
    cfg.LOG_DIR = tmp / "logs"
    cfg.ensure_directories()

    from app.db import database as db
    db._local.conn = None
    from app.db.database import init_database
    init_database()

    from app.services import user_service, transaction_service, auth_service
    user_service.ensure_super_admin()
    admin = auth_service.login("admin", "admin123")
    cais = user_service.create_user("c1", "p", "Caissier Test", "caissier")
    transaction_service.create_transaction("MAT-1", "700", "depot", 5000, cais)
    transaction_service.create_transaction("MAT-1", "700", "retrait", 1000, cais)

    from PySide6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication(sys.argv)
    from app.ui.style import QSS
    qapp.setStyleSheet(QSS)

    from app.ui.login_window import LoginWindow
    from app.ui.main_window import MainWindow

    # Construire la fenêtre principale en tant que super-admin (toutes les vues)
    win = MainWindow(admin)
    win.show()
    print("OK MainWindow construite (super_admin) — vues :", list(win.views.keys()))

    # Rafraîchir chaque vue
    for key, view in win.views.items():
        if hasattr(view, "refresh"):
            view.refresh()
    print("OK toutes les vues rafraîchies")

    # Construire aussi en tant que caissier (menu restreint)
    win2 = MainWindow(cais)
    print("OK MainWindow construite (caissier) — entrées nav :", win2.nav_keys)

    # Login window
    lw = LoginWindow()
    print("OK LoginWindow construite")

    qapp.processEvents()
    print("\nTest UI OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
