"""Réévalue les droits du compte métier à chaque requête authentifiée."""
import hashlib

from django.contrib.auth import logout
from sync.models import RemoteUser


def password_version(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


class RemoteSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        identity = request.session.get("remote_user")
        if request.user.is_authenticated and identity:
            if identity.get("uuid"):
                remote = RemoteUser.objects.filter(uuid=identity["uuid"]).first()
            else:
                remote = RemoteUser.objects.filter(pk=identity.get("id")).first()
            version = password_version(remote.password_hash) if remote else ""
            if remote is None or not remote.actif or (
                identity.get("auth_version") and identity["auth_version"] != version
            ):
                logout(request)
            else:
                request.session["remote_user"] = {
                    "id": remote.id, "uuid": remote.uuid,
                    "identifiant": remote.identifiant, "nom_complet": remote.nom_complet,
                    "role": remote.role, "matricule": remote.matricule,
                    "can_delete": remote.role in ("admin", "super_admin") or remote.can_delete,
                    "auth_version": version,
                }
                # L'objet utilisé par /admin/ doit refléter le rôle actuel.
                request.user.is_staff = remote.role in ("admin", "super_admin")
                request.user.is_superuser = remote.role == "super_admin"
        return self.get_response(request)
