"""Présentation du diagnostic avant une réparation explicitement demandée."""
from PySide6.QtWidgets import QAbstractItemView, QDialog, QVBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QMessageBox
from app.services.reconciliation_service import preview, apply_reconciliation
from server.sync.reconciliation_engine import plan_token


class ReconciliationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Vérification des stocks et des soldes')
        self.resize(1050, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Stock initial + entrées − sorties = stock final'))
        self.info = QLabel()
        layout.addWidget(self.info)
        self.table = QTableWidget(0, 6)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setHorizontalHeaderLabels(['Produit', 'Stock initial', 'Entrées', 'Sorties', 'Stock calculé', 'Stock enregistré'])
        layout.addWidget(self.table)
        self.issues = QTextEdit()
        self.issues.setReadOnly(True)
        self.issues.setMaximumHeight(140)
        layout.addWidget(self.issues)
        self.apply_button = QPushButton('Sauvegarder et appliquer ces recalculs')
        self.apply_button.clicked.connect(self.apply)
        layout.addWidget(self.apply_button)
        refresh = QPushButton('Actualiser le diagnostic')
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        self.refresh()

    def refresh(self):
        self.plan = preview()
        self.token = plan_token(self.plan)
        self.info.setText(f"{len(self.plan['changes'])} lignes à recalculer ; {len(self.plan['issues'])} points à vérifier. Une sauvegarde sera créée avant correction.")
        self.table.setRowCount(len(self.plan['stocks']))
        for row, stock in enumerate(self.plan['stocks']):
            for column, name in enumerate(('nom', 'initial', 'entries', 'exits', 'closing', 'previous')):
                self.table.setItem(row, column, QTableWidgetItem(str(stock[name])))
        self.table.resizeColumnsToContents()
        self.issues.setPlainText('\n'.join(f"{i['label'] or i['uuid']}: {i['reason']}" for i in self.plan['issues']))
        self.apply_button.setEnabled(bool(self.plan['changes']))

    def apply(self):
        try:
            report = apply_reconciliation(self.token)
        except Exception as exc:
            QMessageBox.critical(self, 'Recalcul non appliqué', str(exc))
            self.refresh()
            return
        QMessageBox.information(self, 'Recalcul terminé', f"{len(report['changes'])} lignes corrigées.\nRapport : {report.get('report_file', '')}")
        self.refresh()
