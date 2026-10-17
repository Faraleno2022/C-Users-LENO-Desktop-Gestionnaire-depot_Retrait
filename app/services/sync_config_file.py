"""Import de la configuration de synchronisation depuis un fichier JSON.

Permet de configurer un poste sans passer par l'interface : on dépose un
fichier `sync_config.json` à côté de l'application (ou dans le dossier de
données) et il est appliqué au démarrage, puis renommé en
`sync_config.applied.json` pour ne pas être réimporté.

Le même fichier est lu par l'outil cliquable `Configurer_Synchronisation.bat`
(voir `tools/configurer_sync.py`) et par le modèle `sync_config.example.json`.

Format attendu (toutes les clés sont optionnelles sauf server_url et device_token) :

    {
      "server_url": "https://mon-serveur.onrender.com",
      "device_token": "JETON_DU_POSTE",
      "device_name": "Caisse principale",
      "auto_sync": true,
      "auto_sync_interval_seconds": 15
    }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Optional

from app.config import BASE_DIR, DATA_DIR
from app.services import settings_service

CONFIG_FILENAME = "sync_config.json"
APPLIED_SUFFIX = ".applied.json"

# Clés JSON acceptées et leurs synonymes (tolérance pour les saisies manuelles).
_ALIASES = {
    "server_url": ("server_url", "url", "serveur", "server"),
    "device_token": ("device_token", "token", "jeton"),
    "device_name": ("device_name", "name", "poste", "nom_poste"),
    "auto_sync": ("auto_sync", "auto_enabled", "sync_auto"),
    "auto_sync_interval_seconds": (
        "auto_sync_interval_seconds", "interval_seconds", "intervalle",
    ),
}


class SyncConfigFileError(Exception):
    pass


def candidate_paths() -> list[Path]:
    """Emplacements où chercher le fichier, par ordre de priorité."""
    paths: list[Path] = []
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / CONFIG_FILENAME)
    paths.append(BASE_DIR / CONFIG_FILENAME)
    paths.append(DATA_DIR / CONFIG_FILENAME)
    # Dédoublonne en conservant l'ordre.
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _pick(data: dict, key: str):
    for alias in _ALIASES[key]:
        if alias in data:
            return data[alias]
    return None


def _to_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "oui", "yes", "on")


def parse_sync_config(data: dict) -> dict:
    """Normalise un dictionnaire JSON en configuration exploitable.

    Lève SyncConfigFileError si l'URL ou le jeton manquent.
    """
    if not isinstance(data, dict):
        raise SyncConfigFileError("Le fichier doit contenir un objet JSON {...}.")
    server_url = str(_pick(data, "server_url") or "").strip().rstrip("/")
    device_token = str(_pick(data, "device_token") or "").strip()
    device_name = str(_pick(data, "device_name") or "").strip()
    if not server_url:
        raise SyncConfigFileError("Clé 'server_url' manquante ou vide.")
    if not server_url.lower().startswith(("http://", "https://")):
        raise SyncConfigFileError("'server_url' doit commencer par http:// ou https://.")
    if not device_token:
        raise SyncConfigFileError("Clé 'device_token' manquante ou vide.")

    auto_raw = _pick(data, "auto_sync")
    interval_raw = _pick(data, "auto_sync_interval_seconds")
    try:
        interval = int(interval_raw) if interval_raw is not None else None
    except (TypeError, ValueError) as exc:
        raise SyncConfigFileError("'auto_sync_interval_seconds' doit être un entier.") from exc

    return {
        "server_url": server_url,
        "device_token": device_token,
        "device_name": device_name,
        "auto_sync": None if auto_raw is None else _to_bool(auto_raw, True),
        "auto_sync_interval_seconds": interval,
    }


def load_sync_config_file(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SyncConfigFileError(f"Lecture impossible : {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SyncConfigFileError(f"JSON invalide ({exc}).") from exc
    return parse_sync_config(data)


def apply_sync_config(cfg: dict) -> None:
    """Écrit la configuration dans app_settings (même stockage que l'IHM)."""
    settings_service.set_sync_config(
        server_url=cfg["server_url"],
        device_token=cfg["device_token"],
        device_name=cfg.get("device_name", ""),
    )
    auto = cfg.get("auto_sync")
    interval = cfg.get("auto_sync_interval_seconds")
    if auto is not None or interval is not None:
        current = settings_service.get_auto_sync_config()
        settings_service.set_auto_sync_config(
            enabled=current["enabled"] if auto is None else bool(auto),
            interval_seconds=current["interval_seconds"] if interval is None else int(interval),
        )


def apply_sync_config_file_if_present(
    paths: Optional[Iterable[Path]] = None,
) -> Optional[Path]:
    """Applique le premier `sync_config.json` trouvé puis le renomme.

    Retourne le chemin du fichier appliqué, ou None s'il n'y en avait pas.
    Les erreurs de format sont remontées en SyncConfigFileError pour que
    l'appelant puisse les signaler sans bloquer le démarrage.
    """
    for path in (paths if paths is not None else candidate_paths()):
        if not path.is_file():
            continue
        cfg = load_sync_config_file(path)
        apply_sync_config(cfg)
        applied = path.with_name(path.stem + APPLIED_SUFFIX)
        try:
            if applied.exists():
                applied.unlink()
            path.rename(applied)
        except OSError:
            pass  # la config est appliquée ; le renommage est un confort
        return path
    return None
