"""Gestion des clients : fiches par matricule, solde et historique."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.user import User
from app.services import client_service
from app.utils.helpers import format_money
from app.ui.widgets.dialogs import access_denied, confirm, error, info


CLIENT_COLS = ["Matricule", "Nom", "Téléphone", "Solde", "Opérations", "Fiche"]
OP_COLS = ["Date", "Type", "Détail", "Montant", "Solde après", "Agent"]


class ClientFormDialog(QDialog):
    def __init__(self, parent, client=None, matricule: str = "") -> None:
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("Modifier la fiche client" if client else "Nouvelle fiche client")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)

        self.mat_edit = QLineEdit(client.matricule if client else matricule)
        self.nom_edit = QLineEdit(client.nom if client and client.nom else "")
        self.tel_edit = QLineEdit(client.telephone if client and client.telephone else "")
        self.note_edit = QTextEdit(client.note if client and client.note else "")
        self.note_edit.setMaximumHeight(80)

        layout.addRow("Matricule *", self.mat_edit)
        layout.addRow("Nom", self.nom_edit)
        layout.addRow("Téléphone", self.tel_edit)
        layout.addRow("Note", self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def data(self) -> dict:
        return {
            "matricule": self.mat_edit.text().strip(),
            "nom": self.nom_edit.text().strip(),
            "telephone": self.tel_edit.text().strip(),
            "note": self.note_edit.toPlainText().strip(),
        }


class ClientDetailDialog(QDialog):
    def __init__(self, parent, matricule: str) -> None:
        super().__init__(parent)
        self.matricule = matricule
        self.setWindowTitle(f"Client — {matricule}")
        self.setMinimumSize(720, 520)
        layout = QVBoxLayout(self)

        client = client_service.get_client_by_matricule(matricule)
        from app.services import transaction_service
        solde = transaction_service.get_matricule_balance(matricule)

        nom = (client.nom if client and client.nom else "—")
        tel = (client.telephone if client and client.telephone else "—")
        head = QLabel(
            f"<b>Matricule :</b> {matricule}&nbsp;&nbsp;&nbsp;"
            f"<b>Nom :</b> {nom}&nbsp;&nbsp;&nbsp;"
            f"<b>Téléphone :</b> {tel}"
        )
        head.setTextFormat(Qt.RichText)
        layout.addWidget(head)

        solde_label = QLabel(f"Solde actuel : <b>{format_money(solde)}</b>")
        solde_label.setTextFormat(Qt.RichText)
        solde_label.setStyleSheet("font-size: 16px; padding: 6px 0;")
        layout.addWidget(solde_label)

        if client and client.note:
            note = QLabel(f"<i>Note : {client.note}</i>")
            note.setTextFormat(Qt.RichText)
            note.setWordWrap(True)
            layout.addWidget(note)

        layout.addWidget(QLabel("Historique des opérations"))
        self.table = QTableWidget(0, len(OP_COLS))
        self.table.setHorizontalHeaderLabels(OP_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        layout.addWidget(self.table, 1)

        ops = client_service.client_operations(matricule)
        for op in ops:
            row = self.table.rowCount()
            self.table.insertRow(row)
            montant_txt = ("+" if op.montant >= 0 else "") + format_money(op.montant)
            cells = [op.date, op.categorie, op.detail, montant_txt,
                     format_money(op.solde_apres), op.agent]
            for col, val in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(str(val)))
            if op.categorie == "Dépôt":
                color = QColor("#dcfce7")
            elif op.categorie == "Retrait":
                color = QColor("#fee2e2")
            else:
                color = QColor("#e0e7ff")
            for c in range(self.table.columnCount()):
                self.table.item(row, c).setBackground(color)

        if not ops:
            layout.addWidget(QLabel("Aucune opération enregistrée pour ce client."))

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)


class ClientsView(QWidget):
    def __init__(self, current_user: User, on_changed: Optional[Callable] = None) -> None:
        super().__init__()
        self.current_user = current_user
        self.on_changed = on_changed
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Rechercher par matricule ou nom…")
        self.search_edit.setMinimumWidth(220)
        self.search_edit.setMaximumWidth(380)
        self.search_edit.textChanged.connect(self.refresh)
        add_btn = QPushButton("+ Nouvelle fiche")
        add_btn.setProperty("class", "success")
        add_btn.clicked.connect(self._create)
        edit_btn = QPushButton("Modifier la fiche")
        edit_btn.clicked.connect(self._edit)
        detail_btn = QPushButton("Voir l'historique")
        detail_btn.setProperty("class", "secondary")
        detail_btn.clicked.connect(self._detail)
        delete_btn = QPushButton("Supprimer la fiche")
        delete_btn.setProperty("class", "danger")
        delete_btn.clicked.connect(self._delete)
        bar.addWidget(self.search_edit)
        bar.addStretch()
        bar.addWidget(add_btn)
        bar.addWidget(edit_btn)
        bar.addWidget(detail_btn)
        bar.addWidget(delete_btn)
        # Scroll horizontal pour la barre d'actions sur fenêtre étroite
        bar_widget = QWidget()
        bar_widget.setLayout(bar)
        bar_widget.setMinimumWidth(720)
        bar_scroll = QScrollArea()
        bar_scroll.setWidgetResizable(True)
        bar_scroll.setFrameShape(QFrame.NoFrame)
        bar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        bar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bar_scroll.setFixedHeight(56)
        bar_scroll.setWidget(bar_widget)
        layout.addWidget(bar_scroll)

        self.table = QTableWidget(0, len(CLIENT_COLS))
        self.table.setHorizontalHeaderLabels(CLIENT_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.doubleClicked.connect(self._detail)
        layout.addWidget(self.table, 1)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("color: #6b7280;")
        layout.addWidget(self.summary_label)

        self.refresh()

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        query = self.search_edit.text().strip() or None
        clients = client_service.list_clients(query=query)
        self.table.setRowCount(0)
        total_solde = 0.0
        for c in clients:
            total_solde += c.solde
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = [
                c.matricule,
                c.nom or "—",
                c.telephone or "—",
                format_money(c.solde),
                str(c.nb_operations),
                "Oui" if c.enregistre else "—",
            ]
            for col, val in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(val))
            self.table.item(row, 0).setData(Qt.UserRole, c.matricule)
            self.table.item(row, 0).setData(Qt.UserRole + 1, c.client_id)
            if c.solde < 0:
                color = QColor("#fee2e2")
            elif not c.enregistre:
                color = QColor("#fef9c3")
            else:
                color = QColor("#ffffff")
            for col in range(self.table.columnCount()):
                self.table.item(row, col).setBackground(color)
        self.summary_label.setText(
            f"{len(clients)} client(s) — Solde cumulé : {format_money(total_solde)}"
        )

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole), item.data(Qt.UserRole + 1)

    # ------------------------------------------------------------- actions
    def _create(self) -> None:
        dlg = ClientFormDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        try:
            client_service.create_client(
                matricule=d["matricule"], nom=d["nom"],
                telephone=d["telephone"], note=d["note"],
            )
        except client_service.ClientError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()
        if self.on_changed:
            self.on_changed()

    def _edit(self) -> None:
        matricule, client_id = self._selected()
        if matricule is None:
            info(self, "Sélection", "Sélectionnez un client.")
            return
        client = client_service.get_client_by_matricule(matricule)
        if client is None:
            # Matricule connu via transactions mais pas encore de fiche : on la crée
            dlg = ClientFormDialog(self, matricule=matricule)
        else:
            dlg = ClientFormDialog(self, client=client)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        try:
            if client is None:
                client_service.create_client(
                    matricule=d["matricule"], nom=d["nom"],
                    telephone=d["telephone"], note=d["note"],
                )
            else:
                client_service.update_client(
                    client.id, nom=d["nom"], telephone=d["telephone"],
                    note=d["note"], matricule=d["matricule"],
                )
        except client_service.ClientError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()
        if self.on_changed:
            self.on_changed()

    def _detail(self) -> None:
        matricule, _ = self._selected()
        if matricule is None:
            info(self, "Sélection", "Sélectionnez un client.")
            return
        ClientDetailDialog(self, matricule).exec()

    def _delete(self) -> None:
        if not self.current_user.is_admin():
            access_denied(self)
            return
        matricule, client_id = self._selected()
        if matricule is None:
            info(self, "Sélection", "Sélectionnez un client.")
            return
        if client_id is None:
            info(self, "Fiche", "Ce matricule n'a pas de fiche enregistrée à supprimer.")
            return
        if not confirm(
            self, "Supprimer la fiche",
            "Supprimer la fiche de ce client ? Les transactions et ventes liées "
            "au matricule sont conservées.",
        ):
            return
        try:
            client_service.delete_client(client_id)
        except client_service.ClientError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()
        if self.on_changed:
            self.on_changed()
