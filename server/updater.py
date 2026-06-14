"""Mise à jour automatique de la console web via GitHub Releases.

Principe : au démarrage, la console interroge la dernière version publiée sur
GitHub. Si elle est plus récente que la version installée, elle télécharge
l'installateur en arrière-plan (sans interrompre la session en cours) et dépose
un « drapeau ». L'installateur s'applique au démarrage suivant (via le lanceur
de démarrage), pendant que la console n'est pas encore lancée — l'exe n'est donc
pas verrouillé.

La base de données n'est JAMAIS touchée : elle vit dans
%LOCALAPPDATA%\\EMAB GROUP\\ConsoleWeb, séparée du programme
(%LOCALAPPDATA%\\Programs). L'installateur ne remplace que le programme, et les
migrations Django au démarrage n'ajoutent que les nouveautés de schéma, sans
supprimer de données.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

# Dépôt public où sont publiées les versions (onglet « Releases » sur GitHub).
GITHUB_REPO = "Faraleno2022/C-Users-LENO-Desktop-Gestionnaire-depot_Retrait"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Nom du drapeau déposé quand une mise à jour est téléchargée et prête.
FLAG_NAME = "update_pending.flag"
# Sous-dossier où l'installateur téléchargé est stocké.
UPDATES_DIR = "updates"

# Identifie l'installateur de la console parmi les fichiers d'une release.
ASSET_HINT = "Console-Web-Setup"


def _parse_version(value: str):
    """'v1.2.3' ou '1.2.3' -> (1, 2, 3). Renvoie None si non interprétable."""
    if not value:
        return None
    cleaned = value.strip().lstrip("vV")
    parts = cleaned.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def is_newer(latest: str, current: str) -> bool:
    a, b = _parse_version(latest), _parse_version(current)
    if a is None or b is None:
        return False
    # Égalise la longueur (1.2 vs 1.2.0)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _fetch_latest_release() -> dict | None:
    req = urllib.request.Request(
        API_LATEST,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "EMAB-Console-Updater",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _find_installer_asset(release: dict) -> dict | None:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".exe") and ASSET_HINT in name:
            return asset
    return None


def check_and_prepare_update(current_version: str, data_dir: Path) -> str | None:
    """Vérifie GitHub ; télécharge l'installateur si une version plus récente existe.

    Retourne la version téléchargée (str) si une mise à jour est prête, sinon None.
    Toutes les erreurs (hors-ligne, etc.) sont avalées : la console continue
    normalement avec la version actuelle.
    """
    try:
        release = _fetch_latest_release()
        if not release:
            return None
        latest = release.get("tag_name") or ""
        if not is_newer(latest, current_version):
            return None
        asset = _find_installer_asset(release)
        if asset is None:
            return None

        updates_dir = Path(data_dir) / UPDATES_DIR
        updates_dir.mkdir(parents=True, exist_ok=True)
        target = updates_dir / asset["name"]

        # Télécharge si pas déjà présent et complet.
        expected = asset.get("size") or 0
        if not (target.exists() and expected and target.stat().st_size == expected):
            req = urllib.request.Request(
                asset["browser_download_url"],
                headers={"User-Agent": "EMAB-Console-Updater"},
            )
            tmp = target.with_suffix(".part")
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
            tmp.replace(target)

        # Dépose le drapeau : chemin de l'installateur à appliquer au prochain démarrage.
        flag = Path(data_dir) / FLAG_NAME
        flag.write_text(str(target), encoding="utf-8")
        return latest
    except Exception:
        return None
