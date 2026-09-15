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

## Publier une mise à jour du Gestionnaire (application bureau)

Depuis la console **1.0.21**, chaque poste client installe et met à jour aussi
l'application bureau « EMAB Gestionnaire » automatiquement : au démarrage, la
console compare la version publiée sur GitHub à celle installée sur le poste
(ou l'installe si elle est absente), en silencieux. L'installateur du
Gestionnaire crée **son propre raccourci** « EMAB Gestionnaire » sur le Bureau,
distinct de celui de la console. Si le Gestionnaire est ouvert à ce moment-là,
l'installation est simplement reportée au prochain démarrage de la console.

### À faire à chaque nouvelle version du Gestionnaire
1. Incrémente la version à **deux** endroits (la même valeur) :
   - `app/config.py` → `APP_VERSION = "1.1.1"`
   - `installer.iss` → `#define MyAppVersion "1.1.1"`
2. Recompile :
   ```
   python -m PyInstaller --noconfirm EMAB-Gestionnaire.spec
   ISCC.exe installer.iss
   ```
   Cela produit `dist\EMAB-Gestionnaire-Setup-1.1.1.exe`.
3. Publie la release avec un tag **`desktop-v1.1.1`** (préfixe `desktop-v`
   obligatoire), cochée **pre-release** pour ne pas perturber `/releases/latest`
   utilisé par la console :
   ```
   gh release create desktop-v1.1.1 "dist/EMAB-Gestionnaire-Setup-1.1.1.exe" --title "Gestionnaire 1.1.1" --prerelease --notes "..."
   ```
4. Le nom de l'installateur doit contenir **`Gestionnaire-Setup`** (nom par
   défaut : rien à changer).

Une fois installé en 1.1.0 ou plus, le Gestionnaire vérifie aussi lui-même les
mises à jour à chaque lancement — la console sert surtout à l'installer la
première fois et à rattraper les postes en retard.

## Points importants
- **Le nom de l'installateur doit contenir `Console-Web-Setup`** (c'est ainsi que
  les clients le reconnaissent dans la release). Le nom par défaut convient.
- **Le tag doit être un numéro supérieur** à la version installée, sinon rien ne
  se passe (normal).
- **Les données du client sont conservées** : base, sauvegardes, clé secrète,
  jeton et configuration `render_sync.json` survivent à la mise à jour.
- Si un client est **hors-ligne**, il se mettra à jour à son prochain démarrage
  **avec** internet — aucune perte.
