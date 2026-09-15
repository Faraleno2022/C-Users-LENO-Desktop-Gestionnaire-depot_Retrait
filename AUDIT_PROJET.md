# Audit du projet — 14 septembre 2026

## Résultat

Les défauts confirmés ont été corrigés dans le code du bureau, de la console web
et de la synchronisation. Les vérifications finales passent : **88 tests**
(32 côté bureau/utilitaires et 56 côté Django), plus trois scénarios intégrés.

L'audit a porté sur les services métier, le schéma et les migrations, les vues
et formulaires, les sessions et droits, les exports, les sauvegardes, la
synchronisation et les mises à jour. La syntaxe des 120 fichiers Python du
projet a également été vérifiée.

## Corrections

| Module | Défaut constaté | Comportement corrigé |
| --- | --- | --- |
| Dépôts, retraits, ventes | Résidus décimaux, déduction incorrecte des lignes répétées et écritures partielles en cas d'erreur | Calcul décimal, regroupement des quantités et opérations indivisibles ; refus du stock ou du solde insuffisant |
| Stock | Absence du mouvement initial sur le web, annulations/restaurations incohérentes | Entrées et sorties tracées, contrôles avant restauration, blocage des quantités invalides |
| Synchronisation | Modification locale acquittée alors qu'elle avait changé pendant l'envoi | Seule la version effectivement transmise est acquittée ; la modification suivante reste à envoyer |
| Pagination | Des enregistrements de même date pouvaient être sautés | Reprise par date et UUID sur le serveur, le bureau et la console locale |
| Réception | Curseur avancé malgré une ligne non intégrée ; agents absents impossibles à importer | Reprise de la page non intégrée ; agent local facultatif, avec conservation de son UUID et de son nom |
| API de synchronisation | Lot partiellement enregistré, nombres invalides et accès possible par session navigateur | Validation du lot avec annulation complète sur erreur ; authentification exclusivement par jeton de poste |
| Réplication console | Fichier d'état susceptible d'être tronqué ; édition locale récente écrasée lors du pull | Écriture de l'état par remplacement atomique, reprise des pages et protection des éditions non encore envoyées |
| Sauvegardes | Collision de noms à la même seconde et connexions SQLite non fermées | Noms distincts et fermeture explicite des fichiers |
| Restauration | Fichier invalide remplaçant la base ; anciennes écritures WAL perturbant le résultat | Validation préalable, migrations sur copie préparée puis restauration via SQLite ; sauvegarde de sécurité conservée dans la liste |
| Export de base | Copie brute de la base ouverte pouvant manquer des écritures récentes | Export d'un instantané SQLite cohérent incluant les écritures WAL |
| Comptes | Suppression refusée par les références historiques ; possibilité de perdre le dernier super-administrateur | Désactivation conservant l'historique ; protection du dernier super-administrateur actif |
| Sessions web | Droits périmés et connexion dans un deuxième navigateur invalidant le premier | Droits réévalués à chaque requête ; révocation après désactivation ou changement de mot de passe ; connexions distinctes préservées |
| Attribution des opérations | Identifiants de connexion identiques pouvant désigner le mauvais agent | Recherche de l'auteur par UUID de session |
| Clients | Changement de matricule détachant le solde de la fiche | Changement refusé quand le matricule possède des opérations |
| Excel et PDF | Titres d'onglets interdits ; textes interprétés comme formules ou balises | Titres Excel normalisés, textes littéraux et échappement des champs PDF |
| Fermeture du bureau | Destruction d'un thread encore occupé par le réseau | Interruption demandée et références conservées jusqu'à l'arrêt effectif ; connexion du thread fermée |
| Mises à jour | Téléchargement incomplet considéré comme installable | Contrôle de taille et de l'empreinte SHA-256 lorsqu'elle est fournie ; activation après validation seulement |
| Configuration console | JSON de forme incorrecte ou intervalle invalide interrompant le démarrage de la synchronisation | Valeurs validées et retour aux paramètres par défaut |

Les règles de calcul et exemples chiffrés sont détaillés dans
[CORRECTION_STOCK.md](CORRECTION_STOCK.md).

