"""Génération de rapports (journalier / mensuel / annuel / par agent)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models.user import User
from app.services import product_service, report_service, sale_service, transaction_service, user_service
from app.utils.helpers import format_money
from app.ui.widgets.dialogs import error, info


class ReportsView(QWidget):
    def __init__(self, current_user: User) -> None:
        super().__init__()
        self.current_user = current_user
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Rapports")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        layout.addWidget(title)

        # --- Quick stats ------------------------------------------------
        stats_card = QFrame()
        stats_card.setProperty("class", "card")
        sg = QGridLayout(stats_card)
        sg.setContentsMargins(16, 12, 16, 12)
        self.today_label = QLabel("—")
        self.month_label = QLabel("—")
        self.year_label = QLabel("—")
        for r, (k, lbl, value) in enumerate([
            ("today", "Aujourd'hui", self.today_label),
            ("month", "Ce mois", self.month_label),
            ("year", "Cette année", self.year_label),
        ]):
            name = QLabel(f"<b>{lbl}</b>")
            name.setTextFormat(Qt.RichText)
            sg.addWidget(name, r, 0)
            sg.addWidget(value, r, 1)
        layout.addWidget(stats_card)

        # --- Report builder --------------------------------------------
        form_card = QFrame()
        form_card.setProperty("class", "card")
        fl = QFormLayout(form_card)
        fl.setContentsMargins(16, 12, 16, 12)

        self.dataset_combo = QComboBox()
        self.dataset_combo.addItem("Transactions (dépôts/retraits)", "transactions")
        self.dataset_combo.addItem("Ventes de produits", "sales")
        self.dataset_combo.addItem("État du stock", "stock")
        self.dataset_combo.currentIndexChanged.connect(self._dataset_changed)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Journalier", "daily")
        self.kind_combo.addItem("Mensuel", "monthly")
        self.kind_combo.addItem("Annuel", "annual")
        self.kind_combo.addItem("Personnalisé", "custom")
        self.kind_combo.addItem("Par agent", "agent")
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)

        today = QDate.currentDate()
        self.date_from = QDateEdit(today)
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_to = QDateEdit(today)
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")

        self.agent_combo = QComboBox()
        self.agent_combo.addItem("(Tous les agents)", None)
        for u in user_service.list_users():
            self.agent_combo.addItem(u.nom_complet, u.id)

        self.format_combo = QComboBox()
        self.format_combo.addItem("PDF", "pdf")
        self.format_combo.addItem("Excel", "xlsx")

        fl.addRow("Données", self.dataset_combo)
        fl.addRow("Type de rapport", self.kind_combo)
        fl.addRow("Date de début", self.date_from)
        fl.addRow("Date de fin", self.date_to)
        fl.addRow("Agent", self.agent_combo)
        fl.addRow("Format", self.format_combo)

        btn_row = QHBoxLayout()
        self.generate_btn = QPushButton("Générer le rapport")
        self.generate_btn.setProperty("class", "success")
        self.generate_btn.clicked.connect(self._generate)
        self.open_btn = QPushButton("Ouvrir le fichier généré")
        self.open_btn.setProperty("class", "secondary")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_last)
        btn_row.addWidget(self.generate_btn)
        btn_row.addWidget(self.open_btn)
        fl.addRow(btn_row)

        layout.addWidget(form_card)
        layout.addStretch()
        self._kind_changed()
        self._dataset_changed()
        self.refresh()

    def refresh(self) -> None:
        today_from, today_to = report_service.today_period()
        d, r, _ = transaction_service.totals_by_period(today_from, today_to)
        sm, sn, _ = sale_service.sales_totals(today_from, today_to)
        self.today_label.setText(
            f"Dépôts : {format_money(d)}   Retraits : {format_money(r)}   "
            f"Ventes : {format_money(sm)} ({sn})"
        )

        mfrom, mto = report_service.month_period()
        d, r, _ = transaction_service.totals_by_period(mfrom, mto)
        sm, sn, _ = sale_service.sales_totals(mfrom, mto)
        self.month_label.setText(
            f"Dépôts : {format_money(d)}   Retraits : {format_money(r)}   "
            f"Ventes : {format_money(sm)} ({sn})"
        )

        yfrom, yto = report_service.year_period()
        d, r, _ = transaction_service.totals_by_period(yfrom, yto)
        sm, sn, _ = sale_service.sales_totals(yfrom, yto)
        self.year_label.setText(
            f"Dépôts : {format_money(d)}   Retraits : {format_money(r)}   "
            f"Ventes : {format_money(sm)} ({sn})"
        )

    def _dataset_changed(self) -> None:
        is_stock = self.dataset_combo.currentData() == "stock"
        self.kind_combo.setEnabled(not is_stock)
        self.date_from.setEnabled(not is_stock)
        self.date_to.setEnabled(not is_stock)

    def _kind_changed(self) -> None:
        kind = self.kind_combo.currentData()
        today = QDate.currentDate()
        if kind == "daily":
            self.date_from.setDate(today)
            self.date_to.setDate(today)
        elif kind == "monthly":
            self.date_from.setDate(QDate(today.year(), today.month(), 1))
            self.date_to.setDate(today)
        elif kind == "annual":
            self.date_from.setDate(QDate(today.year(), 1, 1))
            self.date_to.setDate(QDate(today.year(), 12, 31))

    def _generate(self) -> None:
        kind = self.kind_combo.currentData()
        dataset = self.dataset_combo.currentData()
        date_from = self.date_from.date().toString("yyyy-MM-dd")
        date_to = self.date_to.date().toString("yyyy-MM-dd")
        agent_id = self.agent_combo.currentData() if kind == "agent" else None
        fmt = self.format_combo.currentData()
        try:
            path = report_service.generate_report(
                kind=kind, date_from=date_from, date_to=date_to, agent_id=agent_id,
                fmt=fmt, dataset=dataset,
            )
        except Exception as e:
            error(self, "Erreur", f"Génération impossible : {e}")
            return
        self.last_report_path = path
        self.open_btn.setEnabled(True)
        info(self, "Rapport généré", f"Fichier enregistré :\n{path}")

    def _open_last(self) -> None:
        path: Path = getattr(self, "last_report_path", None)
        if not path or not Path(path).exists():
            return
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.call(["open", str(path)])
            else:
                subprocess.call(["xdg-open", str(path)])
        except Exception as e:
            error(self, "Ouverture impossible", str(e))
