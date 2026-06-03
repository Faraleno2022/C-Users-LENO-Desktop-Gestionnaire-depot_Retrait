from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Client:
    id: Optional[int]
    uuid: str
    matricule: str
    nom: Optional[str]
    telephone: Optional[str]
    note: Optional[str]
    actif: bool
    created_at: str
    updated_at: str
    sync_status: str = "pending"
    last_synced_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Client":
        return cls(
            id=row["id"],
            uuid=row["uuid"],
            matricule=row["matricule"],
            nom=row["nom"],
            telephone=row["telephone"],
            note=row["note"],
            actif=bool(row["actif"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sync_status=row["sync_status"],
            last_synced_at=row["last_synced_at"],
        )
