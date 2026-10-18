"""Impression des reçus sur imprimante thermique à tickets (Epson TM-T20III…).

Deux voies d'impression :

1. **ESC/POS direct** (voie principale) : le reçu est converti en commandes
   ESC/POS et envoyé en RAW au spouleur Windows. Aucune boîte de dialogue,
   aucune mise en page A4 : le ticket sort immédiatement à la bonne largeur
   (80 mm ou 58 mm) et le papier est coupé. Fonctionne avec le pilote Epson
   (« EPSON TM-T20III Receipt ») comme avec un pilote « Generic / Text Only ».

2. **Repli Qt** (dans les vues) : s'il n'y a aucune imprimante à tickets, la
   boîte de dialogue d'impression habituelle est proposée pour les imprimantes
   bureautiques.

L'imprimante est choisie automatiquement (pilote thermique détecté, imprimante
Windows par défaut…) ou imposée via Administration → Impression des tickets ou
la variable d'environnement EMAB_RECEIPT_PRINTER. Ce module n'importe pas Qt
pour rester testable et réutilisable.
"""
from __future__ import annotations

import html as html_mod
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

ENV_PRINTER = "EMAB_RECEIPT_PRINTER"

# Mots-clés : pilotes à tickets connus / imprimantes virtuelles à écarter.
# Partagés avec la console web (server/console_web.py).
THERMAL_KEYWORDS = (
    "pos", "thermal", "ticket", "receipt", "caisse", "58mm", "80mm",
    "xprinter", "rongta", "pozer", "tp150",
    "epson tm", "tm-t", "tm-m", "tm-u", "tm-p", "tm-l",
)
VIRTUAL_KEYWORDS = ("pdf", "xps", "onenote", "fax", "anydesk", "send to")

# Largeur utile en caractères (police A, 12 points par caractère).
COLUMNS = {"80": 48, "58": 32}


class ReceiptPrintError(Exception):
    """Échec d'impression (spouleur, pilote, imprimante hors ligne…)."""


class NoReceiptPrinter(ReceiptPrintError):
    """Aucune imprimante à tickets détectée : l'appelant peut proposer un repli."""


@dataclass
class Receipt:
    """Contenu d'un reçu indépendant du support (écran, ESC/POS, HTML)."""

    title: str                       # ex. "REÇU D'OPÉRATION"
    number: str                      # ex. "N° 42"
    date: str                        # ex. "2026-10-18 09:30:00"
    highlight_label: str             # ex. "DÉPÔT"
    highlight_value: str             # ex. "150 000 GNF"
    rows: List[Tuple[str, str]] = field(default_factory=list)
    footer: str = "Merci pour votre confiance."
    reference: str = ""              # uuid, imprimé en petit
    highlight_color: str = "#111827"  # couleur écran uniquement


# --- Imprimantes Windows ------------------------------------------------------

def windows_printers() -> tuple[str, list[str]]:
    """(imprimante par défaut, liste des imprimantes installées) via winspool.

    Renvoie des valeurs vides hors Windows ou en cas d'échec.
    """
    if not sys.platform.startswith("win"):
        return "", []
    import ctypes
    from ctypes import wintypes

    default, names = "", []
    try:
        winspool = ctypes.WinDLL("winspool.drv")

        n = wintypes.DWORD(0)
        winspool.GetDefaultPrinterW(None, ctypes.byref(n))
        if n.value:
            buf = ctypes.create_unicode_buffer(n.value)
            if winspool.GetDefaultPrinterW(buf, ctypes.byref(n)):
                default = buf.value or ""

        class PRINTER_INFO_4W(ctypes.Structure):
            _fields_ = [
                ("pPrinterName", wintypes.LPWSTR),
                ("pServerName", wintypes.LPWSTR),
                ("Attributes", wintypes.DWORD),
            ]

        PRINTER_ENUM_LOCAL, PRINTER_ENUM_CONNECTIONS = 2, 4
        flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
        needed, count = wintypes.DWORD(0), wintypes.DWORD(0)
        winspool.EnumPrintersW(flags, None, 4, None, 0,
                               ctypes.byref(needed), ctypes.byref(count))
        if needed.value:
            raw = ctypes.create_string_buffer(needed.value)
            if winspool.EnumPrintersW(flags, None, 4, raw, needed,
                                      ctypes.byref(needed), ctypes.byref(count)):
                arr = ctypes.cast(raw, ctypes.POINTER(PRINTER_INFO_4W * count.value)).contents
                names = [p.pPrinterName for p in arr if p.pPrinterName]
    except Exception:
        pass
    return default, names


