# Gestionnaire Dépôt / Retrait

Application bureau Windows pour la gestion des dépôts, retraits, soldes, utilisateurs et rapports.

## Stack technique

- **Interface** : PySide6
- **Base de données locale** : SQLite
- **Synchronisation** : API REST Django + PostgreSQL (envoi montant, *push-only*) — voir `server/`

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Lancement

```bash
python main.py
```

Au premier lancement, un compte super-administrateur est créé automatiquement :

- **Identifiant** : `admin`
- **Mot de passe** : `admin123`

**Changez ce mot de passe immédiatement après la première connexion.**

## Structure du projet

```
app/
├── config.py           # Configuration globale
├── db/                 # Couche base de données
├── models/             # Modèles de données
├── services/           # Logique métier
├── ui/                 # Interfaces PySide6
│   └── widgets/        # Composants réutilisables
└── utils/              # Utilitaires (sécurité, export, etc.)
data/                   # Base SQLite + sauvegardes
exports/                # Fichiers PDF/Excel générés
main.py                 # Point d'entrée
```

## Rôles

- **super_admin** : tous les droits (gestion admins, suppression, restauration)
- **admin** : gestion utilisateurs, rapports, suppression de transactions
- **superviseur** : consultation rapports et historique
- **caissier** : saisie dépôts / retraits, impression reçus

## Fonctionnalités

- Tableau de bord temps réel
- Saisie dépôts / retraits avec calcul automatique du solde
- Historique avec filtres, recherche, pagination, export Excel/PDF
- Gestion utilisateurs et administrateurs
- Rapports journalier / mensuel / annuel
- Sauvegarde automatique de la base locale
- Journal d'audit complet
- Gestion des produits (catégorie, unité, prix d'achat/vente, seuil min, stock max, emplacement), du stock (entrées/sorties) et des ventes décomptées du solde client
- Alertes visuelles : rupture, stock bas, surstock
- Bons et documents de stock en PDF : bon d'entrée, bon de sortie, fiche article (avec historique) et fiche d'inventaire (colonnes comptage physique / écart), avec en-tête société configurable — enregistrés dans `exports/bons/`
- Synchronisation montante vers un serveur en ligne (statuts : en attente / synchronisé)

## Imprimante à tickets (Epson TM-T20III et autres thermiques)

Les reçus de dépôt/retrait et de vente sont envoyés **directement** à
l'imprimante à tickets en ESC/POS (sans boîte de dialogue, papier coupé en fin
de ticket), dès la validation si l'option *Imprimer automatiquement* est active
(c'est le cas par défaut). Sans imprimante à tickets, le bouton **Imprimer le
reçu** ouvre la boîte de dialogue Windows classique.

### Installer l'imprimante sur le poste

1. Installez le pilote Epson **Advanced Printer Driver (APD)** pour TM-T20III
   depuis le site Epson (support → TM-T20III → Pilotes). L'imprimante apparaît
   dans Windows sous le nom **EPSON TM-T20III Receipt**.
2. Branchez l'imprimante (USB) et allumez-la. Imprimez une page de test depuis
   Windows (Paramètres → Imprimantes) pour vérifier le câblage.
3. Dans l'application : **Administration → Impression des tickets**. Laissez
   *Automatique* (le pilote thermique est détecté) ou choisissez l'imprimante
   dans la liste, réglez la largeur (80 mm par défaut), puis **Imprimer un
   ticket test**. Si le ticket sort lisible et coupé, c'est terminé.

La détection automatique reconnaît les pilotes dont le nom contient `Receipt`,
`POS`, `Thermal`, `Ticket`, `EPSON TM`, `TM-T`, `XPrinter`, `Rongta`, `POZER`…
Pour un pilote au nom quelconque (ex. *Generic / Text Only*), sélectionnez-le
explicitement dans la liste. La variable d'environnement `EMAB_RECEIPT_PRINTER`
impose aussi un nom d'imprimante (application de bureau et console web).

L'en-tête du ticket reprend les **Coordonnées société** (nom, adresse,
téléphone, pied de page) saisies dans Administration. Une case permet
d'ouvrir le tiroir-caisse branché sur l'imprimante à chaque ticket.

## Synchronisation en ligne (Phase 2)

Le serveur Django REST (dossier `server/`) reçoit les données poussées par les
postes locaux pour consolidation et sauvegarde en ligne. La synchronisation est
**unidirectionnelle** : le poste est la source de vérité, il envoie ses
enregistrements `pending` au serveur et ne rapatrie rien.

