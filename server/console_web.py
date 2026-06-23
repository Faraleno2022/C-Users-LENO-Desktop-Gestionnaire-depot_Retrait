"""Console web EMAB GROUP en local (hors-ligne).

Lance le serveur Django sur la machine (par défaut http://127.0.0.1:8765),
ouvre le navigateur, et stocke les données dans un dossier utilisateur
persistant : %LOCALAPPDATA%\\EMAB GROUP\\ConsoleWeb.

Empaquetable en .exe avec PyInstaller (voir EMAB-Console-Web.spec).

Synchronisation avec le serveur en ligne (Render) : renseignez le fichier
`render_sync.json` du dossier de données (créé au premier démarrage) avec
l'URL et un jeton Device du serveur ; la console répliquera alors ses données
dans les deux sens dès qu'il y a une connexion internet.

Variables d'environnement optionnelles :
  EMAB_WEB_PORT  port d'écoute (défaut 8765)
  EMAB_WEB_HOST  hôte d'écoute (défaut 127.0.0.1 ; mettre 0.0.0.0 pour
                 autoriser les postes du réseau local à se synchroniser ici)
  EMAB_DATA_DIR  dossier de données (défaut %LOCALAPPDATA%/EMAB GROUP/ConsoleWeb)
"""
from __future__ import annotations

import json
import os
import secrets as secrets_mod
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Version de la console. À INCRÉMENTER à chaque nouvelle release publiée sur
# GitHub (et reporter la même valeur dans MyAppVersion de installer_console_web.iss).
# C'est ce numéro que l'updater compare à la dernière release pour décider d'une MAJ.
APP_VERSION = "1.0.8"

PORT = int(os.environ.get("EMAB_WEB_PORT", "8765"))
HOST = os.environ.get("EMAB_WEB_HOST", "127.0.0.1")

RENDER_SYNC_TEMPLATE = {
    "enabled": False,
    "url": "https://gestionnaire-depot-retrait.onrender.com",
    "token": "COLLEZ-ICI-LE-JETON-DEVICE-DU-SERVEUR",
    # 5 s : quasi temps réel. Convient au plan Render payant (toujours actif).
    # Sur le plan gratuit, préférez 15 s pour ménager le quota.
    "interval_seconds": 5,
}