def is_virtual(name: str) -> bool:
    low = (name or "").lower()
    return any(k in low for k in VIRTUAL_KEYWORDS)


def is_thermal(name: str) -> bool:
    low = (name or "").lower()
    return any(k in low for k in THERMAL_KEYWORDS)


def pick_receipt_printer(default: str, names: Sequence[str], requested: str = "") -> str:
    """Nom de l'imprimante à tickets à utiliser, ou '' si aucune n'est détectée.

    Ordre : nom imposé (réglage ou variable d'environnement) → imprimante
    Windows par défaut si elle est thermique → première imprimante thermique.
    Les imprimantes bureautiques ne sont PAS retenues : l'appelant garde alors
    la boîte de dialogue classique, mieux adaptée au papier A4.
    """
    requested = (requested or "").strip()
    if requested:
        for name in names:
            if name.casefold() == requested.casefold() and not is_virtual(name):
                return name
    if default and not is_virtual(default) and is_thermal(default):
        return default
    for name in names:
        if not is_virtual(name) and is_thermal(name):
            return name
    return ""


def detect_receipt_printer(requested: str = "") -> str:
    """Détection sur la machine courante (réglage > variable d'environnement)."""
    default, names = windows_printers()
    wanted = requested or os.environ.get(ENV_PRINTER, "")
    return pick_receipt_printer(default, names, wanted)


# --- ESC/POS ------------------------------------------------------------------

ESC, GS = b"\x1b", b"\x1d"
_CODEPAGE = "cp858"          # Latin-1 + € ; page de code 19 côté Epson


class EscPos:
    """Petit constructeur de flux ESC/POS (texte, alignement, gras, taille, coupe)."""

    def __init__(self, cols: int = 48) -> None:
        self.cols = cols
        self.buf = bytearray()
        self.buf += ESC + b"@"            # initialisation
        self.buf += ESC + b"t" + bytes([19])  # page de code PC858
        self.buf += ESC + b"R" + bytes([1])   # jeu international : France

    # -- primitives --
    def _enc(self, text: str) -> bytes:
        return text.encode(_CODEPAGE, errors="replace")

    def align(self, mode: str) -> "EscPos":
        self.buf += ESC + b"a" + bytes([{"left": 0, "center": 1, "right": 2}[mode]])
        return self

    def bold(self, on: bool) -> "EscPos":
        self.buf += ESC + b"E" + bytes([1 if on else 0])
        return self

    def size(self, width: int = 1, height: int = 1) -> "EscPos":
        """Multiplicateurs 1..8 (GS !)."""
        w = max(1, min(8, width)) - 1
        h = max(1, min(8, height)) - 1
        self.buf += GS + b"!" + bytes([(w << 4) | h])
        return self

    def text(self, line: str = "") -> "EscPos":
        self.buf += self._enc(line) + b"\n"
        return self

    def wrapped(self, text: str, cols: Optional[int] = None) -> "EscPos":
        cols = cols or self.cols
        for para in (text or "").splitlines() or [""]:
            words, line = para.split(" "), ""
            for w in words:
                if not line:
                    line = w
                elif len(line) + 1 + len(w) <= cols:
                    line += " " + w
                else:
                    self.text(line)
                    line = w
            self.text(line)
        return self

    def row(self, label: str, value: str) -> "EscPos":
        """Libellé à gauche, valeur alignée à droite ; passe à la ligne si trop long."""
        label, value = label or "", value or ""
        if len(label) + 1 + len(value) <= self.cols:
            self.text(label + " " * (self.cols - len(label) - len(value)) + value)
        else:
            self.wrapped(label)
            self.text(" " * max(0, self.cols - len(value)) + value if len(value) < self.cols else value)
        return self

    def separator(self, char: str = "-") -> "EscPos":
        return self.text(char * self.cols)

    def feed(self, lines: int = 1) -> "EscPos":
        self.buf += ESC + b"d" + bytes([max(0, min(255, lines))])
        return self

    def cut(self, partial: bool = True) -> "EscPos":
        # GS V 66/65 n : avance le papier puis coupe (partielle = laisse une attache)
        self.buf += GS + b"V" + bytes([66 if partial else 65, 3])
        return self

    def open_drawer(self) -> "EscPos":
        self.buf += ESC + b"p" + bytes([0, 25, 250])
        return self

    def bytes(self) -> bytes:
        return bytes(self.buf)


