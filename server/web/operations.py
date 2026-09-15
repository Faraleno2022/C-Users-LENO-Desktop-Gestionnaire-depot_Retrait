"""Transactions métier indivisibles, sérialisées avant lecture des soldes.

La ligne verrou est locale à chaque base. Elle protège aussi SQLite, dont
select_for_update() est sans effet, et les comptes sans aucun dépôt préalable.
"""
from contextlib import contextmanager

from django.db import transaction
from django.db.models import F

from sync.models import OperationLock


@contextmanager
def operation_transaction():
    with transaction.atomic():
        # UPDATE prend un verrou d'écriture, même si la valeur est inchangée.
        if not OperationLock.objects.filter(pk=1).update(id=F("id")):
            # Réinitialisation de base/restauration sans la ligne technique.
            OperationLock.objects.get_or_create(pk=1)
            OperationLock.objects.filter(pk=1).update(id=F("id"))
        yield


def snapshot_read(view):
    """Même instant de lecture pour le récapitulatif et le détail d'un rapport."""
    from functools import wraps
    from django.db import connection
    @wraps(view)
    def wrapped(*args, **kwargs):
        outer_transaction = connection.in_atomic_block
        with transaction.atomic():
            if connection.vendor == 'postgresql' and not outer_transaction:
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            return view(*args, **kwargs)
    return wrapped
