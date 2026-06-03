"""Dialogues utilitaires."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QMessageBox, QWidget


def confirm(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    box.button(QMessageBox.Yes).setText("Oui")
    box.button(QMessageBox.No).setText("Non")
    return box.exec() == QMessageBox.Yes


def info(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def warn(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def error(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.critical(parent, title, text)


def access_denied(parent: QWidget) -> None:
    QMessageBox.warning(
        parent,
        "Accès refusé",
        "Accès refusé. Fonction réservée aux administrateurs.",
    )
