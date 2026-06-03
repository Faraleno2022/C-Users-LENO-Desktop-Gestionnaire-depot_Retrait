"""Journal d'audit."""
from __future__ import annotations

from typing import List, Optional

from app.db.database import get_connection
from app.models.audit_log import AuditLog
from app.utils.helpers import new_uuid, now_iso


def log_action(
    user_id: Optional[int],
    user_identifiant: Optional[str],
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    conn = get_connection()
    # Récupère user_uuid via users.id pour permettre la sync vers le serveur.
    user_uuid = None
    if user_id is not None:
        row = conn.execute("SELECT uuid FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            user_uuid = row["uuid"]
    conn.execute(
        """INSERT INTO audit_logs
           (uuid, user_id, user_uuid, user_identifiant, action, target_type, target_id, details, created_at, sync_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (new_uuid(), user_id, user_uuid, user_identifiant, action, target_type, target_id, details, now_iso()),
    )
    conn.commit()


def list_logs(limit: int = 200, user_id: Optional[int] = None) -> List[AuditLog]:
    conn = get_connection()
    if user_id is not None:
        rows = conn.execute(
            "SELECT * FROM audit_logs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [AuditLog.from_row(r) for r in rows]
