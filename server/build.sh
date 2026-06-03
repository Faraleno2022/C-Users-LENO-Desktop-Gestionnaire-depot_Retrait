#!/usr/bin/env bash
# Script de build Render : installe les dépendances, collecte les fichiers
# statiques et applique les migrations.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
