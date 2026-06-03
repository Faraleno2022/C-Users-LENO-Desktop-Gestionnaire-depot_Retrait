"""Crée (ou réaffiche) un poste et son jeton de synchronisation.

Exemple :
    python manage.py createdevice "Caisse principale"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from sync.models import Device


class Command(BaseCommand):
    help = "Crée un poste autorisé et affiche son jeton de synchronisation."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Nom du poste (unique).")
        parser.add_argument(
            "--regenerate",
            action="store_true",
            help="Régénère le jeton si le poste existe déjà.",
        )

    def handle(self, *args, **options):
        name = options["name"].strip()
        if not name:
            raise CommandError("Le nom du poste ne peut pas être vide.")

        device, created = Device.objects.get_or_create(name=name)
        if not created and options["regenerate"]:
            from sync.models import generate_token

            device.token = generate_token()
            device.active = True
            device.save(update_fields=["token", "active"])

        action = "créé" if created else "existant"
        self.stdout.write(self.style.SUCCESS(f"Poste {action} : {device.name}"))
        self.stdout.write(f"Jeton (device token) : {device.token}")
        self.stdout.write(
            "Configurez ce jeton et l'URL du serveur dans l'application de bureau "
            "(Administration -> Synchronisation)."
        )
