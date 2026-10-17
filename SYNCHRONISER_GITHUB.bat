@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

rem ============================================================
rem  SYNCHRONISER_GITHUB.bat
rem  Double-cliquer pour envoyer le projet sur GitHub :
rem    https://github.com/Faraleno2022/EMAB_SKS.git
rem  1. Enregistre les modifications locales (commit)
rem  2. Récupère les modifications distantes (pull --rebase)
rem  3. Envoie le tout sur GitHub (push)
rem ============================================================

set "DEPOT=https://github.com/Faraleno2022/EMAB_SKS.git"
set "BRANCHE=main"

cd /d "%~dp0"

echo.
echo ============================================================
echo   Synchronisation du projet avec GitHub
echo   Dossier : %CD%
echo   Depot   : %DEPOT%
echo ============================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Git n'est pas installe ou n'est pas dans le PATH.
    echo          Telechargez-le sur https://git-scm.com/download/win
    goto :fin_erreur
)

if not exist ".git" (
    echo [ERREUR] Ce dossier n'est pas un depot Git.
    goto :fin_erreur
)

rem --- Configurer le remote "origin" vers le bon depot ---------------
set "ORIGINE="
for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do set "ORIGINE=%%u"
if "%ORIGINE%"=="" (
    echo [INFO] Ajout du remote origin : %DEPOT%
    git remote add origin "%DEPOT%" || goto :fin_erreur
) else if /i not "%ORIGINE%"=="%DEPOT%" (
    echo [INFO] Remote origin mis a jour :
    echo        ancien : %ORIGINE%
    echo        nouveau: %DEPOT%
    git remote set-url origin "%DEPOT%" || goto :fin_erreur
)

rem --- Se placer sur la branche principale ---------------------------
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "COURANTE=%%b"
if /i not "%COURANTE%"=="%BRANCHE%" (
    echo [INFO] Branche courante : %COURANTE% - passage sur %BRANCHE%
    git checkout "%BRANCHE%" || goto :fin_erreur
)

rem --- 1. Enregistrer les modifications locales ----------------------
echo.
echo [1/3] Modifications locales :
git status --short
git add -A
git diff --cached --quiet
if errorlevel 1 (
    set "MSG="
    set /p MSG=Message de la mise a jour (Entree = message automatique) : 
    if "!MSG!"=="" set "MSG=Synchronisation du %DATE% %TIME:~0,8%"
    git commit -m "!MSG!" || goto :fin_erreur
) else (
    echo        Aucune modification a enregistrer.
)

rem --- 2. Recuperer les modifications distantes ----------------------
echo.
echo [2/3] Recuperation des modifications distantes...
git ls-remote --exit-code --heads origin "%BRANCHE%" >nul 2>&1
if errorlevel 1 (
    echo        Le depot distant est vide : premier envoi.
) else (
    git pull --rebase origin "%BRANCHE%"
    if errorlevel 1 (
        echo.
        echo [ERREUR] Conflit lors de la recuperation. Resolvez les conflits puis
        echo          relancez ce fichier. Pour annuler : git rebase --abort
        goto :fin_erreur
    )
)

rem --- 3. Envoyer sur GitHub ----------------------------------------
echo.
echo [3/3] Envoi sur GitHub...
git push -u origin "%BRANCHE%" || goto :fin_erreur

echo.
echo ============================================================
echo   Synchronisation terminee avec succes.
echo   https://github.com/Faraleno2022/EMAB_SKS
echo ============================================================
echo.
pause
exit /b 0

:fin_erreur
echo.
echo ============================================================
echo   La synchronisation a echoue. Lisez le message ci-dessus.
echo ============================================================
echo.
pause
exit /b 1
