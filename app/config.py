"""Configuration globale de l'application."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "EMAB GROUP — Gestionnaire Dépôt / Retrait"
# Version de l'app desktop. À INCRÉMENTER à chaque release publiée sur GitHub
# (tag « desktop-vX.Y.Z » + installateur ; reporter la valeur dans installer.iss).
APP_VERSION = "1.1.0"
ORG_NAME = "EMAB GROUP"

IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    # Exécutable PyInstaller : les données vont dans un dossier utilisateur
    # stable (PAS le dossier temporaire d'extraction, effacé à chaque run).
    BASE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EMAB GROUP" / "Gestionnaire"
    # Les ressources embarquées (assets) sont extraites dans sys._MEIPASS.
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    RESOURCE_DIR = BASE_DIR

DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = BASE_DIR / "exports"
LOG_DIR = BASE_DIR / "logs"
ASSETS_DIR = RESOURCE_DIR / "assets"

DB_PATH = DATA_DIR / "gestionnaire.db"
LOGO_PATH = ASSETS_DIR / "logo_emab.png"
ICON_PATH = ASSETS_DIR / "logo_emab.ico"

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
