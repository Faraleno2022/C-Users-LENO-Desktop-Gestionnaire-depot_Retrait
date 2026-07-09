"""Synchronisation poste ↔ serveur (push + pull).

Modèle retenu : le poste reste source de vérité pour les opérations financières
(transactions, ventes, mouvements de stock). Les entités administratives
(catalogue produits, fiches clients, comptes utilisateurs) peuvent être éditées
depuis la console web : un `pull` régulier les rapatrie sur le poste.

Règle de merge (pull) :
  - Si la ligne locale n'existe pas (par uuid)        → INSERT (sync_status='synced')
  - Si la ligne locale existe et sync_status='synced' → UPDATE (server wins)
  - Si la ligne locale existe et sync_status='pending'→ SKIP (le push sortant gagnera)

Authentification : jeton par poste, en-tête `Authorization: Device <token>`.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.config import SYNC_STATUS_SYNCED
from app.db.database import get_connection
from app.services import settings_service
from app.utils.helpers import now_iso

try:
    import requests
except ImportError:  # pragma: no cover - requests fait partie des dépendances
    requests = None  # type: ignore


class SyncError(Exception):
    pass


# Tables synchronisées et colonnes envoyées (le serveur n'a pas besoin des id locaux
# ni des hash de mot de passe). L'ordre respecte les dépendances logiques.
PUSH_TABLES: Dict[str, List[str]] = {
    "users": [
        "uuid", "identifiant", "nom_complet", "matricule", "telephone",
        "role", "actif", "password_hash", "created_at", "updated_at",
    ],
    "products": [
        "uuid", "reference", "nom", "description", "prix_unitaire",
        "quantite_stock", "seuil_alerte", "categorie", "unite", "prix_achat",
        "stock_max", "emplacement", "actif", "created_at", "updated_at",
    ],
    "stock_movements": [
        "uuid", "product_id", "product_uuid", "product_nom", "type", "quantite",
        "stock_apres", "motif", "sale_id", "agent_id", "agent_uuid",
        "agent_nom", "created_at", "deleted",
    ],
    "transactions": [
        "uuid", "matricule", "telephone", "type", "montant", "solde_apres",
        "agent_id", "agent_uuid", "agent_nom", "note", "created_at", "deleted",
    ],
    "sales": [
        "uuid", "matricule", "telephone", "product_id", "product_uuid", "product_nom",
        "quantite", "prix_unitaire", "montant_total", "solde_apres",
        "agent_id", "agent_uuid", "agent_nom", "note", "created_at", "deleted",
    ],
    "clients": [
        "uuid", "matricule", "nom", "telephone", "note", "actif",
        "created_at", "updated_at",
    ],
    "audit_logs": [
        "uuid", "user_id", "user_uuid", "user_identifiant", "action",
        "target_type", "target_id", "details", "created_at",
    ],
}

DEFAULT_BATCH = 200
TIMEOUT = 20


# Tables pull (serveur → poste). L'ordre importe : `users` doit précéder
# `transactions` car ces dernières référencent un agent par uuid.
PULL_TABLES: Dict[str, List[str]] = {
    "users": [
        "uuid", "identifiant", "nom_complet", "matricule", "telephone",
        "role", "actif", "password_hash", "created_at", "updated_at",
    ],
    "products": [
        "uuid", "reference", "nom", "description", "prix_unitaire",
        "quantite_stock", "seuil_alerte", "categorie", "unite", "prix_achat",
        "stock_max", "emplacement", "actif", "created_at", "updated_at",
    ],
    "clients": [
        "uuid", "matricule", "nom", "telephone", "note", "actif",
        "created_at", "updated_at",
    ],
    # Opérations financières : dépôts/retraits créés depuis le web reviennent
    # vers les postes. `agent_id` local est résolu via `agent_uuid` au merge.
    "transactions": [
        "uuid", "matricule", "telephone", "type", "montant", "solde_apres",
        "agent_id", "agent_uuid", "agent_nom", "note", "created_at", "deleted",
    ],
    # Mouvements de stock créés depuis le web (entrées/sorties hors vente).
    # `product_id` local est résolu via `product_uuid`.
    "stock_movements": [
        "uuid", "product_id", "product_uuid", "product_nom", "type", "quantite",
        "stock_apres", "motif", "sale_id", "agent_id", "agent_uuid",
        "agent_nom", "created_at", "deleted",
    ],
    # Ventes créées depuis le web.
    "sales": [
        "uuid", "matricule", "telephone", "product_id", "product_uuid", "product_nom",
        "quantite", "prix_unitaire", "montant_total", "solde_apres",
        "agent_id", "agent_uuid", "agent_nom", "note", "created_at", "deleted",
    ],
    # Audit : pull pour récupérer les actions effectuées depuis le web.
    "audit_logs": [
        "uuid", "user_id", "user_uuid", "user_identifiant", "action",
        "target_type", "target_id", "details", "created_at",
    ],
}


def _pull_since_key(table: str) -> str:
    return f"pull_since_{table}"


# Références à résoudre lors d'un pull (uuid serveur → id local).
# Format par table : liste de (champ uuid, champ id local à remplir, table locale de lookup,
# tolerate_missing). tolerate_missing=True => on met l'id à None plutôt que d'échouer.
_LOOKUP_TABLES = {
    "transactions": [
        ("agent_uuid", "agent_id", "users", False),
    ],
    "sales": [
        ("agent_uuid", "agent_id", "users", False),
        ("product_uuid", "product_id", "products", False),
    ],
    "stock_movements": [
        ("agent_uuid", "agent_id", "users", True),  # tolère agent absent (mouvements anciens)
        ("product_uuid", "product_id", "products", False),
    ],
    "audit_logs": [
        ("user_uuid", "user_id", "users", True),  # un audit sans user reste lisible
    ],
}


def _resolve_local_id(conn, lookup_table: str, ref_uuid: Optional[str]) -> Optional[int]:
    if not ref_uuid:
        return None
    row = conn.execute(
        f"SELECT id FROM {lookup_table} WHERE uuid = ?", (ref_uuid,)
    ).fetchone()
    return int(row["id"]) if row else None


def _require_requests() -> None:
    if requests is None:
        raise SyncError("Le module 'requests' n'est pas installé (pip install requests).")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Device {token}",
        "Content-Type": "application/json",
    }


def _collect_pending(table: str, columns: List[str], limit: int) -> List[dict]:
    conn = get_connection()
    col_sql = ", ".join(columns)
    rows = conn.execute(
        f"SELECT {col_sql} FROM {table} WHERE sync_status = 'pending' "
        f"ORDER BY rowid ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def _mark_synced(table: str, uuids: List[str]) -> None:
    if not uuids:
        return
    conn = get_connection()
    ts = now_iso()
    placeholders = ",".join("?" for _ in uuids)
    conn.execute(
        f"UPDATE {table} SET sync_status = '{SYNC_STATUS_SYNCED}', last_synced_at = ? "
        f"WHERE uuid IN ({placeholders})",
        [ts, *uuids],
    )
    conn.commit()


def pending_total() -> int:
    conn = get_connection()
    total = 0
    for table in PUSH_TABLES:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE sync_status = 'pending'"
        ).fetchone()
        total += int(row["n"])
    return total


def test_connection(server_url: Optional[str] = None, token: Optional[str] = None) -> bool:
    """Vérifie que le serveur répond et que le jeton est valide."""
    _require_requests()
    cfg = settings_service.get_sync_config()
    url = (server_url or cfg["server_url"]).rstrip("/")
    tok = token or cfg["device_token"]
    if not url or not tok:
        raise SyncError("Configuration de synchronisation incomplète.")
    try:
        resp = requests.get(f"{url}/api/sync/ping/", headers=_headers(tok), timeout=TIMEOUT)
    except requests.RequestException as e:
        raise SyncError(f"Connexion impossible : {e}") from e
    if resp.status_code == 401:
        raise SyncError("Jeton du poste refusé par le serveur (401).")
    if resp.status_code != 200:
        raise SyncError(f"Réponse inattendue du serveur ({resp.status_code}).")
    return True


def _merge_pulled_record(table: str, columns: List[str], rec: dict) -> str:
    """Insère ou met à jour une ligne locale à partir d'un record du serveur.

    Retourne 'inserted' | 'updated' | 'skipped_pending' | 'conflict'.
    """
    conn = get_connection()
    uuid = rec.get("uuid")
    if not uuid:
        return "conflict"
    cur = conn.execute(
        f"SELECT id, sync_status FROM {table} WHERE uuid = ?", (uuid,)
    ).fetchone()

    # Prépare un dict de valeurs SQL en castant les booléens.
    values = {}
    for col in columns:
        if col == "uuid":
            continue
        v = rec.get(col)
        # Booléens Django → INTEGER 0/1 attendu en local
        if isinstance(v, bool):
            v = 1 if v else 0
        values[col] = v

    # Tables avec références à traduire (uuid serveur → id local).
    if table in _LOOKUP_TABLES:
        for uuid_field, id_field, lookup_table, tolerate in _LOOKUP_TABLES[table]:
            ref_uuid = values.get(uuid_field)
            local_id = _resolve_local_id(conn, lookup_table, ref_uuid)
            if local_id is None:
                if tolerate:
                    values[id_field] = None
                else:
                    # La référence n'existe pas (encore) localement. Reporté ;
                    # le pull suivant (après pull de la table parente) résoudra.
                    return "conflict"
            else:
                values[id_field] = local_id

    ts = now_iso()
    if cur is None:
        # INSERT — la ligne n'existe pas localement
        cols_list = ["uuid", *values.keys(), "sync_status", "last_synced_at"]
        placeholders = ",".join("?" for _ in cols_list)
        params = [uuid, *values.values(), SYNC_STATUS_SYNCED, ts]
        try:
            conn.execute(
                f"INSERT INTO {table} ({', '.join(cols_list)}) VALUES ({placeholders})",
                params,
            )
            conn.commit()
            return "inserted"
        except Exception:
            # Contraintes UNIQUE concurrentes (matricule, identifiant, etc.)
            conn.rollback()
            return "conflict"
    else:
        if cur["sync_status"] == "pending":
            return "skipped_pending"
        # UPDATE — server wins sur lignes propres
        set_sql = ", ".join(f"{k} = ?" for k in values.keys())
        params = [
            *values.values(), SYNC_STATUS_SYNCED, ts, uuid,
        ]
        try:
            conn.execute(
                f"UPDATE {table} SET {set_sql}, sync_status = ?, last_synced_at = ? "
                f"WHERE uuid = ?",
                params,
            )
            conn.commit()
            return "updated"
        except Exception:
            conn.rollback()
            return "conflict"


def pull_all(batch: int = DEFAULT_BATCH, progress=None) -> dict:
    """Récupère les modifications côté serveur pour les tables admin.

    Retourne un résumé `{table: {"inserted": n, "updated": n, "skipped_pending": n, "conflict": n}}`.
    """
    _require_requests()
    cfg = settings_service.get_sync_config()
    url = cfg["server_url"].rstrip("/")
    token = cfg["device_token"]
    if not url or not token:
        raise SyncError("Configuration de synchronisation incomplète (URL ou jeton manquant).")

    endpoint = f"{url}/api/sync/pull/"
    summary: Dict[str, Dict[str, int]] = {}

    for table, columns in PULL_TABLES.items():
        tally = {"inserted": 0, "updated": 0, "skipped_pending": 0, "conflict": 0}
        since = settings_service.get_setting(_pull_since_key(table), "") or ""
        while True:
            params = {"table": table, "since": since, "limit": batch}
            try:
                resp = requests.get(
                    endpoint, params=params, headers=_headers(token), timeout=TIMEOUT
                )
            except requests.RequestException as e:
                raise SyncError(f"Échec réseau pendant le pull de {table} : {e}") from e
            if resp.status_code == 401:
                raise SyncError("Jeton du poste refusé par le serveur (401).")
            if resp.status_code != 200:
                raise SyncError(
                    f"Le serveur a rejeté le pull de {table} ({resp.status_code}) : {resp.text[:200]}"
                )
            body = resp.json()
            records = body.get("records") or []
            for rec in records:
                outcome = _merge_pulled_record(table, columns, rec)
                tally[outcome] = tally.get(outcome, 0) + 1
            next_since = body.get("next_since") or since
            has_more = bool(body.get("has_more"))
            if next_since:
                settings_service.set_setting(_pull_since_key(table), next_since)
                since = next_since
            if progress:
                progress(f"{table} : +{tally['inserted']} / ~{tally['updated']}")
            if not has_more or not records:
                break
        summary[table] = tally

    return summary


def sync_all(batch: int = DEFAULT_BATCH, progress=None) -> dict:
    """Synchro complète : push d'abord (sortant), puis pull (entrant).

    Le push d'abord garantit que les modifications locales prennent priorité
    en cas de conflit avec une édition concurrente côté serveur.
    """
    push_summary = push_all(batch=batch, progress=progress)
    pull_summary = pull_all(batch=batch, progress=progress)
    return {"pushed": push_summary, "pulled": pull_summary}


def push_all(batch: int = DEFAULT_BATCH, progress=None) -> dict:
    """Pousse tous les enregistrements en attente. Retourne un résumé par table.

    progress : callable optionnel(str) pour remonter l'avancement à l'IHM.
    """
    _require_requests()
    cfg = settings_service.get_sync_config()
    url = cfg["server_url"].rstrip("/")
    token = cfg["device_token"]
    if not url or not token:
        raise SyncError("Configuration de synchronisation incomplète (URL ou jeton manquant).")

    endpoint = f"{url}/api/sync/push/"
    summary: Dict[str, int] = {}

    for table, columns in PUSH_TABLES.items():
        sent = 0
        while True:
            records = _collect_pending(table, columns, batch)
            if not records:
                break
            payload = {"table": table, "records": records}
            try:
                resp = requests.post(
                    endpoint, json=payload, headers=_headers(token), timeout=TIMEOUT
                )
            except requests.RequestException as e:
                raise SyncError(f"Échec réseau pendant l'envoi de {table} : {e}") from e
            if resp.status_code == 401:
                raise SyncError("Jeton du poste refusé par le serveur (401).")
            if resp.status_code not in (200, 201):
                raise SyncError(
                    f"Le serveur a rejeté {table} ({resp.status_code}) : {resp.text[:200]}"
                )
            uuids = [r["uuid"] for r in records]
            _mark_synced(table, uuids)
            sent += len(uuids)
            if progress:
                progress(f"{table} : {sent} envoyé(s)")
            if len(records) < batch:
                break
        summary[table] = sent

    return summary
