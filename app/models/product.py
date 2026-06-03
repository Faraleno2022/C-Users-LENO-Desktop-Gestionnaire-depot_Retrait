from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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
            sync_status=row["sync_status"],
            last_synced_at=row["last_synced_at"],
        )

    def en_alerte(self) -> bool:
        return self.quantite_stock <= self.seuil_alerte
