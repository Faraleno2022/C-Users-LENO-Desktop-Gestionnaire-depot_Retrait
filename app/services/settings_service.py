"""Paramètres persistés dans la table app_settings (clé/valeur).

Sert notamment à stocker la configuration de synchronisation : URL du serveur,
jeton du poste (device token) et nom du poste. Les variables d'environnement
GESTIONNAIRE_SERVER_URL / GESTIONNAIRE_DEVICE_TOKEN ont priorité si elles sont
définies (utile pour un déploiement scripté).
"""
from __future__ import annotations

import os
from typing import Optional

from app.db.database import get_connection

# Clés de configuration de synchronisation
KEY_SERVER_URL = "sync.server_url"
KEY_DEVICE_TOKEN = "sync.device_token"
KEY_DEVICE_NAME = "sync.device_name"

# Clés de la sauvegarde planifiée (automatique)
KEY_AUTO_BACKUP_ENABLED = "backup.auto_enabled"
KEY_AUTO_BACKUP_INTERVAL = "backup.auto_interval_days"
KEY_AUTO_BACKUP_LAST = "backup.auto_last_at"
KEY_AUTO_BACKUP_KEEP = "backup.auto_keep"

DEFAULT_AUTO_BACKUP_INTERVAL = 1   # tous les jours
DEFAULT_AUTO_BACKUP_KEEP = 10      # nombre de sauvegardes auto conservées

# Clés de la synchronisation automatique
KEY_AUTO_SYNC_ENABLED = "sync.auto_enabled"
KEY_AUTO_SYNC_INTERVAL = "sync.auto_interval_seconds"

DEFAULT_AUTO_SYNC_INTERVAL = 15  # secondes

# Clés de l'identité de la société (en-tête des bons et documents PDF)
KEY_COMPANY_NAME = "company.name"
KEY_COMPANY_ADDRESS = "company.address"
KEY_COMPANY_PHONE = "company.phone"
KEY_COMPANY_EMAIL = "company.email"
KEY_COMPANY_FOOTER = "company.footer"

_ENV_OVERRIDES = {
    KEY_SERVER_URL: "GESTIONNAIRE_SERVER_URL",
    KEY_DEVICE_TOKEN: "GESTIONNAIRE_DEVICE_TOKEN",
    KEY_DEVICE_NAME: "GESTIONNAIRE_DEVICE_NAME",
}


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    env_var = _ENV_OVERRIDES.get(key)
    if env_var:
        env_val = os.environ.get(env_var)
        if env_val:
            return env_val
    conn = get_connection()
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row is None or row["value"] is None:
        return default
    return row["value"]


def set_setting(key: str, value: Optional[str]) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO app_settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
    conn.commit()


# --- Helpers de synchronisation ---------------------------------------------

def get_sync_config() -> dict:
    return {
        "server_url": (get_setting(KEY_SERVER_URL, "") or "").strip(),
        "device_token": (get_setting(KEY_DEVICE_TOKEN, "") or "").strip(),
        "device_name": (get_setting(KEY_DEVICE_NAME, "") or "").strip(),
    }


def set_sync_config(server_url: str, device_token: str, device_name: str = "") -> None:
    set_setting(KEY_SERVER_URL, (server_url or "").strip().rstrip("/"))
    set_setting(KEY_DEVICE_TOKEN, (device_token or "").strip())
    set_setting(KEY_DEVICE_NAME, (device_name or "").strip())


def is_sync_configured() -> bool:
    cfg = get_sync_config()
    return bool(cfg["server_url"] and cfg["device_token"])


# --- Helpers de sauvegarde planifiée ----------------------------------------

def _to_int(value: Optional[str], default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_auto_backup_config() -> dict:
    """Configuration de la sauvegarde automatique.

    enabled : activée par défaut. interval_days : périodicité. last_at : horodatage
    (chaîne ISO) de la dernière sauvegarde auto. keep : nombre conservé.
    """
    enabled = get_setting(KEY_AUTO_BACKUP_ENABLED)
    return {
        "enabled": True if enabled is None else (enabled == "1"),
        "interval_days": max(1, _to_int(get_setting(KEY_AUTO_BACKUP_INTERVAL),
                                        DEFAULT_AUTO_BACKUP_INTERVAL)),
        "last_at": get_setting(KEY_AUTO_BACKUP_LAST, "") or "",
        "keep": max(1, _to_int(get_setting(KEY_AUTO_BACKUP_KEEP), DEFAULT_AUTO_BACKUP_KEEP)),
    }


def set_auto_backup_config(enabled: bool, interval_days: int, keep: Optional[int] = None) -> None:
    set_setting(KEY_AUTO_BACKUP_ENABLED, "1" if enabled else "0")
    set_setting(KEY_AUTO_BACKUP_INTERVAL, str(max(1, int(interval_days))))
    if keep is not None:
        set_setting(KEY_AUTO_BACKUP_KEEP, str(max(1, int(keep))))


def mark_auto_backup_done(when_iso: str) -> None:
    set_setting(KEY_AUTO_BACKUP_LAST, when_iso)


# --- Helpers de synchronisation automatique ---------------------------------

def get_auto_sync_config() -> dict:
    enabled = get_setting(KEY_AUTO_SYNC_ENABLED)
    return {
        # Activée par défaut : la sync ne démarre réellement que lorsque
        # l'URL serveur et le jeton du poste sont configurés.
        "enabled": (enabled == "1") if enabled is not None else True,
        "interval_seconds": max(15, _to_int(get_setting(KEY_AUTO_SYNC_INTERVAL),
                                            DEFAULT_AUTO_SYNC_INTERVAL)),
    }


def set_auto_sync_config(enabled: bool, interval_seconds: int) -> None:
    set_setting(KEY_AUTO_SYNC_ENABLED, "1" if enabled else "0")
    set_setting(KEY_AUTO_SYNC_INTERVAL, str(max(15, int(interval_seconds))))


# --- Identité de la société (en-tête des documents) -------------------------

def get_company_info() -> dict:
    """Coordonnées affichées en en-tête des bons et documents PDF.

    À défaut de valeur saisie, on retombe sur le nom de l'application pour que
    les documents restent présentables dès la première utilisation.
    """
    from app.config import APP_NAME

    return {
        "name": (get_setting(KEY_COMPANY_NAME, "") or "").strip() or APP_NAME,
        "address": (get_setting(KEY_COMPANY_ADDRESS, "") or "").strip(),
        "phone": (get_setting(KEY_COMPANY_PHONE, "") or "").strip(),
        "email": (get_setting(KEY_COMPANY_EMAIL, "") or "").strip(),
        "footer": (get_setting(KEY_COMPANY_FOOTER, "") or "").strip(),
    }


def set_company_info(
    name: str = "",
    address: str = "",
    phone: str = "",
    email: str = "",
    footer: str = "",
) -> None:
    set_setting(KEY_COMPANY_NAME, (name or "").strip())
    set_setting(KEY_COMPANY_ADDRESS, (address or "").strip())
    set_setting(KEY_COMPANY_PHONE, (phone or "").strip())
    set_setting(KEY_COMPANY_EMAIL, (email or "").strip())
    set_setting(KEY_COMPANY_FOOTER, (footer or "").strip())
