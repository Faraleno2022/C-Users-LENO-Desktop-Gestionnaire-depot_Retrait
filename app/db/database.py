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
        # Réserver l'écriture avant de lire le stock et le solde.
        conn.execute("BEGIN IMMEDIATE")
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
    _allow_missing_agents(conn)
    _migrate_reconciliation(conn)


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

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_product_fields_v1'")
    row = cur.fetchone()
    if row is None:
        # Fiche article enrichie : catégorie, unité, prix d'achat, stock max, emplacement.
        # Champs locaux (non synchronisés pour l'instant) ; ajout idempotent.
        cols = [r["name"] for r in cur.execute("PRAGMA table_info(products)").fetchall()]
        if "categorie" not in cols:
            cur.execute("ALTER TABLE products ADD COLUMN categorie TEXT")
        if "unite" not in cols:
            cur.execute("ALTER TABLE products ADD COLUMN unite TEXT")
        if "prix_achat" not in cols:
            cur.execute("ALTER TABLE products ADD COLUMN prix_achat REAL NOT NULL DEFAULT 0")
        if "stock_max" not in cols:
            cur.execute("ALTER TABLE products ADD COLUMN stock_max REAL NOT NULL DEFAULT 0")
        if "emplacement" not in cols:
            cur.execute("ALTER TABLE products ADD COLUMN emplacement TEXT")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_products_categorie ON products(categorie)"
        )
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_product_fields_v1', '1')"
        )
        conn.commit()

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_product_extra_fields_resync_v1'")
    row = cur.fetchone()
    if row is None:
        # Les champs enrichis sont maintenant inclus dans le protocole de sync :
        # renvoyer les produits existants une fois pour les propager au serveur.
        cur.execute("UPDATE products SET sync_status = 'pending' WHERE sync_status = 'synced'")
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_product_extra_fields_resync_v1', '1')"
        )
        conn.commit()

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_stock_movement_deleted_v1'")
    row = cur.fetchone()
    if row is None:
        cols = [r["name"] for r in cur.execute("PRAGMA table_info(stock_movements)").fetchall()]
        if "deleted" not in cols:
            cur.execute("ALTER TABLE stock_movements ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
        cur.execute(
            "UPDATE stock_movements SET sync_status = 'pending' WHERE sync_status = 'synced'"
        )
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_stock_movement_deleted_v1', '1')"
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

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_zero_count_v1'")
    if cur.fetchone() is None:
        # Un comptage d'inventaire qui confirme le stock théorique produit un
        # mouvement de quantité nulle. Le serveur n'accepte une quantité nulle
        # que si la quantité comptée est renseignée : sans elle, il refusait le
        # lot entier et toute la synchronisation restait bloquée. La quantité
        # comptée d'un mouvement sans écart est le stock après mouvement.
        cols = [r["name"] for r in cur.execute("PRAGMA table_info(stock_movements)").fetchall()]
        if "stock_compte" in cols:
            cur.execute(
                "UPDATE stock_movements SET stock_compte = stock_apres, "
                "sync_status = 'pending' WHERE quantite = 0 AND stock_compte IS NULL"
            )
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_zero_count_v1', '1')"
        )
        conn.commit()

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_stock_tracking_v1'")
    if cur.fetchone() is None:
        # Certains articles ne se comptent pas en stock (plats servis, services).
        # Les articles existants restent suivis ; les trois plats passent en
        # « sans stock », et sont créés s'ils n'existent pas encore.
        cols = [r["name"] for r in cur.execute("PRAGMA table_info(products)").fetchall()]
        if "suivi_stock" not in cols:
            cur.execute(
                "ALTER TABLE products ADD COLUMN suivi_stock INTEGER NOT NULL DEFAULT 1"
            )
        _apply_untracked_plates(cur)
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_stock_tracking_v1', '1')"
        )
        conn.commit()

    cur.execute("SELECT value FROM app_settings WHERE key = 'mig_cash_register_v1'")
    if cur.fetchone() is None:
        # Caisse : les ventes existantes sont toutes des ventes sur compte.
        cols = [r["name"] for r in cur.execute("PRAGMA table_info(sales)").fetchall()]
        if "mode_paiement" not in cols:
            cur.execute(
                "ALTER TABLE sales ADD COLUMN mode_paiement TEXT NOT NULL DEFAULT 'compte'"
            )
        cur.execute(
            "INSERT INTO app_settings(key, value) VALUES ('mig_cash_register_v1', '1')"
        )
        conn.commit()


