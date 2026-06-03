"""Gestion des administrateurs et journal des actions (super_admin uniquement)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import ROLE_LABELS
from app.models.user import User
from app.services import audit_service, user_service
from app.ui.users_view import UserFormDialog
from app.ui.widgets.dialogs import access_denied, confirm, error, info


ADMIN_COLS = ["ID", "Identifiant", "Nom complet", "Rôle", "Statut"]
AUDIT_COLS = ["Date", "Utilisateur", "Action", "Cible", "Détails"]


class AdminsView(QWidget):
    def __init__(self, current_user: User) -> None:
        super().__init__()
        self.current_user = current_user
        self._build_ui()

    def _build_ui(self) -> None:
        if not self.current_user.is_super_admin():
            # Affiche un message d'accès refusé statique
            layout = QVBoxLayout(self)
            lbl = QLabel("Accès refusé. Fonction réservée au super-administrateur.")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #dc2626; font-size: 16px; font-weight: 700;")
            layout.addWidget(lbl)
            return

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.tabs = QTabWidget()

        # --- Admins tab -------------------------------------------------
        admins_widget = QWidget()
        al = QVBoxLayout(admins_widget)
        bar = QHBoxLayout()
        add_btn = QPushButton("+ Nouvel administrateur")
        add_btn.setProperty("class", "success")
        add_btn.clicked.connect(self._create_admin)
        edit_btn = QPushButton("Modifier")
        edit_btn.clicked.connect(self._edit_admin)
        block_btn = QPushButton("Bloquer / Débloquer")
        block_btn.setProperty("class", "secondary")
        block_btn.clicked.connect(self._toggle_block)
        delete_btn = QPushButton("Supprimer")
        delete_btn.setProperty("class", "danger")
        delete_btn.clicked.connect(self._delete_admin)
        bar.addStretch()
        bar.addWidget(add_btn)
        bar.addWidget(edit_btn)
        bar.addWidget(block_btn)
        bar.addWidget(delete_btn)
        al.addLayout(bar)

        self.admin_table = QTableWidget(0, len(ADMIN_COLS))
        self.admin_table.setHorizontalHeaderLabels(ADMIN_COLS)
        self.admin_table.verticalHeader().setVisible(False)
        self.admin_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.admin_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.admin_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.admin_table.horizontalHeader().setStretchLastSection(True)
        self.admin_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        al.addWidget(self.admin_table, 1)

        # --- Audit tab --------------------------------------------------
        audit_widget = QWidget()
        ll = QVBoxLayout(audit_widget)
        audit_bar = QHBoxLayout()
        self.audit_filter = QComboBox()
        self.audit_filter.addItem("Tous les utilisateurs", None)
        audit_bar.addWidget(QLabel("Filtrer par"))
        audit_bar.addWidget(self.audit_filter)
        audit_bar.addStretch()
        refresh_btn = QPushButton("Rafraîchir")
        refresh_btn.setProperty("class", "secondary")
        refresh_btn.clicked.connect(self._refresh_audit)
        audit_bar.addWidget(refresh_btn)
        ll.addLayout(audit_bar)

        self.audit_table = QTableWidget(0, len(AUDIT_COLS))
        self.audit_table.setHorizontalHeaderLabels(AUDIT_COLS)
        self.audit_table.verticalHeader().setVisible(False)
        self.audit_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.audit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.audit_table.horizontalHeader().setStretchLastSection(True)
        self.audit_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        ll.addWidget(self.audit_table, 1)
        self.audit_filter.currentIndexChanged.connect(self._refresh_audit)

        self.tabs.addTab(admins_widget, "Administrateurs")
        self.tabs.addTab(audit_widget, "Journal d'audit")
        layout.addWidget(self.tabs)
        self.refresh()

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        if not self.current_user.is_super_admin():
            return
        self._refresh_admins()
        self._refresh_audit_filter()
        self._refresh_audit()

    def _refresh_admins(self) -> None:
        admins = [u for u in user_service.list_users() if u.role in ("admin", "super_admin")]
        self.admin_table.setRowCount(0)
        for u in admins:
            row = self.admin_table.rowCount()
            self.admin_table.insertRow(row)
            cells = [
                str(u.id),
                u.identifiant,
                u.nom_complet,
                ROLE_LABELS.get(u.role, u.role),
                "Actif" if u.actif else "Bloqué",
            ]
            for col, val in enumerate(cells):
                self.admin_table.setItem(row, col, QTableWidgetItem(val))
            self.admin_table.item(row, 0).setData(Qt.UserRole, u.id)

    def _refresh_audit_filter(self) -> None:
        current = self.audit_filter.currentData()
        self.audit_filter.blockSignals(True)
        self.audit_filter.clear()
        self.audit_filter.addItem("Tous les utilisateurs", None)
        for u in user_service.list_users():
            self.audit_filter.addItem(f"{u.nom_complet} ({u.identifiant})", u.id)
        idx = self.audit_filter.findData(current)
        if idx >= 0:
            self.audit_filter.setCurrentIndex(idx)
        self.audit_filter.blockSignals(False)

    def _refresh_audit(self) -> None:
        user_id = self.audit_filter.currentData()
        logs = audit_service.list_logs(limit=500, user_id=user_id)
        self.audit_table.setRowCount(0)
        for log in logs:
            row = self.audit_table.rowCount()
            self.audit_table.insertRow(row)
            cells = [
                log.created_at,
                log.user_identifiant or "(système)",
                log.action,
                f"{log.target_type or ''} {log.target_id or ''}".strip(),
                log.details or "",
            ]
            for col, val in enumerate(cells):
                self.audit_table.setItem(row, col, QTableWidgetItem(str(val)))

    def _selected_admin_id(self):
        row = self.admin_table.currentRow()
        if row < 0:
            return None
        return int(self.admin_table.item(row, 0).data(Qt.UserRole))

    # ------------------------------------------------------------- actions
    def _create_admin(self) -> None:
        if not self.current_user.is_super_admin():
            access_denied(self)
            return
        dlg = UserFormDialog(self, allow_admin_role=True)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        if d["role"] not in ("admin", "super_admin"):
            error(self, "Refusé", "Cette vue est réservée aux rôles administrateur.")
            return
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

    def _edit_admin(self) -> None:
        uid = self._selected_admin_id()
        if uid is None:
            info(self, "Sélection", "Sélectionnez un administrateur.")
            return
        user = user_service.get_user(uid)
        dlg = UserFormDialog(self, user=user, allow_admin_role=True)
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

    def _toggle_block(self) -> None:
        uid = self._selected_admin_id()
        if uid is None:
            info(self, "Sélection", "Sélectionnez un administrateur.")
            return
        user = user_service.get_user(uid)
        try:
            user_service.update_user(user_id=uid, actif=not user.actif)
        except user_service.UserServiceError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()

    def _delete_admin(self) -> None:
        uid = self._selected_admin_id()
        if uid is None:
            info(self, "Sélection", "Sélectionnez un administrateur.")
            return
        if uid == self.current_user.id:
            error(self, "Refusé", "Vous ne pouvez pas supprimer votre propre compte.")
            return
        if not confirm(self, "Supprimer", "Confirmer la suppression de cet administrateur ?"):
            return
        try:
            user_service.delete_user(uid)
        except user_service.UserServiceError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()
