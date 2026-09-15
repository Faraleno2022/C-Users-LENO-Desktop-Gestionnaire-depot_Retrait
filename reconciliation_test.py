"""Reproductions de l'écart stock/journal, sur données synthétiques uniquement."""
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.db import database
from app.services.reconciliation_service import preview, apply_reconciliation
from server.sync.reconciliation_engine import build_plan, plan_token


def fixture():
    p = dict(id=1, uuid='p', nom='Article', quantite_stock=7, stock_initial=None,
             stock_initial_source='', created_at='2026-09-01 08:00:00')
    def movement(uuid, kind, q, after, date, **more):
        return dict(id=len(uuid), uuid=uuid, product_id=1, product_uuid='p', product_nom='Article',
                    type=kind, quantite=q, stock_apres=after, created_at=date, is_initial=False,
                    stock_compte=None, sale_id=None, motif='', deleted=False, **more)
    initial = movement('initial','entree',10,10,'2026-09-01 08:00:00');initial['motif']='Stock initial'
    a=movement('m-a','sortie',2,8,'2026-09-02 08:00:00');a.update(sale_id=1,motif='Vente A')
    b=movement('m-b','sortie',3,7,'2026-09-02 08:00:00');b.update(sale_id=2,motif='Vente A')
    sales=[dict(uuid=f's-{i}', id=i, product_id=1, product_uuid='p', product_nom='Article',
        matricule='A', quantite=q, prix_unitaire=100, montant_total=amount, solde_apres=balance,
        created_at='2026-09-02 08:00:00', deleted=False) for i,q,amount,balance in [(1,2,999,1),(2,3,300,2)]]
    tx=[dict(uuid='t', matricule='A', type='depot', montant=1000, solde_apres=1,
             created_at='2026-09-01 09:00:00', deleted=False)]
    return [[p],[initial,a,b],tx,sales]


def apply_fixture(data, plan):
    for change in plan['changes']:
        rows=data[('products','stock_movements','transactions','sales').index(change['table'])]
        next(r for r in rows if r['uuid']==change['uuid']).update(change['after'])


