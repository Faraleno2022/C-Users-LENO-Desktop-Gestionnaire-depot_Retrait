"""Backend d'authentification : vérifie les identifiants contre RemoteUser (bcrypt).

Permet aux utilisateurs créés sur le poste (et synchronisés via /api/sync/push)
de se connecter à la console web avec les mêmes identifiant + mot de passe.

On crée à la volée un `django.contrib.auth.User` miroir (uniquement pour bénéficier
de la session Django et de `request.user`). Le rôle/poste effectif est exposé via
`request.session["remote_user"]` (cf. middleware).
"""
from __future__ import annotations

from typing import Optional

import bcrypt
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

from sync.models import RemoteUser

User = get_user_model()


class RemoteUserBackend(BaseBackend):
    """Authentifie via RemoteUser.identifiant + password_hash (bcrypt)."""

    def authenticate(self, request, username: Optional[str] = None, password: Optional[str] = None, **kwargs):
        if not username or not password:
            return None
        # Plusieurs comptes peuvent partager le même identifiant après une
        # synchronisation multi-machines (ex. un « admin » local + un « admin »
        # venu du serveur). On essaie chacun et on accepte celui dont le mot de
        # passe correspond — le plus récent d'abord.
        candidates = RemoteUser.objects.filter(
            identifiant=username, actif=True
        ).order_by("-id")
        remote = None
        for candidate in candidates:
            if not candidate.password_hash:
                continue
            try:
                if bcrypt.checkpw(password.encode("utf-8"), candidate.password_hash.encode("utf-8")):
                    remote = candidate
                    break
            except (ValueError, TypeError):
                continue
        if remote is None:
            return None

        # User miroir Django (sans mot de passe utilisable côté Django).
        user, _ = User.objects.get_or_create(
            username=remote.identifiant,
            defaults={"first_name": remote.nom_complet[:30] or remote.identifiant},
        )
        if user.first_name != remote.nom_complet[:30]:
            user.first_name = remote.nom_complet[:30]
        user.is_active = True
        # is_staff donne accès au /admin/ Django : on ne l'accorde qu'aux rôles admin.
        user.is_staff = remote.role in ("super_admin", "admin")
        # Un super_admin a tous les droits dans l'admin Django (gestion des
        # Devices/jetons de synchronisation, consultation des données…).
        user.is_superuser = remote.role == "super_admin"
        user.set_unusable_password()
        user.save()

        # On mémorise l'identité « métier » pour les templates et la vérif de rôle.
        if request is not None:
            request.session["remote_user"] = {
                "id": remote.id,
                "identifiant": remote.identifiant,
                "nom_complet": remote.nom_complet,
                "role": remote.role,
                "matricule": remote.matricule,
                "can_delete": remote.role in ("super_admin", "admin") or bool(remote.can_delete),
            }
        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
