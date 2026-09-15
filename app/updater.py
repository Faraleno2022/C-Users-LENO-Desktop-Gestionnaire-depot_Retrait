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
import hashlib
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


def _download_asset(asset: dict, data_dir: Path) -> Path:
    """Ne publie que les téléchargements complets, vérifiés avant leur activation."""
    name = asset["name"]
    if not isinstance(name, str) or any(c in name for c in '/\\<>:"|?*\r\n') or not name.lower().endswith(".exe"):
        raise ValueError("Nom d'installateur invalide.")
    updates = Path(data_dir) / UPDATES_DIR
    updates.mkdir(parents=True, exist_ok=True)
    target = updates / name
    expected = int(asset.get("size") or 0)
    digest = asset.get("digest") or ""

    def valid(path):
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        if expected and path.stat().st_size != expected:
            return False
        if digest.startswith("sha256:"):
            checksum = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(65536), b""):
                    checksum.update(chunk)
            return checksum.hexdigest() == digest.split(":", 1)[1].lower()
        return bool(expected)

    if valid(target):
        return target
    tmp = target.with_suffix(".part")
    request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "EMAB-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                out.write(chunk)
        if not valid(tmp):
            raise ValueError("Téléchargement incomplet ou empreinte incorrecte.")
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


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

        target = _download_asset(asset, data_dir)

        flag = Path(data_dir) / FLAG_NAME
        flag.write_text(str(target), encoding="utf-8")
        return latest
    except Exception:
        return None
