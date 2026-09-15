"""Marge bornée pour le recalcul administratif avec sauvegarde transactionnelle.

Gunicorn charge ce fichier depuis le répertoire server, y compris lorsque
Render utilise encore la commande gunicorn core.wsgi:application.
"""
import os

timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