def _read_render_config(data_dir: Path) -> dict:
    """Lit (et crée au besoin) la config de réplication vers le serveur en ligne.

    Tolère un éventuel BOM ajouté par le Bloc-notes (utf-8-sig) pour que le
    fichier reste lisible même édité maladroitement.
    """
    cfg_path = data_dir / "render_sync.json"
    if not cfg_path.exists():
        cfg_path.write_text(
            json.dumps(RENDER_SYNC_TEMPLATE, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return dict(RENDER_SYNC_TEMPLATE)
    try:
        raw = cfg_path.read_text(encoding="utf-8-sig")
        return {**RENDER_SYNC_TEMPLATE, **json.loads(raw)}
    except (OSError, ValueError):
        return dict(RENDER_SYNC_TEMPLATE)


def _diagnose_render_config(data_dir: Path) -> None:
    """Affiche un diagnostic clair de l'état de la sync au démarrage."""
    cfg_path = data_dir / "render_sync.json"
    cfg = _read_render_config(data_dir)
    token = (cfg.get("token") or "").strip()
    url = (cfg.get("url") or "").strip()
    print("-" * 62)
    if cfg.get("enabled") and url and token and "COLLEZ-ICI" not in token:
        print(f"Sync serveur en ligne : ACTIVEE  ->  {url}")
        print(f"  Intervalle : {max(3, int(cfg.get('interval_seconds') or 5))} s")
        print("  Surveillez les lignes [Sync Render] ci-dessous.")
    else:
        print("Sync serveur en ligne : DESACTIVEE.")
        # Aide au diagnostic : pourquoi ?
        if cfg_path.exists():
            try:
                json.loads(cfg_path.read_text(encoding="utf-8-sig"))
                if not cfg.get("enabled"):
                    print("  Cause : \"enabled\" n'est pas true dans render_sync.json.")
                elif not token or "COLLEZ-ICI" in token:
                    print("  Cause : le jeton (token) n'est pas renseigne.")
            except (OSError, ValueError) as e:
                print(f"  Cause : render_sync.json est mal forme ({e}).")
                print("  Re-collez exactement les 6 lignes du modele, puis enregistrez.")
        print(f"  Fichier : {cfg_path}")
    print("-" * 62)


def _replication_loop(data_dir: Path) -> None:
    """Réplique en continu la base locale vers/depuis le serveur en ligne.

    Relit la config à chaque cycle : on peut activer/modifier render_sync.json
    sans redémarrer la console. Les échecs réseau sont silencieux (hors-ligne).
    """
    from sync.replicator import ReplicationError, Replicator

    state_path = data_dir / "render_sync_state.json"
    first_cycle = True
    while True:
        cfg = _read_render_config(data_dir)
        interval = max(3, int(cfg.get("interval_seconds") or 5))
        token = (cfg.get("token") or "").strip()
        url = (cfg.get("url") or "").strip()
        if cfg.get("enabled") and url and token and "COLLEZ-ICI" not in token:
            try:
                if first_cycle:
                    # Au premier cycle (démarrage), on oublie les filigranes de
                    # pull pour re-télécharger TOUT le serveur : rattrape tout
                    # décalage accumulé (filigrane bloqué). Les cycles suivants
                    # restent incrémentaux (rapides).
                    try:
                        st = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
                        st = {k: v for k, v in st.items() if not str(k).startswith("pull_")}
                        state_path.write_text(json.dumps(st), encoding="utf-8")
                    except (OSError, ValueError):
                        pass
                    first_cycle = False
                rep = Replicator(url, token, state_path)
                summary = rep.run_once()
                if summary:
                    parts = ", ".join(
                        f"{t}: ↑{v['pushed']} ↓{v['inserted'] + v['updated']}"
                        for t, v in summary.items()
                    )
                    print(f"[Sync Render] {parts}")
            except ReplicationError as e:
                print(f"[Sync Render] Erreur : {e}")
            except Exception as e:  # réseau coupé, serveur endormi… on réessaiera
                print(f"[Sync Render] Hors-ligne ou serveur indisponible ({type(e).__name__})")
        time.sleep(interval)


def _find_chrome() -> str:
    """Chemin de chrome.exe si Chrome est installé, sinon chaîne vide."""
    import shutil
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return shutil.which("chrome") or ""


def _open_ui(url: str, data_dir: Path) -> None:
    """Ouvre l'interface. Avec Chrome : mode caisse (impression directe du
    ticket, sans boîte de dialogue). Sinon : navigateur par défaut."""
    import subprocess
    chrome = _find_chrome()
    if chrome:
        profile = str(data_dir / "ChromeCaisse")
        try:
            subprocess.Popen([
                chrome,
                "--kiosk-printing",            # window.print() imprime directement
                f"--app={url}",                # fenêtre épurée, sans barre d'adresse
                f"--user-data-dir={profile}",  # profil dédié, isolé du Chrome habituel
                "--no-first-run",
                "--no-default-browser-check",
            ])
            return
        except Exception:
            pass
    webbrowser.open(url)


def _server_already_running(port: int) -> bool:
    """Vrai si une console répond déjà sur ce port (démarrage auto en arrière-plan)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/login/", timeout=2):
            return True
    except Exception:
        return False


def main() -> int:
    # Console Windows souvent en cp1252 : force UTF-8 pour les messages
    # (coches, accents) sans faire planter le démarrage.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    frozen = bool(getattr(sys, "frozen", False))
    base = Path(getattr(sys, "_MEIPASS", "")) if frozen else Path(__file__).resolve().parent
    sys.path.insert(0, str(base))

    # --- Dossier de données persistant (jamais dans le bundle temporaire) ---
    env_dir = os.environ.get("EMAB_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir)
    else:
        data_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EMAB GROUP" / "ConsoleWeb"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Si une console tourne déjà (démarrage auto en arrière-plan), ne pas
    # relancer le serveur : on ouvre simplement l'interface caisse et on quitte.
    want_browser = not os.environ.get("EMAB_NO_BROWSER")
    if want_browser and _server_already_running(PORT):
        _open_ui(f"http://127.0.0.1:{PORT}/", data_dir)
        return 0

    # Clé secrète persistante (sessions stables entre démarrages)
    key_file = data_dir / "secret_key.txt"
    if not key_file.exists():
        key_file.write_text(secrets_mod.token_urlsafe(48), encoding="utf-8")

    os.environ.setdefault("DJANGO_SECRET_KEY", key_file.read_text(encoding="utf-8").strip())
    os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(data_dir / "console.sqlite3"))
    os.environ.setdefault("DJANGO_DEBUG", "false")
    os.environ.setdefault("DJANGO_SECURE_SSL_REDIRECT", "false")
    os.environ.setdefault("DJANGO_COOKIE_SECURE", "false")
    os.environ.setdefault(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        f"http://127.0.0.1:{PORT},http://localhost:{PORT}",
    )
    os.environ.setdefault("DJANGO_STATIC_ROOT", str(base / "staticfiles"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

    import django

    django.setup()
    from django.core.management import call_command

    print("=" * 62)
    print("  EMAB GROUP — Console web locale")
    print("=" * 62)
    print(f"Données : {data_dir}")
    print("Préparation de la base locale…")
    call_command("migrate", interactive=False, verbosity=0)

    from sync.models import Client, Device, RemoteUser, Transaction

    render_cfg = _read_render_config(data_dir)
    render_ready = bool(
        render_cfg.get("enabled")
        and (render_cfg.get("url") or "").strip()
        and (render_cfg.get("token") or "").strip()
        and "COLLEZ-ICI" not in (render_cfg.get("token") or "")
    )

    # Cohérence base <-> filigranes de synchronisation.
    # Si la base ne contient aucune donnée métier (clients/transactions) mais
    # que des filigranes existent, on les réinitialise : sinon le pull demande
    # « ce qui est plus récent que X » et ne re-télécharge jamais les données
    # déjà présentes sur le serveur (cas typique après suppression de la base).
    state_file = data_dir / "render_sync_state.json"
    if (
        state_file.exists()
        and not Client.objects.exists()
        and not Transaction.objects.exists()
    ):
        try:
            state_file.unlink()
            print("Filigranes de sync réinitialisés (base vierge) : "
                  "re-téléchargement complet depuis le serveur.")
        except OSError:
            pass

    # --- Synchronisation initiale (machine rejoignant un système existant) ---
    # Si la sync en ligne est déjà configurée et qu'aucun compte n'existe encore,
    # on rapatrie d'abord les données du serveur : on évite ainsi de créer un
    # compte « admin » par défaut en double avec celui du serveur.
    if render_ready and not RemoteUser.objects.exists():
        try:
            from sync.replicator import Replicator
            print("Synchronisation initiale avec le serveur en ligne…")
            Replicator(
                render_cfg["url"], render_cfg["token"],
                data_dir / "render_sync_state.json",
            ).run_once()
            print("Synchronisation initiale terminée.")
        except Exception as e:  # réseau indisponible : on continue, sync reprendra
            print(f"Sync initiale impossible ({type(e).__name__}), démarrage hors-ligne.")

    # --- Compte super_admin par défaut (uniquement si la base est vierge) ---
    if not RemoteUser.objects.filter(role="super_admin", actif=True).exists():
        call_command("createwebadmin", "admin", "admin123")
        print(">> Compte par défaut créé : admin / admin123 (changez-le !)")

    # --- Jeton de synchronisation pour le poste local -------------------
    device, _ = Device.objects.get_or_create(name="Poste-local")
    token_file = data_dir / "jeton_poste_local.txt"
    token_file.write_text(device.token, encoding="utf-8")
    print(f"Jeton de sync du poste local : {device.token}")
    print(f"(copié dans : {token_file})")

    # --- Réplication vers le serveur en ligne (Render) -------------------
    _diagnose_render_config(data_dir)
    threading.Thread(target=_replication_loop, args=(data_dir,), daemon=True).start()

    # --- Vérification de mise à jour (arrière-plan, n'interrompt rien) ----
    def _check_update():
        try:
            from updater import check_and_prepare_update
            ready = check_and_prepare_update(APP_VERSION, data_dir)
            if ready:
                print(f"[MAJ] Version {ready} téléchargée — elle s'installera "
                      f"au prochain démarrage (vos données sont conservées).")
        except Exception:
            pass
    threading.Thread(target=_check_update, daemon=True).start()

    # --- Démarrage du serveur -------------------------------------------
    from core.wsgi import application
    from waitress import serve

    url = f"http://127.0.0.1:{PORT}/"
    print()
    print(f"Console démarrée : {url}")
    if HOST == "0.0.0.0":
        print("(accessible aussi depuis le réseau local)")
    print("Laissez cette fenêtre ouverte. Fermez-la pour arrêter la console.")
    print("=" * 62)

    if want_browser:
        threading.Timer(1.5, lambda: _open_ui(url, data_dir)).start()
    serve(application, host=HOST, port=PORT, threads=8)
    return 0


if __name__ == "__main__":
    sys.exit(main())
