"""Utilitaires de sécurité : hachage de mots de passe."""
from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Mot de passe vide")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
