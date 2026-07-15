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
import sys
import urllib.request
from pathlib import Path

# Dépôt public où sont publiées les versions (onglet « Releases » sur GitHub).
GITHUB_REPO = "Faraleno2022/C-Users-LENO-Desktop-Gestionnaire-depot_Retrait"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
# Liste des releases (inclut les pré-releases « desktop-v* », contrairement à /latest).
API_RELEASES = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"

# Nom du drapeau déposé quand une mise à jour est téléchargée et prête.
FLAG_NAME = "update_pending.flag"
# Sous-dossier où l'installateur téléchargé est stocké.
UPDATES_DIR = "updates"

# Identifie l'installateur de la console parmi les fichiers d'une release.
ASSET_HINT = "Console-Web-Setup"

# --- Application bureau « EMAB Gestionnaire » -------------------------------
# La console installe aussi le Gestionnaire sur le poste : ses versions sont
# publiées sous le tag « desktop-vX.Y.Z » avec un installateur dont le nom
# contient « Gestionnaire-Setup ». L'installateur crée son propre raccourci
# sur le Bureau, distinct de celui de la console.
DESKTOP_TAG_PREFIX = "desktop-v"
DESKTOP_ASSET_HINT = "Gestionnaire-Setup"
DESKTOP_EXE_NAME = "EMAB-Gestionnaire.exe"
# AppId Inno Setup du Gestionnaire (installer.iss) : clé de désinstallation
# dans le registre, d'où on lit la version actuellement installée.
DESKTOP_UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{8B5F2E4A-9C31-4D7E-A6B8-3F2C61E0D9A4}_is1"
)


def _parse_version(value: str):
    """'desktop-v1.2.3', 'v1.2.3' ou '1.2.3' -> (1, 2, 3). None si non interprétable."""
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.startswith(DESKTOP_TAG_PREFIX):
        cleaned = cleaned[len(DESKTOP_TAG_PREFIX):]
    cleaned = cleaned.lstrip("vV")
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


def _find_installer_asset(release: dict, hint: str = ASSET_HINT) -> dict | None:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".exe") and hint in name:
            return asset
    return None


def _download_asset(asset: dict, data_dir: Path) -> Path:
    """Télécharge l'installateur dans data_dir/updates (si pas déjà complet)."""
    updates_dir = Path(data_dir) / UPDATES_DIR
    updates_dir.mkdir(parents=True, exist_ok=True)
    target = updates_dir / asset["name"]

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
    return target


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

        target = _download_asset(asset, data_dir)

        # Dépose le drapeau : chemin de l'installateur à appliquer au prochain démarrage.
        flag = Path(data_dir) / FLAG_NAME
        flag.write_text(str(target), encoding="utf-8")
        return latest
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Installation / mise à jour du Gestionnaire bureau depuis la console
# ---------------------------------------------------------------------------

