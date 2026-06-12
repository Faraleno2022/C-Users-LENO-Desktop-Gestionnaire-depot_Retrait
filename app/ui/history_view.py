"""Historique des transactions."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import List

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFileDialog,
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
    QVBoxLayout,
    QWidget,
)

from app.config import EXPORT_DIR, PAGE_SIZE
from app.models.user import User
from app.services import transaction_service, user_service
# openpyxl/reportlab sont lourds : importés au moment de l'export (voir _export).
from app.utils.helpers import format_money
from app.ui.widgets.dialogs import access_denied, confirm, error, info


COLS = ["ID", "Date", "Matricule", "Téléphone", "Dépôt", "Retrait", "Solde", "Agent", "Sync"]
EXPORT_HEADERS = COLS


class HistoryView(QWidget):
    def __init__(self, user: User) -> None:
        super().__init__()
        self.user = user
        self.current_page = 0
        self.last_filters: dict = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # --- Filters card ----------------------------------------------
        filter_card = QFrame()
        filter_card.setProperty("class", "card")
        fl = QHBoxLayout(filter_card)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(10)

        self.matricule_filter = QLineEdit()
        self.matricule_filter.setPlaceholderText("Matricule…")
        self.matricule_filter.setMaximumWidth(160)

        self.type_filter = QComboBox()
        self.type_filter.addItem("Tous types", None)
        self.type_filter.addItem("Dépôts", "depot")
        self.type_filter.addItem("Retraits", "retrait")

        self.agent_filter = QComboBox()
        self.agent_filter.addItem("Tous agents", None)
        for u in user_service.list_users():
            self.agent_filter.addItem(u.nom_complet, u.id)

        today = QDate.currentDate()
        self.date_from = QDateEdit(today.addDays(-30))
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_to = QDateEdit(today)
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")

        self.sync_filter = QComboBox()
        self.sync_filter.addItem("Tous sync", None)
        self.sync_filter.addItem("En attente", "pending")
        self.sync_filter.addItem("Synchronisés", "synced")
        self.sync_filter.addItem("Erreur", "error")
        self.sync_filter.addItem("Conflit", "conflict")

        apply_btn = QPushButton("Filtrer")
        apply_btn.clicked.connect(self._apply_filters)
        reset_btn = QPushButton("Réinitialiser")
        reset_btn.setProperty("class", "secondary")
        reset_btn.clicked.connect(self._reset_filters)

        fl.addWidget(QLabel("Matricule"))
        fl.addWidget(self.matricule_filter)
        fl.addWidget(QLabel("Type"))
        fl.addWidget(self.type_filter)
        fl.addWidget(QLabel("Agent"))
        fl.addWidget(self.agent_filter)
        fl.addWidget(QLabel("Du"))
        fl.addWidget(self.date_from)
        fl.addWidget(QLabel("Au"))
        fl.addWidget(self.date_to)
        fl.addWidget(QLabel("Sync"))
        fl.addWidget(self.sync_filter)
        fl.addStretch()
        fl.addWidget(apply_btn)
        fl.addWidget(reset_btn)

        # Scroll horizontal pour ne pas tronquer les filtres sur fenêtre étroite
        filter_card.setMinimumWidth(950)
        filter_scroll = QScrollArea()
        filter_scroll.setWidgetResizable(True)
        filter_scroll.setFrameShape(QFrame.NoFrame)
        filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        filter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        filter_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        filter_scroll.setFixedHeight(72)
        filter_scroll.setWidget(filter_card)
        layout.addWidget(filter_scroll)

        # --- Action bar -------------------------------------------------
        action_bar = QHBoxLayout()
        self.export_xlsx_btn = QPushButton("Export Excel")
        self.export_xlsx_btn.setProperty("class", "secondary")
        self.export_xlsx_btn.clicked.connect(lambda: self._export("xlsx"))
        self.export_pdf_btn = QPushButton("Export PDF")
        self.export_pdf_btn.setProperty("class", "secondary")
        self.export_pdf_btn.clicked.connect(lambda: self._export("pdf"))
        self.print_btn = QPushButton("Imprimer")
        self.print_btn.setProperty("class", "secondary")
        self.print_btn.clicked.connect(self._print)
        self.delete_btn = QPushButton("Supprimer la ligne")
        self.delete_btn.setProperty("class", "danger")
        self.delete_btn.clicked.connect(self._delete_selected)
        action_bar.addWidget(self.export_xlsx_btn)
        action_bar.addWidget(self.export_pdf_btn)
        action_bar.addWidget(self.print_btn)
        action_bar.addStretch()
        action_bar.addWidget(self.delete_btn)
        layout.addLayout(action_bar)

        # --- Table ------------------------------------------------------
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

        # --- Pagination -------------------------------------------------
        pag = QHBoxLayout()
        self.page_info = QLabel("Page 1")
        self.prev_btn = QPushButton("← Précédent")
        self.prev_btn.setProperty("class", "secondary")
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = QPushButton("Suivant →")
        self.next_btn.setProperty("class", "secondary")
        self.next_btn.clicked.connect(self._next_page)
        pag.addWidget(self.page_info)
        pag.addStretch()
        pag.addWidget(self.prev_btn)
        pag.addWidget(self.next_btn)
        layout.addLayout(pag)

    # ---------------------------------------------------------------- data
    def _collect_filters(self) -> dict:
        return {
            "matricule": self.matricule_filter.text().strip() or None,
            "type_": self.type_filter.currentData(),
            "agent_id": self.agent_filter.currentData(),
            "date_from": self.date_from.date().toString("yyyy-MM-dd"),
            "date_to": self.date_to.date().toString("yyyy-MM-dd"),
            "sync_status": self.sync_filter.currentData(),
        }

    def _apply_filters(self) -> None:
        self.current_page = 0
        self.last_filters = self._collect_filters()
        self.refresh()

    def _reset_filters(self) -> None:
        self.matricule_filter.clear()
        self.type_filter.setCurrentIndex(0)
        self.agent_filter.setCurrentIndex(0)
        today = QDate.currentDate()
        self.date_from.setDate(today.addDays(-30))
        self.date_to.setDate(today)
        self.sync_filter.setCurrentIndex(0)
        self._apply_filters()

    def _prev_page(self) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh()

    def _next_page(self) -> None:
        self.current_page += 1
        self.refresh()

    def refresh(self) -> None:
        if not self.last_filters:
            self.last_filters = self._collect_filters()
        filters = self.last_filters
        total = transaction_service.count_transactions(**filters)
        offset = self.current_page * PAGE_SIZE
        if offset >= total and total > 0:
            self.current_page = max(0, (total - 1) // PAGE_SIZE)
            offset = self.current_page * PAGE_SIZE
        txs = transaction_service.search_transactions(
            limit=PAGE_SIZE, offset=offset, **filters
        )
        self._render_rows(txs)
        max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_info.setText(f"Page {self.current_page + 1} / {max_page} — {total} résultat(s)")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(offset + len(txs) < total)

    def _render_rows(self, txs: List) -> None:
        self.table.setRowCount(0)
        for tx in txs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = [
                str(tx.id),
                tx.created_at,
                tx.matricule,
                tx.telephone or "",
                format_money(tx.montant) if tx.type == "depot" else "",
                format_money(tx.montant) if tx.type == "retrait" else "",
                format_money(tx.solde_apres),
                tx.agent_nom,
                tx.sync_status,
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(val)
                self.table.setItem(row, col, item)

            if tx.type == "depot":
                color = QColor("#dcfce7")
            else:
                color = QColor("#fee2e2")
            if tx.solde_apres <= 0:
                color = QColor("#fecaca")
            for c in range(self.table.columnCount()):
                self.table.item(row, c).setBackground(color)
            self.table.item(row, 0).setData(Qt.UserRole, tx.id)

    # ------------------------------------------------------------- actions
    def _selected_tx_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _delete_selected(self) -> None:
        if not self.user.is_admin():
            access_denied(self)
            return
        tx_id = self._selected_tx_id()
        if tx_id is None:
            info(self, "Sélection", "Sélectionnez une ligne à supprimer.")
            return
        if not confirm(self, "Supprimer", f"Supprimer la transaction #{tx_id} ?"):
            return
        try:
            transaction_service.delete_transaction(int(tx_id))
        except Exception as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()

    def _collect_export_rows(self):
        rows = []
        for r in range(self.table.rowCount()):
            row = [self.table.item(r, c).text() for c in range(self.table.columnCount())]
            rows.append(row)
        return rows

    def _export(self, fmt: str) -> None:
        rows = self._collect_export_rows()
        if not rows:
            info(self, "Export", "Aucune donnée à exporter.")
            return
        default = EXPORT_DIR / f"historique.{fmt}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer", str(default),
            "Excel (*.xlsx)" if fmt == "xlsx" else "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            from app.utils.exporters import export_to_excel, export_to_pdf
            if fmt == "xlsx":
                export_to_excel(Path(path), "Historique des transactions", EXPORT_HEADERS, rows)
            else:
                export_to_pdf(Path(path), "Historique des transactions", EXPORT_HEADERS, rows)
        except Exception as e:
            error(self, "Erreur d'export", str(e))
            return
        info(self, "Export", f"Fichier généré : {path}")

    def _print(self) -> None:
        rows = self._collect_export_rows()
        if not rows:
            info(self, "Impression", "Aucune donnée à imprimer.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QPrintDialog.Accepted:
            return
        html = "<h2>Historique des transactions</h2><table border='1' cellspacing='0' cellpadding='4' width='100%'><tr>"
        for h in EXPORT_HEADERS:
            html += f"<th bgcolor='#1F4E78' color='white'>{h}</th>"
        html += "</tr>"
        for row in rows:
            html += "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
        html += "</table>"
        doc = QTextDocument()
        doc.setHtml(html)
        doc.print_(printer)
