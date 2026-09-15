"""Gestion des transactions (dépôts / retraits) et calcul du solde."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from app.config import DATETIME_FMT
from app.db.database import get_connection, transaction as db_transaction
from app.models.transaction import Transaction
from app.models.user import User
from app.services import audit_service, auth_service
from app.utils.helpers import new_uuid, now_iso
from app.utils.accounting import add, subtract, number


class TransactionError(Exception):
    pass


# --- Soldes ------------------------------------------------------------------

def _balance(matricule: Optional[str] = None) -> float:
    conn = get_connection()
    clause = " AND matricule = ?" if matricule is not None else ""
    params = (matricule,) if matricule is not None else ()
    tx = conn.execute(
        "SELECT type, montant FROM transactions WHERE deleted = 0" + clause, params
    ).fetchall()
    sales = conn.execute(
        "SELECT montant_total FROM sales WHERE deleted = 0" + clause, params
    ).fetchall()
    return add(
        *(r["montant"] if r["type"] == "depot" else -r["montant"] for r in tx),
        *(-r["montant_total"] for r in sales),
    )


def get_global_balance() -> float:
    """Dépôts moins retraits et achats actifs, sans résidu de calcul binaire."""
    return _balance()


def get_matricule_balance(matricule: str) -> float:
    return _balance(matricule.strip())


# --- Création ----------------------------------------------------------------

def create_transaction(
    matricule: str,
    telephone: str,
    type_: str,
    montant: float,
    agent: User,
    note: str = "",
) -> Transaction:
    matricule = (matricule or "").strip()
    telephone = (telephone or "").strip()
    if not matricule:
        raise TransactionError("Le matricule est obligatoire.")
    if type_ not in ("depot", "retrait"):
        raise TransactionError("Type d'opération invalide.")
    try:
        montant = number(montant)
    except (ValueError, TypeError):
        raise TransactionError("Le montant doit être un nombre fini strictement positif.")
    if montant <= 0:
        raise TransactionError("Le montant doit être strictement positif.")
    if agent is None:
        raise TransactionError("Agent non identifié.")

    with db_transaction() as conn:
        current = get_matricule_balance(matricule)
        if type_ == "depot":
            new_balance = add(current, montant)
        else:
            if montant > current:
                raise TransactionError(
                    f"Solde insuffisant pour ce matricule. Solde disponible : {current:.0f}"
                )
            new_balance = subtract(current, montant)

        cur = conn.execute(
            """INSERT INTO transactions
               (uuid, matricule, telephone, type, montant, solde_apres,
                agent_id, agent_uuid, agent_nom, note, created_at, sync_status, deleted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (
                new_uuid(),
                matricule,
                telephone or None,
                type_,
                float(montant),
                float(new_balance),
                agent.id,
                getattr(agent, "uuid", None),
                agent.nom_complet,
                note or None,
                now_iso(),
                "pending",
            ),
        )
        tx_id = cur.lastrowid

    audit_service.log_action(
        agent.id,
        agent.identifiant,
        "TRANSACTION_CREATE",
        target_type="transaction",
        target_id=str(tx_id),
        details=f"{type_} {montant} matricule={matricule}",
    )
    return get_transaction(tx_id)


def get_transaction(tx_id: int) -> Optional[Transaction]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    return Transaction.from_row(row) if row else None


def delete_transaction(tx_id: int) -> None:
    """Suppression logique (réservée admins)."""
    with db_transaction() as conn:
        tx = get_transaction(tx_id)
        if tx is None:
            raise TransactionError("Transaction introuvable.")
        if tx.deleted:
            return
        if tx.type == "depot" and tx.montant > get_matricule_balance(tx.matricule):
            raise TransactionError("Ce dépôt a déjà été utilisé : son annulation rendrait le solde négatif.")
        conn.execute(
            "UPDATE transactions SET deleted = 1, sync_status = 'pending' WHERE id = ?",
            (tx_id,),
        )
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "TRANSACTION_DELETE",
        target_type="transaction",
        target_id=str(tx_id),
    )