def _fetch_latest_desktop_release() -> dict | None:
    """Retourne la release desktop (tag desktop-v*) la plus récente, ou None."""
    req = urllib.request.Request(
        API_RELEASES,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "EMAB-Console-Updater",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        releases = json.load(resp)
    best, best_ver = None, None
    for rel in releases or []:
        tag = rel.get("tag_name") or ""
        if not tag.startswith(DESKTOP_TAG_PREFIX) or rel.get("draft"):
            continue
        ver = _parse_version(tag)
        if ver is None:
            continue
        if best_ver is None or ver > best_ver:
            best, best_ver = rel, ver
    return best


def _installed_desktop_version() -> str | None:
    """Version du Gestionnaire installée sur ce poste (registre), None si absent."""
    if sys.platform != "win32":
        return None
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in (
            winreg.KEY_READ,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
        ):
            try:
                with winreg.OpenKey(hive, DESKTOP_UNINSTALL_KEY, 0, access) as key:
                    value, _ = winreg.QueryValueEx(key, "DisplayVersion")
                    if value:
                        return str(value)
            except OSError:
                continue
    return None


def _desktop_app_running() -> bool:
    """Vrai si le Gestionnaire est ouvert (on n'installe pas par-dessus)."""
    import subprocess
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {DESKTOP_EXE_NAME}"],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        ).stdout or ""
        return DESKTOP_EXE_NAME.lower() in out.lower()
    except Exception:
        return True  # dans le doute, on reporte l'installation


def check_and_install_desktop(data_dir: Path) -> str | None:
    """Installe (ou met à jour) le Gestionnaire bureau publié sur GitHub.

    Appelé en arrière-plan au démarrage de la console. Si la version publiée
    (tag desktop-vX.Y.Z) est plus récente que celle installée — ou si le
    Gestionnaire n'est pas encore installé — l'installateur est téléchargé puis
    exécuté en silencieux : il crée son propre raccourci sur le Bureau et ne
    touche jamais aux données (%LOCALAPPDATA%\\EMAB GROUP\\Gestionnaire).

    Retourne le tag installé, ou None (rien à faire / app ouverte / erreur).
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None  # uniquement depuis la console installée (.exe)
    try:
        release = _fetch_latest_desktop_release()
        if not release:
            return None
        latest = release.get("tag_name") or ""
        installed = _installed_desktop_version()
        if installed is not None and not is_newer(latest, installed):
            return None
        asset = _find_installer_asset(release, DESKTOP_ASSET_HINT)
        if asset is None:
            return None

        target = _download_asset(asset, data_dir)

        # Si le Gestionnaire est ouvert, ne pas couper le travail en cours :
        # l'installateur (déjà téléchargé) sera appliqué au prochain démarrage
        # de la console (elle démarre avec Windows).
        if _desktop_app_running():
            return None

        import subprocess
        result = subprocess.run(
            [str(target), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            timeout=600,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        if result.returncode != 0:
            return None
        try:
            target.unlink()
        except OSError:
            pass
        return latest
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Mise à jour de la CONSOLE elle-même : appliquer une MAJ déjà téléchargée
# (utilisé au démarrage ET par le bouton « Appliquer maintenant » de l'UI web)
# ---------------------------------------------------------------------------

def pending_installer(data_dir: Path) -> str | None:
    """Chemin de l'installateur console en attente (existant), sinon None.

    Nettoie le drapeau s'il pointe vers un fichier disparu.
    """
    flag = Path(data_dir) / FLAG_NAME
    if not flag.exists():
        return None
    try:
        installer = flag.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if installer and os.path.exists(installer):
        return installer
    try:
        flag.unlink()
    except OSError:
        pass
    return None


def pending_version(data_dir: Path) -> str | None:
    """Numéro de version de la MAJ en attente (déduit du nom du fichier), sinon None."""
    installer = pending_installer(data_dir)
    if not installer:
        return None
    import re
    m = re.search(r"(\d+\.\d+\.\d+)", os.path.basename(installer))
    return m.group(1) if m else "?"


def apply_pending_update(data_dir: Path, exe: str) -> bool:
    """Lance le script qui installe la MAJ console en attente puis relance l'exe.

    Un petit .bat attend ~2 s (le temps que la réponse HTTP parte / que la
    console se ferme), termine de force l'exe (sinon il est verrouillé), applique
    l'installateur en silencieux (les données ne sont jamais touchées), puis
    relance la console à jour. Retourne True si le script a été lancé.
    """
    installer = pending_installer(data_dir)
    if not installer:
        return False
    flag = Path(data_dir) / FLAG_NAME
    exe_name = os.path.basename(exe)
    bat = Path(data_dir) / "_apply_update.bat"
    try:
        bat.write_text(
            "@echo off\r\n"
            "ping 127.0.0.1 -n 3 >nul\r\n"
            f'taskkill /IM "{exe_name}" /F >nul 2>&1\r\n'
            "ping 127.0.0.1 -n 2 >nul\r\n"
            f'"{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART\r\n'
            f'del "{installer}" >nul 2>&1\r\n'
            f'del "{flag}" >nul 2>&1\r\n'
            f'start "" "{exe}"\r\n'
            'del "%~f0" >nul 2>&1\r\n',
            encoding="utf-8",
        )
    except OSError:
        return False

    import subprocess
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
    except Exception:
        return False
    return True
