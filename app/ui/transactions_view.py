"""Vue de saisie de dépôt / retrait."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.user import User
from app.services import settings_service, transaction_service
from app.ui import receipt_printing
from app.utils import receipt_printer
from app.utils.helpers import format_money, parse_money


class TransactionsView(QWidget):
    def __init__(self, agent: User, on_changed: Optional[Callable] = None) -> None:
        super().__init__()
        self.agent = agent
        self.on_changed = on_changed
        self._build_ui()

    def _build_ui(self) -> None:
        # Conteneur scrollable pour rester utilisable sur petite fenêtre
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self._scroll)

        content = QWidget()
        self._scroll.setWidget(content)

        # Layout principal commutable horizontal/vertical selon la largeur
        root = QBoxLayout(QBoxLayout.LeftToRight, content)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)
        self._root_box = root

        # --- Left: form -------------------------------------------------
        form_card = QFrame()
        form_card.setProperty("class", "card")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setSpacing(12)

        title = QLabel("Nouvelle opération")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        form_layout.addWidget(title)

        type_box = QHBoxLayout()
        self.depot_radio = QRadioButton("Dépôt")
        self.retrait_radio = QRadioButton("Retrait")
        self.depot_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.depot_radio)
        group.addButton(self.retrait_radio)
        type_box.addWidget(self.depot_radio)
        type_box.addWidget(self.retrait_radio)
        type_box.addStretch()
        form_layout.addLayout(type_box)

        grid = QFormLayout()
        grid.setLabelAlignment(Qt.AlignLeft)
        grid.setSpacing(10)

        self.matricule_edit = QLineEdit()
        self.matricule_edit.setPlaceholderText("ex : MAT-001")
        self.matricule_edit.editingFinished.connect(self._update_current_balance)

        self.telephone_edit = QLineEdit()
        self.telephone_edit.setPlaceholderText("ex : +221 77 000 00 00")

        self.montant_edit = QLineEdit()
        self.montant_edit.setPlaceholderText("0")

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Note optionnelle")

        grid.addRow("Matricule *", self.matricule_edit)
        grid.addRow("Téléphone", self.telephone_edit)
        grid.addRow("Montant *", self.montant_edit)
        grid.addRow("Note", self.note_edit)
        form_layout.addLayout(grid)

        self.balance_label = QLabel("Solde du matricule : —")
        self.balance_label.setStyleSheet("color: #6b7280; font-weight: 600;")
        form_layout.addWidget(self.balance_label)
        self.deposit_limit_label = QLabel("Dépôts : maximum 40 000 GNF par matricule et par jour.")
        self.deposit_limit_label.setWordWrap(True)
        form_layout.addWidget(self.deposit_limit_label)

        agent_label = QLabel(f"Agent : <b>{self.agent.nom_complet}</b>")
        agent_label.setTextFormat(Qt.RichText)
        agent_label.setStyleSheet("color: #374151;")
        form_layout.addWidget(agent_label)

        btn_row = QHBoxLayout()
        validate_btn = QPushButton("Valider l'opération")
        validate_btn.setProperty("class", "success")
        validate_btn.clicked.connect(self._validate)
        clear_btn = QPushButton("Effacer")
        clear_btn.setProperty("class", "secondary")
        clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(validate_btn)
        btn_row.addWidget(clear_btn)
        form_layout.addLayout(btn_row)

        form_layout.addStretch()

        # --- Right: receipt preview -------------------------------------
        receipt_card = QFrame()
        receipt_card.setProperty("class", "card")
        rl = QVBoxLayout(receipt_card)
        rl.setContentsMargins(24, 24, 24, 24)
        rl.setSpacing(10)

        r_title = QLabel("Reçu de la dernière opération")
        r_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        rl.addWidget(r_title)

        self.receipt_view = QTextBrowser()
        self.receipt_view.setMinimumHeight(240)
        self.receipt_view.setHtml(self._empty_receipt_html())
        rl.addWidget(self.receipt_view, 1)

        self.print_btn = QPushButton("Imprimer le reçu")
        self.print_btn.setProperty("class", "secondary")
        self.print_btn.setEnabled(False)
        self.print_btn.clicked.connect(self._print_receipt)
        rl.addWidget(self.print_btn)

        root.addWidget(form_card, 1)
        root.addWidget(receipt_card, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # En dessous de ~900 px on empile verticalement (formulaire au-dessus, reçu en dessous)
        if self.width() < 900:
            if self._root_box.direction() != QBoxLayout.TopToBottom:
                self._root_box.setDirection(QBoxLayout.TopToBottom)
        else:
            if self._root_box.direction() != QBoxLayout.LeftToRight:
                self._root_box.setDirection(QBoxLayout.LeftToRight)

    # ---------------------------------------------------------------- core
    def _update_current_balance(self) -> None:
        matricule = self.matricule_edit.text().strip()
        if not matricule:
            self.balance_label.setText("Solde du matricule : —")
            self.deposit_limit_label.setText("Plafond des dépôts : 40 000 GNF par matricule et par jour.")
            return
        bal = transaction_service.get_matricule_balance(matricule)
        self.balance_label.setText(f"Solde de {matricule} : {format_money(bal)}")
        deposited = transaction_service.deposits_on_day(matricule)
        remaining = max(0, 40000 - deposited)
        self.deposit_limit_label.setText(
            f"Dépôts aujourd'hui : {format_money(deposited)} / 40 000 GNF. "
            f"Reste autorisé : {format_money(remaining)}.")

    def _validate(self) -> None:
        matricule = self.matricule_edit.text().strip()
        telephone = self.telephone_edit.text().strip()
        note = self.note_edit.text().strip()
        type_ = "depot" if self.depot_radio.isChecked() else "retrait"
        try:
            montant = parse_money(self.montant_edit.text())
        except ValueError as e:
            QMessageBox.warning(self, "Montant invalide", str(e))
            return
        if not matricule:
            QMessageBox.warning(self, "Champ requis", "Le matricule est obligatoire.")
            return

        try:
            tx = transaction_service.create_transaction(
                matricule=matricule,
                telephone=telephone,
                type_=type_,
                montant=montant,
                agent=self.agent,
                note=note,
            )
        except transaction_service.TransactionError as e:
            QMessageBox.warning(self, "Opération refusée", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur inattendue : {e}")
            return

        self._show_receipt(tx)
        self._update_current_balance()
        self.montant_edit.clear()
        self.note_edit.clear()
        if self.on_changed:
            self.on_changed()

    def _clear(self) -> None:
        for w in (self.matricule_edit, self.telephone_edit, self.montant_edit, self.note_edit):
            w.clear()
        self.balance_label.setText("Solde du matricule : —")

    def refresh(self) -> None:
        self._update_current_balance()

    # ------------------------------------------------------------- receipt
    def _empty_receipt_html(self) -> str:
        return (
            "<div style='color:#9ca3af;padding:30px;text-align:center;'>"
            "Aucune opération enregistrée pour le moment.<br>"
            "Le reçu apparaîtra ici après validation."
            "</div>"
        )

    def _build_receipt(self, tx) -> receipt_printer.Receipt:
        is_depot = tx.type == "depot"
        return receipt_printer.Receipt(
            title="REÇU D'OPÉRATION",
            number=f"N° {tx.id}",
            date=str(tx.created_at),
            highlight_label="DÉPÔT" if is_depot else "RETRAIT",
            highlight_value=format_money(tx.montant),
            highlight_color="#16a34a" if is_depot else "#dc2626",
            rows=[
                ("Matricule", tx.matricule),
                ("Téléphone", tx.telephone or "—"),
                ("Nouveau solde", format_money(tx.solde_apres)),
                ("Agent", tx.agent_nom),
            ],
            reference=tx.uuid,
        )

    def _show_receipt(self, tx) -> None:
        self.last_receipt = self._build_receipt(tx)
        self.receipt_view.setHtml(
            receipt_printer.render_html(self.last_receipt, settings_service.get_company_info())
        )
        self.last_tx = tx
        self.print_btn.setEnabled(True)
        # Ticket thermique imprimé dès la validation si l'option est active
        # (silencieux s'il n'y a pas d'imprimante à tickets).
        if settings_service.get_print_config()["auto_print"]:
            receipt_printing.print_receipt(self, self.last_receipt, auto=True)

    def _print_receipt(self) -> None:
        receipt = getattr(self, "last_receipt", None)
        if receipt is None:
            return
        receipt_printing.print_receipt(self, receipt)
