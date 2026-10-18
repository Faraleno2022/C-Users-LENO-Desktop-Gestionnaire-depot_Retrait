"""Imprimantes à tickets de la console locale : détection, ESC/POS, envoi direct.

Pourquoi : le ticket HTML imprimé par Chrome exige un vrai pilote graphique
(Epson APD, POS-80…). Avec le pilote Windows « Generic / Text Only », ou sans
pilote adapté, Chrome n'imprime rien. Ici, la console locale convertit le
ticket en commandes ESC/POS et les envoie en RAW au spouleur Windows, comme
l'application bureau : aucun dialogue, papier coupé, quel que soit le pilote.

Ce module n'a aucune dépendance (stdlib + ctypes) ; il n'importe pas Django
pour rester utilisable par `console_web.py` avant l'initialisation du site.
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

ENV_PRINTER = "EMAB_RECEIPT_PRINTER"

# Mots-clés : pilotes à tickets connus / imprimantes virtuelles à écarter.
# Même liste que app/utils/receipt_printer.py (application de bureau).
THERMAL_KEYWORDS = (
    "pos", "thermal", "ticket", "receipt", "caisse", "58mm", "80mm",
    "xprinter", "rongta", "pozer", "tp150",
    "epson tm", "tm-t", "tm-m", "tm-u", "tm-p", "tm-l",
)
VIRTUAL_KEYWORDS = ("pdf", "xps", "onenote", "fax", "anydesk", "send to")

# Largeur utile en caractères (police A).
COLUMNS = {"80": 48, "58": 32}


class PrintError(Exception):
    """Échec d'envoi à l'imprimante (spouleur, imprimante éteinte…)."""


# --- Détection ---------------------------------------------------------------

def is_virtual(name: str) -> bool:
    low = (name or "").lower()
    return any(k in low for k in VIRTUAL_KEYWORDS)


def is_thermal(name: str) -> bool:
    low = (name or "").lower()
    return any(k in low for k in THERMAL_KEYWORDS)


def windows_printers() -> Tuple[str, List[str]]:
    """(imprimante Windows par défaut, imprimantes installées) via winspool."""
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


def pick_receipt_printer(default: str, names: Sequence[str], requested: str = "",
                         fallback: bool = False) -> str:
    """Imprimante à tickets à utiliser, ou '' si aucune.

    Ordre : nom imposé (variable d'environnement ou réglage) → imprimante par
    défaut de Windows si elle est thermique → première imprimante thermique.
    Les imprimantes virtuelles (PDF, XPS, Fax…) ne sont jamais retenues.
    `fallback=True` (impression via Chrome) accepte en dernier recours une
    imprimante physique quelconque ; l'envoi ESC/POS direct, lui, ne doit
    jamais viser une imprimante bureautique.
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
    if fallback:
        if default and not is_virtual(default):
            return default
        for name in names:
            if not is_virtual(name):
                return name
    return ""


def requested_printer(configured: str = "") -> str:
    """Nom imposé : variable d'environnement, sinon réglage de la console."""
    return os.environ.get(ENV_PRINTER, "").strip() or (configured or "").strip()


def detect_ticket_printer(configured: str = "") -> str:
    """Imprimante à tickets (ESC/POS direct) de ce poste, ou ''."""
    default, names = windows_printers()
    return pick_receipt_printer(default, names, requested_printer(configured), fallback=False)


# --- ESC/POS -----------------------------------------------------------------

ESC, GS = b"\x1b", b"\x1d"
_CODEPAGE = "cp858"  # Latin-1 + € ; page de code 19 côté Epson


class EscPos:
    """Petit constructeur de flux ESC/POS (texte, alignement, gras, taille, coupe)."""

    def __init__(self, cols: int = 48) -> None:
        self.cols = cols
        self.buf = bytearray()
        self.buf += ESC + b"@"                 # initialisation
        self.buf += ESC + b"t" + bytes([19])   # page de code PC858
        self.buf += ESC + b"R" + bytes([1])    # jeu international : France

    def _enc(self, text: str) -> bytes:
        return text.encode(_CODEPAGE, errors="replace")

    def align(self, mode: str) -> "EscPos":
        self.buf += ESC + b"a" + bytes([{"left": 0, "center": 1, "right": 2}[mode]])
        return self

    def bold(self, on: bool) -> "EscPos":
        self.buf += ESC + b"E" + bytes([1 if on else 0])
        return self

    def size(self, width: int = 1, height: int = 1) -> "EscPos":
        w, h = max(1, min(8, width)) - 1, max(1, min(8, height)) - 1
        self.buf += GS + b"!" + bytes([(w << 4) | h])
        return self

    def text(self, line: str = "") -> "EscPos":
        self.buf += self._enc(line) + b"\n"
        return self

    def wrapped(self, text: str, cols: Optional[int] = None) -> "EscPos":
        cols = cols or self.cols
        for para in (text or "").splitlines() or [""]:
            line = ""
            for word in para.split(" "):
                if not line:
                    line = word
                elif len(line) + 1 + len(word) <= cols:
                    line += " " + word
                else:
                    self.text(line)
                    line = word
            self.text(line)
        return self

    def row(self, label: str, value: str) -> "EscPos":
        """Libellé à gauche, valeur à droite ; à la ligne si trop long."""
        label, value = str(label or ""), str(value or "")
        if len(label) + 1 + len(value) <= self.cols:
            self.text(label + " " * (self.cols - len(label) - len(value)) + value)
        else:
            self.wrapped(label)
            self.text(" " * max(0, self.cols - len(value)) + value)
        return self

    def separator(self, char: str = "-") -> "EscPos":
        return self.text(char * self.cols)

    def feed(self, lines: int = 1) -> "EscPos":
        self.buf += ESC + b"d" + bytes([max(0, min(255, lines))])
        return self

    def cut(self) -> "EscPos":
        self.buf += GS + b"V" + bytes([66, 3])  # avance puis coupe partielle
        return self

    def bytes(self) -> bytes:
        return bytes(self.buf)


def build_ticket(*, company: dict, title: str, number: str, date: str,
                 info_rows: Iterable[Tuple[str, str]],
                 items: Iterable[dict],
                 balance_before: Optional[str], action_label: str, action_value: str,
                 balance_after: Optional[str], footer: Iterable[str],
                 paper_width: str = "80") -> bytes:
    """Ticket de dépôt / retrait / vente en ESC/POS.

    items : [{"name", "detail", "total"}] (lignes de vente, formatées).
    """
    cols = COLUMNS.get(str(paper_width), COLUMNS["80"])
    p = EscPos(cols)

    p.align("center")
    name = (company.get("name") or "").strip()
    if name:
        p.bold(True).size(1, 2).wrapped(name, cols).size(1, 1).bold(False)
    for key in ("address", "phone"):
        val = (company.get(key) or "").strip()
        if val:
            p.wrapped(val, cols)
    p.separator("=")
    p.bold(True).text(title).bold(False)
    p.text(f"{number}  {date}".strip())
    p.separator("-")

    p.align("left")
    for label, value in info_rows:
        if value not in (None, ""):
            p.row(label, value)

    items = list(items)
    if items:
        p.separator("-")
        for it in items:
            p.wrapped(str(it.get("name") or ""))
            p.row("  " + str(it.get("detail") or ""), str(it.get("total") or ""))

    p.separator("-")
    if balance_before is not None:
        p.row("Solde avant", balance_before)
    p.align("center")
    p.bold(True).size(1, 2).text(action_label).size(2, 2).text(action_value).size(1, 1).bold(False)
    p.align("left")
    if balance_after is not None:
        p.bold(True).row("Solde restant", balance_after).bold(False)
    p.separator("-")

    p.align("center")
    for line in footer:
        if (line or "").strip():
            p.wrapped(line.strip(), cols)
    p.feed(3).cut()
    return p.bytes()


# --- Envoi RAW au spouleur Windows -------------------------------------------

def send_raw(printer_name: str, data: bytes, doc_name: str = "Ticket") -> None:
    """Envoie des octets bruts (ESC/POS) à l'imprimante via le spouleur."""
    if not sys.platform.startswith("win"):
        raise PrintError("L'impression directe n'est disponible que sous Windows.")
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
        raise PrintError(
            f"Imprimante « {printer_name} » introuvable ou inaccessible "
            f"(code {ctypes.get_last_error()})."
        )
    try:
        info = DOC_INFO_1W(doc_name, None, "RAW")
        if not winspool.StartDocPrinterW(handle, 1, ctypes.byref(info)):
            raise PrintError(
                f"Le spouleur a refusé le document (code {ctypes.get_last_error()}). "
                "Vérifiez que l'imprimante est allumée et connectée."
            )
        try:
            winspool.StartPagePrinter(handle)
            written = wintypes.DWORD(0)
            ok = winspool.WritePrinter(handle, data, len(data), ctypes.byref(written))
            winspool.EndPagePrinter(handle)
            if not ok or written.value != len(data):
                raise PrintError(
                    f"Envoi incomplet ({written.value}/{len(data)} octets, code {ctypes.get_last_error()})."
                )
        finally:
            winspool.EndDocPrinter(handle)
    finally:
        winspool.ClosePrinter(handle)


def print_ticket_bytes(data: bytes, configured: str = "",
                       sender: Optional[Callable[[str, bytes], None]] = None) -> str:
    """Envoie `data` à l'imprimante à tickets détectée ; retourne son nom.

    Lève PrintError si aucune imprimante à tickets n'est disponible ou si
    l'envoi échoue (l'appelant retombe alors sur l'impression du navigateur).
    """
    name = detect_ticket_printer(configured)
    if not name:
        raise PrintError("Aucune imprimante à tickets détectée.")
    (sender or send_raw)(name, data)
    return name
