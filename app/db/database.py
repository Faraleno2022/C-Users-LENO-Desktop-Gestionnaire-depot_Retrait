"""Gestion de la connexion SQLite."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from app.config import DB_PATH, ensure_directories
from app.db.schema import SCHEMA_STATEMENTS

_local = threading.local()


def _connect() -> sqlite3.Connection:
    ensure_directories()
    conn = sqlite3.connect(str(DB_PATH), detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def get_connection() -> sqlite3.Connection:
    """Connexion partagée par thread."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Contexte avec rollback automatique en cas d'erreur."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_database() -> None:
    """Crée les tables si elles n'existent pas."""
    conn = get_connection()
    cur = conn.cursor()
    for stmt in SCHEMA_STATEMENTS:
        cur.execute(stmt)
    conn.commit()
    _apply_post_migrations(conn)


def _apply_post_migrations(conn) -> None:
    """Migrations one-shot enregistrées dans app_settings (clé ≈ flag idempotent)."""
    cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_users_hash_resync_v1'")
    row = cur.fetchone()
    if row is None:
        # Force la re-synchronisation des utilisateurs existants pour propager
        # password_hash vers le serveur (utilisé pour l'auth web).
        cur.execute("UPDATE users SET sync_status = 'pending' WHERE sync_status = 'synced'")
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_users_hash_resync_v1', '1')"
        )
        conn.commit()

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_agent_uuid_v1'")
    row = cur.fetchone()
    if row is None:
        # Ajoute agent_uuid aux tables d'opérations (si absent) et le backfill.
        for table in ("transactions", "sales", "stock_movements"):
            cols = [r["name"] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
            if "agent_uuid" not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN agent_uuid TEXT")
            cur.execute(
                f"UPDATE {table} SET agent_uuid = (SELECT uuid FROM users WHERE users.id = {table}.agent_id) "
                f"WHERE agent_uuid IS NULL OR agent_uuid = ''"
            )
            cur.execute(
                f"UPDATE {table} SET sync_status = 'pending' WHERE sync_status = 'synced'"
            )
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_agent_uuid_v1', '1')"
        )
        conn.commit()

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_product_uuid_v1'")
    row = cur.fetchone()
    if row is None:
        for table in ("stock_movements", "sales"):
            cols = [r["name"] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
            if "product_uuid" not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN product_uuid TEXT")
            cur.execute(
                f"UPDATE {table} SET product_uuid = "
                f"(SELECT uuid FROM products WHERE products.id = {table}.product_id) "
                f"WHERE product_uuid IS NULL OR product_uuid = ''"
            )
            cur.execute(
                f"UPDATE {table} SET sync_status = 'pending' WHERE sync_status = 'synced'"
            )
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_product_uuid_v1', '1')"
        )
        conn.commit()

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_audit_sync_v1'")
    row = cur.fetchone()
    if row is None:
        # audit_logs : ajoute uuid, user_uuid, sync_status, last_synced_at + backfill.
        cols = [r["name"] for r in cur.execute("PRAGMA table_info(audit_logs)").fetchall()]
        if "uuid" not in cols:
            cur.execute("ALTER TABLE audit_logs ADD COLUMN uuid TEXT")
        if "user_uuid" not in cols:
            cur.execute("ALTER TABLE audit_logs ADD COLUMN user_uuid TEXT")
        if "sync_status" not in cols:
            cur.execute(
                "ALTER TABLE audit_logs ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'pending'"
            )
        if "last_synced_at" not in cols:
            cur.execute("ALTER TABLE audit_logs ADD COLUMN last_synced_at TEXT")

        # Backfill uuid (random) et user_uuid (via users.id)
        import uuid as _uuid
        rows = cur.execute(
            "SELECT id, user_id FROM audit_logs WHERE uuid IS NULL OR uuid = ''"
        ).fetchall()
        for r in rows:
            new_uuid = str(_uuid.uuid4())
            cur.execute(
                "UPDATE audit_logs SET uuid = ?, "
                "user_uuid = (SELECT uuid FROM users WHERE users.id = ?) "
                "WHERE id = ?",
                (new_uuid, r["user_id"], r["id"]),
            )
        # Index unique pour l'upsert ultérieur (uuid)
        try:
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_uuid ON audit_logs(uuid)"
            )
        except Exception:
            pass
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_audit_sync_v1', '1')"
        )
        conn.commit()


def close_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
