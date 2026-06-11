"""Console web EMAB GROUP en local (hors-ligne).

Lance le serveur Django sur la machine (par défaut http://127.0.0.1:8765),
ouvre le navigateur, et stocke les données dans un dossier utilisateur
persistant : %LOCALAPPDATA%\\EMAB GROUP\\ConsoleWeb.

Empaquetable en .exe avec PyInstaller (voir EMAB-Console-Web.spec).

Variables d'environnement optionnelles :
  EMAB_WEB_PORT  port d'écoute (défaut 8765)
  EMAB_WEB_HOST  hôte d'écoute (défaut 127.0.0.1 ; mettre 0.0.0.0 pour
                 autoriser les postes du réseau local à se synchroniser ici)
"""
from __future__ import annotations

import os
import secrets as secrets_mod
import sys
import threading
import webbrowser
from pathlib import Path

PORT = int(os.environ.get("EMAB_WEB_PORT", "8765"))
HOST = os.environ.get("EMAB_WEB_HOST", "127.0.0.1")


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
    data_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EMAB GROUP" / "ConsoleWeb"
    data_dir.mkdir(parents=True, exist_ok=True)

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

    # --- Compte super_admin par défaut (premier démarrage uniquement) ---
    from sync.models import Device, RemoteUser

    if not RemoteUser.objects.filter(role="super_admin", actif=True).exists():
        call_command("createwebadmin", "admin", "admin123")
        print(">> Compte par défaut créé : admin / admin123 (changez-le !)")

    # --- Jeton de synchronisation pour le poste local -------------------
    device, _ = Device.objects.get_or_create(name="Poste-local")
    token_file = data_dir / "jeton_poste_local.txt"
    token_file.write_text(device.token, encoding="utf-8")
    print(f"Jeton de sync du poste local : {device.token}")
    print(f"(copié dans : {token_file})")

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

    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    serve(application, host=HOST, port=PORT, threads=8)
    return 0


if __name__ == "__main__":
    sys.exit(main())
