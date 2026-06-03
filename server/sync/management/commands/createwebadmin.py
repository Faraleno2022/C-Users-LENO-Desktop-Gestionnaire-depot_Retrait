"""Crée ou met à jour un compte super_admin pour la console web.

Utilisable en une commande :
    python manage.py createwebadmin LENO FARALENO2026

Si le compte existe déjà, son mot de passe est rafraîchi (utile en cas d'oubli).
"""
from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime

import bcrypt
from django.core.management.base import BaseCommand, CommandError

from sync.models import RemoteUser


class Command(BaseCommand):
    help = "Crée ou met à jour un compte super_admin pour la console web."

    def add_arguments(self, parser):
        parser.add_argument("identifiant", help="Nom d'utilisateur (ex: LENO)")
        parser.add_argument("password", help="Mot de passe en clair (sera bcrypt-hashé)")
        parser.add_argument(
            "--nom",
            default="Super Administrateur",
            help="Nom complet (défaut: 'Super Administrateur')",
        )
        parser.add_argument(
            "--role",
            default="super_admin",
            choices=["super_admin", "admin", "superviseur", "caissier"],
            help="Rôle (défaut: super_admin)",
        )

    def handle(self, *args, **opts):
        identifiant = opts["identifiant"].strip()
        password = opts["password"]
        nom = opts["nom"]
        role = opts["role"]

        if not identifiant or not password:
            raise CommandError("Identifiant et mot de passe sont obligatoires.")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pwd_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        user, created = RemoteUser.objects.update_or_create(
            identifiant=identifiant,
            defaults=dict(
                uuid=str(uuid_mod.uuid4()) if not RemoteUser.objects.filter(identifiant=identifiant).exists() else (
                    RemoteUser.objects.filter(identifiant=identifiant).first().uuid
                ),
                nom_complet=nom,
                role=role,
                actif=True,
                password_hash=pwd_hash,
                created_at=now,
                updated_at=now,
            ),
        )
        action = "Créé" if created else "Mis à jour"
        self.stdout.write(self.style.SUCCESS(
            f"{action} : id={user.id} identifiant={user.identifiant!r} role={user.role}"
        ))
        # Vérification bcrypt immédiate
        ok = bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8"))
        if ok:
            self.stdout.write(self.style.SUCCESS("Vérification bcrypt : MATCH ✓"))
        else:
            self.stdout.write(self.style.ERROR("Vérification bcrypt : ÉCHEC ✗ (bug à signaler)"))

        total = RemoteUser.objects.count()
        self.stdout.write(f"Total comptes en base : {total}")
