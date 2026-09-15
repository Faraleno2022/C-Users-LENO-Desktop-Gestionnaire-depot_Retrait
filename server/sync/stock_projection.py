"""Projection du journal reçu, sous le verrou des opérations métier.

Un total absolu d'un poste ne représente pas une nouvelle opération.
Les bases anciennes sans stock initial exigent le diagnostic explicite.
"""
from collections import defaultdict
from django.db.models import Q
from django.utils import timezone
from sync.models import Product, StockMovement
from sync.reconciliation_engine import _ordered_moves, decimal
from sync.reconciliation import _write_batch

MOVEMENT_FACTS = ('product_id', 'product_uuid', 'type', 'quantite', 'stock_apres',
                  'is_initial', 'stock_compte', 'created_at')


def protect_projection(table, obj, values):
    """Un renvoi ne doit pas annuler un recalcul central déjà appliqué."""
    protected = ()
    if table == 'products' and obj.stock_initial is not None:
        protected = ('quantite_stock', 'stock_initial', 'stock_initial_source')
    elif table == 'stock_movements':
        # Annulation/restauration : mouvement compensateur distinct.
        # L'archivage reste synchronisé sans effacer l'effet physique.
        protected = MOVEMENT_FACTS
    different = any(k in values and values[k] != getattr(obj, k) for k in protected)
    for key in protected:
        values.pop(key, None)
    return different


def refresh_stock(product_uuids):
    """Rejoue les produits touchés, mouvements archivés compris.

    Les quantités ordinaires restent intactes. Un comptage explicite ancre
    l'inventaire même si des opérations antérieures arrivent en retard.
    Aucun montant de vente ni solde de compte n'est modifié ici.
    """
    products = list(Product.objects.filter(uuid__in=product_uuids))
    if set(product_uuids) - {p.uuid for p in products}:
        raise ValueError('Produit absent : synchronisez le catalogue avant ses mouvements.')
    products = [p for p in products if p.stock_initial is not None]
    if not products:
        return
    by_uuid = {p.uuid: p for p in products}
    by_id = {p.id: p for p in products}
    grouped = defaultdict(list)
    rows = StockMovement.objects.filter(
        Q(product_uuid__in=by_uuid) | Q(product_uuid='', product_id__in=by_id)
    ).values('id', 'uuid', 'product_uuid', 'product_id', 'quantite', 'type',
             'stock_apres', 'stock_compte', 'is_initial', 'created_at', 'motif')
    for row in rows:
        product = by_uuid.get(row['product_uuid']) if row['product_uuid'] else by_id.get(row['product_id'])
        grouped[product.uuid].append(row)
    now = timezone.now()
    batch = []
    fields = ('quantite', 'type', 'stock_apres', 'received_at')
    for product in products:
        running = decimal(product.stock_initial)
        initial_seen = False
        for row in _ordered_moves(grouped[product.uuid]):
            quantity, kind = decimal(row['quantite']), row['type']
            if row['is_initial']:
                if initial_seen or quantity != decimal(product.stock_initial):
                    raise ValueError('Mouvement initial incohérent : vérifiez le diagnostic de stock.')
                initial_seen = True
            else:
                if row['stock_compte'] is not None:
                    delta = decimal(row['stock_compte']) - running
                    quantity, kind = abs(delta), 'entree' if delta >= 0 else 'sortie'
                else:
                    delta = quantity if kind == 'entree' else -quantity
                running += delta
            after = float(decimal(running))
            if (float(quantity), kind, after) != (row['quantite'], row['type'], row['stock_apres']):
                batch.append((row['id'], dict(quantite=float(quantity), type=kind,
                                              stock_apres=after, received_at=now)))
                if len(batch) == 150:
                    _write_batch('stock_movements', fields, batch)
                    batch.clear()
        if product.quantite_stock != float(running):
            product.quantite_stock = float(running)
            product.updated_at = now.strftime('%Y-%m-%d %H:%M:%S')
            product.save(update_fields=['quantite_stock', 'updated_at', 'received_at'])
    if batch:
        _write_batch('stock_movements', fields, batch)
