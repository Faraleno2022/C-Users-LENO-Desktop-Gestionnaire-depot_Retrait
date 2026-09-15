"""Régressions : postes obsolètes, renvois et inventaires reçus en retard."""
import json
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from sync.models import Device, Product, StockMovement
from sync.replicator import Replicator, TABLE_ORDER


class StockProjectionTests(TestCase):
    def setUp(self):
        device = Device.objects.create(name='Poste test')
        self.auth = {'HTTP_AUTHORIZATION': f'Device {device.token}'}
        self.product = Product.objects.create(uuid='p', nom='Produit test', stock_initial=10,
            stock_initial_source='creation', quantite_stock=8, created_at='2026-09-01 08:00:00')
        StockMovement.objects.create(uuid='before', product_uuid='p', product_id=self.product.id,
            product_nom='Ancien nom', type='sortie', quantite=2, stock_apres=8,
            created_at='2026-09-01 09:00:00')

    def push(self, table, records, code=200):
        response = self.client.post(reverse('sync-push'),
            json.dumps({'table': table, 'records': records}), content_type='application/json', **self.auth)
        self.assertEqual(response.status_code, code, response.content)
        return response

    def move(self, uuid='sale', **values):
        return dict(uuid=uuid, product_uuid='p', product_id=999, product_nom='Produit test',
                    type='sortie', quantite=3, stock_apres=97, created_at='2026-09-01 10:00:00', **values)

    def test_stale_post_cannot_replace_repaired_stock_or_opening(self):
        self.push('products', [dict(uuid='p', quantite_stock=97, stock_initial=100,
                                    stock_initial_source='old', updated_at='2026-09-15 15:00:00')])
        self.product.refresh_from_db()
        self.assertEqual((self.product.stock_initial, self.product.quantite_stock), (10, 8))
        self.push('stock_movements', [self.move()])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 5)
        self.assertEqual(StockMovement.objects.get(uuid='sale').stock_apres, 5)

    def test_retries_and_old_movement_echo_do_not_deduct_again(self):
        self.push('stock_movements', [self.move()])
        self.push('stock_movements', [self.move()])
        old = dict(self.move(), uuid='before', quantite=9, stock_apres=91, deleted=True)
        self.push('stock_movements', [old])
        self.product.refresh_from_db()
        before = StockMovement.objects.get(uuid='before')
        self.assertEqual((self.product.quantite_stock, before.quantite, before.stock_apres), (5, 2, 8))
        self.assertTrue(before.deleted)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_late_sale_before_confirmed_inventory_preserves_count(self):
        counted = dict(self.move(), uuid='count', quantite=1, stock_compte=7, stock_apres=7,
                       created_at='2026-09-01 11:00:00')
        self.push('stock_movements', [counted])
        self.push('stock_movements', [self.move()])
        self.product.refresh_from_db()
        inventory = StockMovement.objects.get(uuid='count')
        self.assertEqual(self.product.quantite_stock, 7)
        self.assertEqual((inventory.type, inventory.quantite, inventory.stock_compte), ('entree', 2, 7))
        # L'ancien delta de cet inventaire ne peut pas revenir d'un autre poste.
        self.push('stock_movements', [counted])
        inventory.refresh_from_db()
        self.assertEqual((inventory.type, inventory.quantite), ('entree', 2))

    def test_late_sale_updates_later_running_balances(self):
        later = dict(self.move(), uuid='later', quantite=1, created_at='2026-09-01 11:00:00')
        self.push('stock_movements', [later])
        self.push('stock_movements', [self.move()])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 4)
        self.assertEqual(StockMovement.objects.get(uuid='later').stock_apres, 4)

    def test_new_product_import_does_not_double_count_initial(self):
        self.push('products', [dict(uuid='new', nom='Nouveau', stock_initial=100,
                                    stock_initial_source='creation', quantite_stock=90)])
        initial = dict(self.move(), uuid='initial', product_uuid='new', type='entree', quantite=100,
                       stock_apres=100, is_initial=True, created_at='2026-09-01 08:00:00')
        sale = dict(self.move(), uuid='new-sale', product_uuid='new', quantite=10)
        self.push('stock_movements', [sale, initial])
        self.assertEqual(Product.objects.get(uuid='new').quantite_stock, 90)

    def test_product_projection_counts_archived_moves(self):
        StockMovement.objects.filter(uuid='before').update(deleted=True)
        self.push('products', [dict(uuid='p', quantite_stock=10)])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 8)

    def test_legacy_opening_is_not_guessed_from_partial_import(self):
        self.product.stock_initial = None
        self.product.save()
        self.push('stock_movements', [self.move()])
        self.product.refresh_from_db()
        self.assertIsNone(self.product.stock_initial)
        self.assertEqual(self.product.quantite_stock, 8)

    def test_unknown_product_does_not_create_an_orphan_movement(self):
        self.push('stock_movements', [dict(self.move(), product_uuid='missing')], 400)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_invalid_batch_rolls_back_movements_and_stock(self):
        self.push('stock_movements', [self.move(), dict(self.move(), uuid='bad', quantite=-1)], 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 8)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_rejected_absolute_stock_is_returned_after_cursor(self):
        cursor = self.product.received_at.isoformat()
        self.push('products', [dict(uuid='p', quantite_stock=99)])
        body = self.client.get(reverse('sync-pull'), {'table':'products', 'since':cursor}, **self.auth).json()
        self.assertEqual(body['records'][0]['quantite_stock'], 8)

    def test_console_sends_all_operations_before_pulling_totals(self):
        events = []
        rep = Replicator('https://example.test', 'test', '/unused/state.json')
        with patch.object(rep, '_push_table', side_effect=lambda t: events.append(('push', t)) or 1), \
             patch.object(rep, '_pull_table', side_effect=lambda t: events.append(('pull', t)) or (0, 1)):
            rep.run_once()
        self.assertEqual(events, [('push', t) for t in TABLE_ORDER] + [('pull', t) for t in TABLE_ORDER])