def build_escpos(receipt: Receipt, company: Optional[dict] = None,
                 paper_width: str = "80", open_drawer: bool = False) -> bytes:
    """Convertit un reçu en flux ESC/POS prêt à envoyer."""
    cols = COLUMNS.get(str(paper_width), COLUMNS["80"])
    p = EscPos(cols)
    company = company or {}

    # En-tête société
    p.align("center")
    name = (company.get("name") or "").strip()
    if name:
        p.bold(True).size(1, 2).wrapped(name, cols).size(1, 1).bold(False)
    for key in ("address", "phone", "email"):
        val = (company.get(key) or "").strip()
        if val:
            p.wrapped(val, cols)
    if name or any(company.get(k) for k in ("address", "phone", "email")):
        p.separator("=")

    # Titre du reçu
    p.bold(True).text(receipt.title).bold(False)
    p.text(f"{receipt.number}  {receipt.date}".strip())
    p.separator("-")

    # Montant en évidence
    p.bold(True).size(1, 2).text(receipt.highlight_label).size(1, 1)
    p.size(2, 2).text(receipt.highlight_value).size(1, 1).bold(False)
    p.separator("-")

    # Lignes de détail
    p.align("left")
    for label, value in receipt.rows:
        p.row(str(label), str(value))
    if receipt.reference:
        p.text("Ref. " + receipt.reference)
    p.separator("-")

    # Pied de page
    p.align("center")
    footer = (company.get("footer") or "").strip()
    if footer:
        p.wrapped(footer, cols)
    if receipt.footer:
        p.wrapped(receipt.footer, cols)
    p.feed(3).cut(partial=True)
    if open_drawer:
        p.open_drawer()
    return p.bytes()


# --- Envoi RAW au spouleur Windows ------------------------------------------

def send_raw(printer_name: str, data: bytes, doc_name: str = "Ticket EMAB") -> None:
    """Envoie des octets bruts (ESC/POS) à l'imprimante via le spouleur Windows."""
    if not sys.platform.startswith("win"):
        raise ReceiptPrintError("L'impression directe n'est disponible que sous Windows.")
    import ctypes
    from ctypes import wintypes

    class DOC_INFO_1W(ctypes.Structure):
        _fields_ = [
            ("pDocName", wintypes.LPWSTR),
            ("pOutputFile", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR),
        ]

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    winspool.StartDocPrinterW.restype = wintypes.DWORD
    winspool.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]

    handle = wintypes.HANDLE()
    if not winspool.OpenPrinterW(printer_name, ctypes.byref(handle), None):
        raise ReceiptPrintError(
            f"Imprimante « {printer_name} » introuvable ou inaccessible "
            f"(code {ctypes.get_last_error()})."
        )
    try:
        info = DOC_INFO_1W(doc_name, None, "RAW")
        job = winspool.StartDocPrinterW(handle, 1, ctypes.byref(info))
        if not job:
            raise ReceiptPrintError(
                f"Le spouleur a refusé le document (code {ctypes.get_last_error()}). "
                "Vérifiez que l'imprimante est allumée et connectée."
            )
        try:
            winspool.StartPagePrinter(handle)
            written = wintypes.DWORD(0)
            ok = winspool.WritePrinter(handle, data, len(data), ctypes.byref(written))
            winspool.EndPagePrinter(handle)
            if not ok or written.value != len(data):
                raise ReceiptPrintError(
                    f"Envoi incomplet ({written.value}/{len(data)} octets, code {ctypes.get_last_error()})."
                )
        finally:
            winspool.EndDocPrinter(handle)
    finally:
        winspool.ClosePrinter(handle)


