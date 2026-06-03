"""Décorateurs : contrôle d'accès basé sur le rôle."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable


class AccessDeniedError(Exception):
    """Levée quand l'utilisateur n'a pas le rôle requis."""


def require_role(*roles: str) -> Callable:
    allowed = set(roles)

    def deco(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            from app.services.auth_service import current_user

            user = current_user()
            if user is None or user.role not in allowed:
                raise AccessDeniedError("Accès refusé. Fonction réservée aux administrateurs.")
            return func(*args, **kwargs)

        return wrapper

    return deco


def has_role(user, *roles: str) -> bool:
    return user is not None and user.role in set(roles)
