"""Feuille de style globale (QSS)."""

QSS = """
* {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #1f2937;
}
QMainWindow, QDialog, QWidget#central {
    background-color: #f3f4f6;
}
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit {
    background: white;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 10px;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2563eb;
}
QPushButton {
    background-color: #2563eb;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover { background-color: #1d4ed8; }
QPushButton:pressed { background-color: #1e40af; }
QPushButton:disabled { background-color: #9ca3af; color: #f3f4f6; }
QPushButton.secondary {
    background-color: #e5e7eb;
    color: #1f2937;
}
QPushButton.secondary:hover { background-color: #d1d5db; }
QPushButton.danger { background-color: #dc2626; }
QPushButton.danger:hover { background-color: #b91c1c; }
QPushButton.success { background-color: #16a34a; }
QPushButton.success:hover { background-color: #15803d; }

QLabel.h1 { font-size: 22px; font-weight: 700; color: #111827; }
QLabel.h2 { font-size: 17px; font-weight: 600; color: #111827; }
QLabel.muted { color: #6b7280; }

QFrame.card {
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}

QTableView, QTableWidget {
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    gridline-color: #f3f4f6;
    selection-background-color: #dbeafe;
    selection-color: #1e3a8a;
}
QHeaderView::section {
    background-color: #1f4e78;
    color: white;
    padding: 8px;
    border: none;
    font-weight: 600;
}
QTableView::item, QTableWidget::item { padding: 6px; }

QListWidget {
    background: #111827;
    color: #f9fafb;
    border: none;
    padding: 8px 0;
    outline: none;
}
QListWidget::item {
    padding: 12px 18px;
    border-left: 3px solid transparent;
}
QListWidget::item:selected {
    background: #1f2937;
    border-left: 3px solid #2563eb;
    color: white;
}
QListWidget::item:hover { background: #1f2937; }

QStatusBar { background: white; border-top: 1px solid #e5e7eb; }
QTabWidget::pane { border: 1px solid #e5e7eb; border-radius: 8px; background: white; }
QTabBar::tab {
    background: #e5e7eb;
    padding: 8px 16px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: white; }
QMenu { background: white; border: 1px solid #d1d5db; }
QMenu::item:selected { background: #dbeafe; color: #1e3a8a; }

QLabel#sync_synced { color: #16a34a; font-weight: 600; }
QLabel#sync_pending { color: #d97706; font-weight: 600; }
QLabel#sync_error { color: #dc2626; font-weight: 600; }
QLabel#sync_offline { color: #6b7280; font-weight: 600; }
"""
