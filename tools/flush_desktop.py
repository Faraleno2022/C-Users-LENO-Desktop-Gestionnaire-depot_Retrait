"""Vide les donnees metier d'une base desktop (gestionnaire.db).

Supprime ventes, transactions, mouvements de stock, produits, clients et
journal d'audit, mais CONSERVE la table `users` (comptes de connexion) afin de
ne pas perdre les comptes ni provoquer de collision a la prochaine sync.

Reinitialise aussi les filigranes de pull (pull_since_*) pour repartir propre.

Usage :
    python tools/flush_desktop.py "C:/chemin/vers/gestionnaire.db"

Sans argument, cible les emplacements habituels :
    %LOCALAPPDATA%/EMAB GROUP/Gestionnaire/data/gestionnaire.db
    <repo>/data/gestionnaire.db

A executer application desktop fermee.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# Tables metier a vider (l'ordre vide les dependantes avant les produits).
TABLES = [
    "sales",
    "transactions",
    "stock_movements",
    "products",
    "clients",
    "audit_logs",
]


def default_targets() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    here = Path(__file__).resolve().parent.parent
    return [
        local / "EMAB GROUP" / "Gestionnaire" / "data" / "gestionnaire.db",
        here / "data" / "gestionnaire.db",
    ]


def flush(db_path: Path) -> bool:
    if not db_path.exists():
        print(f"  (absente)        {db_path}")
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        before = {}
        for t in TABLES:
            try:
                before[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                before[t] = None
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        for t in TABLES:
            try:
                conn.execute(f"DELETE FROM {t}")
            except sqlite3.Error:
                pass
        # Reinitialise les filigranes de pull pour ne pas bloquer un futur
        # re-telechargement (la table app_settings stocke pull_since_<table>).
        try:
            conn.execute("DELETE FROM app_settings WHERE key LIKE 'pull_since_%'")
        except sqlite3.Error:
            pass
        conn.commit()
        try:
            conn.execute("VACUUM")
        except sqlite3.Error:
            pass
        summary = ", ".join(
            f"{t}:{before[t]}" for t in TABLES if before.get(t)
        ) or "deja vide"
        print(f"  [OK] vide ({summary}) — comptes conserves: {users}")
        print(f"       {db_path}")
        return True
    finally:
        conn.close()


def main() -> int:
    args = sys.argv[1:]
    targets = [Path(a) for a in args] if args else default_targets()
    print("Vidage des bases desktop (comptes conserves) :")
    any_done = False
    for db in targets:
        any_done = flush(db) or any_done
    if not any_done:
        print("Aucune base trouvee/videe.")
    else:
        print("\nTermine. Relancez l'application desktop : elle affichera 0 partout.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
