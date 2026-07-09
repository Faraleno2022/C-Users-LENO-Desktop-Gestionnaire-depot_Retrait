"""Sauvegarde et restauration de la base SQLite."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.config import BACKUP_DIR, DATETIME_FMT, DB_PATH, ensure_directories
from app.db.database import close_connection, get_connection
from app.services import audit_service, auth_service
from app.utils.helpers import now_iso


class BackupError(Exception):
    pass


def create_backup(kind: str = "manual", note: str = "") -> Path:
    if kind not in ("auto", "manual"):
        raise BackupError("Type de sauvegarde invalide.")
    ensure_directories()
    if not DB_PATH.exists():
        raise BackupError("Base de données introuvable.")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"backup_{kind}_{ts}.db"

    conn = get_connection()
    conn.commit()
    # Sauvegarde via l'API SQLite (sûr même base ouverte)
    import sqlite3
    with sqlite3.connect(str(dest)) as bck:
        conn.backup(bck)

    size = dest.stat().st_size
    conn.execute(
        "INSERT INTO backups (file_path, size_bytes, kind, created_at, note) VALUES (?,?,?,?,?)",
        (str(dest), size, kind, now_iso(), note or None),
    )
    conn.commit()

    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "BACKUP_CREATE",
        target_type="backup",
        target_id=str(dest.name),
        details=kind,
    )
    return dest


def list_backups() -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM backups ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def restore_backup(backup_path: Path) -> None:
    if not backup_path.exists():
        raise BackupError(f"Fichier introuvable : {backup_path}")
    # On crée une sauvegarde de sécurité avant restauration
    safety = None
    if DB_PATH.exists():
        safety = create_backup(kind="auto", note="Avant restauration")
    actor = auth_service.current_user()

    close_connection()
    shutil.copy2(str(backup_path), str(DB_PATH))

    # On relance les tables si besoin
    from app.db.database import init_database
    init_database()

    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "BACKUP_RESTORE",
        target_type="backup",
        target_id=str(backup_path.name),
        details=f"safety={safety.name if safety else 'none'}",
    )


# --- Sauvegarde planifiée (automatique) -------------------------------------

def prune_auto_backups(keep: int) -> int:
    """Conserve les `keep` sauvegardes automatiques les plus récentes.

    Supprime les fichiers et les lignes correspondantes au-delà de la limite.
    Retourne le nombre de sauvegardes supprimées.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, file_path FROM backups WHERE kind = 'auto' ORDER BY id DESC"
    ).fetchall()
    removed = 0
    for row in rows[keep:]:
        path = Path(row["file_path"])
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        conn.execute("DELETE FROM backups WHERE id = ?", (row["id"],))
        removed += 1
    if removed:
        conn.commit()
    return removed


def run_auto_backup_if_due() -> Optional[Path]:
    """Crée une sauvegarde automatique si la périodicité configurée est échue.

    Appelé au démarrage de l'application. Retourne le chemin de la sauvegarde
    créée, ou None si la sauvegarde planifiée est désactivée ou pas encore due.
    """
    from app.services import settings_service

    cfg = settings_service.get_auto_backup_config()
    if not cfg["enabled"]:
        return None

    now = datetime.now()
    last_at = cfg["last_at"]
    if last_at:
        try:
            last = datetime.strptime(last_at, DATETIME_FMT)
            if (now - last).total_seconds() < cfg["interval_days"] * 86400:
                return None  # pas encore due
        except ValueError:
            pass  # horodatage illisible -> on sauvegarde

    dest = create_backup(kind="auto", note="Sauvegarde planifiée")
    settings_service.mark_auto_backup_done(now.strftime(DATETIME_FMT))
    prune_auto_backups(cfg["keep"])
    return dest


def wipe_data() -> None:
    """Réinitialisation : vide transactions et audit_logs (conserve utilisateurs)."""
    conn = get_connection()
    ts = now_iso()
    conn.execute("UPDATE transactions SET deleted = 1, sync_status = 'pending' WHERE deleted = 0;")
    conn.execute("UPDATE sales SET deleted = 1, sync_status = 'pending' WHERE deleted = 0;")
    conn.execute("UPDATE stock_movements SET deleted = 1, sync_status = 'pending' WHERE deleted = 0;")
    conn.execute(
        "UPDATE products SET actif = 0, updated_at = ?, sync_status = 'pending' WHERE actif = 1;",
        (ts,),
    )
    conn.execute(
        "UPDATE clients SET actif = 0, updated_at = ?, sync_status = 'pending' WHERE actif = 1;",
        (ts,),
    )
    conn.commit()
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "DATA_WIPE",
        details="Toutes les transactions et journaux supprimés",
    )
