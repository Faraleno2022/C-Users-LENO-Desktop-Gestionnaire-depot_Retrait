"""Réparation historique et journal de stock, sur la base de test Django."""
import tempfile
import uuid
from pathlib import Path
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from sync.models import Product, StockMovement, Sale, Transaction, RemoteUser, ReconciliationRun
from sync.reconciliation import preview, apply_reconciliation
from sync.reconciliation_engine import plan_token


class ReconciliationTests(TransactionTestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.remote=RemoteUser.objects.create(uuid=str(uuid.uuid4()),identifiant='repair-admin',nom_complet='Test',role='super_admin',created_at='2026-09-01 07:00:00',updated_at='2026-09-01 07:00:00')
        self.client.force_login(get_user_model().objects.create_user(username='repair-admin'))
        session=self.client.session;session['remote_user']={'uuid':self.remote.uuid,'role':'super_admin'};session.save()
        self.product=Product.objects.create(uuid=str(uuid.uuid4()),nom='CORNBEEF GARI',prix_unitaire=100,quantite_stock=7,created_at='2026-09-01 08:00:00',updated_at='2026-09-01 08:00:00')
        StockMovement.objects.create(uuid=str(uuid.uuid4()),product_id=self.product.pk,product_uuid=self.product.uuid,product_nom=self.product.nom,type='entree',quantite=10,stock_apres=10,motif='Stock initial',created_at='2026-09-01 08:00:00')
        Transaction.objects.create(uuid=str(uuid.uuid4()),matricule='A',type='depot',montant=1000,solde_apres=999,created_at='2026-09-01 09:00:00')
        for quantity,after in [(2,8),(3,7)]:
            sale=Sale.objects.create(uuid=str(uuid.uuid4()),matricule='A',product_id=self.product.pk,product_uuid=self.product.uuid,product_nom=self.product.nom,quantite=quantity,prix_unitaire=100,montant_total=quantity*100,solde_apres=999,created_at='2026-09-02 08:00:00')
            StockMovement.objects.create(uuid=str(uuid.uuid4()),product_id=self.product.pk,product_uuid=self.product.uuid,product_nom=self.product.nom,type='sortie',quantite=quantity,stock_apres=after,motif='Vente A',sale_id=sale.pk,created_at='2026-09-02 08:00:00')

    def test_preview_never_modifies_existing_data(self):
        plan=preview()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock,7)
        self.assertTrue(plan['changes'])
        self.assertEqual(ReconciliationRun.objects.count(),0)

    def test_apply_keeps_backup_and_is_idempotent(self):
        result=apply_reconciliation(plan_token(preview()),report_dir=self.folder.name)
        self.product.refresh_from_db();self.assertEqual(self.product.quantite_stock,5)
        run=ReconciliationRun.objects.get()
        self.assertEqual(run.snapshot['products'][0]['quantite_stock'],7)
        if connection.vendor=='sqlite' and 'backup' in result:self.assertTrue(Path(result['backup']).exists())
        self.assertEqual(preview()['changes'],[])
        self.assertEqual(apply_reconciliation(plan_token(preview()))['changes'],[])
        self.assertEqual(ReconciliationRun.objects.count(),1)

    def test_stale_diagnostic_is_rejected(self):
        token=plan_token(preview());self.product.quantite_stock=99;self.product.save()
        with self.assertRaises(ValueError):apply_reconciliation(token,report_dir=self.folder.name)
        self.assertEqual(ReconciliationRun.objects.count(),0)

    def test_stock_statement_has_opening_and_closing_for_filtered_day(self):
        response=self.client.get(reverse('web:stock_movements'),{'product_uuid':self.product.uuid,'date_from':'2026-09-02','date_to':'2026-09-02'})
        self.assertEqual(response.status_code,200)
        row=response.context['statement_rows'][0]
        self.assertEqual((row['opening'],row['entries'],row['exits'],row['closing']),(10,0,5,5))
        self.assertEqual(response.context['n_total'],2)
        self.assertEqual(response.context['statement_issues'],[])
        self.product.refresh_from_db();self.assertEqual(self.product.quantite_stock,7)

    def test_type_filter_never_changes_stock_balance(self):
        response=self.client.get(reverse('web:stock_movements'),{'product_uuid':self.product.uuid,'type':'entree'})
        self.assertEqual(response.context['n_total'],1)
        self.assertEqual(response.context['statement_rows'][0]['closing'],5)

    def test_exact_product_does_not_mix_similar_rows(self):
        other=Product.objects.create(uuid=str(uuid.uuid4()),nom='CORN FLAKS',prix_unitaire=10000,quantite_stock=426,stock_initial=426,stock_initial_source='creation',created_at='2026-09-01 08:00:00',updated_at='2026-09-01 08:00:00')
        response=self.client.get(reverse('web:stock_movements'),{'product_uuid':other.uuid})
        self.assertEqual(len(response.context['statement_rows']),1)
        self.assertEqual(response.context['statement_rows'][0]['closing'],426)
        self.assertEqual(response.context['n_total'],0)

    def test_invalid_date_is_explained(self):
        response=self.client.get(reverse('web:stock_movements'),{'date_from':'2026-99-15'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Date invalide')

    def test_archived_movements_stay_in_physical_journal(self):
        StockMovement.objects.all().update(deleted=True)
        response=self.client.get(reverse('web:stock_movements'),{'product_uuid':self.product.uuid})
        self.assertEqual(response.context['n_total'],3)
        self.assertEqual(response.context['statement_rows'][0]['closing'],5)
        self.assertContains(response,'Archivé')

    def test_unauthorized_role_cannot_apply(self):
        self.remote.role='caissier';self.remote.save()
        response=self.client.post(reverse('web:reconciliation'),{'plan_token':'plan_'+plan_token(preview())})
        self.assertEqual(response.status_code,403)
        self.product.refresh_from_db();self.assertEqual(self.product.quantite_stock,7)

    def test_report_get_is_read_only(self):
        response=self.client.get(reverse('web:reconciliation'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Sauvegarder et appliquer')
        self.assertEqual(ReconciliationRun.objects.count(),0)
        self.product.refresh_from_db();self.assertEqual(self.product.quantite_stock,7)

    def test_post_without_diagnostic_does_not_apply(self):
        response=self.client.post(reverse('web:reconciliation'),{})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Actualisez le diagnostic')
        self.assertEqual(ReconciliationRun.objects.count(),0)

    def test_inventory_records_physical_count_even_when_equal_to_cached_stock(self):
        response=self.client.post(reverse('web:inventory'),{f'count_{self.product.pk}':'7','motif':'Inventaire physique'})
        self.assertEqual(response.status_code,302)
        count=StockMovement.objects.exclude(stock_compte=None).get()
        self.assertEqual(count.stock_compte,7)
        self.assertEqual(count.quantite,0)
        plan=preview()
        self.assertEqual(plan['stocks'][0]['closing'],7)