### Authentification

Chaque poste possède un **jeton** (device token). Le serveur le crée :

```bash
cd server
python manage.py createdevice "Caisse principale"
```

Le jeton affiché est saisi dans l'application de bureau :
**Administration → Synchronisation** (URL du serveur + jeton + nom du poste),
puis *Tester la connexion* et *Synchroniser maintenant*.

On peut aussi le fournir par variables d'environnement :
`GESTIONNAIRE_SERVER_URL`, `GESTIONNAIRE_DEVICE_TOKEN`.

### Configurer la synchronisation en un clic

Deux moyens de configurer un poste **sans ouvrir l'application** :

1. **`Configurer_Synchronisation.bat`** (racine du projet) : double-cliquez,
   une fenêtre demande l'URL du serveur, le jeton et le nom du poste, propose
   *Tester la connexion* et *Enregistrer*. La configuration est écrite dans la
   base locale du poste (détection automatique : poste installé dans
   `%LOCALAPPDATA%\EMAB GROUP\Gestionnaire`, sinon `data/gestionnaire.db`),
   exactement comme depuis l'écran Administration → Synchronisation.
   Options : `--console` (mode texte), `--apply` (applique `sync_config.json`
   sans fenêtre), `--db chemin\gestionnaire.db`.

2. **Fichier `sync_config.json`** : copiez `sync_config.example.json` en
   `sync_config.json`, remplissez-le et déposez-le à côté de l'application
   (dossier du projet, dossier de l'exécutable, ou dossier de données). Au
   démarrage suivant, l'application l'applique puis le renomme en
   `sync_config.applied.json`. Ce fichier contient le jeton du poste : il est
   ignoré par git.

```json
{
  "server_url": "https://votre-serveur.onrender.com",
  "device_token": "JETON_DU_POSTE",
  "device_name": "Caisse principale",
  "auto_sync": true,
  "auto_sync_interval_seconds": 15
}
```

Redémarrez l'application après la configuration : la synchronisation
automatique démarre dès que l'URL et le jeton sont valides.

### Envoyer le projet sur GitHub en un clic

**`SYNCHRONISER_GITHUB.bat`** (racine du projet) : double-cliquez pour
enregistrer les modifications locales (commit), récupérer celles du dépôt
(`pull --rebase`) puis tout envoyer sur
`https://github.com/Faraleno2022/SKS_EMAB.git`. Le fichier règle lui-même le
remote `origin` sur ce dépôt et se place sur la branche `main`. En cas de
conflit, il s'arrête et indique quoi faire (`git rebase --abort` pour annuler).

### Lancer le serveur en local

```bash
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # pour l'admin Django (/admin/)
python manage.py createdevice "Poste test"
python manage.py runserver
```

Endpoints : `GET /api/sync/ping/` (test du jeton), `POST /api/sync/push/`
(envoi d'un lot `{ "table": ..., "records": [...] }`, upsert idempotent par `uuid`).

### Déploiement sur Render

Le dossier `server/` contient `render.yaml` (service web + PostgreSQL gérée),
`build.sh` (collectstatic + migrations) et `.env.example`. Connectez le dépôt
à Render : le blueprint provisionne la base, applique les migrations et démarre
gunicorn. Définissez `DJANGO_SECRET_KEY` (généré automatiquement) puis créez un
poste via le shell Render (`python manage.py createdevice ...`).


### Export des clients et de leurs soldes

Dans **Clients**, utiliser **Soldes Excel** ou **Soldes PDF**. La recherche
par matricule ou par nom s'applique aussi à l'export. Le fichier inclut tous
les comptes correspondant à cette recherche, même au-delà des lignes affichées :
matricule, nom, téléphone, solde en GNF, nombre d'opérations et présence d'une fiche.

Les comptes sans fiche ayant des opérations sont inclus. Le total général
comprend les soldes négatifs (dettes des clients). Les opérations annulées et
les ventes payées directement en caisse ne débitent pas le solde exporté.
Les montants Excel sont numériques. Le PDF répète les en-têtes sur chaque page.

Disponibilité : site web, Console Web **1.0.34**, Gestionnaire **1.1.10**.
Le solde exporté correspond aux données disponibles dans cette installation :
synchroniser les postes pour intégrer leurs opérations récentes.
