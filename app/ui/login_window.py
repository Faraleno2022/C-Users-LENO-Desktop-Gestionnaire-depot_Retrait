"""Fenêtre de connexion."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_NAME, APP_VERSION, LOGO_PATH
from app.services import auth_service


class LoginWindow(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Connexion")
        self.setMinimumSize(420, 380)
        self.setModal(True)
        self.user = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(14)

        # Logo EMAB GROUP — même présentation que la page de connexion web
        if LOGO_PATH.exists():
            logo = QLabel()
            pix = QPixmap(str(LOGO_PATH))
            if not pix.isNull():
                logo.setPixmap(pix.scaledToWidth(240, Qt.SmoothTransformation))
            logo.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo)
        else:
            title = QLabel("EMAB GROUP")
            title.setAlignment(Qt.AlignCenter)
            title.setProperty("class", "h1")
            title.setFont(QFont("Segoe UI", 18, QFont.Bold))
            layout.addWidget(title)

        subtitle = QLabel("Connectez-vous avec vos identifiants poste")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setProperty("class", "muted")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        layout.addWidget(QLabel("Identifiant"))
        self.identifiant_edit = QLineEdit()
        self.identifiant_edit.setPlaceholderText("Nom d'utilisateur")
        layout.addWidget(self.identifiant_edit)

        layout.addWidget(QLabel("Mot de passe"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("••••••••")
        self.password_edit.returnPressed.connect(self._attempt_login)
        layout.addWidget(self.password_edit)

        layout.addSpacing(10)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #dc2626; font-weight: 600;")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        login_btn = QPushButton("Se connecter")
        login_btn.clicked.connect(self._attempt_login)
        layout.addWidget(login_btn)

        cancel_btn = QPushButton("Quitter")
        cancel_btn.setProperty("class", "secondary")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        version = QLabel(f"v{APP_VERSION}")
        version.setAlignment(Qt.AlignCenter)
        version.setProperty("class", "muted")
        layout.addStretch()
        layout.addWidget(version)

        self.identifiant_edit.setFocus()

    def _attempt_login(self) -> None:
        identifiant = self.identifiant_edit.text().strip()
        password = self.password_edit.text()
        self.error_label.setVisible(False)
        try:
            user = auth_service.login(identifiant, password)
        except auth_service.AuthError as e:
            self.error_label.setText(str(e))
            self.error_label.setVisible(True)
            self.password_edit.clear()
            self.password_edit.setFocus()
            return
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur inattendue : {e}")
            return
        self.user = user
        self.accept()
