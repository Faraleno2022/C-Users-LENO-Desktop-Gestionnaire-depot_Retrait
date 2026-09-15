# Préparation du recalcul des stocks et des soldes

## Versions préparées

- Gestionnaire bureau : **1.1.5**.
- Console Web locale : **1.0.29**.
- Serveur du site : mêmes modèles et calculs, migrations Django **0015_reconciliation** et **0016_reconciliation_snapshot_chunks**.

## Règle de stock

**Stock initial + entrées − sorties = stock final**, par produit.
Pour une période filtrée, le stock de début comprend les mouvements antérieurs.
Les filtres Type et Agent limitent le détail affiché ; ils ne retirent pas des
opérations du calcul du solde. La sélection d'un article utilise son UUID exact.
Le journal présente les mouvements enregistrés. Le diagnostic présente leurs
corrections proposées et le stock qui en résulterait.

Un mouvement initial n'est jamais compté deux fois. Les mouvements archivés
restent dans le journal physique, identifiés comme archivés : leur masquage dans
la corbeille n'avait pas annulé leur effet sur les marchandises. Les retours de
vente sont comptés une seule fois par leur mouvement de compensation.

## Références utilisées

- Stock initial explicitement enregistré, ou reconstitué depuis le solde avant
  le premier mouvement identifiable. Cette provenance apparaît dans le diagnostic.
- Inventaire physique : le comptage enregistré reste inchangé ; la quantité
  d'ajustement est recalculée par rapport au journal corrigé. Le libellé historique
  standard « Inventaire physique » conserve son comptage dans stock_apres. Un
  inventaire au libellé personnalisé exige une trace d'audit ou stock_compte.
- Un inventaire confirmé produit désormais une référence même si la quantité
  comptée est identique au stock affiché.
- Les ventes utilisent quantité × prix unitaire historique. Les montants saisis
  des dépôts et retraits ne sont pas remplacés. Le solde client est la somme des
  dépôts actifs moins les retraits et ventes actifs.
- Les données invalides, références absentes et historiques incomplets sont
  signalés. Aucun stock initial n'est ajusté artificiellement pour retrouver le
  stock affiché. Un résultat négatif est signalé ; il n'est pas ramené à zéro.

## Utilisation

1. Mettre le serveur et tous les postes à jour, puis terminer leur synchronisation.
   Prévoir une courte pause des saisies pendant le diagnostic et son application.
2. Pour un réseau connecté, effectuer le recalcul sur le serveur central, puis
   synchroniser les postes. Pour une installation autonome, ouvrir **Vérification / Recalcul** dans la console ou **Administration →
   Vérifier et recalculer les stocks et les soldes** dans le Gestionnaire.
3. Examiner les produits, valeurs avant/après et points nécessitant un inventaire.
4. L'action **Sauvegarder et appliquer ces recalculs** applique exactement le plan
   examiné. Si les données ont changé entre-temps, le diagnostic doit être actualisé.

La consultation du diagnostic ne modifie aucune donnée métier. Le recalcul
historique complet n'est pas lancé automatiquement au démarrage ou au déploiement.
À réception des mouvements synchronisés, les stocks des produits dont le stock
initial est déjà établi sont entretenus à partir du journal reçu (voir ci-dessous). Cette préparation fournit une application explicite par un
administrateur, après présentation du résultat.

## Sauvegarde et traçabilité

- Bureau : copie SQLite complète avant correction dans data/reconciliation ;
  rapport JSON et journal d'audit conservés.
- Console locale : copie SQLite complète dans le dossier reconciliation des données.
- PostgreSQL : instantané des tables métier concernées et du journal d’audit
  conservé par blocs dans ReconciliationSnapshotChunk, rattachés à ReconciliationRun,
  dans la même transaction que la correction. Les anciennes sauvegardes JSON restent lisibles.
- SQLite : ReconciliationRun référence la copie complète créée avant correction ;
  cette copie est conservée dans le dossier reconciliation, sans duplication intégrale en mémoire.
- Une erreur annule toutes les modifications. Un second passage sur les mêmes
  données ne modifie plus les valeurs corrigées.

