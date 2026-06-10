"""Gestion des produits et des mouvements de stock."""
from __future__ import annotations

from typing import List, Optional

from app.db.database import get_connection, transaction as db_transaction
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.services import audit_service, auth_service
from app.utils.helpers import new_uuid, now_iso


class ProductError(Exception):
    pass


# --- Produits ----------------------------------------------------------------

def list_products(include_inactive: bool = True, query: Optional[str] = None) -> List[Product]:
    conn = get_connection()
    sql = "SELECT * FROM products WHERE 1=1"
    params: list = []
    if not include_inactive:
        sql += " AND actif = 1"
    if query:
        sql += " AND (nom LIKE ? OR reference LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    sql += " ORDER BY nom"
    rows = conn.execute(sql, params).fetchall()
    return [Product.from_row(r) for r in rows]


def get_product(product_id: int) -> Optional[Product]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return Product.from_row(row) if row else None


def create_product(
    nom: str,
    prix_unitaire: float,
    reference: str = "",
    description: str = "",
    quantite_initiale: float = 0,
    seuil_alerte: float = 0,
    categorie: str = "",
    unite: str = "",
    prix_achat: float = 0,
    stock_max: float = 0,
    emplacement: str = "",
) -> Product:
    nom = (nom or "").strip()
    if not nom:
        raise ProductError("Le nom du produit est obligatoire.")
    if prix_unitaire is None or prix_unitaire < 0:
        raise ProductError("Le prix de vente doit être positif ou nul.")
    if prix_achat is not None and prix_achat < 0:
        raise ProductError("Le prix d'achat doit être positif ou nul.")
    if quantite_initiale < 0:
        raise ProductError("La quantité initiale ne peut pas être négative.")
    if stock_max and seuil_alerte and stock_max < seuil_alerte:
        raise ProductError("Le stock maximum doit être supérieur au seuil d'alerte.")

    now = now_iso()
    with db_transaction() as conn:
        cur = conn.execute(
            """INSERT INTO products (uuid, reference, nom, description, categorie, unite,
                                    prix_achat, prix_unitaire, quantite_stock, seuil_alerte,
                                    stock_max, emplacement, actif, created_at, updated_at, sync_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,'pending')""",
            (
                new_uuid(),
                reference or None,
                nom,
                description or None,
                (categorie or "").strip() or None,
                (unite or "").strip() or None,
                float(prix_achat or 0),
                float(prix_unitaire),
                float(quantite_initiale),
                float(seuil_alerte),
                float(stock_max or 0),
                (emplacement or "").strip() or None,
                now,
                now,
            ),
        )
        product_id = cur.lastrowid
        agent = auth_service.current_user()
        if quantite_initiale > 0:
            _record_movement(
                conn, product_id, nom, "entree", quantite_initiale,
                float(quantite_initiale), motif="Stock initial", agent=agent,
            )

    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "PRODUCT_CREATE",
        target_type="product",
        target_id=str(product_id),
        details=nom,
    )
    return get_product(product_id)


def update_product(
    product_id: int,
    nom: Optional[str] = None,
    prix_unitaire: Optional[float] = None,
    reference: Optional[str] = None,
    description: Optional[str] = None,
    seuil_alerte: Optional[float] = None,
    actif: Optional[bool] = None,
    categorie: Optional[str] = None,
    unite: Optional[str] = None,
    prix_achat: Optional[float] = None,
    stock_max: Optional[float] = None,
    emplacement: Optional[str] = None,
) -> Product:
    product = get_product(product_id)
    if product is None:
        raise ProductError("Produit introuvable.")
    fields = []
    params: list = []
    if nom is not None:
        if not nom.strip():
            raise ProductError("Le nom ne peut pas être vide.")
        fields.append("nom = ?")
        params.append(nom.strip())
    if prix_unitaire is not None:
        if prix_unitaire < 0:
            raise ProductError("Le prix de vente doit être positif ou nul.")
        fields.append("prix_unitaire = ?")
        params.append(float(prix_unitaire))
    if reference is not None:
        fields.append("reference = ?")
        params.append(reference or None)
    if description is not None:
        fields.append("description = ?")
        params.append(description or None)
    if seuil_alerte is not None:
        fields.append("seuil_alerte = ?")
        params.append(float(seuil_alerte))
    if categorie is not None:
        fields.append("categorie = ?")
        params.append((categorie or "").strip() or None)
    if unite is not None:
        fields.append("unite = ?")
        params.append((unite or "").strip() or None)
    if prix_achat is not None:
        if prix_achat < 0:
            raise ProductError("Le prix d'achat doit être positif ou nul.")
        fields.append("prix_achat = ?")
        params.append(float(prix_achat))
    if stock_max is not None:
        fields.append("stock_max = ?")
        params.append(float(stock_max))
    if emplacement is not None:
        fields.append("emplacement = ?")
        params.append((emplacement or "").strip() or None)
    if actif is not None:
        fields.append("actif = ?")
        params.append(1 if actif else 0)
    if not fields:
        return product
    fields.append("updated_at = ?")
    params.append(now_iso())
    fields.append("sync_status = 'pending'")
    params.append(product_id)
    conn = get_connection()
    conn.execute(f"UPDATE products SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "PRODUCT_UPDATE",
        target_type="product",
        target_id=str(product_id),
    )
    return get_product(product_id)