# --- Recherche ---------------------------------------------------------------

def search_transactions(
    matricule: Optional[str] = None,
    type_: Optional[str] = None,
    agent_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sync_status: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> List[Transaction]:
    conn = get_connection()
    sql = "SELECT * FROM transactions WHERE 1=1"
    params: list = []
    if not include_deleted:
        sql += " AND deleted = 0"
    if matricule:
        sql += " AND matricule LIKE ?"
        params.append(f"%{matricule.strip()}%")
    if type_ in ("depot", "retrait"):
        sql += " AND type = ?"
        params.append(type_)
    if agent_id is not None:
        sql += " AND agent_id = ?"
        params.append(agent_id)
    if date_from:
        sql += " AND created_at >= ?"
        params.append(f"{date_from} 00:00:00")
    if date_to:
        sql += " AND created_at <= ?"
        params.append(f"{date_to} 23:59:59")
    if sync_status:
        sql += " AND sync_status = ?"
        params.append(sync_status)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return [Transaction.from_row(r) for r in rows]


def count_transactions(
    matricule: Optional[str] = None,
    type_: Optional[str] = None,
    agent_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sync_status: Optional[str] = None,
    include_deleted: bool = False,
) -> int:
    conn = get_connection()
    sql = "SELECT COUNT(*) AS n FROM transactions WHERE 1=1"
    params: list = []
    if not include_deleted:
        sql += " AND deleted = 0"
    if matricule:
        sql += " AND matricule LIKE ?"
        params.append(f"%{matricule.strip()}%")
    if type_ in ("depot", "retrait"):
        sql += " AND type = ?"
        params.append(type_)
    if agent_id is not None:
        sql += " AND agent_id = ?"
        params.append(agent_id)
    if date_from:
        sql += " AND created_at >= ?"
        params.append(f"{date_from} 00:00:00")
    if date_to:
        sql += " AND created_at <= ?"
        params.append(f"{date_to} 23:59:59")
    if sync_status:
        sql += " AND sync_status = ?"
        params.append(sync_status)
    return int(conn.execute(sql, params).fetchone()["n"])


def latest_transactions(limit: int = 10) -> List[Transaction]:
    return search_transactions(limit=limit)


# --- Agrégats ----------------------------------------------------------------

def totals() -> Tuple[float, float, int, int]:
    """Retourne (total_depots, total_retraits, nb_transactions, nb_matricules_distincts)."""
    conn = get_connection()
    row = conn.execute(
        """SELECT
              COALESCE(SUM(CASE WHEN type = 'depot' THEN montant ELSE 0 END), 0) AS depots,
              COALESCE(SUM(CASE WHEN type = 'retrait' THEN montant ELSE 0 END), 0) AS retraits,
              COUNT(*) AS n
           FROM transactions WHERE deleted = 0"""
    ).fetchone()
    matricules = conn.execute(
        "SELECT COUNT(DISTINCT matricule) AS n FROM transactions WHERE deleted = 0"
    ).fetchone()["n"]
    return float(row["depots"]), float(row["retraits"]), int(row["n"]), int(matricules)


def totals_by_period(date_from: str, date_to: str) -> Tuple[float, float, int]:
    conn = get_connection()
    row = conn.execute(
        """SELECT
              COALESCE(SUM(CASE WHEN type = 'depot' THEN montant ELSE 0 END), 0) AS depots,
              COALESCE(SUM(CASE WHEN type = 'retrait' THEN montant ELSE 0 END), 0) AS retraits,
              COUNT(*) AS n
           FROM transactions
           WHERE deleted = 0 AND created_at >= ? AND created_at <= ?""",
        (f"{date_from} 00:00:00", f"{date_to} 23:59:59"),
    ).fetchone()
    return float(row["depots"]), float(row["retraits"]), int(row["n"])


def sync_status_counts() -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT sync_status, COUNT(*) AS n FROM transactions WHERE deleted = 0 GROUP BY sync_status"
    ).fetchall()
    return {r["sync_status"]: r["n"] for r in rows}
