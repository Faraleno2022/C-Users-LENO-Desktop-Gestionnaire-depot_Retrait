"""Réparation historique et journal de stock, sur la base de test Django."""
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from django.test.utils import CaptureQueriesContext
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from sync.models import Product, StockMovement, Sale, Transaction, RemoteUser, ReconciliationRun
from sync.reconciliation import preview, apply_reconciliation, iter_snapshot_rows
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
        self.assertEqual(next(iter_snapshot_rows(run, 'products'))['quantite_stock'],7)
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
        with patch.dict('os.environ', {'RENDER_GIT_COMMIT': 'a' * 40}):
            response=self.client.get(reverse('web:reconciliation'))
        self.assertEqual(response.headers['X-EMAB-Revision'], 'a' * 40)
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

    def test_preview_loads_only_calculation_fields_and_inventory_audits(self):
        from sync.reconciliation import diagnostic_data, snapshot_data, _build
        from sync.models import AuditLog
        AuditLog.objects.create(uuid=str(uuid.uuid4()), action='unrelated', details='x' * 10000, created_at='2026-09-01 08:00:00')
        AuditLog.objects.create(uuid=str(uuid.uuid4()), action='inventory_adjust', details='motif=Comptage', created_at='2026-09-01 08:00:00')
        data = diagnostic_data()
        self.assertNotIn('telephone', data['transactions'][0])
        self.assertNotIn('agent_nom', data['sales'][0])
        self.assertEqual(len(data['audit_logs']), 1)
        self.assertEqual(_build(data), _build(snapshot_data()))

    def test_report_page_does_not_load_previous_backup_or_report(self):
        ReconciliationRun.objects.create(version='previous', report={'changes': ['x'] * 5000}, snapshot={'large': 'x' * 10000})
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('web:reconciliation'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dernier recalcul')
        previous_queries = [q['sql'] for q in queries if 'sync_reconciliationrun' in q['sql']]
        self.assertTrue(previous_queries)
        for query in previous_queries:
            self.assertNotIn('"snapshot"', query)
            self.assertNotIn('"report"', query)

    def test_apply_batches_large_account_history_and_keeps_complete_snapshot(self):
        Transaction.objects.bulk_create([Transaction(uuid=str(uuid.uuid4()), matricule='B', type='depot', montant=1,
            solde_apres=-1, telephone='test-preserved', created_at='2026-09-01 10:00:00') for _ in range(600)])
        token = plan_token(preview())
        with CaptureQueriesContext(connection) as queries:
            result = apply_reconciliation(token, report_dir=self.folder.name)
        updates = [q['sql'] for q in queries if 'UPDATE "sync_transaction"' in q['sql']]
        self.assertLessEqual(len(updates), 8)
        self.assertEqual(sorted(Transaction.objects.filter(matricule='B').values_list('solde_apres', flat=True)), list(range(1, 601)))
        run = ReconciliationRun.objects.get()
        self.assertEqual(sum(row.get('telephone') == 'test-preserved' for row in iter_snapshot_rows(run, 'transactions')), 600)
        self.assertEqual(preview()['changes'], [])
        self.assertTrue(result['changes'])

    def test_apply_merges_sale_amount_and_balance_corrections(self):
        Sale.objects.filter(quantite=2).update(uuid='sale-a', montant_total=1)
        Sale.objects.filter(quantite=3).update(uuid='sale-b', montant_total=1)
        apply_reconciliation(plan_token(preview()), report_dir=self.folder.name)
        self.assertEqual(sum(Sale.objects.values_list('montant_total', flat=True)), 500)
        self.assertEqual(max(Sale.objects.values_list('solde_apres', flat=True)), 800)
        self.assertEqual(preview()['changes'], [])

    def test_bulk_failure_rolls_back_backup_and_all_changes(self):
        token = plan_token(preview())
        from sync import reconciliation
        original = reconciliation._write_batch
        def fail_after_write(table, *args):
            result = original(table, *args)
            if table == 'transactions':
                raise RuntimeError('test failure')
            return result
        with patch.object(reconciliation, '_write_batch', side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                apply_reconciliation(token, report_dir=self.folder.name)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 7)
        self.assertEqual(Transaction.objects.get().solde_apres, 999)
        self.assertEqual(ReconciliationRun.objects.count(), 0)

    def test_chunk_snapshot_preserves_all_fields_and_rolls_back_on_failure(self):
        from sync.reconciliation import _save_snapshot_chunks
        from sync.models import ReconciliationSnapshotChunk
        from django.db import transaction
        Transaction.objects.bulk_create([Transaction(uuid=str(uuid.uuid4()), matricule='C', type='depot', montant=1, solde_apres=1, created_at='2026-09-01 10:00:00') for _ in range(600)])
        run = ReconciliationRun.objects.create(version='chunk-test')
        _save_snapshot_chunks(run)
        self.assertEqual(run.snapshot['format'], 'chunks-v1')
        self.assertEqual(run.snapshot['counts']['transactions'], 601)
        self.assertEqual(run.snapshot_chunks.filter(table_name='transactions').count(), 2)
        self.assertEqual(sum(1 for _ in iter_snapshot_rows(run, 'transactions')), 601)
        self.assertEqual(next(iter_snapshot_rows(run, 'products'))['quantite_stock'], 7)
        self.assertIn('telephone', next(iter_snapshot_rows(run, 'transactions')))
        self.assertTrue(ReconciliationSnapshotChunk.objects.filter(run=run).exists())
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                failed = ReconciliationRun.objects.create(version='rolled-back-chunks')
                _save_snapshot_chunks(failed)
                raise RuntimeError('test rollback')
        self.assertFalse(ReconciliationRun.objects.filter(version='rolled-back-chunks').exists())

    def test_old_json_snapshot_can_still_be_read(self):
        run = ReconciliationRun.objects.create(version='legacy-json', snapshot={'products': [{'quantite_stock': 7}]})
        self.assertEqual(list(iter_snapshot_rows(run, 'products')), [{'quantite_stock': 7}])
