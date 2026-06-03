"""Authentification et session utilisateur courante."""
from __future__ import annotations

from typing import Optional

from app.db.database import get_connection
from app.models.user import User
from app.services import audit_service
from app.utils.security import verify_password

_current_user: Optional[User] = None


class AuthError(Exception):
    pass


def login(identifiant: str, password: str) -> User:
    global _current_user
    identifiant = (identifiant or "").strip()
    if not identifiant or not password:
        raise AuthError("Identifiant et mot de passe requis.")
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE identifiant = ?",
        (identifiant,),
    ).fetchone()
    if row is None:
        raise AuthError("Identifiant ou mot de passe incorrect.")
    user = User.from_row(row)
    if not user.actif:
        raise AuthError("Ce compte est désactivé. Contactez un administrateur.")
    if not verify_password(password, user.password_hash):
        audit_service.log_action(None, identifiant, "LOGIN_FAILED", details="Mot de passe invalide")
        raise AuthError("Identifiant ou mot de passe incorrect.")
    _current_user = user
    audit_service.log_action(user.id, user.identifiant, "LOGIN")
    return user


def logout() -> None:
    global _current_user
    if _current_user is not None:
        audit_service.log_action(_current_user.id, _current_user.identifiant, "LOGOUT")
    _current_user = None


def current_user() -> Optional[User]:
    return _current_user


def set_current_user(user: Optional[User]) -> None:
    """Utilisé après une mise à jour du compte courant (changement de mot de passe, etc.)."""
    global _current_user
    _current_user = user