## Vérifications effectuées

- 32 tests bureau/utilitaires : calculs, accès concurrents, sauvegardes,
  restauration avec WAL ouvert, export, ancienne structure SQLite, comptes,
  synchronisation, configuration, thread Qt, mises à jour simulées et sélection
  de l'imprimante.
- 56 tests Django : métier, annulation complète sur erreur, droits et sessions,
  API, réplication, pages, exports et écritures simultanées.
- Contrôle de syntaxe JavaScript des scripts rendus pour les principaux
  formulaires et pages.
- Scénarios intégrés : smoke_test.py, sync_smoke_test.py et ui_smoke_test.py.
- Django check : aucune anomalie.
- makemigrations --check --dry-run : aucune migration manquante.
- Syntaxe Python : 120 fichiers valides.
- Pyflakes : pas de référence non définie ; des avertissements préexistants
  d'imports ou de variables inutilisés subsistent.
- git diff --check : aucune erreur d'espacement.

### Reproduire les tests

Depuis la racine, dans PowerShell :

~~~powershell
.venv/Scripts/python.exe -X utf8 -m unittest accounting_test project_regression_test updater_test sync_worker_test server.test_console_web_printer
.venv/Scripts/python.exe -X utf8 smoke_test.py
.venv/Scripts/python.exe -X utf8 sync_smoke_test.py
.venv/Scripts/python.exe -X utf8 ui_smoke_test.py
server/.venv/Scripts/python.exe -X utf8 server/run_tests.py
~~~

Le dernier lanceur force une base SQLite temporaire sur disque : les tests de
concurrence s'exécutent réellement et aucune configuration de production n'est
utilisée. Le contrôle JavaScript requiert Node.js ; il a été exécuté ici.
La dépendance requests, déjà déclarée dans server/requirements.txt mais absente
de son environnement virtuel, a été installée pour tester la réplication.

## Mise en service et limites

- Les corrections sont enregistrées dans les sources. Aucun déploiement,
  installation d'exécutable ni changement de données réelles n'a été effectué.
- Les exécutables ont été reconstruits le 15 septembre 2026 : Gestionnaire
  1.1.2 et Console Web 1.0.26. Leur démarrage a été vérifié sur des bases
  temporaires. La migration 0014_operationlock est intégrée et son application
  a été vérifiée dans la console compilée.
- Le bureau migre les anciennes tables d'opérations au démarrage pour autoriser
  un agent local absent. Les données, index et séquences sont conservés.
- La synchronisation continue de transmettre des instantanés avec sa politique
  de résolution des conflits. Plusieurs postes déconnectés ne réservent pas
  un stock ou un solde commun : ce cas nécessite une évolution du protocole.
- Les stocks historiques et reçus existants n'ont pas été recalculés. Un
  inventaire peut rester nécessaire si les erreurs avaient déjà affecté les données.
- Les vérifications de base de données ont utilisé SQLite. Le serveur
  PostgreSQL en production et une installation réelle des exécutables n'ont
  pas été testés pendant cet audit.

## Recompilation du 15 septembre 2026

- Versions : Gestionnaire 1.1.2 et Console Web 1.0.26.
- Construction avec PyInstaller 6.22.3 ; installateurs Inno Setup 6.
- Correction du paquet bureau : exclusion des DLL ICU étrangères au paquet
  Qt, récupérées dans le PATH d'un outil externe. Elles empêchaient QtGui de
  se charger. Le démarrage du paquet final a été vérifié après correction.
- Vérification du bureau compilé : version embarquée, modules corrigés,
  ouverture de l'application et création d'une base temporaire.
- Vérification de la console compilée : connexion, tableau de bord, migration,
  création d'un article avec 10 unités à 100, dépôt de 10 000 et retrait de
  deux lignes du même article (2 + 3 unités). Résultat : stock 5, vente 500,
  aucune écriture de retrait monétaire supplémentaire, intégrité SQLite valide.
- Ces vérifications ont utilisé uniquement des profils et bases de test.
  Les données existantes n'ont pas été modifiées.
