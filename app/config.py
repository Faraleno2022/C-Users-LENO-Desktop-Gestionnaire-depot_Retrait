"""Configuration globale de l'application."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Gestionnaire Dépôt / Retrait"
APP_VERSION = "1.0.0"
ORG_NAME = "Gestionnaire"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = BASE_DIR / "exports"
LOG_DIR = BASE_DIR / "logs"

DB_PATH = DATA_DIR / "gestionnaire.db"

DEFAULT_SUPER_ADMIN = {
    "identifiant": "admin",
    "password": "admin123",
    "nom_complet": "Super Administrateur",
    "matricule": "ADM-000",
    "telephone": "",
    "role": "super_admin",
}

PAGE_SIZE = 50
CURRENCY_SYMBOL = "GNF"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
DATE_FMT = "%Y-%m-%d"

SYNC_STATUS_PENDING = "pending"
SYNC_STATUS_SYNCED = "synced"
SYNC_STATUS_CONFLICT = "conflict"
SYNC_STATUS_ERROR = "error"

ROLES = ("super_admin", "admin", "superviseur", "caissier")
ROLE_LABELS = {
    "super_admin": "Super administrateur",
    "admin": "Administrateur",
    "superviseur": "Superviseur",
    "caissier": "Caissier",
}


def ensure_directories() -> None:
    for d in (DATA_DIR, BACKUP_DIR, EXPORT_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
