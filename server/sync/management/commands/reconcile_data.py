"""Diagnostic par défaut ; l'application des corrections exige --apply et le jeton du plan."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from sync.reconciliation import preview, apply_reconciliation
from sync.reconciliation_engine import plan_token


class Command(BaseCommand):
    help = 'Diagnostiquer les stocks et soldes ; --apply TOKEN applique le plan examiné.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', metavar='TOKEN')
        parser.add_argument('--report', help='Exporter le diagnostic JSON dans ce fichier.')

    def handle(self, *args, **options):
        try:
            plan = apply_reconciliation(options['apply']) if options['apply'] else preview()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if options['report']:
            Path(options['report']).write_text(json.dumps(plan, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
        self.stdout.write(f"Diagnostic : {len(plan['changes'])} lignes à recalculer ; {len(plan['issues'])} points à vérifier.")
        if not options['apply']:
            self.stdout.write('Jeton du plan : ' + plan_token(plan))