def print_receipt(
    receipt: Receipt,
    company: Optional[dict] = None,
    *,
    printer: str = "",
    paper_width: str = "80",
    open_drawer: bool = False,
    sender: Callable[[str, bytes], None] = None,
) -> str:
    """Imprime un reçu sur l'imprimante à tickets. Retourne le nom utilisé.

    Lève NoReceiptPrinter si aucune imprimante thermique n'est disponible,
    ReceiptPrintError sur un échec d'envoi.
    """
    name = detect_receipt_printer(printer)
    if not name:
        raise NoReceiptPrinter(
            "Aucune imprimante à tickets détectée. Branchez l'imprimante (pilote "
            "installé) ou choisissez-la dans Administration → Impression des tickets."
        )
    data = build_escpos(receipt, company, paper_width=paper_width, open_drawer=open_drawer)
    (sender or send_raw)(name, data)
    return name


# --- HTML (aperçu écran et repli impression Qt) ------------------------------

def render_html(receipt: Receipt, company: Optional[dict] = None, *, for_print: bool = False) -> str:
    """Reçu en HTML : coloré pour l'écran, noir et étroit pour l'impression."""
    e = html_mod.escape
    company = company or {}
    color = "#000" if for_print else receipt.highlight_color
    muted = "#000" if for_print else "#6b7280"
    font = "'Consolas','Courier New',monospace" if for_print else "Segoe UI"
    rows = "".join(
        f"<tr><td><b>{e(str(k))}</b></td><td style='text-align:right'>{e(str(v))}</td></tr>"
        for k, v in receipt.rows
    )
    head = ""
    if company.get("name"):
        head += f"<div style='font-size:15px;font-weight:bold;'>{e(company['name'])}</div>"
    for key in ("address", "phone", "email"):
        if company.get(key):
            head += f"<div style='font-size:11px;color:{muted};'>{e(company[key])}</div>"
    footer = ""
    if company.get("footer"):
        footer += f"<div>{e(company['footer'])}</div>"
    if receipt.footer:
        footer += f"<div>{e(receipt.footer)}</div>"
    ref = (f"<tr><td><b>Référence</b></td><td style='font-size:10px;text-align:right'>{e(receipt.reference)}</td></tr>"
           if receipt.reference else "")
    return f"""
    <div style='font-family:{font}; padding:6px; color:#000;'>
      <div style='text-align:center; border-bottom:2px dashed #999; padding-bottom:8px;'>
        {head}
        <div style='font-size:16px; font-weight:bold; margin-top:4px;'>{e(receipt.title)}</div>
        <div style='color:{muted}; font-size:11px;'>{e(receipt.number)} — {e(receipt.date)}</div>
      </div>
      <div style='font-size:22px; font-weight:bold; color:{color}; text-align:center; margin:12px 0;'>
        {e(receipt.highlight_label)}<br>{e(receipt.highlight_value)}
      </div>
      <table style='width:100%; font-size:13px;' cellpadding='3'>{rows}{ref}</table>
      <div style='text-align:center; border-top:2px dashed #999; padding-top:8px; color:{muted}; font-size:11px;'>
        {footer}
      </div>
    </div>
    """


def test_receipt(printer_name: str = "") -> Receipt:
    """Reçu de démonstration pour le bouton « Imprimer un ticket test »."""
    from datetime import datetime
    return Receipt(
        title="TICKET DE TEST",
        number="N° 0",
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        highlight_label="TEST D'IMPRESSION",
        highlight_value="1 234 567 GNF",
        rows=[("Imprimante", printer_name or "auto"), ("Accents", "éèàçù € ÉÀ"), ("Statut", "OK")],
        footer="Si ce ticket est lisible et coupé, l'imprimante est prête.",
        reference="00000000-0000-0000-0000-000000000000",
    )
