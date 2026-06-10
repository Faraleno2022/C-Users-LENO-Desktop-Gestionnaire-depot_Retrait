"""Fonctions utilitaires diverses."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from app.config import CURRENCY_SYMBOL, DATETIME_FMT


def now_iso() -> str:
    return datetime.now().strftime(DATETIME_FMT)


def new_uuid() -> str:
    return str(uuid.uuid4())


def format_money(value: float) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:,.0f} {CURRENCY_SYMBOL}".replace(",", " ")


def open_file(path) -> None:
    """Ouvre un fichier avec l'application par défaut du système d'exploitation."""
    p = str(Path(path))
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception:
        # L'ouverture automatique n'est pas critique : le fichier reste sur le disque.
        pass


def slugify(text: str) -> str:
    """Nettoie une chaîne pour l'utiliser dans un nom de fichier."""
    keep = []
    for ch in (text or "").strip():
        if ch.isalnum():
            keep.append(ch)
        elif ch in (" ", "-", "_"):
            keep.append("-")
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "document"


def parse_money(text: str) -> float:
    if text is None:
        raise ValueError("Montant vide")
    cleaned = str(text).replace(" ", "").replace(CURRENCY_SYMBOL, "").replace(",", ".").strip()
    if not cleaned:
        raise ValueError("Montant vide")
    value = float(cleaned)
    if value <= 0:
        raise ValueError("Le montant doit être strictement positif")
    return value
