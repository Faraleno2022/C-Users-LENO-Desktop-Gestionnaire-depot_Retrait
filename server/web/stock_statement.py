"""Même formule pour l'état du stock et son journal, par produit et période."""
from decimal import Decimal
from sync.models import Product, StockMovement, Sale, AuditLog
from sync.reconciliation_engine import build_plan, decimal


def statement(products, date_from='', date_to=''):
    products = [dict(p) for p in products]
    uuids = {p['uuid'] for p in products}
    ids = {p['id'] for p in products}
    moves = [m for m in StockMovement.objects.order_by('created_at', 'uuid').values()
             if m['product_uuid'] in uuids or (not m['product_uuid'] and m['product_id'] in ids)]
    sales = [s for s in Sale.objects.order_by('uuid').values()
             if s['product_uuid'] in uuids or (not s['product_uuid'] and s['product_id'] in ids)]
    logs = list(AuditLog.objects.filter(action='inventory_adjust').values())
    plan = build_plan(products, moves, [], sales, logs)
    stock_map = {row['uuid']: row for row in plan['stocks']}
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
        for movement in moves:
            if movement.get('product_uuid') != product['uuid'] and not (
                    not movement.get('product_uuid') and movement['product_id'] == product['id']):
                continue
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
    return rows, [i for i in plan['issues'] if i['table'] in ('products', 'stock_movements')]
