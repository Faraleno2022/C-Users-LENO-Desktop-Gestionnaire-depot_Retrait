"""Journal de caisse : entrées, sorties et solde progressif.

La caisse est unique et partagée par tous les postes. Le solde progressif n'est
jamais stocké : il se recalcule à la lecture en cumulant les lignes triées par
(date, created_at, uuid). Deux postes hors connexion peuvent donc écrire le même
jour sans produire deux soldes contradictoires — c'est la somme qui fait foi.
"""
from __future__ import annotations

from typing import List, Optional

from app.db.database import get_connection, transaction as db_transaction
from app.models.cash_entry import CashEntry
from app.models.user import User
from app.services import audit_service
from app.utils.accounting import add, number, subtract
from app.utils.helpers import new_uuid
from server.sync.business_rules import (
    business_day, business_timestamp, cash_running_balances,
)

SOURCES = ("ouverture", "vente", "manuel")


class CashError(Exception):
    pass


# --- Lecture -----------------------------------------------------------------

def _ordered_rows(conn=None, include_deleted: bool = False):
    """Lignes actives du journal, dans l'ordre qui définit le solde progressif."""
    conn = conn or get_connection()
    clause = "" if include_deleted else " WHERE deleted = 0"
    return conn.execute(
        f"SELECT * FROM cash_entries{clause} ORDER BY date, created_at, uuid"
    ).fetchall()


def get_balance(conn=None) -> float:
    """Contenu actuel de la caisse : entrées moins sorties."""
    balances = cash_running_balances(dict(r) for r in _ordered_rows(conn))
    return balances[-1][1] if balances else 0.0


def list_entries(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_deleted: bool = False,
) -> List[CashEntry]:
    """Journal filtré, chaque ligne portant le solde progressif à cet instant.

    Le cumul part toujours du début du journal : filtrer sur une période change
    les lignes affichées, jamais le solde qu'elles portent.
    """
    rows = _ordered_rows(include_deleted=include_deleted)
    by_uuid = {row["uuid"]: row for row in rows}
    entries = []
    for row, running in cash_running_balances(dict(r) for r in rows):
        entry = CashEntry.from_row(by_uuid[row["uuid"]])
        entry.solde_progressif = running
        if date_from and entry.date < date_from:
            continue
        if date_to and entry.date > date_to:
            continue
        entries.append(entry)
    return entries


def get_opening() -> Optional[CashEntry]:
    row = get_connection().execute(
        "SELECT * FROM cash_entries WHERE source = 'ouverture' AND deleted = 0"
    ).fetchone()
    return CashEntry.from_row(row) if row else None


def totals(entries: Optional[List[CashEntry]] = None):
    """Retourne (total_entrees, total_sorties, net) des lignes fournies.

    Sur un journal filtré, `net` est celui de la période, pas le contenu de la
    caisse : pour ce dernier, appeler `get_balance()`.
    """
    entries = list_entries() if entries is None else entries
    actives = [e for e in entries if not e.deleted]
    entrees = add(*(e.entree for e in actives))
    sorties = add(*(e.sortie for e in actives))
    return entrees, sorties, subtract(entrees, sorties)


# --- Écriture ----------------------------------------------------------------

def _validate(libelle: str, montant, date: Optional[str]) -> tuple:
    libelle = (libelle or "").strip()
    if not libelle:
        raise CashError("Le libellé est obligatoire.")
    try:
        montant = number(montant)
    except (ValueError, TypeError):
        raise CashError("Le montant doit être un nombre fini strictement positif.")
    if montant <= 0:
        raise CashError("Le montant doit être strictement positif.")
    date = (date or "").strip() or business_day()
    try:
        business_day(date)
    except (ValueError, TypeError):
        raise CashError("Date invalide : format attendu AAAA-MM-JJ.")
    return libelle, montant, date[:10]


def _insert(conn, *, date, libelle, entree, sortie, source, agent, sale_uuid=None) -> int:
    cur = conn.execute(
        """INSERT INTO cash_entries
           (uuid, date, libelle, entree, sortie, source, sale_uuid,
            agent_id, agent_uuid, agent_nom, created_at, sync_status, deleted)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',0)""",
        (
            new_uuid(), date, libelle, float(entree), float(sortie), source, sale_uuid,
            getattr(agent, "id", None), getattr(agent, "uuid", None),
            getattr(agent, "nom_complet", "") or "", business_timestamp(micro=True),
        ),
    )
    return cur.lastrowid


