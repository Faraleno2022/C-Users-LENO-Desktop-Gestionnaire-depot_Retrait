from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class CashEntry:
    """Une ligne du journal de caisse.

    `solde_progressif` n'est pas stocké : il est recalculé à la lecture par
    `cash_service`, sinon deux postes hors connexion écriraient chacun leur
    propre solde sur la même journée.
    """

    id: Optional[int]
    uuid: str
    date: str
    libelle: str
    entree: float
    sortie: float
    source: str  # 'ouverture', 'vente' ou 'manuel'
    sale_uuid: Optional[str]
    agent_id: Optional[int]
    agent_nom: str
    created_at: str
    sync_status: str = "pending"
    last_synced_at: Optional[str] = None
    deleted: bool = False
    solde_progressif: float = 0.0

    @classmethod
    def from_row(cls, row) -> "CashEntry":
        return cls(
            id=row["id"],
            uuid=row["uuid"],
            date=row["date"],
            libelle=row["libelle"],
            entree=row["entree"],
            sortie=row["sortie"],
            source=row["source"],
            sale_uuid=row["sale_uuid"],
            agent_id=row["agent_id"],
            agent_nom=row["agent_nom"],
            created_at=row["created_at"],
            sync_status=row["sync_status"],
            last_synced_at=row["last_synced_at"],
            deleted=bool(row["deleted"]),
        )
