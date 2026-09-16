"""Règles de crédit/plafond sur une base Django temporaire."""
import uuid
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from sync.models import Transaction, Sale
from sync.business_rules import business_day
from web.views import _matricule_balance
from web.tests import StockAndBalanceTests


class CreditDepositTests(TestCase):
    def setUp(self):
        StockAndBalanceTests.setUp(self)
        del self.deposit
    make_product = StockAndBalanceTests.make_product
    withdraw = StockAndBalanceTests.withdraw

    def deposit(self, amount):
        return self.client.post(reverse("web:deposit_new"), {"matricule": "MAT-1", "montant": str(amount)})

    def test_credit_sale_without_previous_deposit(self):
        Transaction.objects.all().delete()
        response = self.withdraw([self.product.pk], [3])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(_matricule_balance("MAT-1"), -300)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 7)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.withdraw([self.product.pk], [2]).status_code, 302)
        self.assertEqual(_matricule_balance("MAT-1"), -500)
        self.assertEqual(self.deposit(200).status_code, 302)
        self.assertEqual(_matricule_balance("MAT-1"), -300)
        preview = self.client.get(reverse("web:matricule_balance_api"), {"matricule": "MAT-1"}).json()
        self.assertTrue(preview["found"])
        self.assertEqual(preview["daily_deposits"], 200)
        self.assertEqual(preview["daily_deposit_limit"], 40000)

    def test_cash_withdrawal_cannot_create_credit(self):
        Transaction.objects.all().delete()
        response = self.withdraw(amount=1)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Transaction.objects.exists())

    def test_cumulative_cap_and_next_day(self):
        with patch("web.views.business_timestamp", return_value="2026-09-15 23:59:59"):
            self.assertEqual(self.deposit(30000).status_code, 302)
            self.assertEqual(self.deposit(10000).status_code, 302)
            response = self.deposit(1)
            self.assertContains(response, "Plafond journalier")
            self.assertEqual(Transaction.objects.filter(created_at__startswith="2026-09-15").count(), 2)
        with patch("web.views.business_timestamp", return_value="2026-09-16 00:00:00"):
            self.assertEqual(self.deposit(40000).status_code, 302)

    def test_restoring_deposit_checks_original_day(self):
        self.deposit(40000)
        deleted = Transaction.objects.create(uuid=str(uuid.uuid4()), matricule="MAT-1", type="depot",
                    montant=1, solde_apres=1, created_at=business_day()+" 08:00:00", deleted=True)
        response = self.client.post(reverse("web:transaction_restore", args=[deleted.pk]), follow=True)
        self.assertContains(response, "Plafond journalier")
        deleted.refresh_from_db()
        self.assertTrue(deleted.deleted)
        # Yesterday's allowance is independent of today's.
        deleted.created_at = "2026-09-13 08:00:00"
        deleted.save()
        self.client.post(reverse("web:transaction_restore", args=[deleted.pk]))
        deleted.refresh_from_db()
        self.assertFalse(deleted.deleted)

    def test_global_overshoot_is_visible_despite_agent_filter(self):
        Transaction.objects.create(uuid=str(uuid.uuid4()), matricule="MAT-1", type="depot",
                    montant=40000, solde_apres=40000, created_at=self.deposit_record_date())
        response = self.client.get(reverse("web:transactions"), {"agent": "different-agent"})
        self.assertContains(response, "dépassement")
        self.assertContains(response, "50 000 GNF")
        self.assertContains(response, "Contrôle global")

    def deposit_record_date(self):
        return "2026-01-01 10:00:00"
