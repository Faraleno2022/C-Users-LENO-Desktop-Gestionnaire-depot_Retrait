"""Gestion des utilisateurs (caissiers, superviseurs)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import ROLES, ROLE_LABELS
from app.models.user import User
from app.services import user_service
from app.ui.widgets.dialogs import access_denied, confirm, error, info


COLS = ["ID", "Identifiant", "Nom complet", "Matricule", "Téléphone", "Rôle", "Statut"]


class UserFormDialog(QDialog):
    def __init__(self, parent, user: User = None, allow_admin_role: bool = False) -> None:
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Modifier l'utilisateur" if user else "Nouvel utilisateur")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)

        self.identifiant_edit = QLineEdit(user.identifiant if user else "")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Vide = inchangé" if user else "")
        self.nom_edit = QLineEdit(user.nom_complet if user else "")
        self.matricule_edit = QLineEdit(user.matricule if user and user.matricule else "")
        self.telephone_edit = QLineEdit(user.telephone if user and user.telephone else "")

        self.role_combo = QComboBox()
        for r in ROLES:
            if r in ("admin", "super_admin") and not allow_admin_role:
                continue
            self.role_combo.addItem(ROLE_LABELS[r], r)
        if user:
            idx = self.role_combo.findData(user.role)
            if idx >= 0:
                self.role_combo.setCurrentIndex(idx)

        self.actif_check = QCheckBox("Actif")
        self.actif_check.setChecked(user.actif if user else True)

        layout.addRow("Identifiant *", self.identifiant_edit)
        layout.addRow("Mot de passe *" if not user else "Mot de passe", self.password_edit)
        layout.addRow("Nom complet *", self.nom_edit)
        layout.addRow("Matricule", self.matricule_edit)
        layout.addRow("Téléphone", self.telephone_edit)
        layout.addRow("Rôle *", self.role_combo)
        layout.addRow("", self.actif_check)

        if user:
            self.identifiant_edit.setReadOnly(True)
            self.identifiant_edit.setStyleSheet("background: #f3f4f6;")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def data(self) -> dict:
        return {
            "identifiant": self.identifiant_edit.text().strip(),
            "password": self.password_edit.text(),
            "nom_complet": self.nom_edit.text().strip(),
            "matricule": self.matricule_edit.text().strip(),
            "telephone": self.telephone_edit.text().strip(),
            "role": self.role_combo.currentData(),
            "actif": self.actif_check.isChecked(),
        }


class UsersView(QWidget):
    ALLOW_ADMIN_ROLE = False  # n'autorise pas la création d'admin ici

    def __init__(self, current_user: User) -> None:
        super().__init__()
        self.current_user = current_user
        self._build_ui()

    def _filter_roles(self):
        """Rôles affichés dans cette vue (gestion des non-admins)."""
        return ("caissier", "superviseur")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Rechercher par nom ou identifiant…")
        self.search_edit.textChanged.connect(self.refresh)
        self.role_filter = QComboBox()
        self.role_filter.addItem("Tous rôles", None)
        for r in self._filter_roles():
            self.role_filter.addItem(ROLE_LABELS[r], r)
        self.role_filter.currentIndexChanged.connect(self.refresh)

        add_btn = QPushButton("+ Nouvel utilisateur")
        add_btn.setProperty("class", "success")
        add_btn.clicked.connect(self._create)
        edit_btn = QPushButton("Modifier")
        edit_btn.clicked.connect(self._edit_selected)
        reset_btn = QPushButton("Réinitialiser mot de passe")
        reset_btn.setProperty("class", "secondary")
        reset_btn.clicked.connect(self._reset_password)
        toggle_btn = QPushButton("Activer/Désactiver")
        toggle_btn.setProperty("class", "secondary")
        toggle_btn.clicked.connect(self._toggle_active)
        delete_btn = QPushButton("Supprimer")
        delete_btn.setProperty("class", "danger")
        delete_btn.clicked.connect(self._delete_selected)

        bar.addWidget(self.search_edit)
        bar.addWidget(self.role_filter)
        bar.addStretch()
        bar.addWidget(add_btn)
        bar.addWidget(edit_btn)
        bar.addWidget(reset_btn)
        bar.addWidget(toggle_btn)
        bar.addWidget(delete_btn)
        layout.addLayout(bar)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        layout.addWidget(self.table, 1)
        self.refresh()

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        role = self.role_filter.currentData()
        query = self.search_edit.text().strip().lower()
        if role is None:
            users = [u for u in user_service.list_users() if u.role in self._filter_roles()]
        else:
            users = user_service.list_users(role=role)
        if query:
            users = [
                u for u in users
                if query in u.identifiant.lower() or query in (u.nom_complet or "").lower()
            ]
        self.table.setRowCount(0)
        for u in users:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = [
                str(u.id),
                u.identifiant,
                u.nom_complet,
                u.matricule or "",
                u.telephone or "",
                ROLE_LABELS.get(u.role, u.role),
                "Actif" if u.actif else "Inactif",
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(val)
                self.table.setItem(row, col, item)
            self.table.item(row, 0).setData(Qt.UserRole, u.id)

    def _selected_user_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return int(item.data(Qt.UserRole))

    # ------------------------------------------------------------- actions
    def _require_admin(self) -> bool:
        if not self.current_user.is_admin():
            access_denied(self)
            return False
        return True

    def _create(self) -> None:
        if not self._require_admin():
            return
        dlg = UserFormDialog(self, allow_admin_role=self.ALLOW_ADMIN_ROLE)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        try:
            user_service.create_user(
                identifiant=d["identifiant"],
                password=d["password"],
                nom_complet=d["nom_complet"],
                role=d["role"],
                matricule=d["matricule"],
                telephone=d["telephone"],
                actif=d["actif"],
            )
        except user_service.UserServiceError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()

    def _edit_selected(self) -> None:
        if not self._require_admin():
            return
        uid = self._selected_user_id()
        if uid is None:
            info(self, "Sélection", "Sélectionnez un utilisateur.")
            return
        user = user_service.get_user(uid)
        if user is None:
            return
        dlg = UserFormDialog(self, user=user, allow_admin_role=self.ALLOW_ADMIN_ROLE)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        try:
            user_service.update_user(
                user_id=uid,
                nom_complet=d["nom_complet"],
                matricule=d["matricule"],
                telephone=d["telephone"],
                role=d["role"],
                actif=d["actif"],
            )
            if d["password"]:
                user_service.reset_password(uid, d["password"])
        except user_service.UserServiceError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()

    def _reset_password(self) -> None:
        if not self._require_admin():
            return
        uid = self._selected_user_id()
        if uid is None:
            info(self, "Sélection", "Sélectionnez un utilisateur.")
            return
        pwd, ok = QInputDialog.getText(
            self, "Réinitialisation", "Nouveau mot de passe :", QLineEdit.Password
        )
        if not ok or not pwd:
            return
        try:
            user_service.reset_password(uid, pwd)
        except user_service.UserServiceError as e:
            error(self, "Erreur", str(e))
            return
        info(self, "Succès", "Mot de passe réinitialisé.")

    def _toggle_active(self) -> None:
        if not self._require_admin():
            return
        uid = self._selected_user_id()
        if uid is None:
            info(self, "Sélection", "Sélectionnez un utilisateur.")
            return
        user = user_service.get_user(uid)
        if user is None:
            return
        try:
            user_service.update_user(user_id=uid, actif=not user.actif)
        except user_service.UserServiceError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()

    def _delete_selected(self) -> None:
        if not self._require_admin():
            return
        uid = self._selected_user_id()
        if uid is None:
            info(self, "Sélection", "Sélectionnez un utilisateur.")
            return
        if uid == self.current_user.id:
            error(self, "Refusé", "Vous ne pouvez pas supprimer votre propre compte.")
            return
        if not confirm(self, "Supprimer", "Confirmer la suppression de cet utilisateur ?"):
            return
        try:
            user_service.delete_user(uid)
        except user_service.UserServiceError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()
