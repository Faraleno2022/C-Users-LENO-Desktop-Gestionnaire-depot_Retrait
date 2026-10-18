"""Réglages d'impression des tickets de la console web.

Deux niveaux :

- **Serveur** (table WebSetting, partagés par tous les utilisateurs de cette
  console) : coordonnées imprimées en en-tête du ticket, pied de page, largeur
  de rouleau par défaut, impression automatique après chaque validation.
- **Poste** (console web locale uniquement, fichier `printer_config.json` dans
  le dossier de données) : nom de l'imprimante Windows à utiliser. Lu par
  `console_web.py` au lancement pour régler l'impression directe de Chrome.

Sur le serveur en ligne (Render), la partie « poste » est masquée : le
navigateur de l'utilisateur choisit lui-même l'imprimante.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from sync.models import WebSetting

BRAND = "EMAB-SKS"

DEFAULTS = {
    "company_name": BRAND,
    "company_address": "",
    "company_phone": "",
    "ticket_footer": "Merci de votre confiance",
    "paper_width": "80",
    "auto_print": "0",
}
KEYS = tuple(DEFAULTS)
PRINTER_CONFIG_FILENAME = "printer_config.json"


# --- Réglages serveur ---------------------------------------------------------

def get_ticket_settings() -> dict:
    """Réglages effectifs (valeurs par défaut comblées, types normalisés)."""
    stored = {s.key: s.value for s in WebSetting.objects.filter(key__in=KEYS)}
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in stored.items() if v is not None})
    if not cfg["company_name"].strip():
        cfg["company_name"] = BRAND
    if cfg["paper_width"] not in ("80", "58"):
        cfg["paper_width"] = "80"
    cfg["auto_print"] = cfg["auto_print"] == "1"
    return cfg


def save_ticket_settings(**values) -> None:
    for key, value in values.items():
        if key not in KEYS:
            continue
        if key == "auto_print":
            value = "1" if value in (True, "1", "on", "true") else "0"
        elif key == "paper_width":
            value = "58" if str(value).strip() == "58" else "80"
        else:
            value = str(value or "").strip()
        WebSetting.objects.update_or_create(key=key, defaults={"value": value})


# --- Réglages du poste (console locale) --------------------------------------

def is_local_console() -> bool:
    return os.environ.get("EMAB_LOCAL_CONSOLE") == "1"


def printer_config_path() -> Optional[Path]:
    data_dir = os.environ.get("EMAB_DATA_DIR")
    return Path(data_dir) / PRINTER_CONFIG_FILENAME if data_dir else None


def get_local_printer() -> str:
    """Nom d'imprimante imposé sur ce poste ('' = détection automatique)."""
    path = printer_config_path()
    if not path or not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    return str((data or {}).get("printer") or "").strip()


def set_local_printer(name: str) -> None:
    path = printer_config_path()
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"printer": (name or "").strip()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_local_printers() -> tuple[str, list[str]]:
    """(imprimante Windows par défaut, imprimantes installées) sur ce poste."""
    if not is_local_console():
        return "", []
    try:
        import console_web  # module du lanceur, présent sur la console locale
        return console_web._windows_printers()
    except Exception:
        return "", []


def detected_local_printer() -> str:
    if not is_local_console():
        return ""
    try:
        import console_web
        return console_web._pick_receipt_printer()
    except Exception:
        return ""
