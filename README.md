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
- Gestion des produits, du stock (entrées/sorties) et des ventes décomptées du solde client
- Synchronisation montante vers un serveur en ligne (statuts : en attente / synchronisé)

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
