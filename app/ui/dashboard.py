"""Tableau de bord."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services import product_service, sale_service, transaction_service
from app.services.report_service import today_period
from app.utils.helpers import format_money


class StatCard(QFrame):
    def __init__(self, title: str, color: str = "#2563eb") -> None:
        super().__init__()
        self.setProperty("class", "card")
        self.setStyleSheet(self.styleSheet() + f"QFrame {{ border-left: 4px solid {color}; }}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #6b7280; font-size: 12px; font-weight: 600;")
        self.value_label = QLabel("—")
        self.value_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self.value_label.setStyleSheet(f"color: {color};")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class DashboardView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll vertical pour ne jamais tronquer le contenu sur petite fenêtre
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        self._cards_grid = QGridLayout()
        self._cards_grid.setSpacing(12)
        self.solde_card = StatCard("Solde global", "#2563eb")
        self.depots_card = StatCard("Total dépôts", "#16a34a")
        self.retraits_card = StatCard("Total retraits", "#dc2626")
        self.tx_card = StatCard("Nombre de transactions", "#7c3aed")
        self.users_card = StatCard("Matricules distincts", "#0891b2")
        self.pending_card = StatCard("Sync en attente", "#d97706")
        self.stock_value_card = StatCard("Valeur du stock", "#0d9488")
        self.low_stock_card = StatCard("Produits en alerte", "#ea580c")
        self.sales_today_card = StatCard("Ventes du jour", "#2563eb")

        self._cards = [
            self.solde_card,
            self.depots_card,
            self.retraits_card,
            self.tx_card,
            self.users_card,
            self.pending_card,
            self.stock_value_card,
            self.low_stock_card,
            self.sales_today_card,
        ]
        self._current_cols = 0
        self._relayout_cards(3)
        layout.addLayout(self._cards_grid)

        recent_title = QLabel("Dernières opérations")
        recent_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        layout.addWidget(recent_title)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Date", "Matricule", "Type", "Montant", "Solde", "Agent"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setMinimumHeight(220)
        layout.addWidget(self.table, 1)

    def _relayout_cards(self, cols: int) -> None:
        """Replace les cartes dans la grille selon le nombre de colonnes voulu."""
        if cols == self._current_cols:
            return
        # Retire toutes les cartes de la grille sans les détruire
        for card in self._cards:
            self._cards_grid.removeWidget(card)
        for i, card in enumerate(self._cards):
            row, col = divmod(i, cols)
            self._cards_grid.addWidget(card, row, col)
        self._current_cols = cols

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w = self.width()
        if w < 700:
            cols = 1
        elif w < 1050:
            cols = 2
        else:
            cols = 3
        self._relayout_cards(cols)

    def refresh(self) -> None:
        solde = transaction_service.get_global_balance()
        depots, retraits, n_tx, n_matricules = transaction_service.totals()
        sync_counts = transaction_service.sync_status_counts()

        self.solde_card.set_value(format_money(solde))
        self.depots_card.set_value(format_money(depots))
        self.retraits_card.set_value(format_money(retraits))
        self.tx_card.set_value(str(n_tx))
        self.users_card.set_value(str(n_matricules))
        self.pending_card.set_value(str(sync_counts.get("pending", 0)))

        self.stock_value_card.set_value(format_money(product_service.stock_value()))
        self.low_stock_card.set_value(str(len(product_service.low_stock_products())))
        tfrom, tto = today_period()
        sm, sn, _ = sale_service.sales_totals(tfrom, tto)
        self.sales_today_card.set_value(f"{format_money(sm)} ({sn})")

        recent = transaction_service.latest_transactions(limit=15)
        self.table.setRowCount(0)
        for tx in recent:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(tx.id)))
            self.table.setItem(row, 1, QTableWidgetItem(tx.created_at))
            self.table.setItem(row, 2, QTableWidgetItem(tx.matricule))
            self.table.setItem(row, 3, QTableWidgetItem("Dépôt" if tx.type == "depot" else "Retrait"))
            self.table.setItem(row, 4, QTableWidgetItem(format_money(tx.montant)))
            self.table.setItem(row, 5, QTableWidgetItem(format_money(tx.solde_apres)))
            self.table.setItem(row, 6, QTableWidgetItem(tx.agent_nom))

            # Coloration par type
            color = QColor("#dcfce7") if tx.type == "depot" else QColor("#fee2e2")
            if tx.solde_apres <= 0:
                color = QColor("#fecaca")
            for col in range(self.table.columnCount()):
                self.table.item(row, col).setBackground(color)