# Plats servis sans stock : nom affiché et prix de vente.
UNTRACKED_PLATES = (("Plat 5.000", 5000.0), ("Plat 10.000", 10000.0),
                    ("Plat 15.000", 15000.0))


def _plate_key(nom: str) -> str:
    """Nom comparable : « Plat 5.000 », « plat 5000 » et « PLAT 5 000 » se valent."""
    return "".join((nom or "").lower().split()).replace(".", "").replace(",", "")


def _apply_untracked_plates(cur) -> None:
    """Bascule les trois plats en « sans stock », en créant ceux qui manquent."""
    import uuid as _uuid
    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = {}
    for row in cur.execute("SELECT id, nom FROM products").fetchall():
        existing.setdefault(_plate_key(row["nom"]), row["id"])
    for nom, prix in UNTRACKED_PLATES:
        product_id = existing.get(_plate_key(nom))
        if product_id is not None:
            cur.execute(
                "UPDATE products SET suivi_stock = 0, sync_status = 'pending', "
                "updated_at = ? WHERE id = ?",
                (now, product_id),
            )
            continue
        cur.execute(
            "INSERT INTO products (uuid, nom, prix_unitaire, quantite_stock, "
            "stock_initial, stock_initial_source, seuil_alerte, stock_max, "
            "suivi_stock, actif, created_at, updated_at, sync_status) "
            "VALUES (?,?,?,0,0,'creation',0,0,0,1,?,?,'pending')",
            (str(_uuid.uuid4()), nom, prix, now, now),
        )


def _allow_missing_agents(conn):
    """Migre les anciennes tables sans perdre leurs données, index ou séquences."""
    import re
    for table in ("transactions", "sales", "stock_movements"):
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
        if not re.search(r"agent_id\s+INTEGER\s+NOT\s+NULL", sql, re.I):
            continue
        indexes = [r[0] for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL", (table,)
        )]
        sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (table,)).fetchone()
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            replacement = table + "_nullable_agent"
            create = sql.replace(table, replacement, 1)
            create = re.sub(r"agent_id\s+INTEGER\s+NOT\s+NULL", "agent_id INTEGER", create, flags=re.I)
            conn.execute(create)
            columns = ", ".join('"' + r["name"] + '"' for r in conn.execute(f"PRAGMA table_info({table})"))
            conn.execute(f"INSERT INTO {replacement} ({columns}) SELECT {columns} FROM {table}")
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {replacement} RENAME TO {table}")
            if sequence:
                conn.execute("UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name=?", (sequence[0], table))
            for index in indexes:
                conn.execute(index)
            conn.execute("DELETE FROM app_settings WHERE key IN (?, ?)",
                         (f"pull_since_{table}", f"pull_since_{table}_uuid"))


def _migrate_reconciliation(conn):
    """Ajoute les références du journal et autorise un inventaire sans écart."""
    import re
    for table, fields in {
        'products': {'stock_initial': 'REAL', 'stock_initial_source': "TEXT NOT NULL DEFAULT ''"},
        'stock_movements': {'is_initial': 'INTEGER NOT NULL DEFAULT 0', 'stock_compte': 'REAL'},
    }.items():
        columns = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
        for name, definition in fields.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    conn.commit()
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='stock_movements'").fetchone()[0]
    if re.search(r'quantite\s*>\s*0', sql):
        indexes = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE tbl_name='stock_movements' AND type IN ('index','trigger') AND sql IS NOT NULL")]
        sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='stock_movements'").fetchone()
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            create = sql.replace('stock_movements', 'stock_movements_rebuild', 1)
            conn.execute(re.sub(r'quantite\s*>\s*0', 'quantite >= 0', create))
            conn.execute('INSERT INTO stock_movements_rebuild SELECT * FROM stock_movements')
            conn.execute('DROP TABLE stock_movements')
            conn.execute('ALTER TABLE stock_movements_rebuild RENAME TO stock_movements')
            if sequence:
                conn.execute("UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name='stock_movements'", (sequence[0],))
            for index in indexes:
                conn.execute(index)


def close_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