def create_opening(montant, agent: User, date: Optional[str] = None,
                   libelle: str = "Solde initial") -> CashEntry:
    """Ouvre la caisse. Une seule écriture d'ouverture peut être active."""
    libelle, montant, date = _validate(libelle, montant, date)
    if agent is None:
        raise CashError("Agent non identifié.")
    with db_transaction() as conn:
        if conn.execute(
            "SELECT 1 FROM cash_entries WHERE source = 'ouverture' AND deleted = 0"
        ).fetchone():
            raise CashError("La caisse a déjà une écriture d'ouverture.")
        entry_id = _insert(conn, date=date, libelle=libelle, entree=montant, sortie=0,
                           source="ouverture", agent=agent)
    audit_service.log_action(
        agent.id, agent.identifiant, "CASH_OPEN", target_type="cash_entry",
        target_id=str(entry_id), details=f"{libelle} = {montant:.0f}",
    )
    return get_entry(entry_id)


def create_entry(libelle: str, agent: User, entree=0, sortie=0,
                 date: Optional[str] = None) -> CashEntry:
    """Saisit une entrée ou une sortie manuelle (versement, achat, etc.)."""
    if agent is None:
        raise CashError("Agent non identifié.")
    try:
        entree, sortie = number(entree or 0), number(sortie or 0)
    except (ValueError, TypeError):
        raise CashError("Le montant doit être un nombre fini strictement positif.")
    if (entree > 0) == (sortie > 0):
        raise CashError("Saisissez soit une entrée, soit une sortie.")
    libelle, montant, date = _validate(libelle, entree or sortie, date)
    with db_transaction() as conn:
        if sortie > 0:
            available = get_balance(conn)
            if montant > available:
                raise CashError(
                    f"Solde de caisse insuffisant : disponible {available:.0f} GNF, "
                    f"sortie demandée {montant:.0f} GNF."
                )
        entry_id = _insert(
            conn, date=date, libelle=libelle,
            entree=montant if entree > 0 else 0, sortie=montant if sortie > 0 else 0,
            source="manuel", agent=agent,
        )
    audit_service.log_action(
        agent.id, agent.identifiant, "CASH_ENTRY", target_type="cash_entry",
        target_id=str(entry_id),
        details=f"{libelle} — {'entrée' if entree > 0 else 'sortie'} {montant:.0f}",
    )
    return get_entry(entry_id)


def record_sale(conn, sale_uuid: str, libelle: str, montant: float, agent: User) -> int:
    """Encaisse une vente. Appelé dans la transaction de `sale_service`."""
    return _insert(conn, date=business_day(), libelle=libelle, entree=montant,
                   sortie=0, source="vente", agent=agent, sale_uuid=sale_uuid)


def cancel_sale_entry(conn, sale_uuid: str) -> None:
    """Retire de la caisse l'encaissement d'une vente annulée."""
    conn.execute(
        "UPDATE cash_entries SET deleted = 1, sync_status = 'pending' "
        "WHERE sale_uuid = ? AND source = 'vente' AND deleted = 0",
        (sale_uuid,),
    )


def get_entry(entry_id: int) -> Optional[CashEntry]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM cash_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        return None
    entry = CashEntry.from_row(row)
    for candidate, running in cash_running_balances(dict(r) for r in _ordered_rows(conn)):
        entry.solde_progressif = running
        if candidate["id"] == entry_id:
            break
    return entry


def delete_entry(entry_id: int, agent: User) -> None:
    """Annule une écriture manuelle, réservée aux administrateurs.

    Un profil agent (caissier, superviseur) saisit les écritures mais ne peut
    pas les retirer : le journal de caisse doit rester vérifiable.
    """
    if agent is None or not agent.is_admin():
        raise CashError(
            "Annulation d'une écriture de caisse réservée aux administrateurs."
        )
    with db_transaction() as conn:
        row = conn.execute(
            "SELECT source, entree, sortie, libelle, deleted FROM cash_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise CashError("Écriture introuvable.")
        if row["deleted"]:
            raise CashError("Cette écriture est déjà annulée.")
        if row["source"] == "vente":
            raise CashError(
                "Cet encaissement suit sa vente : annulez la vente pour le retirer."
            )
        if row["entree"] > 0 and row["entree"] > get_balance(conn):
            raise CashError(
                "Annuler cette entrée rendrait le solde de caisse négatif."
            )
        conn.execute(
            "UPDATE cash_entries SET deleted = 1, sync_status = 'pending' WHERE id = ?",
            (entry_id,),
        )
    audit_service.log_action(
        getattr(agent, "id", None), getattr(agent, "identifiant", None),
        "CASH_ENTRY_DELETE", target_type="cash_entry", target_id=str(entry_id),
        details=row["libelle"],
    )
