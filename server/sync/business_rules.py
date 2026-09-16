"""Règles métier communes au serveur et au poste."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

DAILY_DEPOSIT_LIMIT = Decimal('40000')
# Fenêtre des alertes recalculées à chaque synchronisation : elle couvre un poste
# resté hors connexion une semaine sans relire tout l'historique des dépôts à
# chaque cycle. La page Dépôts / Retraits affiche, elle, l'historique complet.
RECENT_ALERT_DAYS = 7


def business_day(value=None):
    """Journée civile en Guinée (UTC), indépendante du fuseau du poste."""
    if value is None:
        return datetime.now(timezone.utc).date().isoformat()
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date().isoformat()


def day_offset(day, days):
    """Décale un jour civil (« AAAA-MM-JJ ») de `days` jours."""
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def recent_alert_floor(days_back=RECENT_ALERT_DAYS):
    """Jour plancher des alertes rejouées à chaque synchronisation."""
    return day_offset(business_day(), -days_back)


def check_daily_deposit(amount, deposited):
    amount, deposited = Decimal(str(amount)), Decimal(str(deposited))
    if not amount.is_finite() or amount <= 0 or not deposited.is_finite():
        raise ValueError('Montant de dépôt invalide.')
    if deposited + amount > DAILY_DEPOSIT_LIMIT:
        remaining = max(Decimal(0), DAILY_DEPOSIT_LIMIT - deposited)
        raise ValueError(
            f'Plafond journalier de 40 000 GNF par matricule atteint ou dépassé. '
            f'Déjà déposé : {deposited:,.0f} GNF ; restant autorisé : {remaining:,.0f} GNF.'
            .replace(',', ' '))


def business_timestamp(micro=False):
    """Horodatage et jour de l'opération capturés ensemble, en UTC (Guinée).

    `micro=True` ajoute les microsecondes : le journal de caisse s'ordonne sur
    cet horodatage, et deux écritures de la même seconde doivent garder leur
    ordre de saisie plutôt que de retomber sur un uuid aléatoire.
    """
    stamp = datetime.now(timezone.utc)
    return stamp.strftime("%Y-%m-%d %H:%M:%S.%f" if micro else "%Y-%m-%d %H:%M:%S")


def deposit_warnings(rows):
    """Signaler les cumuls sans réécrire les encaissements déjà effectués."""
    totals = {}
    for row in rows:
        try:
            day = business_day(row['created_at'])
            amount = Decimal(str(row['montant']))
        except (ValueError, TypeError):
            continue  # Les anciennes dates illisibles relèvent du diagnostic.
        if not amount.is_finite() or amount <= 0:
            continue
        key = (row['matricule'], day)
        totals[key] = totals.get(key, Decimal(0)) + amount
    warnings = []
    for (matricule, day), total in sorted(totals.items(), key=lambda item: (item[0][1], item[0][0]), reverse=True):
        if total > DAILY_DEPOSIT_LIMIT:
            excess = total - DAILY_DEPOSIT_LIMIT
            message = (
                f"{matricule} — {day} : {total:,.0f} GNF déposés, "
                f"dépassement de {excess:,.0f} GNF du plafond de 40 000 GNF."
            ).replace(',', ' ')
            warnings.append(dict(matricule=matricule, day=day,
                                 total=float(total), excess=float(excess), message=message))
    return warnings


# --- Caisse -----------------------------------------------------------------

def cash_sort_key(row):
    """Ordre qui définit le solde progressif, identique sur le poste et le serveur."""
    return (str(row.get('date') or ''), str(row.get('created_at') or ''),
            str(row.get('uuid') or ''))


def cash_running_balances(rows):
    """Retourne [(ligne, solde_progressif)] par cumul de (entrée - sortie).

    Une ligne annulée porte le solde en cours sans le modifier : le journal
    reste lisible sans que la corbeille ne fausse les soldes.
    """
    total = Decimal(0)
    result = []
    for row in sorted(rows, key=cash_sort_key):
        if not row.get('deleted'):
            total += (Decimal(str(row.get('entree') or 0))
                      - Decimal(str(row.get('sortie') or 0)))
        result.append((row, float(total)))
    return result


def deposited_on_day(rows, day):
    total = Decimal(0)
    for row in rows:
        try:
            matches = business_day(row['created_at']) == day
        except (TypeError, ValueError):
            continue
        if matches:
            total += Decimal(str(row['montant']))
    return float(total)
