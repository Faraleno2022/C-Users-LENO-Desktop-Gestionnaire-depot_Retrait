"""Lance les tests Django sur un fichier SQLite temporaire, concurrence comprise."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    # Forcer une configuration isolée, même si server/.env vise une base réelle.
    os.environ.update(
        DJANGO_SETTINGS_MODULE="core.settings",
        DATABASE_URL="sqlite:///:memory:",
        DJANGO_SECURE_SSL_REDIRECT="0",
    )
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections
    from django.test.utils import get_runner
    with TemporaryDirectory(prefix="gestionnaire-tests-") as directory:
        settings.DATABASES["default"]["TEST"]["NAME"] = str(Path(directory) / "tests.sqlite3")
        try:
            failures = get_runner(settings)(interactive=False, verbosity=1).run_tests(sys.argv[1:] or ["web", "sync"])
        finally:
            connections.close_all()
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
