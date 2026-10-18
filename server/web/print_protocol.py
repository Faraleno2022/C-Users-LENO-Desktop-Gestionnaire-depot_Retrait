"""Impression directe depuis le site en ligne : lien « emab-print: ».

Le serveur en ligne (Render) n'a pas accès à l'imprimante de la caisse, et
l'impression par le navigateur exige un vrai pilote graphique (le pilote
Windows « Generic / Text Only » n'imprime rien). Solution : le site fabrique un
lien `emab-print:v1.<ticket compressé>` ; l'installateur de la console locale
enregistre ce protocole dans Windows (HKCU) ; un clic sur le lien lance
`EMAB-Console-Web.exe --print-url "<lien>"`, qui décode le ticket, le convertit
en ESC/POS et l'envoie à l'imprimante à tickets du poste.

Sécurité : le lien ne transporte que du texte de ticket. Le gestionnaire le
valide strictement (types, tailles, caractères de contrôle retirés pour
empêcher toute injection de commandes ESC/POS) et choisit lui-même
l'imprimante : jamais une imprimante imposée par le lien.

Ce module n'importe pas Django : il sert aussi bien au serveur (génération des
liens) qu'au lanceur de la console (décodage et impression).
"""
from __future__ import annotations

import base64
import json
import os
import sys
import zlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

SCHEME = "emab-print"
VERSION = "v1"
# Windows limite les adresses transmises à un protocole à environ 2000
# caractères : au-delà, le site n'affiche pas le bouton d'impression directe.
MAX_URL_LENGTH = 1900
MAX_DECOMPRESSED = 24_000

MAX_ITEMS = 40
MAX_INFO_ROWS = 10
MAX_FOOTER = 5


class ProtocolError(Exception):
    """Lien invalide ou impression impossible."""


# --- Encodage (serveur) ----------------------------------------------------------