class EngineTests(unittest.TestCase):
    def test_duplicate_sale_lines_and_balances(self):
        data=fixture();plan=build_plan(*data)
        stock=plan['stocks'][0]
        self.assertEqual((stock['initial'],stock['entries'],stock['exits'],stock['closing']),(10,0,5,5))
        self.assertEqual(plan['balances'],[{'matricule':'A','balance':500}])
        apply_fixture(data,plan)
        self.assertEqual([s['montant_total'] for s in data[3]],[200,300])
        self.assertEqual([s['solde_apres'] for s in data[3]],[800,500])
        self.assertEqual(len(data[2]),1)
        self.assertEqual(data[0][0]['quantite_stock'],5)
        self.assertEqual(build_plan(*data)['changes'],[])

    def test_reported_numbers_require_initial_717(self):
        data=fixture();p=data[0][0];p['quantite_stock']=426
        initial,a,b=data[1];initial['quantite']=initial['stock_apres']=717
        a.update(type='entree',quantite=1920,stock_apres=2637,sale_id=None,motif='Réception')
        b.update(type='sortie',quantite=2211,stock_apres=426,sale_id=None,motif='Sortie')
        plan=build_plan(data[0],data[1],[],[])
        self.assertEqual(plan['stocks'][0]['closing'],426)
        self.assertEqual(plan['stocks'][0]['initial'],717)

    def test_never_invents_717_from_current_stock(self):
        data=fixture();data[0][0]['quantite_stock']=426
        data[1][0]['quantite']=data[1][0]['stock_apres']=10
        plan=build_plan(*data)
        self.assertEqual(plan['stocks'][0]['initial'],10)
        self.assertEqual(plan['stocks'][0]['closing'],5)

    def test_hidden_movements_keep_physical_effect(self):
        data=fixture()
        for m in data[1]:m['deleted']=True
        self.assertEqual(build_plan(*data)['stocks'][0]['closing'],5)

    def test_cancelled_sale_has_one_compensating_entry(self):
        data=fixture();data[3][0]['deleted']=True
        restore=dict(data[1][1],uuid='cancel',type='entree',quantite=2,stock_apres=9,
                     created_at='2026-09-03 08:00:00',motif='Annulation vente #1')
        data[1].append(restore)
        plan=build_plan(*data)
        self.assertEqual(plan['stocks'][0]['closing'],7)
        self.assertEqual(plan['balances'][0]['balance'],700)

    def test_missing_sale_movement_blocks_stock_correction(self):
        data=fixture();data[1].pop()
        plan=build_plan(*data)
        self.assertFalse(any(c['table']=='products' for c in plan['changes']))
        self.assertTrue(any('ne concordent pas' in i['reason'] for i in plan['issues']))

    def test_inventory_preserves_actual_count(self):
        data=fixture();data[1].append(dict(data[1][1],uuid='count',type='sortie',quantite=1,
            stock_apres=6,stock_compte=6,sale_id=None,created_at='2026-09-03 08:00:00',motif='Inventaire'))
        plan=build_plan(*data);apply_fixture(data,plan)
        self.assertEqual(data[0][0]['quantite_stock'],6)
        self.assertEqual((data[1][-1]['type'],data[1][-1]['quantite']),('entree',1))
        self.assertEqual(build_plan(*data)['changes'],[])

    def test_inventory_zero_adjustment_keeps_count(self):
        data=fixture();data[1].append(dict(data[1][1],uuid='count',type='sortie',quantite=2,
            stock_apres=5,stock_compte=5,sale_id=None,created_at='2026-09-03 08:00:00',motif='Inventaire'))
        plan=build_plan(*data);apply_fixture(data,plan)
        self.assertEqual(data[1][-1]['quantite'],0)
        self.assertEqual(build_plan(*data)['changes'],[])

    def test_legacy_inventory_requires_audit_evidence(self):
        data=fixture();data[1].append(dict(data[1][1],uuid='count',type='sortie',quantite=1,
            stock_apres=6,sale_id=None,created_at='2026-09-03 08:00:00',motif='Comptage'))
        logs=[{'action':'inventory_adjust','created_at':'2026-09-03 08:00:00','details':'motif=Comptage | Article: 7→6 (-1)'}]
        plan=build_plan(*data,logs);apply_fixture(data,plan)
        self.assertEqual(data[1][-1]['stock_compte'],6)
        self.assertEqual(data[0][0]['quantite_stock'],6)

    def test_legacy_standard_inventory_preserves_recorded_count(self):
        data=fixture();data[1].append(dict(data[1][1],uuid='count',type='sortie',quantite=1,
            stock_apres=6,sale_id=None,created_at='2026-09-03 08:00:00',motif='Inventaire physique'))
        plan=build_plan(*data);apply_fixture(data,plan)
        self.assertEqual(data[0][0]['quantite_stock'],6)
        self.assertEqual(data[1][-1]['stock_compte'],6)
        self.assertEqual(data[1][-1]['quantite'],1)
        self.assertEqual(data[1][-1]['type'],'entree')

    def test_unverified_custom_inventory_is_not_rewritten(self):
        data=fixture();data[1][0]['motif']='Comptage à vérifier'
        plan=build_plan(*data)
        self.assertEqual(plan['stocks'],[])
        self.assertFalse(any(c['table'] in ('products','stock_movements') for c in plan['changes']))

    def test_initial_inferred_from_first_chain_independent_of_ids(self):
        data=fixture();data[1]=data[1][1:];data[1][0]['uuid']='z';data[1][1]['uuid']='a'
        plan=build_plan(*data)
        self.assertEqual(plan['stocks'][0]['initial'],10)
        self.assertEqual(plan['stocks'][0]['closing'],5)

    def test_conflicting_opening_is_reported(self):
        data=fixture();data[1]=data[1][1:];data[1][1]['stock_apres']=50
        plan=build_plan(*data)
        self.assertEqual(plan['stocks'],[])

    def test_recalculation_is_not_clamped_to_zero(self):
        data=fixture();data[1][0]['quantite']=data[1][0]['stock_apres']=1
        plan=build_plan(*data)
        self.assertEqual(plan['stocks'][0]['closing'],-4)
        self.assertTrue(plan['issues'])

    def test_invalid_movement_leaves_product_unchanged(self):
        data=fixture();data[1][1]['quantite']=float('inf')
        plan=build_plan(*data)
        self.assertEqual(plan['stocks'],[])
        json.dumps(plan,allow_nan=False)


    def test_large_simultaneous_chain_avoids_quadratic_scans(self):
        from server.sync import reconciliation_engine as engine
        n = 1500
        rows = [dict(uuid=f'm-{n-i:04}', created_at='2026-09-01 08:00:00',
                     type='sortie', quantite=1, stock_apres=n-i-1) for i in range(n)]
        with patch.object(engine, '_delta', wraps=engine._delta) as delta:
            ordered = engine._ordered_moves(list(reversed(rows)))
        self.assertEqual(ordered, rows)
        self.assertLessEqual(delta.call_count, n * 2)

    def test_simultaneous_cycles_and_initial_priority_are_stable(self):
        from server.sync.reconciliation_engine import _ordered_moves
        def move(uuid, kind, q, after, **extra):
            return dict(uuid=uuid, type=kind, quantite=q, stock_apres=after,
                        created_at='2026-09-01 08:00:00', **extra)
        rows = [move('a', 'sortie', 1, 1), move('b', 'entree', 1, 2),
                move('z', 'entree', 10, 10, is_initial=True), move('c', 'sortie', 2, 8)]
        self.assertEqual([m['uuid'] for m in _ordered_moves(rows)], ['z', 'c', 'a', 'b'])


class DesktopRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'data.db'
        self.patcher=patch.object(database,'DB_PATH',self.path);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.dirs=patch.object(database,'ensure_directories',lambda:None);self.dirs.start();self.addCleanup(self.dirs.stop)
        database.close_connection();self.addCleanup(database.close_connection);database.init_database()
        conn=database.get_connection()
        data=fixture()
        for table,rows in zip(('products','stock_movements','transactions','sales'),data):
            columns={r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
            for row in rows:
                row=dict(row)
                if table=='stock_movements':row.pop('id',None)
                if table=='products':row.update(prix_unitaire=100,updated_at=row['created_at'])
                if table in ('stock_movements','transactions','sales'):row['agent_nom']='Test'
                row={k:v for k,v in row.items() if k in columns}
                conn.execute(f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' for _ in row)})",list(row.values()))
        conn.commit()

    def test_preview_is_read_only_and_apply_has_backup(self):
        plan=preview();conn=database.get_connection()
        self.assertEqual(conn.execute('SELECT quantite_stock FROM products').fetchone()[0],7)
        self.assertFalse((self.path.parent/'reconciliation').exists())
        result=apply_reconciliation(plan_token(plan))
        self.assertEqual(conn.execute('SELECT quantite_stock FROM products').fetchone()[0],5)
        with closing(sqlite3.connect(result['backup'])) as backup:
            self.assertEqual(backup.execute('SELECT quantite_stock FROM products').fetchone()[0],7)
        self.assertTrue(Path(result['report_file']).exists())
        self.assertEqual(preview()['changes'],[])

    def test_stale_plan_cannot_change_data(self):
        token=plan_token(preview());conn=database.get_connection()
        conn.execute('UPDATE products SET quantite_stock=20');conn.commit()
        with self.assertRaises(ValueError):apply_reconciliation(token)
        self.assertEqual(conn.execute('SELECT quantite_stock FROM products').fetchone()[0],20)

    def test_failure_rolls_back_all_updates(self):
        token=plan_token(preview());conn=database.get_connection()
        conn.execute("CREATE TRIGGER block_repair BEFORE UPDATE OF montant_total ON sales BEGIN SELECT RAISE(ABORT,'test failure'); END")
        conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):apply_reconciliation(token)
        self.assertEqual(conn.execute('SELECT quantite_stock FROM products').fetchone()[0],7)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM app_settings WHERE key LIKE 'reconciliation_%'").fetchone()[0],0)
