"""Caisse : vente encaissée, écritures manuelles et solde progressif."""
import threading
from concurrent.futures import ThreadPoolExecutor

from accounting_test import DatabaseTestCase
from app.db import database as db
from app.services import cash_service as cash, product_service as products
from app.services import sale_service as sales, transaction_service as tx
from server.sync.business_rules import business_day
from server.sync.reconciliation_engine import build_plan


class CashRegisterTests(DatabaseTestCase):
    def test_progressive_balance_follows_the_voice_note_example(self):
        cash.create_opening(100000, self.agent, date="2026-01-01")
        cash.create_entry("Versement à la banque", self.agent, sortie=54000, date="2026-01-01")
        cash.create_entry("Recette annexe", self.agent, entree=20000, date="2026-01-01")
        cash.create_entry("Achat fournitures", self.agent, sortie=40000, date="2026-01-01")
        soldes = [e.solde_progressif for e in cash.list_entries()]
        self.assertEqual(soldes, [100000, 46000, 66000, 26000])
        self.assertEqual(cash.get_balance(), 26000)
        self.assertEqual(cash.totals()[:2], (120000, 94000))

    def test_cash_sale_feeds_the_register_without_touching_any_account(self):
        cash.create_opening(5000, self.agent)
        sale = sales.create_sale("", self.product.id, 3, self.agent, mode_paiement="caisse")
        self.assertEqual(sale.mode_paiement, "caisse")
        self.assertEqual(sale.matricule, "")
        self.assertEqual(sale.solde_apres, 0)
        # Le stock est décompté comme pour n'importe quelle vente.
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 7)
        # L'encaissement entre en caisse, avec sa date et son libellé.
        entry = cash.list_entries()[-1]
        self.assertEqual((entry.source, entry.entree, entry.sortie), ("vente", 300, 0))
        self.assertIn("Ciment", entry.libelle)
        self.assertEqual(cash.get_balance(), 5300)
        # Aucun compte client n'est mouvementé, ni le solde global.
        self.assertEqual(tx.get_matricule_balance("CLIENT"), 10000)
        self.assertEqual(tx.get_global_balance(), 10000)

    def test_cancelling_a_cash_sale_removes_its_encashment(self):
        sale = sales.create_sale("", self.product.id, 2, self.agent, mode_paiement="caisse")
        self.assertEqual(cash.get_balance(), 200)
        sales.cancel_sale(sale.id)
        self.assertEqual(cash.get_balance(), 0)
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 10)
        self.assertEqual([e.solde_progressif for e in cash.list_entries()], [])

    def test_account_sale_never_reaches_the_register(self):
        sales.create_sale("CLIENT", self.product.id, 1, self.agent)
        self.assertEqual(cash.list_entries(), [])
        self.assertEqual(tx.get_matricule_balance("CLIENT"), 9900)

    def test_withdrawal_larger_than_the_drawer_is_refused(self):
        cash.create_opening(1000, self.agent)
        with self.assertRaisesRegex(cash.CashError, "insuffisant"):
            cash.create_entry("Versement à la banque", self.agent, sortie=1001)
        self.assertEqual(cash.get_balance(), 1000)
        cash.create_entry("Versement à la banque", self.agent, sortie=1000)
        self.assertEqual(cash.get_balance(), 0)

    def test_only_one_opening_entry(self):
        cash.create_opening(1000, self.agent)
        with self.assertRaisesRegex(cash.CashError, "déjà une écriture d'ouverture"):
            cash.create_opening(2000, self.agent)

    def test_entry_requires_a_label_a_side_and_a_positive_amount(self):
        for kwargs in ({"entree": 100, "sortie": 100}, {}, {"entree": -5}):
            with self.assertRaises(cash.CashError):
                cash.create_entry("Test", self.agent, **kwargs)
        with self.assertRaisesRegex(cash.CashError, "libellé"):
            cash.create_entry("   ", self.agent, entree=100)
        with self.assertRaisesRegex(cash.CashError, "Date invalide"):
            cash.create_entry("Test", self.agent, entree=100, date="2026-13-45")

    def test_backdated_entry_is_ordered_by_its_own_date(self):
        cash.create_opening(10000, self.agent, date="2026-03-10")
        cash.create_entry("Sortie du 12", self.agent, sortie=1000, date="2026-03-12")
        cash.create_entry("Entrée oubliée du 11", self.agent, entree=500, date="2026-03-11")
        journal = [(e.date, e.solde_progressif) for e in cash.list_entries()]
        self.assertEqual(journal, [("2026-03-10", 10000), ("2026-03-11", 10500), ("2026-03-12", 9500)])

    def test_filtering_keeps_the_balance_of_the_whole_journal(self):
        cash.create_opening(10000, self.agent, date="2026-03-10")
        cash.create_entry("Sortie", self.agent, sortie=4000, date="2026-03-12")
        filtered = cash.list_entries(date_from="2026-03-12")
        self.assertEqual([e.libelle for e in filtered], ["Sortie"])
        self.assertEqual(filtered[0].solde_progressif, 6000)

    def test_deleting_a_manual_entry_and_protecting_the_sale_one(self):
        cash.create_opening(1000, self.agent)
        sale = sales.create_sale("", self.product.id, 1, self.agent, mode_paiement="caisse")
        encaissement = cash.list_entries()[-1]
        with self.assertRaisesRegex(cash.CashError, "annulez la vente"):
            cash.delete_entry(encaissement.id, self.agent)
        entry = cash.create_entry("Erreur de saisie", self.agent, entree=500)
        cash.delete_entry(entry.id, self.agent)
        self.assertEqual(cash.get_balance(), 1100)
        with self.assertRaisesRegex(cash.CashError, "déjà annulée"):
            cash.delete_entry(entry.id, self.agent)
        self.assertEqual(sale.mode_paiement, "caisse")

    def test_deleting_an_entry_cannot_make_the_drawer_negative(self):
        entry = cash.create_entry("Recette", self.agent, entree=1000)
        cash.create_entry("Versement à la banque", self.agent, sortie=800)
        with self.assertRaisesRegex(cash.CashError, "négatif"):
            cash.delete_entry(entry.id, self.agent)

    def test_concurrent_withdrawals_cannot_empty_the_drawer_twice(self):
        cash.create_opening(30000, self.agent)
        barrier = threading.Barrier(2)

        def withdraw():
            try:
                barrier.wait(timeout=10)
                cash.create_entry("Versement à la banque", self.agent, sortie=25000)
                return "accepted"
            except cash.CashError:
                return "refused"
            finally:
                db.close_connection()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: withdraw(), range(2)))
        self.assertCountEqual(results, ["accepted", "refused"])
        self.assertEqual(cash.get_balance(), 5000)

    def test_cash_sale_is_not_reported_as_a_balance_error(self):
        sales.create_sale("", self.product.id, 2, self.agent, mode_paiement="caisse")
        conn = db.get_connection()
        data = {name: [dict(r) for r in conn.execute(f"SELECT * FROM {name} ORDER BY uuid")]
                for name in ("products", "stock_movements", "transactions", "sales", "audit_logs")}
        plan = build_plan(data["products"], data["stock_movements"], data["transactions"],
                          data["sales"], data["audit_logs"])
        self.assertEqual([b["matricule"] for b in plan["balances"]], ["CLIENT"])
        self.assertEqual(plan["issues"], [])

    def test_report_labels_a_cash_sale(self):
        from app.services import report_service
        sales.create_sale("", self.product.id, 1, self.agent, mode_paiement="caisse")
        sales.create_sale("CLIENT", self.product.id, 1, self.agent)
        today = business_day()
        rows = report_service.fetch_sales_rows(today, today)
        self.assertEqual([r[2] for r in rows], ["Caisse", "CLIENT"])
        self.assertEqual(report_service.SALES_HEADERS[2], "Payé par")

    def test_unknown_payment_mode_is_refused(self):
        with self.assertRaisesRegex(sales.SaleError, "Mode de paiement"):
            sales.create_sale("CLIENT", self.product.id, 1, self.agent, mode_paiement="cheque")

    def test_sync_pushes_cash_entries(self):
        from app.services import sync_service
        self.assertIn("cash_entries", sync_service.PUSH_TABLES)
        cash.create_entry("Recette", self.agent, entree=100)
        pending = db.get_connection().execute(
            "SELECT sync_status FROM cash_entries").fetchone()["sync_status"]
        self.assertEqual(pending, "pending")
