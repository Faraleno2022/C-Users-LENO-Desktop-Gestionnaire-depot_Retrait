"""Import de la configuration (synchronisation et impression) depuis un fichier JSON.

Permet de configurer un poste sans passer par l'interface : on dépose un
fichier `sync_config.json` (ou `print_config.json`) à côté de l'application
ou dans le dossier de données ; il est appliqué au démarrage puis renommé en
`*.applied.json` pour ne pas être réimporté.

Les mêmes fichiers sont produits par l'outil cliquable
`Configurer_Synchronisation.bat`, par le bouton « Fichier .cmd » de la page
Postes de la console web, et par `Installer_Imprimante_Ticket.cmd`.

Clés acceptées (toutes optionnelles, mais un fichier doit en contenir au moins une) :

    {
      "server_url": "https://mon-serveur.onrender.com",
      "device_token": "JETON_DU_POSTE",
      "device_name": "Caisse principale",
      "auto_sync": true,
      "auto_sync_interval_seconds": 15,

      "receipt_printer": "EMAB Ticket",     # "" = détection automatique
      "paper_width": "80",                  # ou "58"
      "auto_print": true,
      "open_drawer": false
    }

Si l'une des clés de synchronisation est présente, `server_url` et
`device_token` deviennent obligatoires.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Optional

from app.config import BASE_DIR, DATA_DIR
from app.services import settings_service

CONFIG_FILENAMES = ("sync_config.json", "print_config.json")
CONFIG_FILENAME = CONFIG_FILENAMES[0]
APPLIED_SUFFIX = ".applied.json"

# Clés JSON acceptées et leurs synonymes (tolérance pour les saisies manuelles).
_SYNC_ALIASES = {
    "server_url": ("server_url", "url", "serveur", "server"),
    "device_token": ("device_token", "token", "jeton"),
    "device_name": ("device_name", "name", "poste", "nom_poste"),
    "auto_sync": ("auto_sync", "auto_enabled", "sync_auto"),
    "auto_sync_interval_seconds": (
        "auto_sync_interval_seconds", "interval_seconds", "intervalle",
    ),
}
_PRINT_ALIASES = {
    "receipt_printer": ("receipt_printer", "printer", "imprimante"),
    "paper_width": ("paper_width", "largeur", "largeur_papier"),
    "auto_print": ("auto_print", "impression_auto"),
    "open_drawer": ("open_drawer", "tiroir", "tiroir_caisse"),
}
_ALIASES = {**_SYNC_ALIASES, **_PRINT_ALIASES}


class SyncConfigFileError(Exception):
    pass


def candidate_paths() -> list[Path]:
    """Emplacements où chercher les fichiers, par ordre de priorité."""
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
    dirs.extend([BASE_DIR, DATA_DIR])
    seen: set[Path] = set()
    out: list[Path] = []
    for d in dirs:
        for name in CONFIG_FILENAMES:
            p = d / name
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _pick(data: dict, key: str):
    for alias in _ALIASES[key]:
        if alias in data:
            return data[alias]
    return None


def _present(data: dict, aliases: dict) -> bool:
    return any(alias in data for names in aliases.values() for alias in names)


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

    Retourne un dict plat avec toutes les clés (None quand absentes) et deux
    indicateurs `has_sync` / `has_print`. Lève SyncConfigFileError si le
    fichier est vide de sens ou si la synchronisation est incomplète.
    """
    if not isinstance(data, dict):
        raise SyncConfigFileError("Le fichier doit contenir un objet JSON {...}.")
    has_sync = _present(data, _SYNC_ALIASES)
    has_print = _present(data, _PRINT_ALIASES)
    if not has_sync and not has_print:
        raise SyncConfigFileError(
            "Aucune clé reconnue (server_url, device_token, receipt_printer, paper_width…)."
        )

    cfg: dict = {
        "has_sync": has_sync, "has_print": has_print,
        "server_url": "", "device_token": "", "device_name": "",
        "auto_sync": None, "auto_sync_interval_seconds": None,
        "receipt_printer": None, "paper_width": None,
        "auto_print": None, "open_drawer": None,
    }

    if has_sync:
        server_url = str(_pick(data, "server_url") or "").strip().rstrip("/")
        device_token = str(_pick(data, "device_token") or "").strip()
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
        cfg.update({
            "server_url": server_url,
            "device_token": device_token,
            "device_name": str(_pick(data, "device_name") or "").strip(),
            "auto_sync": None if auto_raw is None else _to_bool(auto_raw, True),
            "auto_sync_interval_seconds": interval,
        })

    if has_print:
        printer = _pick(data, "receipt_printer")
        width = _pick(data, "paper_width")
        if width is not None:
            width = str(width).strip().lower().replace("mm", "").strip()
            if width not in ("80", "58"):
                raise SyncConfigFileError("'paper_width' doit valoir \"80\" ou \"58\".")
        auto_print = _pick(data, "auto_print")
        open_drawer = _pick(data, "open_drawer")
        cfg.update({
            "receipt_printer": None if printer is None else str(printer).strip(),
            "paper_width": width,
            "auto_print": None if auto_print is None else _to_bool(auto_print, True),
            "open_drawer": None if open_drawer is None else _to_bool(open_drawer, False),
        })
    return cfg


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
    """Écrit la configuration dans app_settings (même stockage que l'IHM).

    Seules les clés présentes dans le fichier sont modifiées ; les autres
    réglages sont conservés.
    """
    if cfg.get("has_sync", bool(cfg.get("server_url"))):
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

    if cfg.get("has_print"):
        current = settings_service.get_print_config()
        settings_service.set_print_config(
            printer=current["printer"] if cfg.get("receipt_printer") is None else cfg["receipt_printer"],
            paper_width=current["paper_width"] if cfg.get("paper_width") is None else cfg["paper_width"],
            auto_print=current["auto_print"] if cfg.get("auto_print") is None else bool(cfg["auto_print"]),
            open_drawer=current["open_drawer"] if cfg.get("open_drawer") is None else bool(cfg["open_drawer"]),
        )


def apply_sync_config_file_if_present(
    paths: Optional[Iterable[Path]] = None,
) -> Optional[Path]:
    """Applique tous les fichiers de configuration trouvés puis les renomme.

    Retourne le chemin du dernier fichier appliqué, ou None s'il n'y en avait
    pas. Les erreurs de format sont remontées en SyncConfigFileError pour que
    l'appelant puisse les signaler sans bloquer le démarrage ; un fichier
    invalide n'est pas renommé.
    """
    applied_path: Optional[Path] = None
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
        applied_path = path
    return applied_path
