"""Sauvegarde et restauration de la base SQLite."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from uuid import uuid4
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.config import BACKUP_DIR, DATETIME_FMT, DB_PATH, ensure_directories
from app.db.database import get_connection, transaction as db_transaction
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
    dest = BACKUP_DIR / f"backup_{kind}_{ts}_{uuid4().hex[:8]}.db"

    conn = get_connection()
    conn.commit()
    # Sauvegarde via l'API SQLite (sûr même base ouverte)
    with closing(sqlite3.connect(str(dest))) as bck:
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


def export_database(file_path: Path) -> Path:
    """Exporte un instantané SQLite complet, y compris les écritures WAL."""
    import shutil
    file_path = Path(file_path)
    if file_path.resolve() == Path(DB_PATH).resolve():
        raise BackupError("L'export ne peut pas remplacer la base active.")
    snapshot = create_backup(kind="manual", note="Export manuel")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = file_path.with_name(file_path.name + "." + uuid4().hex + ".tmp")
    try:
        shutil.copy2(snapshot, temporary)
        temporary.replace(file_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return file_path


def list_backups() -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM backups ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def restore_backup(backup_path: Path) -> None:
    """Valide et prépare la copie avant une restauration atomique via SQLite."""
    from app.db import database
    from app.services.sync_service import sync_lock

    backup_path = Path(backup_path)
    if not backup_path.is_file():
        raise BackupError(f"Fichier introuvable : {backup_path}")
    if backup_path.resolve() == Path(DB_PATH).resolve():
        raise BackupError("Sélectionnez une sauvegarde distincte de la base active.")
    with sync_lock, closing(sqlite3.connect(":memory:")) as staged:
        staged.row_factory = sqlite3.Row
        try:
            with closing(sqlite3.connect(backup_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                source.backup(staged)
            if staged.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("La sauvegarde est endommagée.")
            required = {"users": {"id", "uuid", "identifiant", "password_hash", "role"},
                        "transactions": {"id", "uuid", "matricule", "type", "montant"}}
            for table, names in required.items():
                columns = {r["name"] for r in staged.execute(f"PRAGMA table_info({table})")}
                if not names <= columns:
                    raise BackupError("Ce fichier n'est pas une sauvegarde compatible du gestionnaire.")
            for statement in database.SCHEMA_STATEMENTS:
                staged.execute(statement)
            staged.commit()
            database._apply_post_migrations(staged)
            database._allow_missing_agents(staged)
            if staged.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise BackupError("La sauvegarde contient des références de données invalides.")
        except (sqlite3.Error, OSError) as exc:
            raise BackupError(f"Sauvegarde invalide : {exc}") from exc

        safety = create_backup(kind="auto", note="Avant restauration") if DB_PATH.exists() else None
        actor = auth_service.current_user()
        destination = get_connection()
        destination.commit()
        # L'API de sauvegarde respecte WAL et les autres connexions ouvertes.
        staged.backup(destination)
        if safety:
            destination.execute(
                "INSERT INTO backups (file_path, size_bytes, kind, created_at, note) VALUES (?,?,?,?,?)",
                (str(safety), safety.stat().st_size, "auto", now_iso(), "Avant restauration"),
            )
            destination.commit()
        audit_service.log_action(
            actor.id if actor else None, actor.identifiant if actor else None,
            "BACKUP_RESTORE", target_type="backup", target_id=backup_path.name,
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
    if keep < 0:
        raise BackupError("Le nombre de sauvegardes à conserver ne peut pas être négatif.")
    retained = {Path(row["file_path"]).resolve() for row in rows[:keep]}
    removed = 0
    for row in rows[keep:]:
        path = Path(row["file_path"])
        try:
            if not path.resolve().is_relative_to(Path(BACKUP_DIR).resolve()):
                continue
            if path.exists() and path.resolve() not in retained:
                path.unlink()
        except OSError:
            continue
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


@db_transaction()
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
