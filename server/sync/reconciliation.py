"""Diagnostic en lecture seule et application explicite d'un plan vérifié."""
from __future__ import annotations
import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from itertools import islice
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from django.db import connection, transaction
from django.utils import timezone
from sync.models import Product, StockMovement, Transaction, Sale, AuditLog, ReconciliationRun, ReconciliationSnapshotChunk
from sync.reconciliation_engine import build_plan, plan_token, safe_value, REPAIR_VERSION
from web.operations import operation_transaction

MODELS = {'products': Product, 'stock_movements': StockMovement, 'transactions': Transaction, 'sales': Sale}


# Le diagnostic ne charge ni notes, coordonnées, agents, ni audits sans inventaire.
PLAN_FIELDS = {
    'products': ('id', 'uuid', 'nom', 'quantite_stock', 'stock_initial', 'stock_initial_source', 'created_at'),
    'stock_movements': ('id', 'uuid', 'product_id', 'product_uuid', 'product_nom', 'type', 'quantite',
                       'stock_apres', 'is_initial', 'stock_compte', 'motif', 'sale_id', 'created_at', 'deleted'),
    'transactions': ('id', 'uuid', 'matricule', 'type', 'montant', 'solde_apres', 'created_at', 'deleted'),
    'sales': ('id', 'uuid', 'matricule', 'product_id', 'product_uuid', 'product_nom', 'quantite',
              'prix_unitaire', 'montant_total', 'solde_apres', 'created_at', 'deleted'),
}


def diagnostic_data():
    data = {name: list(model.objects.order_by('uuid').values(*PLAN_FIELDS[name]).iterator(chunk_size=1000))
            for name, model in MODELS.items()}
    data['audit_logs'] = list(AuditLog.objects.filter(action='inventory_adjust').order_by('uuid')
                             .values('uuid', 'action', 'details', 'created_at').iterator(chunk_size=1000))
    return data


def snapshot_data():
    # Sauvegarde complète uniquement lors de l'application ; pas de copie JSON
    # intermédiaire de l'intégralité de la base en mémoire.
    return {name: [{key: str(value) if isinstance(value, (date, datetime)) else safe_value(value)
                    for key, value in row.items()}
                   for row in model.objects.order_by('uuid').values().iterator(chunk_size=1000)]
            for name, model in {**MODELS, 'audit_logs': AuditLog}.items()}


def _write_batch(table, fields, batch):
    model = MODELS[table]
    if connection.vendor not in ('sqlite', 'postgresql') or (connection.vendor == 'sqlite' and sqlite3.sqlite_version_info < (3, 33)):
        return model.objects.bulk_update([model(id=pk, **values) for pk, values in batch], fields, batch_size=200)
    quote = connection.ops.quote_name
    columns = [model._meta.pk, *(model._meta.get_field(name) for name in fields)]
    names = [quote(field.column) for field in columns]
    params = []
    for pk, values in batch:
        params.extend(field.get_db_prep_save(value, connection) for field, value in
                      zip(columns, [pk, *(values[name] for name in fields)]))
    row_sql = '(' + ', '.join(['%s'] * len(columns)) + ')'
    table_sql = quote(model._meta.db_table)
    rows_sql = quote('repair_rows')
    assignments = ', '.join(f'{name} = {rows_sql}.{name}' for name in names[1:])
    sql = (f'WITH {rows_sql} ({", ".join(names)}) AS (VALUES {", ".join([row_sql] * len(batch))}) '
           f'UPDATE {table_sql} SET {assignments} FROM {rows_sql} '
           f'WHERE {table_sql}.{names[0]} = {rows_sql}.{names[0]}')
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        if connection.vendor == 'sqlite':
            cursor.execute('SELECT changes()')
            return cursor.fetchone()[0]
        return cursor.rowcount


