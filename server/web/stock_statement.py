"""Même formule pour l'état du stock et son journal, par produit et période."""
from decimal import Decimal
from collections import defaultdict
from django.db.models import Q
from sync.models import Product, StockMovement, Sale, AuditLog
from sync.reconciliation_engine import build_plan, decimal


def statement(products, date_from='', date_to=''):
    products = [dict(p) for p in products]
    uuids = {p['uuid'] for p in products}
    ids = {p['id'] for p in products}
    moves = list(StockMovement.objects.filter(
        Q(product_uuid__in=uuids) | Q(product_uuid='', product_id__in=ids)
    ).order_by('created_at', 'uuid').values())
    grouped = defaultdict(list)
    id_to_uuid = {p['id']: p['uuid'] for p in products}
    for move in moves:
        grouped[move['product_uuid'] or id_to_uuid.get(move['product_id'])].append(move)
    # Un stock initial déjà établi ne doit plus dépendre des totaux historiques
    # envoyés par un poste, ni du moment où arrive sa table des ventes.
    known = [p for p in products if p.get('stock_initial') is not None]
    legacy = [p for p in products if p.get('stock_initial') is None]
    stock_map = {p['uuid']: {'initial': p['stock_initial'],
        'source': p.get('stock_initial_source') or 'creation',
        'initial_movements': [m['uuid'] for m in grouped[p['uuid']] if m['is_initial']]}
        for p in known}
    issues = []
    if legacy:
        legacy_uuids = {p['uuid'] for p in legacy}
        legacy_ids = {p['id'] for p in legacy}
        sales = list(Sale.objects.filter(Q(product_uuid__in=legacy_uuids) |
                     Q(product_uuid='', product_id__in=legacy_ids)).values())
        logs = list(AuditLog.objects.filter(action='inventory_adjust').values())
        plan = build_plan(legacy, [m for key in legacy_uuids for m in grouped[key]], [], sales, logs)
        stock_map.update({row['uuid']: row for row in plan['stocks']})
        issues = plan['issues']
    rows = []
    for product in products:
        item = stock_map.get(product['uuid'])
        if not item:
            rows.append({'uuid': product['uuid'], 'nom': product['nom'], 'known': False,
                         'recorded': product['quantite_stock']})
            continue
        initial = decimal(item['initial'])
        created = str(product.get('created_at') or '')[:10]
        opening, entries, exits = initial, Decimal(0), Decimal(0)
        ledger_closing = initial
        if date_from and created >= date_from:
            opening = Decimal(0)
            if not date_to or created <= date_to:
                entries += initial
        if date_to and created > date_to:
            opening = Decimal(0)
        for movement in grouped[product['uuid']]:
            if movement['uuid'] in item['initial_movements']:
                continue
            current = movement
            day = str(current['created_at'])[:10]
            delta = decimal(current['quantite']) * (1 if current['type'] == 'entree' else -1)
            ledger_closing += delta
            if date_to and day > date_to:
                continue
            if date_from and day < date_from:
                opening += delta
            else:
                entries += max(delta, Decimal(0))
                exits += max(-delta, Decimal(0))
        closing = opening + entries - exits
        try:
            difference = float(decimal(product['quantite_stock']) - ledger_closing)
        except ValueError:
            difference = None
        rows.append({'uuid': product['uuid'], 'nom': product['nom'], 'known': True,
            'opening': float(opening), 'entries': float(entries), 'exits': float(exits),
            'closing': float(closing), 'recorded': product['quantite_stock'],
            'difference': difference,
            'source': item['source']})
    return rows, [i for i in issues if i['table'] in ('products', 'stock_movements')]
