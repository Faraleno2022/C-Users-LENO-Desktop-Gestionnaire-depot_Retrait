"""Supprime TOUS les comptes super_admin puis en cree un seul, authentique.

Utile pour repartir avec un unique super administrateur maitrise (au lieu des
comptes de test / par defaut accumules).

Exemples :
    python manage.py reset_superadmin LENO "MonMotDePasseFort" --nom "Fara Leno"

    # Sans confirmation (Shell Render / scripts)
    python manage.py reset_superadmin LENO "MotDePasse" --yes

Les comptes des autres roles (admin, superviseur, caissier) ne sont PAS touches.
A executer sur le serveur en ligne (Render Shell) : le nouveau compte se
propage ensuite aux postes via la synchronisation (pull des utilisateurs).
"""
from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime

import bcrypt
from django.core.management.base import BaseCommand, CommandError

from sync.models import RemoteUser


class Command(BaseCommand):
    help = "Supprime tous les super_admin et en recree un seul, authentique."

    def add_arguments(self, parser):
        parser.add_argument("identifiant", help="Identifiant du nouveau super admin")
        parser.add_argument("password", help="Mot de passe en clair (sera bcrypt-hashe)")
        parser.add_argument("--nom", default="Super Administrateur", help="Nom complet")
        parser.add_argument(
            "--yes", action="store_true",
            help="Ne pas demander de confirmation.",
        )

    def handle(self, *args, **opts):
        identifiant = opts["identifiant"].strip()
        password = opts["password"]
        nom = opts["nom"]
        if not identifiant or not password:
            raise CommandError("Identifiant et mot de passe sont obligatoires.")

        existing = list(RemoteUser.objects.filter(role="super_admin"))
        self.stdout.write("Comptes super_admin actuels :")
        for u in existing:
            self.stdout.write(f"  - {u.identifiant} ({u.nom_complet})")
        if not existing:
            self.stdout.write("  (aucun)")
        self.stdout.write(
            f"\nAction : supprimer {len(existing)} super_admin, "
            f"puis creer '{identifiant}'."
        )

        if not opts["yes"]:
            self.stdout.write(self.style.WARNING(
                "Operation IRREVERSIBLE. Relancez avec --yes pour confirmer."
            ))
            raise CommandError("Confirmation requise (--yes).")

        # 1) Supprimer tous les super_admin existants.
        deleted = RemoteUser.objects.filter(role="super_admin").delete()[0]

        # 2) Creer le nouveau super_admin authentique.
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pwd_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user = RemoteUser.objects.create(
            uuid=str(uuid_mod.uuid4()),
            identifiant=identifiant,
            nom_complet=nom,
            role="super_admin",
            actif=True,
            password_hash=pwd_hash,
            created_at=now,
            updated_at=now,
        )

        self.stdout.write(self.style.SUCCESS(
            f"\nSupprimes : {deleted} super_admin. Cree : '{user.identifiant}' "
            f"(id={user.id})."
        ))
        # Verification bcrypt immediate
        ok = bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8"))
        self.stdout.write(
            self.style.SUCCESS("Verification mot de passe : OK")
            if ok else self.style.ERROR("Verification mot de passe : ECHEC")
        )
        total = RemoteUser.objects.count()
        self.stdout.write(f"Total comptes en base : {total}")
