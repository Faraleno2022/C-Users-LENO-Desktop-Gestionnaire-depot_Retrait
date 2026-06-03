"""Gestion des ventes : achat d'un produit par un client, décompté sur son compte."""
from __future__ import annotations

from typing import List, Optional

from app.db.database import get_connection, transaction as db_transaction
from app.models.sale import Sale
from app.models.user import User
from app.services import audit_service, auth_service, product_service, transaction_service
from app.utils.helpers import new_uuid, now_iso


class SaleError(Exception):
    pass


def create_sale(
    matricule: str,
    product_id: int,
    quantite: float,
    agent: User,
    telephone: str = "",
    note: str = "",
) -> Sale:
    matricule = (matricule or "").strip()
    telephone = (telephone or "").strip()
    if not matricule:
        raise SaleError("Le matricule du client est obligatoire.")
    if quantite is None or quantite <= 0:
        raise SaleError("La quantité doit être strictement positive.")
    if agent is None:
        raise SaleError("Agent non identifié.")

    with db_transaction() as conn:
        prow = conn.execute(
            "SELECT id, nom, prix_unitaire, quantite_stock, actif FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if prow is None:
            raise SaleError("Produit introuvable.")
        if not prow["actif"]:
            raise SaleError("Ce produit est désactivé.")

        stock = float(prow["quantite_stock"])
        if quantite > stock:
            raise SaleError(
                f"Stock insuffisant pour « {prow['nom']} ». Disponible : {stock:g}, demandé : {quantite:g}"
            )

        prix = float(prow["prix_unitaire"])
        montant = prix * quantite

        balance = transaction_service.get_matricule_balance(matricule)
        if montant > balance:
            raise SaleError(
                f"Solde insuffisant. Solde du client : {balance:.0f}, montant de l'achat : {montant:.0f}"
            )
        new_balance = balance - montant

        cur = conn.execute(
            """INSERT INTO sales
               (uuid, matricule, telephone, product_id, product_uuid, product_nom, quantite, prix_unitaire,
                montant_total, solde_apres, agent_id, agent_uuid, agent_nom, note, created_at, sync_status, deleted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',0)""",
            (
                new_uuid(), matricule, telephone or None, product_id, prow["uuid"], prow["nom"],
                float(quantite), prix, montant, new_balance,
                agent.id, getattr(agent, "uuid", None), agent.nom_complet,
                note or None, now_iso(),
            ),
        )
        sale_id = cur.lastrowid

        new_stock = stock - quantite
        conn.execute(
            "UPDATE products SET quantite_stock = ?, updated_at = ?, sync_status = 'pending' WHERE id = ?",
            (new_stock, now_iso(), product_id),
        )
        product_service._record_movement(
            conn, product_id, prow["nom"], "sortie", quantite, new_stock,
            motif="Vente", sale_id=sale_id, agent=agent,
        )

    audit_service.log_action(
        agent.id, agent.identifiant, "SALE_CREATE",
        target_type="sale", target_id=str(sale_id),
        details=f"{prow['nom']} x{quantite:g} = {montant:.0f} (client {matricule})",
    )
    return get_sale(sale_id)


def get_sale(sale_id: int) -> Optional[Sale]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    return Sale.from_row(row) if row else None


def cancel_sale(sale_id: int) -> None:
    """Annule une vente (admin) : restitue le stock et le solde du client."""
    sale = get_sale(sale_id)
    if sale is None:
        raise SaleError("Vente introuvable.")
    if sale.deleted:
        raise SaleError("Cette vente est déjà annulée.")
    agent = auth_service.current_user()
    with db_transaction() as conn:
        conn.execute(
            "UPDATE sales SET deleted = 1, sync_status = 'pending' WHERE id = ?", (sale_id,)
        )
        prow = conn.execute(
            "SELECT nom, quantite_stock FROM products WHERE id = ?", (sale.product_id,)
        ).fetchone()
        if prow is not None:
            new_stock = float(prow["quantite_stock"]) + sale.quantite
            conn.execute(
                "UPDATE products SET quantite_stock = ?, updated_at = ?, sync_status = 'pending' WHERE id = ?",
                (new_stock, now_iso(), sale.product_id),
            )
            product_service._record_movement(
                conn, sale.product_id, prow["nom"], "entree", sale.quantite, new_stock,
                motif=f"Annulation vente #{sale_id}", agent=agent,
            )
    audit_service.log_action(
        agent.id if agent else None,
        agent.identifiant if agent else None,
        "SALE_CANCEL", target_type="sale", target_id=str(sale_id),
    )


def search_sales(
    matricule: Optional[str] = None,
    product_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> List[Sale]:
    conn = get_connection()
    sql = "SELECT * FROM sales WHERE 1=1"
    params: list = []
    if not include_deleted:
        sql += " AND deleted = 0"
    if matricule:
        sql += " AND matricule LIKE ?"
        params.append(f"%{matricule.strip()}%")
    if product_id is not None:
        sql += " AND product_id = ?"
        params.append(product_id)
    if agent_id is not None:
        sql += " AND agent_id = ?"
        params.append(agent_id)
    if date_from:
        sql += " AND created_at >= ?"
        params.append(f"{date_from} 00:00:00")
    if date_to:
        sql += " AND created_at <= ?"
        params.append(f"{date_to} 23:59:59")
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return [Sale.from_row(r) for r in rows]


def count_sales(**filters) -> int:
    filters.pop("limit", None)
    filters.pop("offset", None)
    conn = get_connection()
    sql = "SELECT COUNT(*) AS n FROM sales WHERE 1=1"
    params: list = []
    if not filters.get("include_deleted"):
        sql += " AND deleted = 0"
    if filters.get("matricule"):
        sql += " AND matricule LIKE ?"
        params.append(f"%{filters['matricule'].strip()}%")
    if filters.get("product_id") is not None:
        sql += " AND product_id = ?"
        params.append(filters["product_id"])
    if filters.get("agent_id") is not None:
        sql += " AND agent_id = ?"
        params.append(filters["agent_id"])
    if filters.get("date_from"):
        sql += " AND created_at >= ?"
        params.append(f"{filters['date_from']} 00:00:00")
    if filters.get("date_to"):
        sql += " AND created_at <= ?"
        params.append(f"{filters['date_to']} 23:59:59")
    return int(conn.execute(sql, params).fetchone()["n"])


def sales_totals(date_from: Optional[str] = None, date_to: Optional[str] = None):
    """Retourne (montant_total, nb_ventes, quantite_totale)."""
    conn = get_connection()
    sql = """SELECT COALESCE(SUM(montant_total),0) AS m, COUNT(*) AS n,
                    COALESCE(SUM(quantite),0) AS q
             FROM sales WHERE deleted = 0"""
    params: list = []
    if date_from:
        sql += " AND created_at >= ?"
        params.append(f"{date_from} 00:00:00")
    if date_to:
        sql += " AND created_at <= ?"
        params.append(f"{date_to} 23:59:59")
    row = conn.execute(sql, params).fetchone()
    return float(row["m"]), int(row["n"]), float(row["q"])
