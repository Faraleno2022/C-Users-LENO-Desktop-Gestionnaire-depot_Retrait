"""Lecture des alertes de dépôts, sans modification des écritures."""
from sync.business_rules import deposit_warnings
from sync.models import Transaction


def get_deposit_warnings(matricules=None, since_day=None):
    qs = Transaction.objects.filter(type='depot', deleted=False)
    if matricules is not None:
        qs = qs.filter(matricule__in=matricules)
    if since_day:
        # created_at est un texte « AAAA-MM-JJ hh:mm:ss » : l'ordre
        # lexicographique est aussi l'ordre chronologique.
        qs = qs.filter(created_at__gte=since_day)
    return deposit_warnings(qs.values('matricule', 'created_at', 'montant').iterator())