def _apply_changes(plan, ids, now):
    """Fusionne les corrections d'une même ligne, puis écrit par lots bornés."""
    merged = defaultdict(dict)
    for change in plan['changes']:
        merged[(change['table'], change['uuid'])].update(change['after'])
    groups = defaultdict(list)
    for (table, uuid), values in merged.items():
        values['received_at'] = now
        if table == 'products':
            values['updated_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
        groups[(table, tuple(sorted(values)))].append((ids[table][uuid], values))
    for (table, fields), rows in groups.items():
        # Respecter aussi la limite de paramètres des anciennes versions SQLite.
        limit = connection.features.max_query_params
        size = min(200, limit // (len(fields) + 1)) if limit else 200
        iterator = iter(rows)
        while batch := list(islice(iterator, size)):
            if _write_batch(table, fields, batch) != len(batch):
                raise RuntimeError('Une ligne a changé pendant le recalcul ; aucune correction appliquée.')


def _save_snapshot_chunks(run):
    counts = {}
    for name, model in {**MODELS, 'audit_logs': AuditLog}.items():
        rows = model.objects.order_by('uuid').values().iterator(chunk_size=500)
        count = sequence = 0
        while batch := list(islice(rows, 500)):
            payload = [{key: str(value) if isinstance(value, (date, datetime)) else safe_value(value)
                        for key, value in row.items()} for row in batch]
            ReconciliationSnapshotChunk.objects.create(run=run, table_name=name, sequence=sequence, rows=payload)
            sequence += 1
            count += len(batch)
        counts[name] = count
    run.snapshot = {'format': 'chunks-v1', 'counts': counts}
    run.save(update_fields=['snapshot'])


def iter_snapshot_rows(run, table):
    """Lecture progressive ; reste compatible avec les anciens instantanés JSON."""
    models = {**MODELS, 'audit_logs': AuditLog}
    if table not in models:
        raise ValueError('Table de sauvegarde inconnue.')
    snapshot = run.snapshot
    if snapshot.get('format') == 'sqlite-backup-v1':
        filename = Path(snapshot['path']).resolve()
        with closing(sqlite3.connect(filename.as_uri() + '?mode=ro', uri=True)) as backup:
            backup.row_factory = sqlite3.Row
            for row in backup.execute('SELECT * FROM ' + models[table]._meta.db_table + ' ORDER BY uuid'):
                yield dict(row)
    elif snapshot.get('format') == 'chunks-v1':
        for rows in run.snapshot_chunks.filter(table_name=table).order_by('sequence').values_list('rows', flat=True).iterator(chunk_size=1):
            yield from rows
    else:
        yield from snapshot.get(table, [])


def _build(data):
    return build_plan(data['products'], data['stock_movements'], data['transactions'], data['sales'], data['audit_logs'])


def preview():
    with transaction.atomic():
        return _build(diagnostic_data())


def apply_reconciliation(expected_token, report_dir=None):
    """Aucune utilisation implicite au démarrage, au déploiement ou au pull."""
    with operation_transaction():
        data = diagnostic_data()
        plan = _build(data)
        if plan_token(plan) != expected_token:
            raise ValueError('Les données ont changé. Actualisez le diagnostic avant de recalculer.')
        if not plan['changes']:
            return plan
        ids = {name: {row['uuid']: row['id'] for row in rows} for name, rows in data.items() if name in MODELS}
        del data
        now = timezone.now()
        version = REPAIR_VERSION + '-' + uuid4().hex[:8]
        plan['created_at'] = now.isoformat()
        plan['run'] = version
        snapshot = None
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
                snapshot = {'format': 'sqlite-backup-v1', 'path': str(backup)}
        run = ReconciliationRun.objects.create(version=version, report=plan, snapshot=snapshot or {})
        if snapshot is None:
            _save_snapshot_chunks(run)
        _apply_changes(plan, ids, now)
        AuditLog.objects.create(uuid=str(uuid4()), action='DATA_RECONCILIATION', target_type='database',
            target_id=str(run.pk), details=f"{len(plan['changes'])} lignes corrigées ; {len(plan['issues'])} points à vérifier ; rapport={version}",
            created_at=now.strftime('%Y-%m-%d %H:%M:%S'))
        return plan
