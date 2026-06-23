"""Vide les données métier du système (mise à disposition / remise à zéro).

Efface les opérations et le catalogue, mais CONSERVE par défaut les comptes de
connexion (RemoteUser) et les jetons de synchronisation (Device) afin que le
système reste utilisable immédiatement et que la synchronisation continue.

Tables effacées par défaut :
    sales, transactions, stock_movements, products, clients, audit_logs

Exemples :
    # Remise à zéro standard (garde comptes + jetons) — demande confirmation
    python manage.py flush_data

    # Sans confirmation (pour le Shell Render ou un script)
    python manage.py flush_data --yes

    # Garder aussi les produits (n'effacer que les opérations)
    python manage.py flush_data --yes --keep-products

    # TOUT effacer, y compris les comptes de connexion (⚠ irréversible)
    python manage.py flush_data --yes --include-accounts

À exécuter sur le serveur en ligne (Render Shell) ET sur chaque base locale,
toutes les consoles fermées, pour éviter qu'une machine ne re-pousse ses lignes.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from sync.models import (
    AuditLog,
    Client,
    Product,
    RemoteUser,
    Sale,
    StockMovement,
    Transaction,
)


class Command(BaseCommand):
    help = "Vide les données métier (opérations + produits) en gardant les comptes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true",
            help="Ne pas demander de confirmation (Shell Render / scripts).",
        )
        parser.add_argument(
            "--keep-products", action="store_true",
            help="Conserver le catalogue produits (n'effacer que les opérations).",
        )
        parser.add_argument(
            "--keep-clients", action="store_true",
            help="Conserver la liste des clients (matricules).",
        )
        parser.add_argument(
            "--include-accounts", action="store_true",
            help="⚠ Effacer AUSSI les comptes de connexion (remise à zéro totale).",
        )
        parser.add_argument(
            "--include-devices", action="store_true",
            help="⚠ Effacer AUSSI les jetons de synchronisation (à éviter).",
        )

    def handle(self, *args, **opts):
        # Modèles toujours effacés : les opérations et le journal d'audit.
        # On efface dans l'ordre des dépendances logiques (ventes/mouvements avant
        # produits) même si la sync ne pose pas de contrainte FK stricte.
        targets = [
            ("Ventes", Sale),
            ("Transactions (dépôts/retraits)", Transaction),
            ("Mouvements de stock", StockMovement),
            ("Journal d'audit", AuditLog),
        ]
        if not opts["keep_products"]:
            targets.append(("Produits", Product))
        if not opts["keep_clients"]:
            targets.append(("Clients", Client))
        if opts["include_accounts"]:
            targets.append(("Comptes de connexion", RemoteUser))
        if opts["include_devices"]:
            from sync.models import Device
            targets.append(("Jetons de synchronisation", Device))

        # Aperçu avant action
        self.stdout.write("À effacer :")
        counts = {}
        for label, model in targets:
            n = model.objects.count()
            counts[label] = n
            self.stdout.write(f"  - {label} : {n}")
        kept = []
        if opts["keep_products"]:
            kept.append("produits")
        if opts["keep_clients"]:
            kept.append("clients")
        if not opts["include_accounts"]:
            kept.append(f"comptes de connexion ({RemoteUser.objects.count()})")
        if not opts["include_devices"]:
            from sync.models import Device
            kept.append(f"jetons de sync ({Device.objects.count()})")
        if kept:
            self.stdout.write(self.style.WARNING("Conservés : " + ", ".join(kept)))

        if sum(counts.values()) == 0:
            self.stdout.write(self.style.SUCCESS("Rien à effacer : déjà vide."))
            return

        if not opts["yes"]:
            self.stdout.write(self.style.WARNING(
                "\nOpération IRRÉVERSIBLE. Relancez avec --yes pour confirmer."
            ))
            raise CommandError("Confirmation requise (--yes).")

        with db_transaction.atomic():
            for label, model in targets:
                deleted, _ = model.objects.all().delete()
                self.stdout.write(f"  ✓ {label} : effacé(s)")

        self.stdout.write(self.style.SUCCESS("\nBase vidée. Système prêt à la mise à disposition."))
        if not opts["include_accounts"]:
            self.stdout.write(
                f"Comptes de connexion conservés : {RemoteUser.objects.count()}"
            )
