"""Impression d'un reçu depuis une vue Qt : ticket thermique d'abord, dialogue sinon.

Partagé par les écrans Dépôts/Retraits et Ventes :
  - une imprimante à tickets est détectée → envoi ESC/POS direct, sans dialogue ;
  - aucune → boîte de dialogue d'impression Qt classique (imprimantes A4),
    sauf en impression automatique où l'on ne dérange pas le caissier.
"""
from __future__ import annotations

from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QWidget

from app.services import settings_service
from app.ui.widgets.dialogs import error
from app.utils import receipt_printer


def print_receipt(parent: QWidget, receipt: receipt_printer.Receipt, *, auto: bool = False) -> bool:
    """Imprime `receipt`. Retourne True si quelque chose a été envoyé.

    auto=True : déclenché juste après la validation ; silencieux s'il n'y a
    pas d'imprimante à tickets (le bouton « Imprimer » reste disponible).
    """
    cfg = settings_service.get_print_config()
    company = settings_service.get_company_info()
    try:
        receipt_printer.print_receipt(
            receipt, company,
            printer=cfg["printer"],
            paper_width=cfg["paper_width"],
            open_drawer=cfg["open_drawer"],
        )
        return True
    except receipt_printer.NoReceiptPrinter:
        if auto:
            return False
        return _print_with_dialog(parent, receipt, company)
    except receipt_printer.ReceiptPrintError as exc:
        error(parent, "Impression du reçu", str(exc))
        return False


def _print_with_dialog(parent: QWidget, receipt: receipt_printer.Receipt, company: dict) -> bool:
    printer = QPrinter(QPrinter.HighResolution)
    dlg = QPrintDialog(printer, parent)
    if dlg.exec() != QPrintDialog.Accepted:
        return False
    doc = QTextDocument()
    doc.setHtml(receipt_printer.render_html(receipt, company, for_print=True))
    doc.print_(printer)
    return True
