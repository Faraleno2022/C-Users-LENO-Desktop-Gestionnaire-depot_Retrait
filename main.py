"""Point d'entrée — Gestionnaire Dépôt / Retrait."""
from __future__ import annotations

import sys
import traceback

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.config import APP_NAME, ICON_PATH, ORG_NAME, ensure_directories
from app.db.database import init_database
from app.services import backup_service, user_service
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow
from app.ui.style import QSS


def main() -> int:
    ensure_directories()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyleSheet(QSS)

    try:
        init_database()
        user_service.ensure_super_admin()
    except Exception as e:
        traceback.print_exc()
        QMessageBox.critical(None, "Erreur d'initialisation", str(e))
        return 1

    # Sauvegarde planifiée : exécutée au démarrage si la périodicité est échue.
    try:
        created = backup_service.run_auto_backup_if_due()
        if created is not None:
            print(f"Sauvegarde planifiée créée : {created.name}")
    except Exception:
        traceback.print_exc()  # une sauvegarde ratée ne doit pas bloquer l'appli

    while True:
        login = LoginWindow()
        if login.exec() != QDialog.Accepted or login.user is None:
            return 0
        win = MainWindow(login.user)
        win.show()
        app.exec()
        # à la fermeture, on retourne au login (déconnexion)


if __name__ == "__main__":
    sys.exit(main())
