"""Articles sans suivi de stock côté Console Web."""
import uuid

from django.test import TestCase
from django.urls import reverse

from sync.models import CashEntry, Product, Sale, StockMovement
from web.tests import StockAndBalanceTests
from web.views import _cash_balance, _matricule_balance


class UntrackedStockWebTests(TestCase):
    def setUp(self):
        StockAndBalanceTests.setUp(self)
        self.plate = Product.objects.create(
            uuid=str(uuid.uuid4()), nom="Plat 5.000", prix_unitaire=5000,
            quantite_stock=0, suivi_stock=False,
            created_at="2026-01-01 09:00:00", updated_at="2026-01-01 09:00:00")

    make_product = StockAndBalanceTests.make_product

    def sell(self, pk, qte, matricule="MAT-1"):
        return self.client.post(reverse("web:withdrawal_new"), {
            "matricule": matricule, "confirmed": "1", "montant": "",
            "prod_id": [pk], "prod_qte": [qte],
        })

    def test_selling_a_plate_never_runs_out_and_writes_no_movement(self):
        for _ in range(3):
            self.assertEqual(self.sell(self.plate.pk, 2).status_code, 302)
        self.plate.refresh_from_db()
        self.assertEqual(self.plate.quantite_stock, 0)
        self.assertEqual(StockMovement.objects.filter(product_uuid=self.plate.uuid).count(), 0)
        self.assertEqual(Sale.objects.count(), 3)
        # Le compte du client est bien débité.
        self.assertEqual(_matricule_balance("MAT-1"), 10000 - 30000)

    def test_a_tracked_product_still_runs_out(self):
        response = self.sell(self.product.pk, 11)
        self.assertContains(response, "Stock insuffisant")
        self.assertEqual(Sale.objects.count(), 0)

    def test_a_plate_can_be_sold_in_cash(self):
        response = self.client.post(reverse("web:withdrawal_new"), {
            "mode_paiement": "caisse", "confirmed": "1", "montant": "",
            "prod_id": [self.plate.pk], "prod_qte": [2],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(_cash_balance(), 10000)
        self.assertEqual(CashEntry.objects.get(source="vente").entree, 10000)

    def test_no_stock_movement_can_be_applied_to_a_plate(self):
        response = self.client.post(reverse("web:stock_adjust", args=[self.plate.pk]),
                                    {"type": "entree", "quantite": "5"})
        self.assertContains(response, "sans suivi de stock")
        self.assertEqual(StockMovement.objects.filter(product_uuid=self.plate.uuid).count(), 0)

    def test_no_stock_entry_can_be_requested_for_a_plate(self):
        response = self.client.post(reverse("web:stock_entry_request", args=[self.plate.pk]),
                                    {"quantite": "5", "motif": "Livraison"})
        self.assertContains(response, "sans suivi de stock")

    def test_a_plate_is_left_out_of_the_physical_inventory(self):
        listed = self.client.get(reverse("web:inventory")).context["products"]
        self.assertIn(self.product.pk, [p.pk for p in listed])
        self.assertNotIn(self.plate.pk, [p.pk for p in listed])

    def test_creating_a_product_without_stock_ignores_quantity_and_threshold(self):
        self.client.post(reverse("web:product_new"), {
            "nom": "Plat 15.000", "prix_unitaire": "15000", "suivi_stock": "0",
            "quantite_stock": "9", "seuil_alerte": "3", "stock_max": "50",
        })
        created = Product.objects.get(nom="Plat 15.000")
        self.assertFalse(created.suivi_stock)
        self.assertEqual((created.quantite_stock, created.seuil_alerte, created.stock_max),
                         (0, 0, 0))
        self.assertEqual(StockMovement.objects.filter(product_uuid=created.uuid).count(), 0)

    def test_an_absent_field_keeps_the_product_tracked(self):
        """Un formulaire ancien, sans le champ, ne doit pas dé-suivre un article."""
        self.client.post(reverse("web:product_new"), {
            "nom": "Ciment 50kg", "prix_unitaire": "1000", "quantite_stock": "4",
        })
        self.assertTrue(Product.objects.get(nom="Ciment 50kg").suivi_stock)

    def test_switching_a_tracked_product_to_untracked_clears_its_counters(self):
        self.client.post(reverse("web:product_edit", args=[self.product.pk]), {
            "nom": self.product.nom, "prix_unitaire": "100", "suivi_stock": "0",
            "seuil_alerte": "2", "stock_max": "80",
        })
        self.product.refresh_from_db()
        self.assertFalse(self.product.suivi_stock)
        self.assertEqual((self.product.quantite_stock, self.product.seuil_alerte,
                          self.product.stock_max), (0, 0, 0))

    def test_the_product_list_shows_the_plate_without_figures(self):
        page = self.client.get(reverse("web:products")).content.decode()
        self.assertIn("Sans stock", page)
