"""Régressions des débits clients et des mouvements de stock (base de test)."""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sync.models import RemoteUser, Product, Sale, StockEntryRequest, StockMovement, Transaction
from web.views import _matricule_balance


class StockAndBalanceTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="test-admin"))
        session = self.client.session
        remote = RemoteUser.objects.create(uuid=str(uuid.uuid4()), identifiant="test-admin", nom_complet="Test",
                                           role="admin", created_at="now", updated_at="now")
        session["remote_user"] = {"id": remote.id, "uuid": remote.uuid, "role": "admin", "identifiant": "test-admin"}
        session.save()
        self.product = self.make_product("Ciment", 100, 10)
        self.deposit = Transaction.objects.create(
            uuid=str(uuid.uuid4()), matricule="MAT-1", type="depot",
            montant=10000, solde_apres=10000, created_at="2026-01-01 10:00:00",
        )

    def make_product(self, name, price, stock):
        return Product.objects.create(
            uuid=str(uuid.uuid4()), nom=name, prix_unitaire=price,
            quantite_stock=stock, created_at="2026-01-01 09:00:00",
            updated_at="2026-01-01 09:00:00",
        )

    def withdraw(self, ids=(), quantities=(), amount="9999"):
        return self.client.post(reverse("web:withdrawal_new"), {
            "matricule": "MAT-1", "confirmed": "1", "montant": amount,
            "prod_id": list(ids), "prod_qte": list(quantities),
        })

    def assert_stock(self, expected):
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, expected)

    def test_duplicate_product_lines_deduct_combined_quantity_once(self):
        response = self.withdraw([self.product.pk] * 2, [2, 3])
        self.assertEqual(response.status_code, 302)
        self.assert_stock(5)
        self.assertEqual(_matricule_balance("MAT-1"), 9500)
        self.assertEqual(sum(Sale.objects.values_list("quantite", flat=True)), 5)
        self.assertEqual(sum(StockMovement.objects.values_list("quantite", flat=True)), 5)
        self.assertFalse(Transaction.objects.filter(type="retrait").exists())

    def test_duplicate_lines_cannot_exceed_combined_stock(self):
        response = self.withdraw([self.product.pk] * 2, [6, 6])
        self.assertEqual(response.status_code, 200)
        self.assert_stock(10)
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertEqual(_matricule_balance("MAT-1"), 10000)

    def test_failed_second_line_rolls_back_whole_withdrawal(self):
        other = self.make_product("Fer", 200, 20)
        create = StockMovement.objects.create
        calls = 0

        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("Échec simulé")
            return create(**kwargs)

        with patch("web.views.StockMovement.objects.create", side_effect=fail_second):
            response = self.withdraw([self.product.pk, other.pk], [2, 3])
        self.assertEqual(response.status_code, 200)
        self.assert_stock(10)
        other.refresh_from_db()
        self.assertEqual(other.quantite_stock, 20)
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertEqual(_matricule_balance("MAT-1"), 10000)

    def test_cash_withdrawal_does_not_change_stock(self):
        self.assertEqual(self.withdraw(amount="3000").status_code, 302)
        self.assert_stock(10)
        self.assertEqual(_matricule_balance("MAT-1"), 7000)
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_invalid_product_quantity_does_not_become_cash_withdrawal(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                response = self.withdraw([self.product.pk], [value], amount="100")
                self.assertEqual(response.status_code, 200)
                self.assert_stock(10)
                self.assertEqual(_matricule_balance("MAT-1"), 10000)

    def test_incomplete_product_lines_are_rejected(self):
        response = self.withdraw([self.product.pk], [], amount="100")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_matricule_balance("MAT-1"), 10000)

    def test_cancel_and_restore_sale_reverse_both_stock_and_balance(self):
        self.withdraw([self.product.pk], [2])
        sale = Sale.objects.get()
        self.client.post(reverse("web:sale_delete", args=[sale.pk]))
        self.assert_stock(10)
        self.assertEqual(_matricule_balance("MAT-1"), 10000)
        self.client.post(reverse("web:sale_restore", args=[sale.pk]))
        self.assert_stock(8)
        self.assertEqual(_matricule_balance("MAT-1"), 9800)

    def test_sale_restore_refuses_insufficient_stock(self):
        self.withdraw([self.product.pk], [2])
        sale = Sale.objects.get()
        self.client.post(reverse("web:sale_delete", args=[sale.pk]))
        self.product.quantite_stock = 1
        self.product.save()
        self.client.post(reverse("web:sale_restore", args=[sale.pk]))
        self.assert_stock(1)
        sale.refresh_from_db()
        self.assertTrue(sale.deleted)
        self.assertEqual(_matricule_balance("MAT-1"), 10000)

    def test_sale_restore_can_restore_credit_sale(self):
        self.withdraw([self.product.pk], [2])
        sale = Sale.objects.get()
        self.client.post(reverse("web:sale_delete", args=[sale.pk]))
        self.withdraw(amount="9900")
        self.client.post(reverse("web:sale_restore", args=[sale.pk]))
        self.assert_stock(8)
        sale.refresh_from_db()
        self.assertFalse(sale.deleted)
        self.assertEqual(_matricule_balance("MAT-1"), -100)

    def test_initial_stock_creates_entry_movement(self):
        response = self.client.post(reverse("web:product_new"), {
            "nom": "Sable", "prix_unitaire": "200", "quantite_stock": "7",
        })
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(nom="Sable")
        movement = StockMovement.objects.get(product_uuid=product.uuid)
        self.assertEqual((movement.type, movement.quantite, movement.stock_apres), ("entree", 7, 7))

    def test_inventory_validation_is_atomic(self):
        other = self.make_product("Fer", 200, 20)
        response = self.client.post(reverse("web:inventory"), {
            f"count_{self.product.pk}": "8", f"count_{other.pk}": "-1",
        })
        self.assertEqual(response.status_code, 200)
        self.assert_stock(10)
        self.assertFalse(StockMovement.objects.exists())

    def test_fractional_stock_can_be_fully_used(self):
        self.product.quantite_stock = 0.3
        self.product.save()
        self.client.post(reverse("web:stock_adjust", args=[self.product.pk]), {
            "type": "sortie", "quantite": "0.1",
        })
        self.assert_stock(0.2)
        self.client.post(reverse("web:stock_adjust", args=[self.product.pk]), {
            "type": "sortie", "quantite": "0.2",
        })
        self.assert_stock(0)

    def test_multiple_products_and_exact_remaining_balance(self):
        other = self.make_product("Fer", 200, 30)
        response = self.withdraw([self.product.pk, other.pk], [10, 30])
        self.assertEqual(response.status_code, 302)
        self.assert_stock(0)
        other.refresh_from_db()
        self.assertEqual(other.quantite_stock, 0)
        self.assertEqual(_matricule_balance("MAT-1"), 3000)
        self.assertEqual(self.withdraw(amount="3000").status_code, 302)
        self.assertEqual(_matricule_balance("MAT-1"), 0)
        self.assertEqual(self.withdraw(amount="1").status_code, 200)

    def test_fractional_prices_are_not_rounded_in_preview_or_debit(self):
        self.product.prix_unitaire = 2.5
        self.product.save()
        response = self.client.get(reverse("web:withdrawal_new"))
        self.assertContains(response, 'data-prix="2.5"')
        self.assertEqual(self.withdraw([self.product.pk], [2]).status_code, 302)
        self.assertEqual(_matricule_balance("MAT-1"), 9995)
        self.assertEqual(Sale.objects.get().montant_total, 5)

    def test_nonfinite_deposits_are_rejected(self):
        for amount in ("nan", "inf", "-inf"):
            with self.subTest(amount=amount):
                response = self.client.post(reverse("web:deposit_new"), {
                    "matricule": "MAT-1", "montant": amount,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(_matricule_balance("MAT-1"), 10000)

    def test_fractional_deposits_can_be_fully_withdrawn(self):
        for amount in ("0,1", "0,2"):
            response = self.client.post(reverse("web:deposit_new"), {
                "matricule": "DECIMAL", "montant": amount,
            })
            self.assertEqual(response.status_code, 302)
        self.assertEqual(_matricule_balance("DECIMAL"), 0.3)
        response = self.client.post(reverse("web:withdrawal_new"), {
            "matricule": "DECIMAL", "montant": "0,3", "confirmed": "1",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(_matricule_balance("DECIMAL"), 0)

    def test_used_deposit_cannot_be_deleted(self):
        self.withdraw(amount="100")
        self.client.post(reverse("web:transaction_delete", args=[self.deposit.pk]))
        self.deposit.refresh_from_db()
        self.assertFalse(self.deposit.deleted)
        self.assertEqual(_matricule_balance("MAT-1"), 9900)

    def test_cash_restore_refuses_insufficient_balance(self):
        self.withdraw(amount="9000")
        tx = Transaction.objects.get(type="retrait")
        self.client.post(reverse("web:transaction_delete", args=[tx.pk]))
        self.withdraw(amount="2000")
        self.client.post(reverse("web:transaction_restore", args=[tx.pk]))
        tx.refresh_from_db()
        self.assertTrue(tx.deleted)
        self.assertEqual(_matricule_balance("MAT-1"), 8000)

    def test_failed_cancellation_does_not_refund_or_change_stock(self):
        self.withdraw([self.product.pk], [2])
        sale = Sale.objects.get()
        with patch("web.views.StockMovement.objects.create", side_effect=ValueError("Échec simulé")):
            with self.assertLogs("django.request", level="ERROR"), self.assertRaises(ValueError):
                self.client.post(reverse("web:sale_delete", args=[sale.pk]))
        sale.refresh_from_db()
        self.assertFalse(sale.deleted)
        self.assert_stock(8)
        self.assertEqual(_matricule_balance("MAT-1"), 9800)

    def test_missing_uuid_product_does_not_restore_another_product(self):
        self.withdraw([self.product.pk], [2])
        sale = Sale.objects.get()
        self.client.post(reverse("web:sale_delete", args=[sale.pk]))
        sale.refresh_from_db()
        sale.product_uuid = str(uuid.uuid4())
        sale.save()
        self.client.post(reverse("web:sale_restore", args=[sale.pk]))
        self.assert_stock(10)
        sale.refresh_from_db()
        self.assertTrue(sale.deleted)

    def test_stock_entry_validation_is_applied_once(self):
        req = StockEntryRequest.objects.create(
            uuid=str(uuid.uuid4()), product_uuid=self.product.uuid,
            product_nom=self.product.nom, quantite=5, kind="entree",
            created_at="2026-01-01 11:00:00",
        )
        self.assert_stock(10)
        for _ in range(2):
            self.client.post(reverse("web:stock_request_validate", args=[req.pk]))
        self.assert_stock(15)
        self.assertEqual(StockMovement.objects.filter(product_uuid=self.product.uuid).count(), 1)

    def test_failed_stock_entry_validation_can_be_retried_once(self):
        req = StockEntryRequest.objects.create(
            uuid=str(uuid.uuid4()), product_uuid=self.product.uuid,
            product_nom=self.product.nom, quantite=5, kind="entree",
            created_at="2026-01-01 11:00:00",
        )
        with patch("web.views.StockEntryRequest.save", side_effect=ValueError("Échec simulé")):
            with self.assertLogs("django.request", level="ERROR"), self.assertRaises(ValueError):
                self.client.post(reverse("web:stock_request_validate", args=[req.pk]))
        self.assert_stock(10)
        self.assertFalse(StockMovement.objects.exists())
        req.refresh_from_db()
        self.assertEqual(req.statut, "en_attente")
        self.client.post(reverse("web:stock_request_validate", args=[req.pk]))
        self.assert_stock(15)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_stock_adjustment_failure_rolls_back_movement(self):
        with patch("web.views.Product.save", side_effect=ValueError("Échec simulé")):
            response = self.client.post(reverse("web:stock_adjust", args=[self.product.pk]), {
                "type": "sortie", "quantite": "2",
            })
        self.assertEqual(response.status_code, 200)
        self.assert_stock(10)
        self.assertFalse(StockMovement.objects.exists())
