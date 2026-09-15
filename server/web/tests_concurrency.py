"""Concurrence réelle : utiliser une base de test SQLite fichier ou PostgreSQL."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import close_old_connections, connection
from django.test import RequestFactory, TransactionTestCase

from sync.models import Product, Sale, StockMovement, Transaction
from web.views import _matricule_balance, withdrawal_new


class ConcurrentAccountingTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor == "sqlite" and ("memory" in str(connection.settings_dict["NAME"])):
            self.skipTest("Utiliser une base de test SQLite fichier pour le verrouillage interconnexions.")
        self.product = Product.objects.create(
            uuid=str(uuid.uuid4()), nom="Ciment", prix_unitaire=100,
            quantite_stock=10, created_at="now", updated_at="now",
        )
        Transaction.objects.create(
            uuid=str(uuid.uuid4()), matricule="CLIENT", type="depot",
            montant=10000, solde_apres=10000, created_at="now",
        )

    def concurrent_withdrawals(self, product=False):
        barrier = threading.Barrier(2)
        def operation():
            close_old_connections()
            try:
                payload = {"matricule": "CLIENT", "confirmed": "1", "montant": "7000"}
                if product:
                    payload.update(prod_id=[str(self.product.pk)], prod_qte=["7"])
                request = RequestFactory().post("/transactions/retrait/", payload)
                request.user = SimpleNamespace(is_authenticated=True, username="test", first_name="Test")
                request.session = {"remote_user": {"role": "admin"}}
                request._messages = FallbackStorage(request)
                barrier.wait(timeout=10)
                return withdrawal_new(request).status_code
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: operation(), range(2)))
        self.assertCountEqual(results, [302, 200])

    def test_concurrent_cash_withdrawals(self):
        self.concurrent_withdrawals()
        self.assertEqual(_matricule_balance("CLIENT"), 3000)
        self.assertEqual(Transaction.objects.filter(type="retrait").count(), 1)

    def test_concurrent_product_withdrawals(self):
        self.concurrent_withdrawals(product=True)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 3)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(_matricule_balance("CLIENT"), 9300)
