@echo off
rem ============================================================
rem  EMAB GROUP - Configurer la synchronisation en un clic
rem  Double-cliquez sur ce fichier : une fenetre permet de saisir
rem  l'URL du serveur, le jeton du poste et le nom du poste, de
rem  tester la connexion et d'enregistrer la configuration.
rem
rem  Options (invite de commandes) :
rem    Configurer_Synchronisation.bat --apply     applique sync_config.json sans fenetre
rem    Configurer_Synchronisation.bat --console   mode texte (sans Tkinter)
rem    Configurer_Synchronisation.bat --db "C:\chemin\gestionnaire.db"
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if not defined PYEXE (
    where py >nul 2>&1 && set "PYEXE=py -3"
)
if not defined PYEXE (
    where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo.
    echo [ERREUR] Python 3 est introuvable sur ce poste.
    echo Installez Python depuis https://www.python.org/downloads/ ^(cochez "Add to PATH"^)
    echo puis relancez ce fichier.
    echo.
    pause
    exit /b 1
)

%PYEXE% "tools\configurer_sync.py" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo La configuration s'est terminee avec le code %RC%.
    pause
)
endlocal & exit /b %RC%
