# Publier une mise à jour vers les PC clients

Les consoles installées chez les clients vérifient **à chaque démarrage** s'il
existe une version plus récente sur GitHub. Si oui, elles la téléchargent en
arrière-plan et l'installent **au démarrage suivant**, **sans jamais toucher à
la base de données** (données et programme sont dans des dossiers séparés ; les
migrations Django n'ajoutent que les nouveautés de schéma).

## À faire à chaque nouvelle version

### 1. Choisir le nouveau numéro de version
Incrémente la version à **deux** endroits (la même valeur) :

- `server/console_web.py` → `APP_VERSION = "1.0.1"`
- `installer_console_web.iss` → `#define MyAppVersion "1.0.1"`

Règle simple : correction → `1.0.1`, `1.0.2`… ; nouveautés → `1.1.0` ; refonte → `2.0.0`.

### 2. Recompiler la console et son installateur
```
cd server
python -m PyInstaller --noconfirm EMAB-Console-Web.spec
cd ..
ISCC.exe installer_console_web.iss
```
Cela produit `dist\EMAB-Console-Web-Setup-1.0.1.exe`.

### 3. Publier la release sur GitHub
Deux méthodes — la plus simple d'abord.

**A. Par le site GitHub (sans rien installer)**
1. Va sur `https://github.com/Faraleno2022/C-Users-LENO-Desktop-Gestionnaire-depot_Retrait/releases`
2. Clique **Draft a new release**
3. **Tag** : `v1.0.1` (le « v » est optionnel mais recommandé)
4. **Title** : `1.0.1`
5. Glisse le fichier `dist\EMAB-Console-Web-Setup-1.0.1.exe` dans la zone **Attach binaries**
6. **Publish release**

**B. En ligne de commande (si `gh` est installé)**
```
gh release create v1.0.1 "dist/EMAB-Console-Web-Setup-1.0.1.exe" --title "1.0.1" --notes "Nouvelles fonctionnalités"
```

### 4. C'est tout
- N'oublie pas de pousser le code sur GitHub (`git push`) — cela met aussi à jour
  le **site Render** (consultation en ligne) automatiquement.
- Les PC clients récupèrent la mise à jour **au prochain redémarrage de Windows**
  (le lanceur de démarrage applique l'installateur téléchargé, puis lance la
  nouvelle version).

## Points importants
- **Le nom de l'installateur doit contenir `Console-Web-Setup`** (c'est ainsi que
  les clients le reconnaissent dans la release). Le nom par défaut convient.
- **Le tag doit être un numéro supérieur** à la version installée, sinon rien ne
  se passe (normal).
- **Les données du client sont conservées** : base, sauvegardes, clé secrète,
  jeton et configuration `render_sync.json` survivent à la mise à jour.
- Si un client est **hors-ligne**, il se mettra à jour à son prochain démarrage
  **avec** internet — aucune perte.
