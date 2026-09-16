"""Gestion des ventes : achat d'un produit par un client, décompté sur son compte."""
from __future__ import annotations

from typing import List, Optional

from app.db.database import get_connection, transaction as db_transaction
from app.models.sale import Sale
from app.models.user import User
from app.services import audit_service, auth_service, cash_service, product_service, transaction_service
from app.utils.helpers import new_uuid, now_iso
from app.utils.accounting import add, subtract, multiply, number


class SaleError(Exception):
    pass


def create_sale(
    matricule: str,
    product_id: int,
    quantite: float,
    agent: User,
    telephone: str = "",
    note: str = "",
    mode_paiement: str = "compte",
) -> Sale:
    """Vend un produit, sur le compte d'un matricule ou encaissé en caisse."""
    mode_paiement = (mode_paiement or "compte").strip().lower()
    if mode_paiement not in ("compte", "caisse"):
        raise SaleError("Mode de paiement inconnu : attendu « compte » ou « caisse ».")
    matricule = (matricule or "").strip()
    telephone = (telephone or "").strip()
    if mode_paiement == "caisse":
        # Vente encaissée : le client paie comptant, aucun compte n'est mouvementé.
        matricule, telephone = "", ""
    elif not matricule:
        raise SaleError("Le matricule du client est obligatoire.")
    try:
        quantite = number(quantite)
    except (ValueError, TypeError):
        raise SaleError("La quantité doit être un nombre fini strictement positif.")
    if quantite <= 0:
        raise SaleError("La quantité doit être strictement positive.")
    if agent is None:
        raise SaleError("Agent non identifié.")

    with db_transaction() as conn:
        prow = conn.execute(
            "SELECT id, uuid, nom, prix_unitaire, quantite_stock, suivi_stock, actif "
            "FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if prow is None:
            raise SaleError("Produit introuvable.")
        if not prow["actif"]:
            raise SaleError("Ce produit est désactivé.")

        suivi_stock = bool(prow["suivi_stock"])
        stock = float(prow["quantite_stock"])
        if suivi_stock and quantite > stock:
            raise SaleError(
                f"Stock insuffisant pour « {prow['nom']} ». Disponible : {stock:g}, demandé : {quantite:g}"
            )

        prix = float(prow["prix_unitaire"])
        montant = multiply(prix, quantite)
        if montant < 0:
            raise SaleError("Le prix du produit ne peut pas être négatif.")

        if mode_paiement == "caisse":
            new_balance = 0.0
        else:
            balance = transaction_service.get_matricule_balance(matricule)
            # Les ventes à crédit sont autorisées, même sans dépôt préalable.
            new_balance = subtract(balance, montant)

        sale_uuid = new_uuid()
        cur = conn.execute(
            """INSERT INTO sales
               (uuid, matricule, telephone, product_id, product_uuid, product_nom, quantite, prix_unitaire,
                montant_total, solde_apres, mode_paiement, agent_id, agent_uuid, agent_nom, note,
                created_at, sync_status, deleted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',0)""",
            (
                sale_uuid, matricule, telephone or None, product_id, prow["uuid"], prow["nom"],
                float(quantite), prix, montant, new_balance, mode_paiement,
                agent.id, getattr(agent, "uuid", None), agent.nom_complet,
                note or None, now_iso(),
            ),
        )
        sale_id = cur.lastrowid
        if mode_paiement == "caisse":
            cash_service.record_sale(
                conn, sale_uuid, f"Vente — {prow['nom']} x{quantite:g}", montant, agent,
            )

        if suivi_stock:
            new_stock = subtract(stock, quantite)
            conn.execute(
                "UPDATE products SET quantite_stock = ?, updated_at = ?, sync_status = 'pending' WHERE id = ?",
                (new_stock, now_iso(), product_id),
            )
            product_service._record_movement(
                conn, product_id, prow["nom"], "sortie", quantite, new_stock,
                motif="Vente", sale_id=sale_id, agent=agent,
            )
        # Un article sans suivi n'a ni quantité à décompter ni mouvement à écrire :
        # la vente elle-même reste la trace de l'opération.

    audit_service.log_action(
        agent.id, agent.identifiant, "SALE_CREATE",
        target_type="sale", target_id=str(sale_id),
        details=(f"{prow['nom']} x{quantite:g} = {montant:.0f} "
                 + ("(encaissé en caisse)" if mode_paiement == "caisse" else f"(client {matricule})")),
    )
    return get_sale(sale_id)


def get_sale(sale_id: int) -> Optional[Sale]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    return Sale.from_row(row) if row else None


def cancel_sale(sale_id: int) -> None:
    """Annule une vente (admin) : restitue le stock et le solde du client."""
    agent = auth_service.current_user()
    with db_transaction() as conn:
        sale = get_sale(sale_id)
        if sale is None:
            raise SaleError("Vente introuvable.")
        if sale.deleted:
            raise SaleError("Cette vente est déjà annulée.")
        conn.execute(
            "UPDATE sales SET deleted = 1, sync_status = 'pending' WHERE id = ?", (sale_id,)
        )
        if sale.mode_paiement == "caisse":
            cash_service.cancel_sale_entry(conn, sale.uuid)
        prow = conn.execute(
            "SELECT nom, quantite_stock, suivi_stock FROM products WHERE id = ?",
            (sale.product_id,),
        ).fetchone()
        if prow is not None and prow["suivi_stock"]:
            new_stock = add(prow["quantite_stock"], sale.quantite)
            conn.execute(
                "UPDATE products SET quantite_stock = ?, updated_at = ?, sync_status = 'pending' WHERE id = ?",
                (new_stock, now_iso(), sale.product_id),
            )
            product_service._record_movement(
                conn, sale.product_id, prow["nom"], "entree", sale.quantite, new_stock,
                motif=f"Annulation vente #{sale_id}", sale_id=sale_id, agent=agent,
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
