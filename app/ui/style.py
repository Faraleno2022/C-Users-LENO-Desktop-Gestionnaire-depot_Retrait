"""Feuille de style globale (QSS).

Alignée sur la console web (Bootstrap 5.3) : mêmes couleurs de boutons
(primary #0d6efd, success #198754, danger #dc3545, secondary #6c757d),
mêmes champs (#ced4da, focus #86b7fe), mêmes tableaux (en-tête #1f4e78),
même fond de page (#f3f4f6) et cartes blanches arrondies.
"""

QSS = """
* {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #212529;
}
QMainWindow, QDialog, QWidget#central {
    background-color: #f3f4f6;
}

/* ---------- Champs de formulaire (Bootstrap .form-control) ---------- */
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit {
    background: white;
    border: 1px solid #ced4da;
    border-radius: 6px;
    padding: 6px 12px;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QTextEdit:focus {
    border: 1px solid #86b7fe;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: #e9ecef;
    color: #6c757d;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: white;
    border: 1px solid #ced4da;
    selection-background-color: #0d6efd;
    selection-color: white;
}

/* ---------- Boutons (Bootstrap .btn) ---------- */
QPushButton {
    background-color: #0d6efd;          /* btn-primary */
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover { background-color: #0b5ed7; }
QPushButton:pressed { background-color: #0a58ca; }
QPushButton:disabled { background-color: #adb5bd; color: #f8f9fa; }

QPushButton.secondary {                  /* btn-secondary (Annuler…) */
    background-color: #6c757d;
    color: white;
}
QPushButton.secondary:hover { background-color: #5c636a; }
QPushButton.secondary:pressed { background-color: #565e64; }

QPushButton.success {                    /* btn-success (Valider dépôt…) */
    background-color: #198754;
}
QPushButton.success:hover { background-color: #157347; }
QPushButton.success:pressed { background-color: #146c43; }

QPushButton.danger {                     /* btn-danger (Valider retrait, Supprimer) */
    background-color: #dc3545;
}
QPushButton.danger:hover { background-color: #bb2d3b; }
QPushButton.danger:pressed { background-color: #b02a37; }

QPushButton.info {                       /* btn-info (Vente) */
    background-color: #0dcaf0;
    color: #000;
}
QPushButton.info:hover { background-color: #31d2f2; }

/* ---------- Titres et textes ---------- */
QLabel.h1 { font-size: 24px; font-weight: 700; color: #111827; }
QLabel.h2 { font-size: 18px; font-weight: 600; color: #111827; }
QLabel.muted { color: #6b7280; }

/* ---------- Badges (mêmes couleurs que la console web) ---------- */
QLabel.badge-depot {
    background: #dcfce7; color: #166534;
    border-radius: 8px; padding: 2px 10px; font-weight: 600;
}
QLabel.badge-retrait {
    background: #fee2e2; color: #991b1b;
    border-radius: 8px; padding: 2px 10px; font-weight: 600;
}

/* ---------- Alertes (Bootstrap .alert) ---------- */
QLabel.alert-info {
    background: #cff4fc; color: #055160;
    border: 1px solid #9eeaf9; border-radius: 8px; padding: 10px 14px;
}
QLabel.alert-warning {
    background: #fff3cd; color: #664d03;
    border: 1px solid #ffe69c; border-radius: 8px; padding: 10px 14px;
}
QLabel.alert-danger {
    background: #f8d7da; color: #58151c;
    border: 1px solid #f1aeb5; border-radius: 8px; padding: 10px 14px;
}
QLabel.alert-success {
    background: #d1e7dd; color: #0a3622;
    border: 1px solid #a3cfbb; border-radius: 8px; padding: 10px 14px;
}

/* ---------- Cartes (Bootstrap .card.shadow-sm) ---------- */
QFrame.card {
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}
QGroupBox {
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: #111827;
}

/* ---------- Tableaux (web : thead #1f4e78, lignes survolées) ---------- */
QTableView, QTableWidget {
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    gridline-color: #f3f4f6;
    alternate-background-color: #f8f9fa;
    selection-background-color: #cfe2ff;
    selection-color: #052c65;
}
QHeaderView::section {
    background-color: #1f4e78;
    color: white;
    padding: 8px;
    border: none;
    font-weight: 600;
}
QTableView::item, QTableWidget::item { padding: 6px; }
QTableCornerButton::section { background-color: #1f4e78; border: none; }

/* ---------- Barre latérale (identique à la sidebar web) ---------- */
QListWidget {
    background: #111827;
    color: #d1d5db;
    border: none;
    padding: 6px 0;
    outline: none;
}
QListWidget::item {
    padding: 11px 19px;
    border-left: 3px solid transparent;
}
QListWidget::item:selected {
    background: #1f2937;
    border-left: 3px solid #2563eb;
    color: white;
}
QListWidget::item:hover { background: #1f2937; color: white; }
QListWidget::item:disabled { padding: 12px 19px 4px; }

/* ---------- Divers ---------- */
QStatusBar { background: white; border-top: 1px solid #e5e7eb; }

QTabWidget::pane { border: 1px solid #dee2e6; border-radius: 8px; background: white; }
QTabBar::tab {
    background: transparent;
    color: #0d6efd;
    padding: 8px 16px;
    border: 1px solid transparent;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:hover { border-color: #e9ecef #e9ecef #dee2e6; }
QTabBar::tab:selected {
    background: white;
    color: #495057;
    border-color: #dee2e6 #dee2e6 white;
}

QMenu { background: white; border: 1px solid #ced4da; }
QMenu::item:selected { background: #0d6efd; color: white; }

QScrollBar:vertical { background: #f3f4f6; width: 10px; border: none; }
QScrollBar::handle:vertical { background: #c4c9d0; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #9ca3af; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #f3f4f6; height: 10px; border: none; }
QScrollBar::handle:horizontal { background: #c4c9d0; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }

/* ---------- Indicateur de synchronisation ---------- */
QLabel#sync_synced { color: #198754; font-weight: 600; }
QLabel#sync_pending { color: #d97706; font-weight: 600; }
QLabel#sync_error { color: #dc3545; font-weight: 600; }
QLabel#sync_offline { color: #6c757d; font-weight: 600; }
"""
