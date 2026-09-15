# Correction des calculs de stock et des débits

## Erreurs reproduites

- Retrait avec deux lignes du même produit : 2 + 3 unités sur un stock de 10
  donnaient 7 au lieu de 5, alors que le client était débité pour 5 unités.
  Deux lignes de 6 unités étaient également acceptées malgré un stock de 10.
- Une erreur sur une ligne suivante conservait les premières écritures
  (ventes, débit et/ou mouvements de stock).
- Une restauration de vente pouvait rendre le stock ou le solde négatif.
- Sur le bureau, la création de vente échouait : uuid était utilisé sans
  figurer dans la requête de lecture du produit.
- Les opérations décimales pouvaient laisser des résidus, par exemple
  0,3 − 0,1 = 0,19999999999999998.
- Une quantité de produit invalide pouvait être ignorée et l'opération
  transformée en retrait d'espèces.
- Le stock initial créé sur le web ne générait pas son mouvement d'entrée.

## Règles appliquées

- Solde client = dépôts actifs − retraits actifs − ventes actives.
- Une vente débite une seule fois le client et diminue le stock de la quantité
  totale du produit ; aucun retrait d'espèces supplémentaire n'est créé.
- Une entrée/sortie manuelle modifie uniquement le stock.
- Une annulation restitue stock et solde ; une restauration contrôle leur
  disponibilité avant tout changement.
- Les montants/quantités doivent être finis et valides ; les calculs utilisent
  Decimal avant conversion vers les colonnes historiques en flottant.
- Les opérations sont transactionnelles : une erreur annule toutes leurs
  écritures. Les écritures locales sont sérialisées avant de lire les soldes.

## Mise en service

La migration Django 0014_operationlock crée une petite table technique locale
(non synchronisée) et sa ligne de verrou. Exécuter les migrations au déploiement :

    cd server
    .venv/Scripts/python.exe manage.py migrate

La console web et server/build.sh exécutent déjà les migrations au démarrage
ou au déploiement. Les exécutables distribués doivent être reconstruits avec
le code corrigé. Aucun déploiement ni changement de données réelles n'a été
effectué pendant cette correction.

## Vérifications

Depuis la racine :

    .venv/Scripts/python.exe -X utf8 -m unittest accounting_test -v
    .venv/Scripts/python.exe -X utf8 smoke_test.py
    .venv/Scripts/python.exe -X utf8 sync_smoke_test.py
    .venv/Scripts/python.exe -X utf8 ui_smoke_test.py

Depuis server, avec une configuration de test :

    $env:DATABASE_URL = 'sqlite:///:memory:'
    .venv/Scripts/python.exe -X utf8 manage.py test web sync --noinput
    .venv/Scripts/python.exe -X utf8 manage.py makemigrations --check --dry-run

Les tests de concurrence web nécessitent une base de test SQLite sur disque
(DATABASES["default"]["TEST"]["NAME"]) ou PostgreSQL. Ils sont ignorés avec
SQLite en mémoire. Le contrôle réalisé ici utilise un fichier temporaire.

## Périmètre

Les anciens stocks et reçus ne sont pas réécrits automatiquement : les stocks
historiques peuvent nécessiter un inventaire physique. Le verrou protège les
écritures au sein d'une base ; il ne réserve pas un solde entre plusieurs
postes déconnectés. Le protocole de synchronisation existant transmet des
instantanés et conserve sa politique de résolution des conflits.
