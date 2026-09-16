"""Ventes à crédit et plafond journalier, sans base client ni réseau."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from accounting_test import DatabaseTestCase
from app.db import database as db
from app.services import transaction_service as tx, sale_service as sales, product_service as products
from app.services import sync_service, settings_service
from server.sync.business_rules import RECENT_ALERT_DAYS, business_day, day_offset, deposit_warnings
from server.sync.reconciliation_engine import build_plan
from reconciliation_test import fixture


class CreditDepositTests(DatabaseTestCase):
    def deposit(self, amount, matricule="NEW"):
        return tx.create_transaction(matricule, "", "depot", amount, self.agent)

    def test_credit_without_deposit_then_repayment(self):
        first = sales.create_sale("NEW", self.product.id, 3, self.agent)
        self.assertEqual(first.solde_apres, -300)
        second = sales.create_sale("NEW", self.product.id, 2, self.agent)
        self.assertEqual(second.solde_apres, -500)
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 5)
        self.assertEqual(self.deposit(200).solde_apres, -300)
        self.assertEqual(self.deposit(300).solde_apres, 0)
        sales.cancel_sale(first.id)
        self.assertEqual(tx.get_matricule_balance("NEW"), 300)
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 8)

    def test_cash_still_requires_balance(self):
        sales.create_sale("NEW", self.product.id, 1, self.agent)
        with self.assertRaises(tx.TransactionError):
            tx.create_transaction("NEW", "", "retrait", 1, self.agent)

    def test_daily_cumulative_limit_not_freed_by_spending(self):
        self.deposit(30000)
        self.deposit(10000)
        tx.create_transaction("NEW", "", "retrait", 39000, self.agent)
        with self.assertRaisesRegex(tx.TransactionError, "40 000"):
            self.deposit(1)
        self.assertEqual(tx.get_matricule_balance("NEW"), 1000)
        self.assertEqual(tx.deposits_on_day("NEW"), 40000)
        self.deposit(40000, "OTHER")

    def test_limit_resets_on_next_day_and_timestamp_matches(self):
        with patch.object(tx, "business_timestamp", return_value="2026-09-14 23:59:59"):
            self.deposit(40000)
        with patch.object(tx, "business_timestamp", return_value="2026-09-15 00:00:00"):
            self.assertEqual(self.deposit(40000).created_at, "2026-09-15 00:00:00")
            with self.assertRaises(tx.TransactionError):
                self.deposit(1)
        self.assertEqual(tx.deposits_on_day("NEW", "2026-09-14"), 40000)

    def test_cancelled_deposit_no_longer_counts(self):
        deposit = self.deposit(40000)
        tx.delete_transaction(deposit.id)
        self.deposit(40000)
        self.assertEqual(tx.deposits_on_day("NEW"), 40000)

    def test_concurrent_deposits_cannot_exceed_limit(self):
        barrier = threading.Barrier(2)
        def deposit():
            try:
                barrier.wait(timeout=10)
                self.deposit(25000)
                return "accepted"
            except tx.TransactionError:
                return "refused"
            finally:
                db.close_connection()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: deposit(), range(2)))
        self.assertCountEqual(results, ["accepted", "refused"])
        self.assertEqual(tx.deposits_on_day("NEW"), 25000)

    def test_sync_warns_without_changing_encashments(self):
        a = self.deposit(30000)
        # Simulate the receipt actually recorded offline on another workstation.
        conn = db.get_connection()
        conn.execute("INSERT INTO transactions(uuid,matricule,type,montant,solde_apres,created_at,deleted,agent_nom) VALUES(?,?,?,?,?,?,0,'Test')",
                     ("remote-receipt", "NEW", "depot", 30000, 30000, a.created_at))
        conn.commit()
        with patch.object(sync_service, "push_all", return_value={}), patch.object(sync_service, "pull_all", return_value={}):
            result = sync_service.sync_all()
        self.assertEqual(result["warnings"][0]["total"], 60000)
        self.assertEqual(result["warnings"][0]["excess"], 20000)
        self.assertIn("60000", settings_service.get_setting("sync.deposit_warnings"))
        self.assertEqual(tx.get_matricule_balance("NEW"), 60000)
        tx.delete_transaction(a.id)
        with patch.object(sync_service, "push_all", return_value={}), patch.object(sync_service, "pull_all", return_value={}):
            self.assertEqual(sync_service.sync_all()["warnings"], [])

    def test_sync_alerts_are_bounded_but_history_is_preserved(self):
        """Le recalcul à chaque synchro ne relit pas tout l'historique."""
        old_day = day_offset(business_day(), -(RECENT_ALERT_DAYS + 1))
        conn = db.get_connection()
        for uid in ("ancien-1", "ancien-2"):
            conn.execute("INSERT INTO transactions(uuid,matricule,type,montant,solde_apres,created_at,deleted,agent_nom) VALUES(?,?,?,?,?,?,0,'Test')",
                         (uid, "NEW", "depot", 30000, 30000, f"{old_day} 12:00:00"))
        conn.commit()
        with patch.object(sync_service, "push_all", return_value={}), patch.object(sync_service, "pull_all", return_value={}):
            self.assertEqual(sync_service.sync_all()["warnings"], [])
        # Rien n'est effacé : le dépassement reste listable sans borne.
        self.assertEqual(tx.get_deposit_warnings()[0]["day"], old_day)
        self.assertEqual(tx.deposits_on_day("NEW", old_day), 60000)

    def test_credit_is_not_reported_as_calculation_error(self):
        data = fixture()
        data[2] = []
        plan = build_plan(*data)
        self.assertEqual(plan["balances"], [{"matricule": "A", "balance": -500}])
        self.assertFalse(any("Solde négatif" in i["reason"] for i in plan["issues"]))

    def test_warning_uses_decimal_totals_and_guinea_day(self):
        rows = [dict(matricule="A", montant=amount, created_at="2026-09-15 23:00:00-01:00")
                for amount in (39999.7, .1, .2)]
        self.assertEqual(deposit_warnings(rows), [])
        rows.append(dict(rows[0], montant=1))
        self.assertEqual(deposit_warnings(rows)[0]["day"], "2026-09-16")
        self.assertEqual(business_day("2026-09-15T00:15:00+01:00"), "2026-09-14")
