"""Outil cliquable de configuration de la synchronisation.

Lancé par `Configurer_Synchronisation.bat` (double-clic). Ouvre une petite
fenêtre Tkinter pour saisir l'URL du serveur, le jeton du poste et le nom du
poste, tester la connexion (`GET /api/sync/ping/`) et enregistrer la
configuration directement dans la base locale (`app_settings`), au même endroit
que l'écran **Administration → Synchronisation** de l'application.

Ne dépend que de la bibliothèque standard (sqlite3, urllib, tkinter) : il
fonctionne même si l'environnement virtuel du projet n'est pas installé.

Usage :
    python tools/configurer_sync.py                 # fenêtre graphique
    python tools/configurer_sync.py --console       # mode texte
    python tools/configurer_sync.py --apply         # applique sync_config.json sans interaction
    python tools/configurer_sync.py --db "C:/.../gestionnaire.db"
    python tools/configurer_sync.py --file ma_config.json --apply

Le fichier `sync_config.json` (modèle : `sync_config.example.json`) placé à la
racine du projet pré-remplit les champs ; avec `--apply` il est appliqué tel quel.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Clés identiques à app/services/settings_service.py. On tente l'import pour
# rester synchronisé avec l'application ; en cas d'échec (script copié seul),
# on retombe sur les valeurs littérales.
try:  # pragma: no cover - dépend de l'emplacement du script
    from app.services.settings_service import (  # type: ignore
        KEY_AUTO_SYNC_ENABLED, KEY_AUTO_SYNC_INTERVAL, KEY_DEVICE_NAME,
        KEY_DEVICE_TOKEN, KEY_SERVER_URL,
    )
except Exception:  # pragma: no cover
    KEY_SERVER_URL = "sync.server_url"
    KEY_DEVICE_TOKEN = "sync.device_token"
    KEY_DEVICE_NAME = "sync.device_name"
    KEY_AUTO_SYNC_ENABLED = "sync.auto_enabled"
    KEY_AUTO_SYNC_INTERVAL = "sync.auto_interval_seconds"

try:
    from app.services.sync_config_file import (  # type: ignore
        SyncConfigFileError, parse_sync_config,
    )
except Exception:  # pragma: no cover - fallback minimal
    class SyncConfigFileError(Exception):
        pass

    def parse_sync_config(data: dict) -> dict:  # type: ignore
        if not isinstance(data, dict):
            raise SyncConfigFileError("Le fichier doit contenir un objet JSON {...}.")
        url = str(data.get("server_url") or "").strip().rstrip("/")
        tok = str(data.get("device_token") or "").strip()
        if not url or not tok:
            raise SyncConfigFileError("'server_url' et 'device_token' sont obligatoires.")
        return {
            "server_url": url,
            "device_token": tok,
            "device_name": str(data.get("device_name") or "").strip(),
            "auto_sync": data.get("auto_sync"),
            "auto_sync_interval_seconds": data.get("auto_sync_interval_seconds"),
        }

CONFIG_FILE = ROOT / "sync_config.json"
PING_TIMEOUT = 30
MIN_INTERVAL = 15


# --- Base de données ---------------------------------------------------------

def candidate_dbs() -> list[Path]:
    """Bases possibles : poste installé (%LOCALAPPDATA%) puis dépôt de dev."""
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return [
        local / "EMAB GROUP" / "Gestionnaire" / "data" / "gestionnaire.db",
        ROOT / "data" / "gestionnaire.db",
    ]


def default_db() -> Path:
    env = os.environ.get("GESTIONNAIRE_DB")
    if env:
        return Path(env)
    for p in candidate_dbs():
        if p.exists():
            return p
    installed_dir = candidate_dbs()[0].parent.parent
    if installed_dir.exists():
        return candidate_dbs()[0]
    return candidate_dbs()[1]


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    return conn


def read_config(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT key, value FROM app_settings WHERE key IN (?,?,?,?,?)",
        (KEY_SERVER_URL, KEY_DEVICE_TOKEN, KEY_DEVICE_NAME,
         KEY_AUTO_SYNC_ENABLED, KEY_AUTO_SYNC_INTERVAL),
    ).fetchall()
    kv = {r["key"]: (r["value"] or "") for r in rows}
    auto = kv.get(KEY_AUTO_SYNC_ENABLED)
    try:
        interval = max(MIN_INTERVAL, int(kv.get(KEY_AUTO_SYNC_INTERVAL) or MIN_INTERVAL))
    except ValueError:
        interval = MIN_INTERVAL
    return {
        "server_url": kv.get(KEY_SERVER_URL, "").strip(),
        "device_token": kv.get(KEY_DEVICE_TOKEN, "").strip(),
        "device_name": kv.get(KEY_DEVICE_NAME, "").strip(),
        "auto_sync": True if auto in (None, "") else auto == "1",
        "auto_sync_interval_seconds": interval,
    }


def write_config(conn: sqlite3.Connection, cfg: dict) -> None:
    values = {
        KEY_SERVER_URL: cfg["server_url"].strip().rstrip("/"),
        KEY_DEVICE_TOKEN: cfg["device_token"].strip(),
        KEY_DEVICE_NAME: cfg.get("device_name", "").strip(),
    }
    if cfg.get("auto_sync") is not None:
        values[KEY_AUTO_SYNC_ENABLED] = "1" if cfg["auto_sync"] else "0"
    if cfg.get("auto_sync_interval_seconds") is not None:
        values[KEY_AUTO_SYNC_INTERVAL] = str(max(MIN_INTERVAL, int(cfg["auto_sync_interval_seconds"])))
    for key, value in values.items():
        conn.execute(
            "INSERT INTO app_settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    conn.commit()


# --- Fichier JSON ------------------------------------------------------------

def load_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise SyncConfigFileError(f"Lecture impossible de {path} : {exc}") from exc
    except ValueError as exc:
        raise SyncConfigFileError(f"JSON invalide dans {path} : {exc}") from exc
    return parse_sync_config(data)


# --- Test de connexion -------------------------------------------------------

def ping(server_url: str, token: str) -> str:
    """Interroge /api/sync/ping/. Retourne un message de succès ou lève RuntimeError."""
    url = server_url.strip().rstrip("/")
    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError("L'URL doit commencer par http:// ou https://.")
    if not token.strip():
        raise RuntimeError("Le jeton du poste est vide.")
    req = urllib.request.Request(
        f"{url}/api/sync/ping/",
        headers={"Authorization": f"Device {token.strip()}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=PING_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("Jeton du poste refusé par le serveur (401).") from exc
        raise RuntimeError(f"Réponse inattendue du serveur ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Connexion impossible : {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"Connexion impossible : {exc}") from exc
    if status != 200:
        raise RuntimeError(f"Réponse inattendue du serveur ({status}).")
    device = ""
    try:
        device = json.loads(body).get("device") or ""
    except ValueError:
        pass
    return f"Connexion réussie{f' — poste reconnu : {device}' if device else ''}."


# --- Mode non interactif -----------------------------------------------------

def apply_from_file(db_path: Path, file_path: Path) -> int:
    if not file_path.is_file():
        print(f"[ERREUR] Fichier introuvable : {file_path}")
        print(f"Copiez sync_config.example.json vers {CONFIG_FILE.name} et remplissez-le.")
        return 2
    try:
        cfg = load_json_file(file_path)
    except SyncConfigFileError as exc:
        print(f"[ERREUR] {exc}")
        return 2
    conn = open_db(db_path)
    try:
        write_config(conn, cfg)
    finally:
        conn.close()
    print(f"[OK] Configuration appliquée dans {db_path}")
    print(f"     Serveur : {cfg['server_url']}")
    print(f"     Poste   : {cfg['device_name'] or '(sans nom)'}")
    print("Redémarrez l'application de bureau pour que la synchronisation démarre.")
    return 0


# --- Mode console ------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix} : ").strip()
    return value or default


def run_console(db_path: Path, prefill: dict) -> int:
    print("=== Configuration de la synchronisation ===")
    print(f"Base : {db_path}\n")
    cfg = dict(prefill)
    cfg["server_url"] = _ask("URL du serveur", cfg["server_url"])
    cfg["device_token"] = _ask("Jeton du poste", cfg["device_token"])
    cfg["device_name"] = _ask("Nom du poste", cfg["device_name"])
    auto = _ask("Sync automatique (o/n)", "o" if cfg["auto_sync"] else "n").lower()
    cfg["auto_sync"] = auto.startswith("o") or auto.startswith("y")
    try:
        cfg["auto_sync_interval_seconds"] = int(
            _ask("Intervalle (secondes)", str(cfg["auto_sync_interval_seconds"]))
        )
    except ValueError:
        cfg["auto_sync_interval_seconds"] = MIN_INTERVAL
    if not cfg["server_url"] or not cfg["device_token"]:
        print("\n[ERREUR] L'URL du serveur et le jeton sont obligatoires.")
        return 2
    if _ask("Tester la connexion maintenant ? (o/n)", "o").lower().startswith("o"):
        try:
            print("  " + ping(cfg["server_url"], cfg["device_token"]))
        except RuntimeError as exc:
            print(f"  [ÉCHEC] {exc}")
            if not _ask("Enregistrer quand même ? (o/n)", "n").lower().startswith("o"):
                return 1
    conn = open_db(db_path)
    try:
        write_config(conn, cfg)
    finally:
        conn.close()
    print("\n[OK] Configuration enregistrée. Redémarrez l'application de bureau.")
    return 0


# --- Mode graphique (Tkinter) ------------------------------------------------

def run_gui(db_path: Path, prefill: dict) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("EMAB-SKS — Configurer la synchronisation")
    root.resizable(False, False)
    try:
        ico = ROOT / "assets" / "logo_emab.ico"
        if ico.exists():
            root.iconbitmap(str(ico))
    except Exception:
        pass

    pad = {"padx": 8, "pady": 4}
    frame = ttk.Frame(root, padding=12)
    frame.grid(sticky="nsew")

    db_var = tk.StringVar(value=str(db_path))
    url_var = tk.StringVar(value=prefill["server_url"])
    token_var = tk.StringVar(value=prefill["device_token"])
    name_var = tk.StringVar(value=prefill["device_name"])
    auto_var = tk.BooleanVar(value=bool(prefill["auto_sync"]))
    interval_var = tk.IntVar(value=int(prefill["auto_sync_interval_seconds"]))
    show_token = tk.BooleanVar(value=False)
    status_var = tk.StringVar(value="Renseignez les champs puis cliquez sur Enregistrer.")

    ttk.Label(frame, text="Base de données du poste").grid(row=0, column=0, sticky="w", **pad)
    db_entry = ttk.Entry(frame, textvariable=db_var, width=58)
    db_entry.grid(row=0, column=1, sticky="we", **pad)

    def browse_db() -> None:
        chosen = filedialog.askopenfilename(
            title="Choisir gestionnaire.db",
            filetypes=[("Base SQLite", "*.db"), ("Tous les fichiers", "*.*")],
            initialdir=str(Path(db_var.get()).parent),
        )
        if chosen:
            db_var.set(chosen)
            reload_from_db()

    ttk.Button(frame, text="Parcourir…", command=browse_db).grid(row=0, column=2, **pad)

    ttk.Separator(frame).grid(row=1, column=0, columnspan=3, sticky="we", pady=6)

    ttk.Label(frame, text="URL du serveur").grid(row=2, column=0, sticky="w", **pad)
    ttk.Entry(frame, textvariable=url_var, width=58).grid(row=2, column=1, columnspan=2, sticky="we", **pad)

    ttk.Label(frame, text="Jeton du poste").grid(row=3, column=0, sticky="w", **pad)
    token_entry = ttk.Entry(frame, textvariable=token_var, width=58, show="•")
    token_entry.grid(row=3, column=1, sticky="we", **pad)

    def toggle_token() -> None:
        token_entry.configure(show="" if show_token.get() else "•")

    ttk.Checkbutton(frame, text="Afficher", variable=show_token, command=toggle_token).grid(
        row=3, column=2, sticky="w", **pad)

    ttk.Label(frame, text="Nom du poste").grid(row=4, column=0, sticky="w", **pad)
    ttk.Entry(frame, textvariable=name_var, width=58).grid(row=4, column=1, columnspan=2, sticky="we", **pad)

    ttk.Separator(frame).grid(row=5, column=0, columnspan=3, sticky="we", pady=6)

    auto_row = ttk.Frame(frame)
    auto_row.grid(row=6, column=0, columnspan=3, sticky="w", **pad)
    ttk.Checkbutton(auto_row, text="Synchronisation automatique (push + pull en arrière-plan)",
                    variable=auto_var).pack(side="left")
    ttk.Label(auto_row, text="   toutes les").pack(side="left")
    ttk.Spinbox(auto_row, from_=MIN_INTERVAL, to=3600, increment=15, width=6,
                textvariable=interval_var).pack(side="left", padx=4)
    ttk.Label(auto_row, text="secondes").pack(side="left")

    status = ttk.Label(frame, textvariable=status_var, foreground="#444", wraplength=560)
    status.grid(row=7, column=0, columnspan=3, sticky="w", **pad)

    def set_status(msg: str, ok: Optional[bool] = None) -> None:
        status_var.set(msg)
        status.configure(foreground={True: "#1b7f3b", False: "#b00020"}.get(ok, "#444"))
        root.update_idletasks()

    def collect() -> dict:
        try:
            interval = int(interval_var.get())
        except (tk.TclError, ValueError):
            interval = MIN_INTERVAL
        return {
            "server_url": url_var.get().strip().rstrip("/"),
            "device_token": token_var.get().strip(),
            "device_name": name_var.get().strip(),
            "auto_sync": bool(auto_var.get()),
            "auto_sync_interval_seconds": max(MIN_INTERVAL, interval),
        }

    def reload_from_db() -> None:
        try:
            conn = open_db(Path(db_var.get()))
        except (OSError, sqlite3.Error) as exc:
            set_status(f"Base inaccessible : {exc}", False)
            return
        try:
            current = read_config(conn)
        finally:
            conn.close()
        if current["server_url"] or current["device_token"]:
            url_var.set(current["server_url"])
            token_var.set(current["device_token"])
            name_var.set(current["device_name"])
            auto_var.set(current["auto_sync"])
            interval_var.set(current["auto_sync_interval_seconds"])
        set_status(f"Configuration actuelle chargée depuis {db_var.get()}")

    def do_test() -> None:
        cfg = collect()
        if not cfg["server_url"] or not cfg["device_token"]:
            set_status("Renseignez l'URL du serveur et le jeton avant de tester.", False)
            return
        set_status("Test de connexion en cours…")
        try:
            set_status(ping(cfg["server_url"], cfg["device_token"]), True)
        except RuntimeError as exc:
            set_status(str(exc), False)

    def do_save() -> None:
        cfg = collect()
        if not cfg["server_url"] or not cfg["device_token"]:
            messagebox.showerror("Synchronisation",
                                 "L'URL du serveur et le jeton du poste sont obligatoires.")
            return
        if not cfg["server_url"].lower().startswith(("http://", "https://")):
            messagebox.showerror("Synchronisation",
                                 "L'URL du serveur doit commencer par http:// ou https://.")
            return
        try:
            conn = open_db(Path(db_var.get()))
        except (OSError, sqlite3.Error) as exc:
            messagebox.showerror("Synchronisation", f"Base inaccessible :\n{exc}")
            return
        try:
            write_config(conn, cfg)
        except sqlite3.Error as exc:
            messagebox.showerror("Synchronisation", f"Écriture impossible :\n{exc}")
            return
        finally:
            conn.close()
        set_status("Configuration enregistrée.", True)
        messagebox.showinfo(
            "Synchronisation",
            "Configuration enregistrée.\n\n"
            "Redémarrez l'application de bureau : la synchronisation "
            + ("automatique démarrera toute seule." if cfg["auto_sync"]
               else "pourra être lancée depuis Administration → Synchronisation."),
        )

    def do_import() -> None:
        chosen = filedialog.askopenfilename(
            title="Importer un fichier sync_config.json",
            filetypes=[("Fichier JSON", "*.json"), ("Tous les fichiers", "*.*")],
            initialdir=str(ROOT),
        )
        if not chosen:
            return
        try:
            cfg = load_json_file(Path(chosen))
        except SyncConfigFileError as exc:
            messagebox.showerror("Import", str(exc))
            return
        url_var.set(cfg["server_url"])
        token_var.set(cfg["device_token"])
        name_var.set(cfg["device_name"])
        if cfg.get("auto_sync") is not None:
            auto_var.set(bool(cfg["auto_sync"]))
        if cfg.get("auto_sync_interval_seconds") is not None:
            interval_var.set(int(cfg["auto_sync_interval_seconds"]))
        set_status(f"Valeurs importées depuis {Path(chosen).name} — cliquez sur Enregistrer.")

    buttons = ttk.Frame(frame)
    buttons.grid(row=8, column=0, columnspan=3, sticky="e", pady=(10, 0))
    ttk.Button(buttons, text="Importer un JSON…", command=do_import).pack(side="left", padx=4)
    ttk.Button(buttons, text="Tester la connexion", command=do_test).pack(side="left", padx=4)
    ttk.Button(buttons, text="Enregistrer", command=do_save).pack(side="left", padx=4)
    ttk.Button(buttons, text="Fermer", command=root.destroy).pack(side="left", padx=4)

    frame.columnconfigure(1, weight=1)
    root.bind("<Return>", lambda _e: do_save())
    root.bind("<Escape>", lambda _e: root.destroy())
    root.eval("tk::PlaceWindow . center")
    root.mainloop()
    return 0


# --- Point d'entrée ----------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Configurer la synchronisation du poste.")
    parser.add_argument("--db", help="Chemin de gestionnaire.db (détection automatique sinon).")
    parser.add_argument("--file", help=f"Fichier JSON à utiliser (défaut : {CONFIG_FILE.name}).")
    parser.add_argument("--apply", action="store_true",
                        help="Applique le fichier JSON sans interaction.")
    parser.add_argument("--console", action="store_true", help="Mode texte (sans fenêtre).")
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else default_db()
    file_path = Path(args.file) if args.file else CONFIG_FILE

    if args.apply:
        return apply_from_file(db_path, file_path)

    # Pré-remplissage : base actuelle, puis fichier JSON s'il existe (prioritaire).
    conn = open_db(db_path)
    try:
        prefill = read_config(conn)
    finally:
        conn.close()
    if file_path.is_file():
        try:
            from_file = load_json_file(file_path)
            prefill.update({k: v for k, v in from_file.items() if v is not None})
        except SyncConfigFileError as exc:
            print(f"[AVERTISSEMENT] {exc}")

    if not args.console:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            print("Tkinter indisponible : passage en mode console.")
            args.console = True
    if args.console:
        return run_console(db_path, prefill)
    return run_gui(db_path, prefill)


if __name__ == "__main__":
    sys.exit(main())
