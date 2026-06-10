from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def _get(row, key, default=None):
    """Accès tolérant à une colonne (robuste si la base n'est pas encore migrée)."""
    try:
        keys = row.keys()
    except AttributeError:
        keys = []
    return row[key] if key in keys else default


@dataclass
class Product:
    id: Optional[int]
    uuid: str
    reference: Optional[str]
    nom: str
    description: Optional[str]
    prix_unitaire: float
    quantite_stock: float
    seuil_alerte: float
    actif: bool
    created_at: str
    updated_at: str
    categorie: Optional[str] = None
    unite: Optional[str] = None
    prix_achat: float = 0.0
    stock_max: float = 0.0
    emplacement: Optional[str] = None
    sync_status: str = "pending"
    last_synced_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Product":
        return cls(
            id=row["id"],
            uuid=row["uuid"],
            reference=row["reference"],
            nom=row["nom"],
            description=row["description"],
            prix_unitaire=row["prix_unitaire"],
            quantite_stock=row["quantite_stock"],
            seuil_alerte=row["seuil_alerte"],
            actif=bool(row["actif"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            categorie=_get(row, "categorie"),
            unite=_get(row, "unite"),
            prix_achat=_get(row, "prix_achat", 0.0) or 0.0,
            stock_max=_get(row, "stock_max", 0.0) or 0.0,
            emplacement=_get(row, "emplacement"),
            sync_status=row["sync_status"],
            last_synced_at=row["last_synced_at"],
        )

    def en_alerte(self) -> bool:
        """Stock au niveau du seuil d'alerte ou en dessous (rupture incluse)."""
        return self.quantite_stock <= self.seuil_alerte

    def en_rupture(self) -> bool:
        return self.quantite_stock <= 0

    def en_surstock(self) -> bool:
        """Stock au-dessus de la limite maximale (si une limite est définie)."""
        return self.stock_max > 0 and self.quantite_stock > self.stock_max