Les champs nouveaux sont synchronisés. Un serveur ou un poste ancien peut
renvoyer des valeurs périmées : la mise à jour de l'ensemble des composants
précède l'application du recalcul. La réservation de stock entre postes hors
ligne reste une limitation du protocole actuel.

## Commande serveur

Le déploiement applique uniquement les migrations de schéma habituelles.
Le diagnostic peut être exporté sans modifier les données métier :

~~~powershell
python manage.py reconcile_data --report diagnostic_recalcul.json
~~~

La commande affiche un jeton du plan. Après examen, l'application explicite
utilise ce jeton ; toute modification concurrente invalide le plan :

~~~powershell
python manage.py reconcile_data --apply JETON_DU_PLAN --report resultat_recalcul.json
~~~

## Vérification

Tests de calcul, historiques incomplets, inventaires et annulations ; tests
SQLite de sauvegarde, refus d'un plan périmé et annulation après erreur ; tests
Django des rôles, du journal, des dates et des exports. Parcours de réparation
vérifié dans le navigateur sur une base synthétique, et écran Qt contrôlé.
Les installations existantes et les données de production n'ont pas été modifiées.

## Correctif de l’erreur 502 du vérificateur

Le diagnostic ne charge que les champs nécessaires au calcul et les audits
liés aux inventaires. Les ventes sont indexées par produit, les audits par date,
et les mouvements simultanés sont ordonnés sans parcours quadratique.
Le détail des anciennes sauvegardes n’est plus chargé pour afficher leur date.

Lors de l’application, les corrections d’une même ligne sont regroupées et les
écritures SQL sont paramétrées et limitées à 200 lignes par lot (ou moins selon
la limite SQLite). La sauvegarde PostgreSQL utilise des blocs de 500 lignes.
La copie SQLite complète reste conservée avant toute correction. Le plan est
revérifié sous verrou et toutes les écritures restent dans une seule transaction.

Le fichier server/gunicorn.conf.py fixe un délai de 120 secondes par défaut,
surchargeable par GUNICORN_TIMEOUT. Il est chargé depuis le répertoire server,
y compris avec l’ancienne commande gunicorn core.wsgi:application. Cette marge
accompagne les réductions du travail et de la mémoire nécessaires au recalcul.
La migration 0016 doit être appliquée par le déploiement avant utilisation.


## Synchronisation et exports — versions 1.1.5 / 1.0.29

- Un total de stock absolu envoyé par un ancien poste ne remplace plus le stock
  d'un produit dont le stock initial est établi. Le serveur calcule ce total depuis
  le journal identifié par UUID, en incluant les mouvements archivés.
- Un même mouvement reçu plusieurs fois ne déduit pas plusieurs fois sa quantité.
  Les faits d'un mouvement déjà reçu sont conservés ; une annulation utilise un
  nouveau mouvement compensateur. Les anciens échos ne défont pas un recalcul central.
- Les mouvements reçus en retard remettent à jour les soldes suivants du produit.
  Un comptage explicitement enregistré reste un point d'inventaire : son ajustement
  est recalculé lorsque des opérations antérieures arrivent.
- La console envoie toutes les tables avant de recevoir les totaux. Les bases
  anciennes sans stock initial doivent encore passer par le diagnostic explicite.
- Les modifications d'un stock initial déjà établi se font sur le serveur central,
  avec diagnostic et sauvegarde ; elles ne s'imposent pas depuis un miroir local.
- Le récapitulatif et le détail des mouvements sont lus dans un même instantané.
  Les exports effectués à des heures différentes peuvent varier avec les ventes.
- Excel reçoit des cellules numériques exactes, avec un format d'affichage GNF
  pour les montants. Les références et matricules restent du texte. Le format
  scientifique à six chiffres significatifs n'est plus utilisé pour les quantités.
- L'inventaire affiche « À compter » et conserve des cases vides tant qu'aucune
  quantité réelle n'est saisie. Un résultat théorique négatif ne vaut pas comptage zéro.

Le logiciel ne peut pas déduire une quantité physique absente des justificatifs.
Après mise à jour, vérifier les écarts restants, compter les articles concernés,
puis enregistrer l'inventaire réel pour obtenir un ajustement traçable.