def delete_product(product_id: int) -> None:
    product = get_product(product_id)
    if product is None:
        raise ProductError("Produit introuvable.")
    conn = get_connection()
    sales = conn.execute(
        "SELECT COUNT(*) AS n FROM sales WHERE product_id = ? AND deleted = 0", (product_id,)
    ).fetchone()["n"]
    if sales > 0:
        raise ProductError(
            "Ce produit a des ventes associées. Désactivez-le plutôt que de le supprimer."
        )
    conn.execute("DELETE FROM stock_movements WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "PRODUCT_DELETE",
        target_type="product",
        target_id=str(product_id),
        details=product.nom,
    )


# --- Mouvements de stock -----------------------------------------------------

def _record_movement(conn, product_id, product_nom, type_, quantite, stock_apres,
                     motif=None, sale_id=None, agent=None) -> int:
    # Récupère le product_uuid pour permettre la traduction lors d'un pull.
    prow = conn.execute(
        "SELECT uuid FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    product_uuid = prow["uuid"] if prow else None
    cur = conn.execute(
        """INSERT INTO stock_movements
           (uuid, product_id, product_uuid, product_nom, type, quantite, stock_apres,
            motif, sale_id, agent_id, agent_uuid, agent_nom, created_at, sync_status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'pending')""",
        (
            new_uuid(), product_id, product_uuid, product_nom, type_,
            float(quantite), float(stock_apres),
            motif, sale_id,
            agent.id if agent else None,
            getattr(agent, "uuid", None) if agent else None,
            agent.nom_complet if agent else "—",
            now_iso(),
        ),
    )
    return cur.lastrowid


def adjust_stock(product_id: int, type_: str, quantite: float, motif: str = "") -> Product:
    """Entrée ou sortie manuelle de stock."""
    if type_ not in ("entree", "sortie"):
        raise ProductError("Type de mouvement invalide.")
    if quantite is None or quantite <= 0:
        raise ProductError("La quantité doit être strictement positive.")
    agent = auth_service.current_user()
    with db_transaction() as conn:
        row = conn.execute(
            "SELECT nom, quantite_stock FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            raise ProductError("Produit introuvable.")
        current = float(row["quantite_stock"])
        if type_ == "entree":
            new_stock = current + quantite
        else:
            if quantite > current:
                raise ProductError(
                    f"Stock insuffisant. Disponible : {current:g}, demandé : {quantite:g}"
                )
            new_stock = current - quantite
        conn.execute(
            "UPDATE products SET quantite_stock = ?, updated_at = ?, sync_status = 'pending' WHERE id = ?",
            (new_stock, now_iso(), product_id),
        )
        _record_movement(
            conn, product_id, row["nom"], type_, quantite, new_stock,
            motif=motif or None, agent=agent,
        )
    actor = agent
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "STOCK_" + type_.upper(),
        target_type="product",
        target_id=str(product_id),
        details=f"{quantite:g} ({motif})" if motif else f"{quantite:g}",
    )
    return get_product(product_id)


def get_movement(movement_id: int) -> Optional[StockMovement]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM stock_movements WHERE id = ?", (movement_id,)
    ).fetchone()
    return StockMovement.from_row(row) if row else None


def list_movements(product_id: Optional[int] = None, limit: int = 200) -> List[StockMovement]:
    conn = get_connection()
    if product_id is not None:
        rows = conn.execute(
            "SELECT * FROM stock_movements WHERE product_id = ? ORDER BY id DESC LIMIT ?",
            (product_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM stock_movements ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [StockMovement.from_row(r) for r in rows]


def low_stock_products() -> List[Product]:
    return [p for p in list_products(include_inactive=False) if p.en_alerte()]


def stock_value() -> float:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(quantite_stock * prix_unitaire), 0) AS v FROM products WHERE actif = 1"
    ).fetchone()
    return float(row["v"])


def stock_value_cost() -> float:
    """Valeur du stock au prix d'achat (coût), à défaut au prix de vente."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(quantite_stock * "
        "CASE WHEN prix_achat > 0 THEN prix_achat ELSE prix_unitaire END), 0) AS v "
        "FROM products WHERE actif = 1"
    ).fetchone()
    return float(row["v"])


def list_categories() -> List[str]:
    """Catégories distinctes déjà saisies (pour l'auto-complétion du formulaire)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT categorie FROM products "
        "WHERE categorie IS NOT NULL AND TRIM(categorie) <> '' ORDER BY categorie"
    ).fetchall()
    return [r["categorie"] for r in rows]
