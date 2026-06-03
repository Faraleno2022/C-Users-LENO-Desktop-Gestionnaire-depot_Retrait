"""Gestion des utilisateurs."""
from __future__ import annotations

from typing import List, Optional

from app.config import DEFAULT_SUPER_ADMIN, ROLES
from app.db.database import get_connection
from app.models.user import User
from app.services import audit_service, auth_service
from app.utils.helpers import new_uuid, now_iso
from app.utils.security import hash_password


class UserServiceError(Exception):
    pass


def ensure_super_admin() -> None:
    """Crée un super-admin par défaut si aucun n'existe."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE role = 'super_admin'"
    ).fetchone()
    if row["n"] > 0:
        return
    now = now_iso()
    conn.execute(
        """INSERT INTO users (uuid, identifiant, password_hash, nom_complet, matricule, telephone,
                              role, actif, created_at, updated_at, sync_status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            new_uuid(),
            DEFAULT_SUPER_ADMIN["identifiant"],
            hash_password(DEFAULT_SUPER_ADMIN["password"]),
            DEFAULT_SUPER_ADMIN["nom_complet"],
            DEFAULT_SUPER_ADMIN["matricule"],
            DEFAULT_SUPER_ADMIN["telephone"],
            DEFAULT_SUPER_ADMIN["role"],
            1,
            now,
            now,
            "pending",
        ),
    )
    conn.commit()


def list_users(role: Optional[str] = None, include_inactive: bool = True) -> List[User]:
    conn = get_connection()
    sql = "SELECT * FROM users WHERE 1=1"
    params: list = []
    if role is not None:
        sql += " AND role = ?"
        params.append(role)
    if not include_inactive:
        sql += " AND actif = 1"
    sql += " ORDER BY nom_complet"
    rows = conn.execute(sql, params).fetchall()
    return [User.from_row(r) for r in rows]


def get_user(user_id: int) -> Optional[User]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return User.from_row(row) if row else None


def get_user_by_identifiant(identifiant: str) -> Optional[User]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE identifiant = ?", (identifiant,)).fetchone()
    return User.from_row(row) if row else None


def create_user(
    identifiant: str,
    password: str,
    nom_complet: str,
    role: str,
    matricule: str = "",
    telephone: str = "",
    actif: bool = True,
) -> User:
    identifiant = (identifiant or "").strip()
    nom_complet = (nom_complet or "").strip()
    if not identifiant or not password or not nom_complet:
        raise UserServiceError("Identifiant, mot de passe et nom complet sont obligatoires.")
    if role not in ROLES:
        raise UserServiceError(f"Rôle invalide : {role}")
    if get_user_by_identifiant(identifiant) is not None:
        raise UserServiceError(f"L'identifiant '{identifiant}' existe déjà.")

    conn = get_connection()
    now = now_iso()
    cur = conn.execute(
        """INSERT INTO users (uuid, identifiant, password_hash, nom_complet, matricule, telephone,
                              role, actif, created_at, updated_at, sync_status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            new_uuid(),
            identifiant,
            hash_password(password),
            nom_complet,
            matricule or None,
            telephone or None,
            role,
            1 if actif else 0,
            now,
            now,
            "pending",
        ),
    )
    conn.commit()
    user = get_user(cur.lastrowid)
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "USER_CREATE",
        target_type="user",
        target_id=str(user.id) if user else None,
        details=f"{identifiant} ({role})",
    )
    return user


def update_user(
    user_id: int,
    nom_complet: Optional[str] = None,
    matricule: Optional[str] = None,
    telephone: Optional[str] = None,
    role: Optional[str] = None,
    actif: Optional[bool] = None,
) -> User:
    user = get_user(user_id)
    if user is None:
        raise UserServiceError("Utilisateur introuvable.")
    if role is not None and role not in ROLES:
        raise UserServiceError(f"Rôle invalide : {role}")

    fields = []
    params: list = []
    if nom_complet is not None:
        fields.append("nom_complet = ?")
        params.append(nom_complet.strip())
    if matricule is not None:
        fields.append("matricule = ?")
        params.append(matricule or None)
    if telephone is not None:
        fields.append("telephone = ?")
        params.append(telephone or None)
    if role is not None:
        fields.append("role = ?")
        params.append(role)
    if actif is not None:
        fields.append("actif = ?")
        params.append(1 if actif else 0)

    if not fields:
        return user

    fields.append("updated_at = ?")
    params.append(now_iso())
    fields.append("sync_status = ?")
    params.append("pending")
    params.append(user_id)

    conn = get_connection()
    conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()

    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "USER_UPDATE",
        target_type="user",
        target_id=str(user_id),
    )
    return get_user(user_id)


def reset_password(user_id: int, new_password: str) -> None:
    if not new_password or len(new_password) < 4:
        raise UserServiceError("Le mot de passe doit contenir au moins 4 caractères.")
    user = get_user(user_id)
    if user is None:
        raise UserServiceError("Utilisateur introuvable.")
    conn = get_connection()
    conn.execute(
        "UPDATE users SET password_hash = ?, updated_at = ?, sync_status = 'pending' WHERE id = ?",
        (hash_password(new_password), now_iso(), user_id),
    )
    conn.commit()
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "PASSWORD_RESET",
        target_type="user",
        target_id=str(user_id),
    )


def delete_user(user_id: int) -> None:
    user = get_user(user_id)
    if user is None:
        raise UserServiceError("Utilisateur introuvable.")
    if user.role == "super_admin":
        # On vérifie qu'au moins un autre super-admin existe
        conn = get_connection()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'super_admin' AND id != ?",
            (user_id,),
        ).fetchone()
        if row["n"] == 0:
            raise UserServiceError("Impossible de supprimer le dernier super-administrateur.")
    conn = get_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    actor = auth_service.current_user()
    audit_service.log_action(
        actor.id if actor else None,
        actor.identifiant if actor else None,
        "USER_DELETE",
        target_type="user",
        target_id=str(user_id),
        details=user.identifiant,
    )
