from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AuditLog:
    id: Optional[int]
    user_id: Optional[int]
    user_identifiant: Optional[str]
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    details: Optional[str]
    created_at: str

    @classmethod
    def from_row(cls, row) -> "AuditLog":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            user_identifiant=row["user_identifiant"],
            action=row["action"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            details=row["details"],
            created_at=row["created_at"],
        )
