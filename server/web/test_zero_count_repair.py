"""Un comptage d'inventaire sans écart ne doit pas bloquer la réplication."""
import json
import uuid

from django.test import TestCase
from django.urls import reverse

from sync.models import Device, Product, StockMovement


class ZeroCountPushTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(name="Console test")
        self.auth = {"HTTP_AUTHORIZATION": f"Device {self.device.token}"}
        # Le catalogue doit précéder ses mouvements.
        self.product = Product.objects.create(
            uuid="p-1", nom="PATTES DOCTOR", prix_unitaire=10,
            quantite_stock=12, created_at="now", updated_at="now")

    def push(self, record):
        return self.client.post(
            reverse("sync-push"),
            data=json.dumps({"table": "stock_movements", "records": [record]}),
            content_type="application/json", **self.auth)

    def movement(self, **extra):
        base = dict(uuid=str(uuid.uuid4()), product_id=self.product.id,
                    product_uuid="p-1",
                    product_nom="PATTES DOCTOR", type="entree", quantite=0,
                    stock_apres=12, motif="Inventaire physique",
                    created_at="2026-08-18 00:36:32", deleted=False)
        base.update(extra)
        return base

    def test_a_zero_count_without_counted_quantity_is_refused(self):
        """C'est le rejet qui bloquait toute la synchronisation en production."""
        response = self.push(self.movement(stock_compte=None))
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantite doit être strictement positif",
                      response.json()["detail"])
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_the_same_count_passes_once_the_counted_quantity_is_set(self):
        response = self.push(self.movement(stock_compte=12))
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["created"], 1)
        moved = StockMovement.objects.get()
        self.assertEqual((moved.quantite, moved.stock_compte), (0, 12))

    def test_a_negative_quantity_stays_refused(self):
        """La réparation ne doit pas légitimer une quantité négative."""
        response = self.push(self.movement(quantite=-3, stock_compte=12))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(StockMovement.objects.count(), 0)


class ZeroCountRepairTests(TestCase):
    def test_the_migration_fills_the_counted_quantity(self):
        from django.db import models as dj_models
        from sync.migrations import (
            __name__ as _pkg,  # noqa: F401  (garantit le paquet importable)
        )
        Product.objects.create(uuid="p-1", nom="PATTES DOCTOR", prix_unitaire=10,
                               created_at="now", updated_at="now")
        broken = StockMovement.objects.create(
            uuid=str(uuid.uuid4()), product_id=1, product_uuid="p-1",
            product_nom="PATTES DOCTOR", type="entree", quantite=0,
            stock_apres=12, stock_compte=None, motif="Inventaire physique",
            created_at="2026-08-18 00:36:32")
        healthy = StockMovement.objects.create(
            uuid=str(uuid.uuid4()), product_id=1, product_uuid="p-1",
            product_nom="PATTES DOCTOR", type="sortie", quantite=5,
            stock_apres=7, stock_compte=None, motif="Vente",
            created_at="2026-08-18 00:40:00")

        # Même opération que la migration 0019.
        StockMovement.objects.filter(quantite=0, stock_compte__isnull=True).update(
            stock_compte=dj_models.F("stock_apres"))

        broken.refresh_from_db()
        healthy.refresh_from_db()
        self.assertEqual(broken.stock_compte, 12)
        # Un mouvement normal n'est pas touché.
        self.assertIsNone(healthy.stock_compte)
