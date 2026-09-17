# Préparation du recalcul des stocks et des soldes

## Versions préparées

- Gestionnaire bureau : **1.1.9**.
- Console Web locale : **1.0.33**.
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
  stock affiché. Un stock négatif est signalé ; il n'est pas ramené à zéro.

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


## Ventes à crédit et plafond des dépôts

- Une vente est autorisée sans dépôt préalable, et même si le client est déjà
  débiteur. Son solde devient négatif : c'est sa dette. Le stock disponible reste
  contrôlé et chaque vente produit son mouvement de sortie.
- Les retraits en espèces restent limités au solde disponible.
- Les dépôts actifs sont limités à **40 000 GNF cumulés par matricule et par jour**,
  selon la journée civile en Guinée (UTC). Exemple : 30 000 + 10 000 acceptés,
  puis tout supplément refusé. Les achats et retraits ne libèrent pas ce plafond.
- La règle s'applique aux nouveaux dépôts et aux restaurations de dépôts annulés.
  Une restauration est contrôlée sur le jour d'origine de l'encaissement.
- Le contrôle fonctionne hors connexion sur chaque base locale. Deux postes
  déconnectés peuvent chacun accepter un dépôt pour le même matricule : le total
  global ne peut alors être garanti avant synchronisation.
- La synchronisation conserve tous les encaissements réels et leurs UUID. Un
  cumul supérieur au plafond déclenche une alerte avec matricule, date, total et
  dépassement. Aucune somme n'est effacée ou réduite automatiquement.
- Détails : **Dépôts / Retraits** sur le site et la Console Web ; voyant d'alerte
  et résultat de synchronisation dans le Gestionnaire. Mettre tous les postes à
  jour pour appliquer le même contrôle.
- Les anciennes opérations restent conservées. Un solde client négatif n'est
  plus signalé comme une erreur de calcul simplement parce qu'il est négatif.


## Caisse

- Une **caisse unique**, partagée par tous les postes et la Console Web. Son
  journal comporte la date, le libellé, les entrées, les sorties et le solde
  progressif.
- Le solde progressif n'est pas stocké : il se recalcule en cumulant les lignes
  actives triées par date, horodatage puis UUID. Deux postes hors connexion ne
  peuvent donc pas inscrire deux soldes contradictoires — c'est la somme qui fait
  foi. Une écriture antidatée se replace d'elle-même dans le cumul.
- La caisse démarre par une **écriture d'ouverture** (« Solde initial ») portant
  sa propre date. Une seule ouverture active est admise.
- Au moment de la vente, choisir **Compte client (matricule)** ou **Caisse
  (espèces)**. En caisse, il n'y a ni matricule ni téléphone : le stock est
  décompté normalement, aucun compte client n'est mouvementé, et le montant entre
  au journal sous le libellé « Vente — <produit> x<quantité> ». Le reçu indique
  « Payé par : Caisse (espèces) ».
- Les sorties (versement à la banque, achat, remise au propriétaire) se saisissent
  dans la caisse elle-même. Une sortie supérieure au contenu du tiroir est
  refusée, avec le montant disponible affiché.
- Annuler une vente encaissée retire son encaissement et rend le stock ; la
  restaurer depuis la corbeille le rétablit. Une ligne d'encaissement ne peut pas
  être supprimée seule : il faut annuler la vente.
- Les ventes encaissées n'entrent dans aucun solde de matricule, ni dans le solde
  global des comptes clients, ni dans le recalcul des soldes.
- **Annuler une écriture de caisse est réservé aux administrateurs.** Un profil
  agent (caissier, superviseur) saisit les entrées et les sorties mais ne peut pas
  les retirer : le journal doit rester vérifiable. Sur la Console Web, la règle
  suit la permission de suppression déjà en place (admin, ou responsable dont le
  droit a été activé) ; le bouton d'annulation n'apparaît pas sans ce droit.


## Articles vendus sans stock

- Chaque article porte un mode de gestion : **suivi en stock** (par défaut) ou
  **sans stock**. Un article sans stock se vend toujours : aucune quantité n'est
  décomptée, aucun mouvement de stock n'est écrit, et la vente elle-même reste la
  trace de l'opération.
- Trois plats sont livrés dans ce mode : **Plat 5.000**, **Plat 10.000** et
  **Plat 15.000**. À la mise à jour, un plat déjà présent au catalogue est
  simplement basculé — la comparaison ignore la casse, les espaces et les points,
  donc « PLAT 10 000 » est reconnu — et les plats absents sont créés avec leur
  prix. Aucun doublon n'est produit, et la bascule ne s'exécute qu'une fois.
- Un article sans stock n'a ni seuil d'alerte, ni stock maximum, ni valeur
  d'inventaire. Il n'apparaît pas dans l'inventaire physique, n'entre pas dans la
  valorisation du stock et n'est jamais signalé en rupture.
- Aucun mouvement manuel ne peut lui être appliqué : ni entrée, ni sortie, ni
  demande d'entrée de stock. La saisie est refusée avec un message explicite.
- Le **recalcul du stock l'ignore entièrement** : sans stock initial ni mouvement,
  il n'y a rien à reconstruire et aucun écart à signaler.
- Basculer un article suivi vers « sans stock » remet sa quantité, son seuil et
  son stock maximum à zéro : sans mouvement, une quantité résiduelle ne voudrait
  plus rien dire. L'opération se fait sur la fiche article, depuis le poste ou la
  Console Web.
- Le mode se synchronise entre les postes et le serveur comme le reste de la fiche
  article.


## Compatibilité de synchronisation des anciennes consoles

Le serveur accepte aussi un ancien mouvement de quantité nulle lorsqu'il porte
le libellé exact **Inventaire physique** et un stock après fini, non négatif.
Ce stock après représente le comptage enregistré par l'ancien écran ; il est
repris dans le champ du comptage physique. Un simple mouvement nul sans cette preuve reste refusé.

Cette compatibilité évite qu'un ancien inventaire sans écart bloque les lots
suivants de ventes et de dépôts. Les UUID restent inchangés, un renvoi ne crée
pas de doublon et ne remplace pas un mouvement déjà corrigé sur le serveur.
Le correctif serveur fonctionne avec les anciennes consoles, sans leur demander
de réécrire l'historique ni de réinitialiser leur base locale.
