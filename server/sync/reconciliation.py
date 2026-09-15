"""Diagnostic en lecture seule et application explicite d'un plan vérifié."""
from __future__ import annotations
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from django.db import connection, transaction
from django.utils import timezone
from sync.models import Product, StockMovement, Transaction, Sale, AuditLog, ReconciliationRun
from sync.reconciliation_engine import build_plan, plan_token, safe_value, REPAIR_VERSION
from web.operations import operation_transaction

MODELS = {'products': Product, 'stock_movements': StockMovement, 'transactions': Transaction, 'sales': Sale}


def snapshot_data():
    data = {name: list(model.objects.order_by('uuid').values()) for name, model in MODELS.items()}
    data['audit_logs'] = list(AuditLog.objects.order_by('uuid').values())
    return json.loads(json.dumps(safe_value(data), default=str, allow_nan=False))


def _build(data):
    return build_plan(data['products'], data['stock_movements'], data['transactions'], data['sales'], data['audit_logs'])


def preview():
    with transaction.atomic():
        return _build(snapshot_data())


def apply_reconciliation(expected_token, report_dir=None):
    """Aucune utilisation implicite au démarrage, au déploiement ou au pull."""
    with operation_transaction():
        data = snapshot_data()
        plan = _build(data)
        if plan_token(plan) != expected_token:
            raise ValueError('Les données ont changé. Actualisez le diagnostic avant de recalculer.')
        if not plan['changes']:
            return plan
        now = timezone.now()
        version = REPAIR_VERSION + '-' + uuid4().hex[:8]
        plan['created_at'] = now.isoformat()
        plan['run'] = version
        if connection.vendor == 'sqlite':
            filename = str(connection.settings_dict['NAME'])
            if filename and filename != ':memory:' and not filename.startswith('file:memory'):
                folder = Path(report_dir or os.environ.get('EMAB_DATA_DIR') or Path(filename).parent) / 'reconciliation'
                folder.mkdir(parents=True, exist_ok=True)
                backup = folder / ('avant_recalcul_' + uuid4().hex + '.db')
                with closing(sqlite3.connect(Path(filename).resolve().as_uri() + '?mode=ro', uri=True)) as source:
                    with closing(sqlite3.connect(backup)) as target:
                        source.backup(target)
                        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                            raise RuntimeError('Sauvegarde SQLite avant recalcul invalide.')
                plan['backup'] = str(backup)
        # Sauvegarde métier persistante en base, également sur PostgreSQL.
        run = ReconciliationRun.objects.create(version=version, report=plan, snapshot=data)
        for change in plan['changes']:
            values = dict(change['after'], received_at=now)
            if change['table'] == 'products':
                values['updated_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
            MODELS[change['table']].objects.filter(uuid=change['uuid']).update(**values)
        AuditLog.objects.create(uuid=str(uuid4()), action='DATA_RECONCILIATION', target_type='database',
            target_id=str(run.pk), details=f"{len(plan['changes'])} lignes corrigées ; {len(plan['issues'])} points à vérifier ; rapport={version}",
            created_at=now.strftime('%Y-%m-%d %H:%M:%S'))
        return plan
