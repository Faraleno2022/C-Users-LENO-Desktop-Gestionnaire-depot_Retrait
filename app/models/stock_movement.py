from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class StockMovement:
    id: Optional[int]
    uuid: str
    product_id: int
    product_nom: str
    type: str  # 'entree' ou 'sortie'
    quantite: float
    stock_apres: float
    motif: Optional[str]
    sale_id: Optional[int]
    agent_id: int
    agent_nom: str
    created_at: str
    sync_status: str = "pending"
    last_synced_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "StockMovement":
        return cls(
            id=row["id"],
            uuid=row["uuid"],
            product_id=row["product_id"],
            product_nom=row["product_nom"],
            type=row["type"],
            quantite=row["quantite"],
            stock_apres=row["stock_apres"],
            motif=row["motif"],
            sale_id=row["sale_id"],
            agent_id=row["agent_id"],
            agent_nom=row["agent_nom"],
            created_at=row["created_at"],
            sync_status=row["sync_status"],
            last_synced_at=row["last_synced_at"],
        )
