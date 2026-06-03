# Déploiement du serveur de synchronisation sur Render

Ce guide explique, étape par étape, comment mettre en ligne le serveur Django
(dossier `server/`) sur [Render](https://render.com) et le relier à l'application
de bureau. Aucune connaissance d'administration système n'est nécessaire.

La synchronisation est **montante uniquement** : l'application de bureau reste la
source de vérité et **envoie** ses données vers le serveur. Aucune donnée n'est
rapatriée et **les mots de passe ne sont jamais transmis**.

---

## 1. Ce qui est déjà prêt dans le projet

Le dossier `server/` contient tout le nécessaire :

| Fichier | Rôle |
|---|---|
| `render.yaml` | Décrit le service web + la base PostgreSQL (déploiement « Blueprint ») |
| `build.sh` | Installe les dépendances, collecte les fichiers statiques, applique les migrations |
| `requirements.txt` | Dépendances Python (Django, DRF, gunicorn, whitenoise, psycopg2…) |
| `.env.example` | Modèle des variables d'environnement pour le développement local |
| `core/settings.py` | Configuration pilotée par variables d'environnement (prod/dev) |

Vous n'avez normalement **rien à modifier** pour déployer.

---

## 2. Pré-requis

1. Un compte **GitHub** (gratuit).
2. Un compte **Render** (gratuit) — connectez-le à votre compte GitHub.
3. Le projet poussé sur un dépôt GitHub (voir étape 3).

> Le plan gratuit de Render suffit pour démarrer. Limite à connaître : le service
> web gratuit « s'endort » après 15 min d'inactivité et met ~30 s à se réveiller
> à la première requête. La base PostgreSQL gratuite expire après 90 jours
> (Render prévient par e-mail ; il faut alors en recréer une ou passer au plan payant).

---

## 3. Mettre le code sur GitHub

Depuis le dossier racine du projet :

```bash
git init
git add .
git commit -m "Gestionnaire dépôt/retrait + serveur de synchronisation"
git branch -M main
git remote add origin https://github.com/VOTRE-COMPTE/VOTRE-DEPOT.git
git push -u origin main
```

> Le fichier `server/.gitignore` empêche déjà de publier la base de dev
> (`dev.sqlite3`), le `.env` et les fichiers statiques générés.

---

## 4. Créer les services sur Render (méthode Blueprint, recommandée)

1. Sur le tableau de bord Render, cliquez **New +** → **Blueprint**.
2. Sélectionnez votre dépôt GitHub.
3. Render lit automatiquement `server/render.yaml` et propose de créer :
   - une base **gestionnaire-db** (PostgreSQL) ;
   - un service web **gestionnaire-sync** (Python).
4. Cliquez **Apply**. Render lance le build (`bash build.sh`) puis démarre
   le serveur avec `gunicorn core.wsgi:application`.

Les variables d'environnement sont injectées automatiquement par `render.yaml` :

| Variable | Valeur | Effet |
|---|---|---|
| `DATABASE_URL` | depuis la base | connexion PostgreSQL |
| `DJANGO_SECRET_KEY` | générée | clé secrète Django |
| `DJANGO_DEBUG` | `false` | mode production |
| `DJANGO_DB_SSL` | `true` | SSL exigé par Render Postgres |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` | force HTTPS |
| `PYTHON_VERSION` | `3.12.4` | version Python |

Après quelques minutes, votre serveur est accessible à une URL du type :

```
https://gestionnaire-sync.onrender.com
```

> **Vérification rapide** : ouvrez cette URL dans un navigateur. Vous devez voir
> `{"service": "gestionnaire-sync", "status": "ok"}`.

### Variante manuelle (sans Blueprint)

Si vous préférez créer les services à la main :

1. **New + → PostgreSQL** : nommez-la, plan *Free*, créez-la, copiez son
   *Internal Database URL*.
2. **New + → Web Service** : choisissez le dépôt, réglez **Root Directory** sur
   `server`, **Build Command** sur `bash build.sh`, **Start Command** sur
   `gunicorn core.wsgi:application`.
3. Dans **Environment**, ajoutez les variables du tableau ci-dessus
   (`DATABASE_URL` = l'URL copiée, `DJANGO_SECRET_KEY` = une longue chaîne
   aléatoire, `DJANGO_DEBUG=false`, `DJANGO_DB_SSL=true`,
   `DJANGO_SECURE_SSL_REDIRECT=true`).

---

## 5. Déclarer un poste et obtenir son jeton

Chaque poste de l'application de bureau s'authentifie avec un **jeton** unique.
Pour le générer, ouvrez un terminal sur le service Render (onglet **Shell** du
service web) et lancez :

```bash
python manage.py createdevice "Caisse principale"
```

La commande affiche le **jeton du poste** (device token). Copiez-le.

> Pour régénérer le jeton d'un poste existant :
> `python manage.py createdevice "Caisse principale" --regenerate`

---

## 6. Relier l'application de bureau au serveur

1. Lancez l'application de bureau et connectez-vous en administrateur.
2. Allez dans **Administration → Synchronisation en ligne**.
3. Renseignez :
   - **URL du serveur** : `https://gestionnaire-sync.onrender.com`
   - **Jeton du poste** : le jeton obtenu à l'étape 5
   - **Nom du poste** : libre (ex. *Caisse principale*)
4. Cliquez **Enregistrer la configuration**, puis **Tester la connexion**.
   Un message confirme que le serveur a accepté le jeton.
5. Cliquez **Synchroniser maintenant** pour envoyer les données en attente.

L'indicateur en haut de la fenêtre passe à « Synchronisation configurée » et le
nombre d'enregistrements en attente tombe à 0 après l'envoi.

---

## 7. Vérifier les données côté serveur

Vous pouvez consulter les données reçues via l'**admin Django** :

1. Sur le Shell Render : `python manage.py createsuperuser` (créez un compte).
2. Ouvrez `https://gestionnaire-sync.onrender.com/admin/` et connectez-vous.
3. Les utilisateurs, produits, transactions, ventes et clients synchronisés
   y sont visibles (lecture). Le poste source et l'horodatage de réception
   sont conservés pour chaque enregistrement.

---

## 8. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `401` au test de connexion | Jeton incorrect ou poste désactivé | Recopiez le jeton ; vérifiez `active=True` côté serveur |
| Connexion impossible / délai | Serveur gratuit endormi | Réessayez après ~30 s (le premier appel réveille le service) |
| `500` au push | Migration manquante après mise à jour | Render relance `migrate` à chaque build ; redéployez |
| `DisallowedHost` | Hôte non autorisé | Render fournit `RENDER_EXTERNAL_HOSTNAME` automatiquement ; sinon réglez `DJANGO_ALLOWED_HOSTS` |
| Build échoue sur `build.sh` | Bit exécutable absent | Le `buildCommand` utilise déjà `bash build.sh`, indépendant du bit exécutable |

---

## 9. Mises à jour ultérieures

À chaque `git push` sur la branche `main`, Render redéploie automatiquement :
il réinstalle les dépendances, **applique les nouvelles migrations** et redémarre
le serveur. Aucune action manuelle n'est requise pour les évolutions du schéma
(par ex. l'ajout de la table `clients`).
