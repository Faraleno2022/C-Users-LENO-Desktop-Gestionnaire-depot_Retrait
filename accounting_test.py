"""Tests du stock et des soldes bureau, toujours dans une base temporaire."""
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.db import database as db
from app.models.user import User
from app.services import product_service as products, sale_service as sales
from app.services import transaction_service as transactions


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="accounting_test_")
        self.db_path = patch.object(db, "DB_PATH", Path(self.tmp.name) / "test.db")
        self.dirs = patch.object(db, "ensure_directories", lambda: None)
        self.addCleanup(self.tmp.cleanup)
        self.db_path.start()
        self.addCleanup(self.db_path.stop)
        self.dirs.start()
        self.addCleanup(self.dirs.stop)
        self.addCleanup(db.close_connection)
        db.close_connection()
        db.init_database()
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO users (uuid, identifiant, password_hash, nom_complet, role, "
            "actif, created_at, updated_at) VALUES ('test-user','test','unused','Test','admin',1,'now','now')"
        )
        conn.commit()
        self.agent = User.from_row(conn.execute("SELECT * FROM users").fetchone())
        self.auth = patch("app.services.auth_service.current_user", return_value=self.agent)
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.product = products.create_product("Ciment", 100, quantite_initiale=10)
        transactions.create_transaction("CLIENT", "", "depot", 10000, self.agent)

class AccountingTests(DatabaseTestCase):
    def test_full_sale_and_cancel_cycle(self):
        sale = sales.create_sale("CLIENT", self.product.id, 3, self.agent)
        self.assertEqual(sale.montant_total, 300)
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 7)
        self.assertEqual(transactions.get_matricule_balance("CLIENT"), 9700)
        sales.cancel_sale(sale.id)
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 10)
        self.assertEqual(transactions.get_matricule_balance("CLIENT"), 10000)
        with self.assertRaises(sales.SaleError):
            sales.cancel_sale(sale.id)
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 10)

    def test_failed_sale_rolls_back_debit_and_stock(self):
        with patch.object(products, "_record_movement", side_effect=ValueError("Échec simulé")):
            with self.assertRaises(ValueError):
                sales.create_sale("CLIENT", self.product.id, 3, self.agent)
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 10)
        self.assertEqual(transactions.get_matricule_balance("CLIENT"), 10000)
        self.assertEqual(sales.count_sales(), 0)

    def test_fractional_amounts_and_stock_have_no_residual(self):
        p = products.create_product("Fraction", 0.1, quantite_initiale=0.3)
        products.adjust_stock(p.id, "sortie", 0.1)
        self.assertEqual(products.get_product(p.id).quantite_stock, 0.2)
        products.adjust_stock(p.id, "sortie", 0.2)
        self.assertEqual(products.get_product(p.id).quantite_stock, 0)
        for amount in (0.1, 0.2):
            transactions.create_transaction("DECIMAL", "", "depot", amount, self.agent)
        self.assertEqual(transactions.get_matricule_balance("DECIMAL"), 0.3)
        tx = transactions.create_transaction("DECIMAL", "", "retrait", 0.3, self.agent)
        self.assertEqual(tx.solde_apres, 0)
        self.assertEqual(transactions.get_matricule_balance("DECIMAL"), 0)
        self.assertEqual(transactions.get_global_balance(), 10000)

    def test_invalid_values_never_change_stock_or_balance(self):
        for value in (float("nan"), float("inf"), -1, 0):
            with self.subTest(value=value):
                with self.assertRaises(transactions.TransactionError):
                    transactions.create_transaction("CLIENT", "", "depot", value, self.agent)
                with self.assertRaises(products.ProductError):
                    products.adjust_stock(self.product.id, "entree", value)
                with self.assertRaises(sales.SaleError):
                    sales.create_sale("CLIENT", self.product.id, value, self.agent)
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 10)
        self.assertEqual(transactions.get_matricule_balance("CLIENT"), 10000)

    def test_used_deposit_cannot_be_deleted(self):
        deposit = transactions.search_transactions()[0]
        transactions.create_transaction("CLIENT", "", "retrait", 100, self.agent)
        with self.assertRaises(transactions.TransactionError):
            transactions.delete_transaction(deposit.id)
        self.assertEqual(transactions.get_matricule_balance("CLIENT"), 9900)

    def test_concurrent_withdrawals_cannot_spend_same_balance(self):
        barrier = threading.Barrier(2)
        def withdraw():
            try:
                barrier.wait(timeout=10)
                transactions.create_transaction("CLIENT", "", "retrait", 7000, self.agent)
                return "accepted"
            except transactions.TransactionError:
                return "refused"
            finally:
                db.close_connection()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: withdraw(), range(2)))
        self.assertCountEqual(results, ["accepted", "refused"])
        self.assertEqual(transactions.get_matricule_balance("CLIENT"), 3000)

    def test_concurrent_sales_cannot_spend_same_stock(self):
        barrier = threading.Barrier(2)
        def sell():
            try:
                barrier.wait(timeout=10)
                sales.create_sale("CLIENT", self.product.id, 7, self.agent)
                return "accepted"
            except sales.SaleError:
                return "refused"
            finally:
                db.close_connection()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: sell(), range(2)))
        self.assertCountEqual(results, ["accepted", "refused"])
        self.assertEqual(products.get_product(self.product.id).quantite_stock, 3)
        self.assertEqual(transactions.get_matricule_balance("CLIENT"), 9300)


if __name__ == "__main__":
    unittest.main()
