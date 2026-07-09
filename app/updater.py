"""Mise à jour automatique de l'app desktop via GitHub Releases.

Même principe que la console web (server/updater.py) : au démarrage, l'app
interroge GitHub. Si une version plus récente est publiée, l'installateur est
téléchargé en arrière-plan et un « drapeau » est déposé ; la mise à jour
s'applique au prochain lancement de l'app (l'exe n'est alors pas verrouillé).

Différence importante : les versions desktop sont publiées avec un tag
« desktop-vX.Y.Z » (en pré-release) pour ne pas interférer avec les releases
« vX.Y.Z » de la console web, qui utilise /releases/latest.

Les données (%LOCALAPPDATA%\\EMAB GROUP\\Gestionnaire) ne sont JAMAIS touchées :
l'installateur ne remplace que le programme.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

GITHUB_REPO = "Faraleno2022/C-Users-LENO-Desktop-Gestionnaire-depot_Retrait"
# Liste des releases (inclut les pré-releases, contrairement à /latest).
API_RELEASES = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"

TAG_PREFIX = "desktop-v"          # tags des versions desktop
ASSET_HINT = "Gestionnaire-Setup"  # identifie l'installateur desktop
FLAG_NAME = "update_pending.flag"
UPDATES_DIR = "updates"


def _parse_version(value: str):
    """'desktop-v1.2.3', 'v1.2.3' ou '1.2.3' -> (1, 2, 3)."""
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.startswith(TAG_PREFIX):
        cleaned = cleaned[len(TAG_PREFIX):]
    cleaned = cleaned.lstrip("vV")
    try:
        return tuple(int(p) for p in cleaned.split("."))
    except ValueError:
        return None


def is_newer(latest: str, current: str) -> bool:
    a, b = _parse_version(latest), _parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _fetch_latest_desktop_release() -> dict | None:
    """Retourne la release desktop (tag desktop-v*) la plus récente, ou None."""
    req = urllib.request.Request(
        API_RELEASES,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "EMAB-Gestionnaire-Updater",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        releases = json.load(resp)
    best, best_ver = None, None
    for rel in releases or []:
        tag = rel.get("tag_name") or ""
        if not tag.startswith(TAG_PREFIX) or rel.get("draft"):
            continue
        ver = _parse_version(tag)
        if ver is None:
            continue
        if best_ver is None or ver > best_ver:
            best, best_ver = rel, ver
    return best


def _find_installer_asset(release: dict) -> dict | None:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".exe") and ASSET_HINT in name:
            return asset
    return None


def check_and_prepare_update(current_version: str, data_dir: Path) -> str | None:
    """Télécharge l'installateur si une version desktop plus récente existe.

    Retourne le tag téléchargé si une mise à jour est prête, sinon None.
    Toutes les erreurs (hors-ligne…) sont avalées : l'app continue normalement.
    """
    try:
        release = _fetch_latest_desktop_release()
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

        expected = asset.get("size") or 0
        if not (target.exists() and expected and target.stat().st_size == expected):
            req = urllib.request.Request(
                asset["browser_download_url"],
                headers={"User-Agent": "EMAB-Gestionnaire-Updater"},
            )
            tmp = target.with_suffix(".part")
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
            tmp.replace(target)

        flag = Path(data_dir) / FLAG_NAME
        flag.write_text(str(target), encoding="utf-8")
        return latest
    except Exception:
        return None
