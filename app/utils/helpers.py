"""Fonctions utilitaires diverses."""
from __future__ import annotations

import uuid
from datetime import datetime

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
