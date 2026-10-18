@echo off
rem ============================================================
rem  EMAB-SKS - Installer l'imprimante a tickets en un clic
rem  (Epson TM-T20III, POS-80 et autres imprimantes thermiques USB)
rem
rem  Double-cliquez : Windows demande les droits administrateur,
rem  l'imprimante est installee (pilote constructeur deja present
rem  ou pilote Windows "Generic / Text Only"), les reglages sont
rem  ecrits pour EMAB Gestionnaire et un ticket de test est imprime.
rem
rem  Options : Installer_Imprimante_Ticket.cmd -PaperWidth 58
rem            Installer_Imprimante_Ticket.cmd -PrinterName "Caisse 2"
rem            Installer_Imprimante_Ticket.cmd -NoTest
rem ============================================================
setlocal
set "PS1=%~dp0installer_assets\Installer_Imprimante_Ticket.ps1"
if not exist "%PS1%" set "PS1=%~dp0Installer_Imprimante_Ticket.ps1"
if not exist "%PS1%" (
    echo [ERREUR] Script introuvable : Installer_Imprimante_Ticket.ps1
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
endlocal
