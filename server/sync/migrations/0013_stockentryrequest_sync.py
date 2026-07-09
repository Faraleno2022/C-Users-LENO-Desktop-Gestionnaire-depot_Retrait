"""Rend StockEntryRequest synchronisable (SyncedModel : uuid, device, received_at ;
product_uuid au lieu de la FK ; dates en texte ISO).

Les demandes « en attente » sont transitoires (un agent peut re-proposer), donc
on recree la table proprement plutot que de tenter une conversion de type
risquee. Les produits/mouvements deja valides ne sont PAS impactes (autres
tables).
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("sync", "0012_stockmovement_deleted"),
    ]

    operations = [
        migrations.DeleteModel(name="StockEntryRequest"),
        migrations.CreateModel(
            name="StockEntryRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.CharField(db_index=True, max_length=36, unique=True)),
                ("received_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("kind", models.CharField(choices=[("entree", "Entrée sur produit existant"), ("nouveau_produit", "Création d'un nouveau produit")], db_index=True, default="entree", max_length=16)),
                ("product_uuid", models.CharField(blank=True, db_index=True, default="", max_length=36)),
                ("product_nom", models.CharField(max_length=200)),
                ("quantite", models.FloatField()),
                ("motif", models.CharField(blank=True, default="", max_length=255)),
                ("new_reference", models.CharField(blank=True, default="", max_length=80)),
                ("new_prix_unitaire", models.FloatField(default=0)),
                ("new_seuil_alerte", models.FloatField(default=0)),
                ("new_description", models.TextField(blank=True, default="")),
                ("statut", models.CharField(choices=[("en_attente", "En attente"), ("valide", "Validée"), ("rejete", "Rejetée")], db_index=True, default="en_attente", max_length=12)),
                ("requested_by_identifiant", models.CharField(blank=True, default="", max_length=120)),
                ("requested_by_nom", models.CharField(blank=True, default="", max_length=200)),
                ("requested_by_uuid", models.CharField(blank=True, default="", max_length=36)),
                ("created_at", models.CharField(max_length=32)),
                ("validated_by_identifiant", models.CharField(blank=True, default="", max_length=120)),
                ("validated_by_nom", models.CharField(blank=True, default="", max_length=200)),
                ("validated_at", models.CharField(blank=True, default="", max_length=32)),
                ("decision_motif", models.CharField(blank=True, default="", max_length=255)),
                ("resulting_movement_uuid", models.CharField(blank=True, default="", max_length=36)),
                ("device", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="sync.device")),
            ],
            options={
                "verbose_name": "Demande d'entrée de stock",
                "verbose_name_plural": "Demandes d'entrée de stock",
                "ordering": ["-created_at"],
            },
        ),
    ]
