"""Vue de vente de produit à un client (décompté sur son solde)."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.models.user import User
from app.services import product_service, sale_service, transaction_service
from app.utils.helpers import format_money


SALE_COLS = ["ID", "Date", "Matricule", "Produit", "Qté", "Montant", "Solde après", "Agent"]


class SalesView(QWidget):
    def __init__(self, agent: User, on_changed: Optional[Callable] = None) -> None:
        super().__init__()
        self.agent = agent
        self.on_changed = on_changed
        self.last_sale = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # Conteneur commutable horizontal/vertical selon largeur
        self._top_container = QWidget()
        top = QBoxLayout(QBoxLayout.LeftToRight, self._top_container)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(16)
        self._top_box = top

        # --- Left: sale form -------------------------------------------
        form_card = QFrame()
        form_card.setProperty("class", "card")
        fl = QVBoxLayout(form_card)
        fl.setContentsMargins(24, 24, 24, 24)
        fl.setSpacing(12)

        title = QLabel("Nouvelle vente")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        fl.addWidget(title)

        grid = QFormLayout()
        grid.setLabelAlignment(Qt.AlignLeft)
        grid.setSpacing(10)

        self.product_combo = QComboBox()
        self.product_combo.currentIndexChanged.connect(self._on_product_changed)

        self.matricule_edit = QLineEdit()
        self.matricule_edit.setPlaceholderText("ex : MAT-001")
        self.matricule_edit.editingFinished.connect(self._update_balance)

        self.telephone_edit = QLineEdit()
        self.telephone_edit.setPlaceholderText("ex : +221 77 000 00 00")

        self.qte_spin = QDoubleSpinBox()
        self.qte_spin.setMaximum(1_000_000)
        self.qte_spin.setDecimals(0)
        self.qte_spin.setMinimum(1)
        self.qte_spin.valueChanged.connect(self._update_total)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Note optionnelle")

        grid.addRow("Produit *", self.product_combo)
        grid.addRow("Matricule client *", self.matricule_edit)
        grid.addRow("Téléphone", self.telephone_edit)
        grid.addRow("Quantité *", self.qte_spin)
        grid.addRow("Note", self.note_edit)
        fl.addLayout(grid)

        self.stock_label = QLabel("Stock disponible : —")
        self.stock_label.setStyleSheet("color: #6b7280; font-weight: 600;")
        fl.addWidget(self.stock_label)

        self.balance_label = QLabel("Solde du client : —")
        self.balance_label.setStyleSheet("color: #6b7280; font-weight: 600;")
        fl.addWidget(self.balance_label)

        self.total_label = QLabel("Montant total : —")
        self.total_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.total_label.setStyleSheet("color: #111827;")
        fl.addWidget(self.total_label)

        agent_label = QLabel(f"Agent : <b>{self.agent.nom_complet}</b>")
        agent_label.setTextFormat(Qt.RichText)
        agent_label.setStyleSheet("color: #374151;")
        fl.addWidget(agent_label)

        btn_row = QHBoxLayout()
        validate_btn = QPushButton("Valider la vente")
        validate_btn.setProperty("class", "success")
        validate_btn.clicked.connect(self._validate)
        clear_btn = QPushButton("Effacer")
        clear_btn.setProperty("class", "secondary")
        clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(validate_btn)
        btn_row.addWidget(clear_btn)
        fl.addLayout(btn_row)
        fl.addStretch()

        # --- Right: receipt --------------------------------------------
        receipt_card = QFrame()
        receipt_card.setProperty("class", "card")
        rl = QVBoxLayout(receipt_card)
        rl.setContentsMargins(24, 24, 24, 24)
        rl.setSpacing(10)
        r_title = QLabel("Reçu de la dernière vente")
        r_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        rl.addWidget(r_title)
        self.receipt_view = QTextBrowser()
        self.receipt_view.setMinimumHeight(220)
        self.receipt_view.setHtml(self._empty_receipt_html())
        rl.addWidget(self.receipt_view, 1)
        self.print_btn = QPushButton("Imprimer le reçu")
        self.print_btn.setProperty("class", "secondary")
        self.print_btn.setEnabled(False)
        self.print_btn.clicked.connect(self._print_receipt)
        rl.addWidget(self.print_btn)

        top.addWidget(form_card, 1)
        top.addWidget(receipt_card, 1)
        root.addWidget(self._top_container, 1)

        # --- Bottom: sales history -------------------------------------
        hist_label = QLabel("Dernières ventes")
        hist_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        root.addWidget(hist_label)
        self.table = QTableWidget(0, len(SALE_COLS))
        self.table.setHorizontalHeaderLabels(SALE_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setMinimumHeight(180)
        root.addWidget(self.table, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.width() < 950:
            if self._top_box.direction() != QBoxLayout.TopToBottom:
                self._top_box.setDirection(QBoxLayout.TopToBottom)
        else:
            if self._top_box.direction() != QBoxLayout.LeftToRight:
                self._top_box.setDirection(QBoxLayout.LeftToRight)

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        self._load_products()
        self._update_balance()
        self._update_total()
        self._load_sales()

    def _load_products(self) -> None:
        current_id = self.product_combo.currentData()
        self.product_combo.blockSignals(True)
        self.product_combo.clear()
        self._products = product_service.list_products(include_inactive=False)
        for p in self._products:
            self.product_combo.addItem(f"{p.nom} — {format_money(p.prix_unitaire)}", p.id)
        self.product_combo.blockSignals(False)
        if current_id is not None:
            idx = self.product_combo.findData(current_id)
            if idx >= 0:
                self.product_combo.setCurrentIndex(idx)
        self._on_product_changed()

    def _selected_product(self):
        pid = self.product_combo.currentData()
        if pid is None:
            return None
        for p in self._products:
            if p.id == pid:
                return p
        return None

    def _on_product_changed(self) -> None:
        p = self._selected_product()
        if p is None:
            self.stock_label.setText("Stock disponible : —")
        else:
            self.stock_label.setText(f"Stock disponible : {p.quantite_stock:g}")
        self._update_total()

    def _update_balance(self) -> None:
        matricule = self.matricule_edit.text().strip()
        if not matricule:
            self.balance_label.setText("Solde du client : —")
            return
        bal = transaction_service.get_matricule_balance(matricule)
        self.balance_label.setText(f"Solde de {matricule} : {format_money(bal)}")

    def _update_total(self) -> None:
        p = self._selected_product()
        if p is None:
            self.total_label.setText("Montant total : —")
            return
        total = p.prix_unitaire * self.qte_spin.value()
        self.total_label.setText(f"Montant total : {format_money(total)}")

    def _load_sales(self) -> None:
        sales = sale_service.search_sales(limit=100)
        self.table.setRowCount(0)
        for s in sales:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = [
                str(s.id),
                s.created_at,
                s.matricule,
                s.product_nom,
                f"{s.quantite:g}",
                format_money(s.montant_total),
                format_money(s.solde_apres),
                s.agent_nom,
            ]
            for col, val in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(str(val)))

    # ------------------------------------------------------------- actions
    def _validate(self) -> None:
        p = self._selected_product()
        if p is None:
            QMessageBox.warning(self, "Champ requis", "Sélectionnez un produit.")
            return
        matricule = self.matricule_edit.text().strip()
        if not matricule:
            QMessageBox.warning(self, "Champ requis", "Le matricule du client est obligatoire.")
            return
        try:
            sale = sale_service.create_sale(
                matricule=matricule,
                product_id=p.id,
                quantite=self.qte_spin.value(),
                agent=self.agent,
                telephone=self.telephone_edit.text().strip(),
                note=self.note_edit.text().strip(),
            )
        except sale_service.SaleError as e:
            QMessageBox.warning(self, "Vente refusée", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur inattendue : {e}")
            return

        self._show_receipt(sale)
        self.refresh()
        if self.on_changed:
            self.on_changed()

    def _clear(self) -> None:
        self.matricule_edit.clear()
        self.telephone_edit.clear()
        self.note_edit.clear()
        self.qte_spin.setValue(1)
        self.balance_label.setText("Solde du client : —")

    # ------------------------------------------------------------- receipt
    def _empty_receipt_html(self) -> str:
        return (
            "<div style='color:#9ca3af;padding:30px;text-align:center;'>"
            "Aucune vente enregistrée pour le moment.<br>"
            "Le reçu apparaîtra ici après validation."
            "</div>"
        )

    def _show_receipt(self, sale) -> None:
        html = f"""
        <div style='font-family:Segoe UI; padding: 6px;'>
          <div style='text-align:center; border-bottom: 2px dashed #cbd5e1; padding-bottom:10px;'>
            <div style='font-size:16px; font-weight:bold;'>REÇU DE VENTE</div>
            <div style='color:#6b7280; font-size:11px;'>N° {sale.id} — {sale.created_at}</div>
          </div>
          <div style='font-size:20px; font-weight:bold; color:#2563eb; text-align:center; margin:14px 0;'>
            {sale.product_nom}<br>{format_money(sale.montant_total)}
          </div>
          <table style='width:100%; font-size:13px;' cellpadding='4'>
            <tr><td><b>Matricule</b></td><td>{sale.matricule}</td></tr>
            <tr><td><b>Téléphone</b></td><td>{sale.telephone or '—'}</td></tr>
            <tr><td><b>Quantité</b></td><td>{sale.quantite:g} × {format_money(sale.prix_unitaire)}</td></tr>
            <tr><td><b>Nouveau solde</b></td><td><b>{format_money(sale.solde_apres)}</b></td></tr>
            <tr><td><b>Agent</b></td><td>{sale.agent_nom}</td></tr>
            <tr><td><b>Référence</b></td><td style='font-size:10px;'>{sale.uuid}</td></tr>
          </table>
          <div style='text-align:center; border-top: 2px dashed #cbd5e1; padding-top:10px; color:#6b7280; font-size:11px;'>
            Merci pour votre confiance.
          </div>
        </div>
        """
        self.receipt_view.setHtml(html)
        self.last_sale = sale
        self.print_btn.setEnabled(True)

    def _print_receipt(self) -> None:
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QPrintDialog.Accepted:
            return
        self.receipt_view.document().print_(printer)
