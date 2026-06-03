from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: Optional[int]
    uuid: str
    identifiant: str
    password_hash: str
    nom_complet: str
    matricule: Optional[str]
    telephone: Optional[str]
    role: str
    actif: bool
    created_at: str
    updated_at: str
    sync_status: str = "pending"
    last_synced_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "User":
        return cls(
            id=row["id"],
            uuid=row["uuid"],
            identifiant=row["identifiant"],
            password_hash=row["password_hash"],
            nom_complet=row["nom_complet"],
            matricule=row["matricule"],
            telephone=row["telephone"],
            role=row["role"],
            actif=bool(row["actif"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sync_status=row["sync_status"],
            last_synced_at=row["last_synced_at"],
        )

    def is_admin(self) -> bool:
        return self.role in ("admin", "super_admin")

    def is_super_admin(self) -> bool:
        return self.role == "super_admin"