def encode(kwargs: dict) -> str:
    """Lien `emab-print:` pour les arguments de `printers.build_ticket`."""
    raw = json.dumps(kwargs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")
    return f"{SCHEME}:{VERSION}.{token}"


def encode_checked(kwargs: dict) -> str:
    """Comme `encode`, mais renvoie '' si le lien dépasse la limite de Windows."""
    url = encode(kwargs)
    return url if len(url) <= MAX_URL_LENGTH else ""


# --- Décodage et validation (poste) --------------------------------------------

def _text(value, limit: int) -> str:
    """Texte sûr : sans caractères de contrôle (ESC, GS…), tronqué."""
    s = "" if value is None else str(value)
    s = "".join(" " if ch in "\r\n\t" else ch for ch in s)
    s = "".join(ch for ch in s if ch >= " " and ch != "\x7f")
    return s.strip()[:limit]


def _optional(value, limit: int) -> Optional[str]:
    return None if value is None else _text(value, limit)


def sanitize(data) -> dict:
    """Valide un ticket décodé et renvoie les arguments de `build_ticket`."""
    if not isinstance(data, dict):
        raise ProtocolError("Ticket invalide.")
    company = data.get("company") if isinstance(data.get("company"), dict) else {}
    rows = data.get("info_rows") if isinstance(data.get("info_rows"), list) else []
    items = data.get("items") if isinstance(data.get("items"), list) else []
    footer = data.get("footer") if isinstance(data.get("footer"), list) else []

    info_rows = []
    for row in rows[:MAX_INFO_ROWS]:
        if not (isinstance(row, (list, tuple)) and len(row) == 2):
            raise ProtocolError("Ticket invalide (lignes d'information).")
        info_rows.append((_text(row[0], 30), _text(row[1], 60)))
    clean_items = []
    for it in items[:MAX_ITEMS]:
        if not isinstance(it, dict):
            raise ProtocolError("Ticket invalide (articles).")
        clean_items.append({"name": _text(it.get("name"), 80),
                            "detail": _text(it.get("detail"), 40),
                            "total": _text(it.get("total"), 30)})
    return {
        "company": {k: _text(company.get(k), 80) for k in ("name", "address", "phone")},
        "title": _text(data.get("title"), 60),
        "number": _text(data.get("number"), 30),
        "date": _text(data.get("date"), 30),
        "info_rows": info_rows,
        "items": clean_items,
        "balance_before": _optional(data.get("balance_before"), 30),
        "action_label": _text(data.get("action_label"), 40),
        "action_value": _text(data.get("action_value"), 40),
        "balance_after": _optional(data.get("balance_after"), 30),
        "footer": [_text(x, 120) for x in footer[:MAX_FOOTER]],
        "paper_width": "58" if str(data.get("paper_width")) == "58" else "80",
    }


def decode(url: str) -> dict:
    """Arguments validés de `printers.build_ticket` à partir d'un lien."""
    url = (url or "").strip().strip('"').strip("'")
    if url[: len(SCHEME) + 1].lower() != SCHEME + ":":
        raise ProtocolError("Lien d'impression non reconnu.")
    body = url[len(SCHEME) + 1:].lstrip("/").rstrip("/")
    version, _, token = body.partition(".")
    if version.lower() != VERSION or not token:
        raise ProtocolError("Version de lien non prise en charge : mettez à jour la console.")
    try:
        packed = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(packed, MAX_DECOMPRESSED)
        if decompressor.unconsumed_tail:
            raise ProtocolError("Ticket trop volumineux.")
        data = json.loads(raw.decode("utf-8"))
    except ProtocolError:
        raise
    except Exception as exc:
        raise ProtocolError("Lien d'impression illisible ou tronqué.") from exc
    return sanitize(data)


def print_url(url: str, configured: str = "", sender: Optional[Callable[[str, bytes], None]] = None) -> str:
    """Décode le lien, construit l'ESC/POS et l'envoie à l'imprimante à tickets.

    Retourne le nom de l'imprimante utilisée. Lève ProtocolError ou
    `printers.PrintError`.
    """
    from web import printers
    kwargs = decode(url)
    data = printers.build_ticket(**kwargs)
    return printers.print_ticket_bytes(data, configured, sender)


# --- Point d'entrée du lanceur (EMAB-Console-Web.exe --print-url "<lien>") ------

def _data_dir() -> Path:
    env = os.environ.get("EMAB_DATA_DIR")
    if env:
        return Path(env)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EMAB GROUP" / "ConsoleWeb"


def _configured_printer(data_dir: Path) -> str:
    try:
        cfg = json.loads((data_dir / "printer_config.json").read_text(encoding="utf-8-sig"))
        return str((cfg or {}).get("printer") or "").strip()
    except (OSError, ValueError):
        return ""


def _log(data_dir: Path, message: str) -> None:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(data_dir / "print_handler.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except OSError:
        pass


def _message_box(text: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "EMAB-SKS - Impression du ticket", 0x10)
    except Exception:
        pass


def run(argv: list[str], sender: Optional[Callable[[str, bytes], None]] = None,
        show_errors: bool = True) -> int:
    """Traite `--print-url <lien>` ; 0 si le ticket est parti, 1 sinon."""
    data_dir = _data_dir()
    try:
        url = argv[argv.index("--print-url") + 1]
    except (ValueError, IndexError):
        _log(data_dir, "Appel sans lien --print-url.")
        return 2
    try:
        used = print_url(url, _configured_printer(data_dir), sender)
    except ProtocolError as exc:
        _log(data_dir, f"Lien refusé : {exc}")
        if show_errors:
            _message_box(str(exc))
        return 1
    except Exception as exc:  # PrintError ou imprévu
        _log(data_dir, f"Échec d'impression : {exc}")
        if show_errors:
            _message_box(f"{exc}\n\nVérifiez que l'imprimante est allumée et branchée, "
                         "ou lancez Diagnostic_Imprimante.cmd.")
        return 1
    _log(data_dir, f"Ticket envoyé à « {used} ».")
    return 0
