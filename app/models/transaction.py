from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Transaction:
    id: Optional[int]
    uuid: str
    matricule: str
    telephone: Optional[str]
    type: str  # 'depot' ou 'retrait'
    montant: float
    solde_apres: float
    agent_id: int
    agent_nom: str
    note: Optional[str]
    created_at: str
    sync_status: str = "pending"
    last_synced_at: Optional[str] = None
    deleted: bool = False

    @classmethod
    def from_row(cls, row) -> "Transaction":
        return cls(
            id=row["id"],
            uuid=row["uuid"],
            matricule=row["matricule"],
            telephone=row["telephone"],
            type=row["type"],
            montant=row["montant"],
            solde_apres=row["solde_apres"],
            agent_id=row["agent_id"],
            agent_nom=row["agent_nom"],
            note=row["note"],
            created_at=row["created_at"],
            sync_status=row["sync_status"],
            last_synced_at=row["last_synced_at"],
            deleted=bool(row["deleted"]),
        )
