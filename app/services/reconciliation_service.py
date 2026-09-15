"""Diagnostic et réparation explicite ; aucune réécriture au démarrage."""
from __future__ import annotations
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from app.db import database
from app.utils.helpers import now_iso
from server.sync.reconciliation_engine import build_plan, plan_token, REPAIR_VERSION

TABLES = ('products', 'stock_movements', 'transactions', 'sales')
KEY = 'reconciliation_' + REPAIR_VERSION


def _plan(conn):
    data = {name: [dict(r) for r in conn.execute(f'SELECT * FROM {name} ORDER BY uuid')] for name in (*TABLES, 'audit_logs')}
    return build_plan(data['products'], data['stock_movements'], data['transactions'], data['sales'], data['audit_logs'])


def preview():
    return _plan(database.get_connection())


def apply_reconciliation(expected_token, report_dir=None):
    """Appelé seulement par l'action explicite Recalculer, après diagnostic."""
    with database.transaction() as conn:
        plan = _plan(conn)
        if plan_token(plan) != expected_token:
            raise ValueError('Les données ont changé. Actualisez le diagnostic avant de recalculer.')
        if not plan['changes']:
            return plan
        filename = conn.execute('PRAGMA database_list').fetchone()[2]
        if not filename:
            raise ValueError('La réparation nécessite une base persistante sauvegardable.')
        folder = Path(report_dir) if report_dir else Path(filename).parent / 'reconciliation'
        folder.mkdir(parents=True, exist_ok=True)
        tag = uuid4().hex
        backup = folder / ('avant_recalcul_' + tag + '.db')
        with closing(sqlite3.connect(Path(filename).resolve().as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('La sauvegarde avant recalcul est invalide.')
        plan['backup'] = str(backup)
        plan['created_at'] = now_iso()
        report_file = folder / ('rapport_recalcul_' + tag + '.json')
        plan['report_file'] = str(report_file)
        for change in plan['changes']:
            values = dict(change['after'], sync_status='pending')
            if change['table'] == 'products':
                values['updated_at'] = now_iso()
            names = ', '.join(name + '=?' for name in values)
            conn.execute(f"UPDATE {change['table']} SET {names} WHERE uuid=?", [*values.values(), change['uuid']])
        encoded = json.dumps(plan, ensure_ascii=False, allow_nan=False, indent=2)
        conn.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY, encoded))
        conn.execute("INSERT INTO audit_logs(uuid,action,target_type,target_id,details,created_at,sync_status) VALUES(?,?,?,?,?,?,'pending')",
            (str(uuid4()), 'DATA_RECONCILIATION', 'database', REPAIR_VERSION,
             f"{len(plan['changes'])} lignes corrigées ; {len(plan['issues'])} points à vérifier ; sauvegarde={backup.name}", now_iso()))
        temporary = report_file.with_suffix('.tmp')
        temporary.write_text(encoded, encoding='utf-8')
    temporary.replace(report_file)
    return plan
