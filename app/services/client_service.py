"""Gestion des clients (fiches par matricule).

Le matricule reste la clé métier : les transactions et ventes y font référence
par chaîne. La table `clients` enrichit ces matricules avec un nom, un téléphone
et une note. La liste fusionne les fiches enregistrées avec les matricules connus
des transactions/ventes qui n'ont pas encore de fiche.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.db.database import get_connection, transaction as db_transaction
from app.models.client import Client
from app.services import audit_service, auth_service, transaction_service
from app.utils.helpers import new_uuid, now_iso


class ClientError(Exception):
    pass


@dataclass
class ClientRow:
    """Ligne agrégée pour la liste des clients."""
    matricule: str
    nom: str
    telephone: str
    solde: float
    nb_operations: int
    enregistre: bool
    client_id: Optional[int] = None


@dataclass
class ClientOperation:
    """Une opération (transaction ou vente) dans l'historique d'un client."""
    date: str
    categorie: str   # 'Dépôt', 'Retrait', 'Achat'
    detail: str
    montant: float   # signé : + dépôt, - retrait/achat
    solde_apres: float
    agent: str


# --- Fiches ------------------------------------------------------------------

def get_client(client_id: int) -> Optional[Client]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return Client.from_row(row) if row else None


def get_client_by_matricule(matricule: str, include_inactive: bool = False) -> Optional[Client]:
    conn = get_connection()
    sql = "SELECT * FROM clients WHERE matricule = ?"
    if not include_inactive:
        sql += " AND actif = 1"
    row = conn.execute(
        sql, ((matricule or "").strip(),)
    ).fetchone()
    return Client.from_row(row) if row else None


def create_client(
    matricule: str,
    nom: str = "",
    telephone: str = "",
    note: str = "",
) -> Client:
    matricule = (matricule or "").strip()
    if not matricule:
        raise ClientError("Le matricule est obligatoire.")
    if get_client_by_matricule(matricule) is not None:
        raise ClientError(f"Une fiche existe déjà pour le matricule « {matricule} ».")

    existing_inactive = get_client_by_matricule(matricule, include_inactive=True)
    if existing_inactive is not None and not existing_inactive.actif:
        return update_client(
            existing_inactive.id,
            matricule=matricule,
            nom=nom,
            telephone=telephone,
            note=note,
            actif=True,
        )

    now = now_iso()
    with db_transaction() as conn:
        cur = conn.execute(
            """INSERT INTO clients (uuid, matricule, nom, telephone, note, actif,
                                    created_at, updated_at, sync_status)
               VALUES (?,?,?,?,?,1,?,?,'pending')""",
            (
                new_uuid(), matricule, (nom or "").strip() or None,
                (telephone or "").strip() or None, (note or "").strip() or None,
                now, now,
            ),
        )
        client_id = cur.lastrowid

    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "CLIENT_CREATE", target_type="client", target_id=str(client_id),
        details=matricule,
    )
    return get_client(client_id)


def update_client(
    client_id: int,
    nom: Optional[str] = None,
    telephone: Optional[str] = None,
    note: Optional[str] = None,
    matricule: Optional[str] = None,
    actif: Optional[bool] = None,
) -> Client:
    client = get_client(client_id)
    if client is None:
        raise ClientError("Fiche client introuvable.")
    fields: list = []
    params: list = []
    if matricule is not None:
        new_mat = matricule.strip()
        if not new_mat:
            raise ClientError("Le matricule ne peut pas être vide.")
        existing = get_client_by_matricule(new_mat, include_inactive=True)
        if existing is not None and existing.id != client_id:
            raise ClientError(f"Le matricule « {new_mat} » est déjà utilisé.")
        fields.append("matricule = ?")
        params.append(new_mat)
    if nom is not None:
        fields.append("nom = ?")
        params.append(nom.strip() or None)
    if telephone is not None:
        fields.append("telephone = ?")
        params.append(telephone.strip() or None)
    if note is not None:
        fields.append("note = ?")
        params.append(note.strip() or None)
    if actif is not None:
        fields.append("actif = ?")
        params.append(1 if actif else 0)
    if not fields:
        return client
    fields.append("updated_at = ?")
    params.append(now_iso())
    fields.append("sync_status = 'pending'")
    params.append(client_id)
    conn = get_connection()
    conn.execute(f"UPDATE clients SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "CLIENT_UPDATE", target_type="client", target_id=str(client_id),
    )
    return get_client(client_id)


def ensure_client(matricule: str) -> Client:
    """Crée une fiche minimale pour un matricule s'il n'en a pas encore."""
    existing = get_client_by_matricule(matricule)
    if existing is not None:
        return existing
    return create_client(matricule)


def delete_client(client_id: int) -> None:
    """Supprime la fiche (les transactions/ventes liées au matricule restent)."""
    client = get_client(client_id)
    if client is None:
        raise ClientError("Fiche client introuvable.")
    conn = get_connection()
    conn.execute(
        "UPDATE clients SET actif = 0, updated_at = ?, sync_status = 'pending' WHERE id = ?",
        (now_iso(), client_id),
    )
    conn.commit()
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "CLIENT_DEACTIVATE", target_type="client", target_id=str(client_id),
        details=client.matricule,
    )


# --- Liste agrégée -----------------------------------------------------------

def _known_matricules() -> List[str]:
    """Tous les matricules présents en base (fiches + transactions + ventes)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT matricule FROM clients
           UNION SELECT matricule FROM transactions WHERE deleted = 0
           UNION SELECT matricule FROM sales WHERE deleted = 0"""
    ).fetchall()
    return [r["matricule"] for r in rows if r["matricule"]]


def list_clients(query: Optional[str] = None) -> List[ClientRow]:
    conn = get_connection()
    fiches = {
        c["matricule"]: c
        for c in conn.execute("SELECT * FROM clients WHERE actif = 1").fetchall()
    }
    result: List[ClientRow] = []
    q = (query or "").strip().lower()
    for matricule in sorted(set(_known_matricules())):
        fiche = fiches.get(matricule)
        nom = (fiche["nom"] if fiche else "") or ""
        telephone = (fiche["telephone"] if fiche else "") or ""
        if q and q not in matricule.lower() and q not in nom.lower():
            continue
        nb = conn.execute(
            """SELECT
                  (SELECT COUNT(*) FROM transactions WHERE deleted = 0 AND matricule = ?)
                + (SELECT COUNT(*) FROM sales WHERE deleted = 0 AND matricule = ?) AS n""",
            (matricule, matricule),
        ).fetchone()["n"]
        result.append(
            ClientRow(
                matricule=matricule,
                nom=nom,
                telephone=telephone,
                solde=transaction_service.get_matricule_balance(matricule),
                nb_operations=int(nb),
                enregistre=fiche is not None,
                client_id=fiche["id"] if fiche else None,
            )
        )
    return result


def client_operations(matricule: str, limit: int = 200) -> List[ClientOperation]:
    """Historique chronologique (récent d'abord) des opérations d'un client."""
    conn = get_connection()
    ops: List[ClientOperation] = []
    txs = conn.execute(
        """SELECT type, montant, solde_apres, agent_nom, note, created_at
           FROM transactions WHERE deleted = 0 AND matricule = ?
           ORDER BY id DESC LIMIT ?""",
        (matricule, limit),
    ).fetchall()
    for t in txs:
        is_depot = t["type"] == "depot"
        ops.append(
            ClientOperation(
                date=t["created_at"],
                categorie="Dépôt" if is_depot else "Retrait",
                detail=t["note"] or "",
                montant=float(t["montant"]) if is_depot else -float(t["montant"]),
                solde_apres=float(t["solde_apres"]),
                agent=t["agent_nom"],
            )
        )
    ventes = conn.execute(
        """SELECT product_nom, quantite, montant_total, solde_apres, agent_nom, created_at
           FROM sales WHERE deleted = 0 AND matricule = ?
           ORDER BY id DESC LIMIT ?""",
        (matricule, limit),
    ).fetchall()
    for v in ventes:
        ops.append(
            ClientOperation(
                date=v["created_at"],
                categorie="Achat",
                detail=f"{v['product_nom']} x{v['quantite']:g}",
                montant=-float(v["montant_total"]),
                solde_apres=float(v["solde_apres"]),
                agent=v["agent_nom"],
            )
        )
    ops.sort(key=lambda o: o.date, reverse=True)
    return ops[:limit]


def count_clients() -> int:
    return len(set(_known_matricules()))
