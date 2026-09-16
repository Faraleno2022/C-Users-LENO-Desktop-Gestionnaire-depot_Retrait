"""Vue Caisse : journal des entrées / sorties et solde progressif."""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.cash_entry import CashEntry
from app.models.user import User
from app.services import cash_service
from app.utils.helpers import format_money, parse_money
from server.sync.business_rules import business_day

COLS = ["Date", "Libellé", "Entrées", "Sorties", "Solde progressif", "Agent", "Sync"]


class CashView(QWidget):
    def __init__(self, agent: User, on_changed: Optional[Callable] = None) -> None:
        super().__init__()
        self.agent = agent
        self.on_changed = on_changed
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("Caisse")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title)

        self.balance_label = QLabel("Solde de la caisse : —")
        self.balance_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(self.balance_label)

        self.totals_label = QLabel()
        self.totals_label.setStyleSheet("color: #6b7280; font-weight: 600;")
        layout.addWidget(self.totals_label)

        # --- Saisie d'une écriture --------------------------------------
        form_card = QFrame()
        form_card.setProperty("class", "card")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(20, 20, 20, 20)
        form_layout.setSpacing(10)

        form_title = QLabel("Nouvelle écriture")
        form_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        form_layout.addWidget(form_title)

        sens_box = QHBoxLayout()
        self.entree_radio = QRadioButton("Entrée")
        self.sortie_radio = QRadioButton("Sortie")
        self.sortie_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.entree_radio)
        group.addButton(self.sortie_radio)
        sens_box.addWidget(self.entree_radio)
        sens_box.addWidget(self.sortie_radio)
        sens_box.addStretch()
        form_layout.addLayout(sens_box)

        grid = QFormLayout()
        grid.setLabelAlignment(Qt.AlignLeft)
        grid.setSpacing(10)
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText(business_day())
        self.libelle_edit = QLineEdit()
        self.libelle_edit.setPlaceholderText("ex : versement à la banque")
        self.montant_edit = QLineEdit()
        self.montant_edit.setPlaceholderText("0")
        grid.addRow("Date", self.date_edit)
        grid.addRow("Libellé *", self.libelle_edit)
        grid.addRow("Montant *", self.montant_edit)
        form_layout.addLayout(grid)

        self.hint_label = QLabel(
            "Les ventes encaissées entrent automatiquement dans la caisse. "
            "Cette saisie sert aux versements, achats et autres mouvements d'espèces."
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #6b7280;")
        form_layout.addWidget(self.hint_label)

        btn_row = QHBoxLayout()
        validate_btn = QPushButton("Enregistrer l'écriture")
        validate_btn.setProperty("class", "success")
        validate_btn.clicked.connect(self._validate)
        self.opening_btn = QPushButton("Ouvrir la caisse (solde initial)")
        self.opening_btn.setProperty("class", "secondary")
        self.opening_btn.clicked.connect(self._open_register)
        self.delete_btn = QPushButton("Annuler l'écriture sélectionnée")
        self.delete_btn.setProperty("class", "secondary")
        self.delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(validate_btn)
        btn_row.addWidget(self.opening_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.delete_btn)
        form_layout.addLayout(btn_row)
        layout.addWidget(form_card)

        # --- Journal ----------------------------------------------------
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

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        entries = cash_service.list_entries()
        entrees, sorties, _ = cash_service.totals(entries)
        balance = cash_service.get_balance()
        self.balance_label.setText(f"Solde de la caisse : {format_money(balance)}")
        self.totals_label.setText(
            f"Entrées : {format_money(entrees)} · Sorties : {format_money(sorties)} · "
            f"{len(entries)} écriture(s)"
        )
        self.opening_btn.setEnabled(cash_service.get_opening() is None)
        self._render_rows(entries)

    def _render_rows(self, entries: List[CashEntry]) -> None:
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = [
                entry.date,
                entry.libelle,
                format_money(entry.entree) if entry.entree else "",
                format_money(entry.sortie) if entry.sortie else "",
                format_money(entry.solde_progressif),
                entry.agent_nom,
                entry.sync_status,
            ]
            for col, value in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(value))
            color = QColor("#dcfce7") if entry.entree else QColor("#fee2e2")
            if entry.source == "ouverture":
                color = QColor("#e0e7ff")
            for col in range(self.table.columnCount()):
                self.table.item(row, col).setBackground(color)
            self.table.item(row, 0).setData(Qt.UserRole, entry.id)
            self.table.item(row, 1).setData(Qt.UserRole, entry.source)

    # ------------------------------------------------------------- actions
    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None
        return (self.table.item(row, 0).data(Qt.UserRole),
                self.table.item(row, 1).data(Qt.UserRole))

    def _validate(self) -> None:
        try:
            montant = parse_money(self.montant_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Montant invalide", str(exc))
            return
        sens = "entree" if self.entree_radio.isChecked() else "sortie"
        try:
            cash_service.create_entry(
                self.libelle_edit.text(), self.agent,
                entree=montant if sens == "entree" else 0,
                sortie=montant if sens == "sortie" else 0,
                date=self.date_edit.text(),
            )
        except cash_service.CashError as exc:
            QMessageBox.warning(self, "Écriture refusée", str(exc))
            return
        self._clear()
        self.refresh()
        if self.on_changed:
            self.on_changed()

    def _open_register(self) -> None:
        try:
            montant = parse_money(self.montant_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Montant invalide", str(exc))
            return
        libelle = self.libelle_edit.text().strip() or "Solde initial"
        try:
            cash_service.create_opening(
                montant, self.agent, date=self.date_edit.text(), libelle=libelle
            )
        except cash_service.CashError as exc:
            QMessageBox.warning(self, "Ouverture refusée", str(exc))
            return
        self._clear()
        self.refresh()
        if self.on_changed:
            self.on_changed()

    def _delete_selected(self) -> None:
        entry_id, source = self._selected()
        if entry_id is None:
            QMessageBox.information(self, "Caisse", "Sélectionnez d'abord une écriture.")
            return
        if source == "vente":
            QMessageBox.warning(
                self, "Écriture protégée",
                "Cet encaissement suit sa vente : annulez la vente pour le retirer.",
            )
            return
        confirm = QMessageBox.question(
            self, "Annuler l'écriture",
            "Annuler cette écriture ? Le solde progressif sera recalculé.",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            cash_service.delete_entry(entry_id, self.agent)
        except cash_service.CashError as exc:
            QMessageBox.warning(self, "Annulation refusée", str(exc))
            return
        self.refresh()
        if self.on_changed:
            self.on_changed()

    def _clear(self) -> None:
        self.date_edit.clear()
        self.libelle_edit.clear()
        self.montant_edit.clear()
