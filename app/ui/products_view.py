"""Gestion des produits et du stock."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.user import User
from app.services import product_service
from app.utils import stock_documents
from app.utils.helpers import format_money, open_file
from app.ui.widgets.dialogs import access_denied, confirm, error, info


PRODUCT_COLS = ["ID", "Référence", "Nom", "Catégorie", "Unité", "Prix vente",
                "Stock", "Seuil", "Max", "Emplacement", "Valeur", "Statut"]
UNITES = ["Pièce", "Carton", "Kg", "Litre", "Sac", "Paquet", "Mètre", "Boîte"]
MOVE_COLS = ["Date", "Produit", "Type", "Quantité", "Stock après", "Motif", "Agent"]


class ProductFormDialog(QDialog):
    def __init__(self, parent, product=None) -> None:
        super().__init__(parent)
        self.product = product
        self.setWindowTitle("Modifier le produit" if product else "Nouveau produit")
        self.setMinimumWidth(440)
        layout = QFormLayout(self)

        self.nom_edit = QLineEdit(product.nom if product else "")
        self.ref_edit = QLineEdit(product.reference if product and product.reference else "")

        # Catégorie : combo éditable pré-rempli avec les catégories existantes.
        self.cat_combo = QComboBox()
        self.cat_combo.setEditable(True)
        existing_cats = product_service.list_categories()
        self.cat_combo.addItem("")
        self.cat_combo.addItems(existing_cats)
        if product and product.categorie:
            if product.categorie not in existing_cats:
                self.cat_combo.addItem(product.categorie)
            self.cat_combo.setCurrentText(product.categorie)
        else:
            self.cat_combo.setCurrentText("")

        # Unité : combo éditable avec unités courantes.
        self.unite_combo = QComboBox()
        self.unite_combo.setEditable(True)
        self.unite_combo.addItem("")
        self.unite_combo.addItems(UNITES)
        self.unite_combo.setCurrentText(product.unite if product and product.unite else "")

        self.desc_edit = QTextEdit(product.description if product and product.description else "")
        self.desc_edit.setMaximumHeight(60)

        self.prix_achat_spin = QDoubleSpinBox()
        self.prix_achat_spin.setMaximum(1_000_000_000)
        self.prix_achat_spin.setDecimals(0)
        self.prix_achat_spin.setGroupSeparatorShown(True)
        self.prix_achat_spin.setValue(product.prix_achat if product else 0)

        self.prix_spin = QDoubleSpinBox()
        self.prix_spin.setMaximum(1_000_000_000)
        self.prix_spin.setDecimals(0)
        self.prix_spin.setGroupSeparatorShown(True)
        self.prix_spin.setValue(product.prix_unitaire if product else 0)

        self.seuil_spin = QDoubleSpinBox()
        self.seuil_spin.setMaximum(1_000_000)
        self.seuil_spin.setDecimals(0)
        self.seuil_spin.setValue(product.seuil_alerte if product else 0)

        self.stock_max_spin = QDoubleSpinBox()
        self.stock_max_spin.setMaximum(10_000_000)
        self.stock_max_spin.setDecimals(0)
        self.stock_max_spin.setValue(product.stock_max if product else 0)

        self.empl_edit = QLineEdit(product.emplacement if product and product.emplacement else "")

        layout.addRow("Nom *", self.nom_edit)
        layout.addRow("Référence", self.ref_edit)
        layout.addRow("Catégorie", self.cat_combo)
        layout.addRow("Unité", self.unite_combo)
        layout.addRow("Description", self.desc_edit)
        layout.addRow("Prix d'achat", self.prix_achat_spin)
        layout.addRow("Prix de vente *", self.prix_spin)
        layout.addRow("Seuil d'alerte (min)", self.seuil_spin)
        layout.addRow("Stock maximum", self.stock_max_spin)
        layout.addRow("Emplacement", self.empl_edit)

        if product is None:
            self.qte_spin = QDoubleSpinBox()
            self.qte_spin.setMaximum(1_000_000)
            self.qte_spin.setDecimals(0)
            layout.addRow("Quantité initiale", self.qte_spin)
        else:
            self.qte_spin = None

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def data(self) -> dict:
        return {
            "nom": self.nom_edit.text().strip(),
            "reference": self.ref_edit.text().strip(),
            "categorie": self.cat_combo.currentText().strip(),
            "unite": self.unite_combo.currentText().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "prix_achat": self.prix_achat_spin.value(),
            "prix_unitaire": self.prix_spin.value(),
            "seuil_alerte": self.seuil_spin.value(),
            "stock_max": self.stock_max_spin.value(),
            "emplacement": self.empl_edit.text().strip(),
            "quantite_initiale": self.qte_spin.value() if self.qte_spin else 0,
        }


class StockDialog(QDialog):
    def __init__(self, parent, product, type_: str) -> None:
        super().__init__(parent)
        self.product = product
        self.type_ = type_
        label = "Entrée de stock" if type_ == "entree" else "Sortie de stock"
        self.setWindowTitle(f"{label} — {product.nom}")
        self.setMinimumWidth(360)
        layout = QFormLayout(self)
        layout.addRow(QLabel(f"Stock actuel : {product.quantite_stock:g}"))
        self.qte_spin = QDoubleSpinBox()
        self.qte_spin.setMaximum(1_000_000)
        self.qte_spin.setDecimals(0)
        self.qte_spin.setMinimum(1)
        self.motif_edit = QLineEdit()
        layout.addRow("Quantité *", self.qte_spin)
        layout.addRow("Motif", self.motif_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def data(self) -> dict:
        return {"quantite": self.qte_spin.value(), "motif": self.motif_edit.text().strip()}


class ProductsView(QWidget):
    def __init__(self, current_user: User, on_changed: Optional[Callable] = None) -> None:
        super().__init__()
        self.current_user = current_user
        self.on_changed = on_changed
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        self.tabs = QTabWidget()

        # --- Onglet produits -------------------------------------------
        prod_widget = QWidget()
        pl = QVBoxLayout(prod_widget)

        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Rechercher un produit…")
        self.search_edit.setMinimumWidth(180)
        self.search_edit.setMaximumWidth(320)
        self.search_edit.textChanged.connect(self.refresh)
        add_btn = QPushButton("+ Nouveau produit")
        add_btn.setProperty("class", "success")
        add_btn.clicked.connect(self._create)
        edit_btn = QPushButton("Modifier")
        edit_btn.clicked.connect(self._edit)
        entree_btn = QPushButton("Entrée stock")
        entree_btn.setProperty("class", "secondary")
        entree_btn.clicked.connect(lambda: self._adjust("entree"))
        sortie_btn = QPushButton("Sortie stock")
        sortie_btn.setProperty("class", "secondary")
        sortie_btn.clicked.connect(lambda: self._adjust("sortie"))
        delete_btn = QPushButton("Supprimer")
        delete_btn.setProperty("class", "danger")
        delete_btn.clicked.connect(self._delete)
        fiche_btn = QPushButton("Fiche article (PDF)")
        fiche_btn.clicked.connect(self._fiche_article)
        inv_btn = QPushButton("Inventaire (PDF)")
        inv_btn.clicked.connect(self._inventaire)
        bar.addWidget(self.search_edit)
        bar.addStretch()
        bar.addWidget(add_btn)
        bar.addWidget(edit_btn)
        bar.addWidget(entree_btn)
        bar.addWidget(sortie_btn)
        bar.addWidget(fiche_btn)
        bar.addWidget(inv_btn)
        bar.addWidget(delete_btn)
        # Scroll horizontal pour la barre d'actions si la fenêtre est étroite
        bar_widget = QWidget()
        bar_widget.setLayout(bar)
        bar_widget.setMinimumWidth(940)
        bar_scroll = QScrollArea()
        bar_scroll.setWidgetResizable(True)
        bar_scroll.setFrameShape(QFrame.NoFrame)
        bar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        bar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bar_scroll.setFixedHeight(56)
        bar_scroll.setWidget(bar_widget)
        pl.addWidget(bar_scroll)

        self.table = QTableWidget(0, len(PRODUCT_COLS))
        self.table.setHorizontalHeaderLabels(PRODUCT_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        pl.addWidget(self.table, 1)

        # --- Onglet mouvements -----------------------------------------
        move_widget = QWidget()
        ml = QVBoxLayout(move_widget)
        move_bar = QHBoxLayout()
        move_bar.addWidget(QLabel("Historique des mouvements de stock"))
        move_bar.addStretch()
        bon_btn = QPushButton("Bon du mouvement (PDF)")
        bon_btn.setProperty("class", "secondary")
        bon_btn.clicked.connect(self._bon_mouvement)
        move_bar.addWidget(bon_btn)
        ml.addLayout(move_bar)
        self.move_table = QTableWidget(0, len(MOVE_COLS))
        self.move_table.setHorizontalHeaderLabels(MOVE_COLS)
        self.move_table.verticalHeader().setVisible(False)
        self.move_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.move_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.move_table.horizontalHeader().setStretchLastSection(True)
        self.move_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        ml.addWidget(self.move_table, 1)

        self.tabs.addTab(prod_widget, "Produits")
        self.tabs.addTab(move_widget, "Mouvements de stock")
        layout.addWidget(self.tabs)
        self.refresh()

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        query = self.search_edit.text().strip() or None
        products = product_service.list_products(query=query)
        self.table.setRowCount(0)
        for p in products:
            row = self.table.rowCount()
            self.table.insertRow(row)
            valeur = p.quantite_stock * p.prix_unitaire
            cells = [
                str(p.id),
                p.reference or "",
                p.nom,
                p.categorie or "",
                p.unite or "",
                format_money(p.prix_unitaire),
                f"{p.quantite_stock:g}",
                f"{p.seuil_alerte:g}",
                f"{p.stock_max:g}" if p.stock_max else "",
                p.emplacement or "",
                format_money(valeur),
                "Actif" if p.actif else "Inactif",
            ]
            for col, val in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(val))
            self.table.item(row, 0).setData(Qt.UserRole, p.id)
            if not p.actif:
                color = QColor("#f3f4f6")
            elif p.en_rupture():
                color = QColor("#fecaca")  # rupture de stock
            elif p.en_alerte():
                color = QColor("#fef3c7")  # alerte stock bas
            elif p.en_surstock():
                color = QColor("#dbeafe")  # surstock
            else:
                color = QColor("#ffffff")
            for c in range(self.table.columnCount()):
                self.table.item(row, c).setBackground(color)
        self._refresh_movements()

    def _refresh_movements(self) -> None:
        moves = product_service.list_movements(limit=300)
        self.move_table.setRowCount(0)
        for m in moves:
            row = self.move_table.rowCount()
            self.move_table.insertRow(row)
            cells = [
                m.created_at,
                m.product_nom,
                "Entrée" if m.type == "entree" else "Sortie",
                f"{m.quantite:g}",
                f"{m.stock_apres:g}",
                m.motif or "",
                m.agent_nom,
            ]
            for col, val in enumerate(cells):
                self.move_table.setItem(row, col, QTableWidgetItem(str(val)))
            self.move_table.item(row, 0).setData(Qt.UserRole, m.id)
            color = QColor("#dcfce7") if m.type == "entree" else QColor("#fee2e2")
            for c in range(self.move_table.columnCount()):
                self.move_table.item(row, c).setBackground(color)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return int(self.table.item(row, 0).data(Qt.UserRole))

    # ------------------------------------------------------------- actions
    def _create(self) -> None:
        dlg = ProductFormDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        try:
            product_service.create_product(
                nom=d["nom"], prix_unitaire=d["prix_unitaire"], reference=d["reference"],
                description=d["description"], quantite_initiale=d["quantite_initiale"],
                seuil_alerte=d["seuil_alerte"], categorie=d["categorie"], unite=d["unite"],
                prix_achat=d["prix_achat"], stock_max=d["stock_max"], emplacement=d["emplacement"],
            )
        except product_service.ProductError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()
        if self.on_changed:
            self.on_changed()

    def _edit(self) -> None:
        pid = self._selected_id()
        if pid is None:
            info(self, "Sélection", "Sélectionnez un produit.")
            return
        product = product_service.get_product(pid)
        dlg = ProductFormDialog(self, product=product)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        try:
            product_service.update_product(
                pid, nom=d["nom"], prix_unitaire=d["prix_unitaire"],
                reference=d["reference"], description=d["description"],
                seuil_alerte=d["seuil_alerte"], categorie=d["categorie"], unite=d["unite"],
                prix_achat=d["prix_achat"], stock_max=d["stock_max"], emplacement=d["emplacement"],
            )
        except product_service.ProductError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()

    def _adjust(self, type_: str) -> None:
        pid = self._selected_id()
        if pid is None:
            info(self, "Sélection", "Sélectionnez un produit.")
            return
        product = product_service.get_product(pid)
        dlg = StockDialog(self, product, type_)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        try:
            updated = product_service.adjust_stock(pid, type_, d["quantite"], motif=d["motif"])
        except product_service.ProductError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()
        if self.on_changed:
            self.on_changed()
        # Proposer la génération du bon correspondant au mouvement qui vient d'être créé.
        moves = product_service.list_movements(product_id=pid, limit=1)
        if moves and confirm(
            self, "Bon de mouvement",
            "Mouvement enregistré. Générer le bon PDF correspondant ?",
        ):
            self._generate_bon(moves[0], updated)

    def _delete(self) -> None:
        if not self.current_user.is_admin():
            access_denied(self)
            return
        pid = self._selected_id()
        if pid is None:
            info(self, "Sélection", "Sélectionnez un produit.")
            return
        if not confirm(self, "Supprimer", "Confirmer la suppression de ce produit ?"):
            return
        try:
            product_service.delete_product(pid)
        except product_service.ProductError as e:
            error(self, "Erreur", str(e))
            return
        self.refresh()
        if self.on_changed:
            self.on_changed()

    # ----------------------------------------------------------- documents PDF
    def _generate_bon(self, movement, product=None) -> None:
        if product is None:
            product = product_service.get_product(movement.product_id)
        try:
            path = stock_documents.bon_mouvement_pdf(movement, product)
        except Exception as e:  # génération PDF non critique : on informe sans planter
            error(self, "Erreur", f"Impossible de générer le bon : {e}")
            return
        open_file(path)
        info(self, "Bon généré", f"Bon enregistré :\n{path}")

    def _bon_mouvement(self) -> None:
        row = self.move_table.currentRow()
        if row < 0:
            info(self, "Sélection", "Sélectionnez un mouvement dans la liste.")
            return
        mid = self.move_table.item(row, 0).data(Qt.UserRole)
        if mid is None:
            return
        movement = product_service.get_movement(int(mid))
        if movement is None:
            error(self, "Erreur", "Mouvement introuvable.")
            return
        self._generate_bon(movement)

    def _fiche_article(self) -> None:
        pid = self._selected_id()
        if pid is None:
            info(self, "Sélection", "Sélectionnez un produit.")
            return
        product = product_service.get_product(pid)
        if product is None:
            error(self, "Erreur", "Produit introuvable.")
            return
        movements = product_service.list_movements(product_id=pid, limit=500)
        try:
            path = stock_documents.fiche_article_pdf(product, movements)
        except Exception as e:
            error(self, "Erreur", f"Impossible de générer la fiche : {e}")
            return
        open_file(path)
        info(self, "Fiche générée", f"Fiche enregistrée :\n{path}")

    def _inventaire(self) -> None:
        products = product_service.list_products(include_inactive=False)
        if not products:
            info(self, "Inventaire", "Aucun produit actif à inventorier.")
            return
        try:
            path = stock_documents.inventaire_pdf(products)
        except Exception as e:
            error(self, "Erreur", f"Impossible de générer l'inventaire : {e}")
            return
        open_file(path)
        info(self, "Inventaire généré", f"Inventaire enregistré :\n{path}")
