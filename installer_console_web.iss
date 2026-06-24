; Installateur Windows — EMAB GROUP / Console web locale (hors-ligne)
; Compiler : ISCC.exe installer_console_web.iss
; (nécessite server\dist\EMAB-Console-Web.exe, produit par PyInstaller)

#define MyAppName "EMAB Console Web"
#define MyAppPublisher "EMAB GROUP"
#define MyAppVersion "1.0.11"
#define MyAppExeName "EMAB-Console-Web.exe"

[Setup]
AppId={{4C7D91B2-5E80-4F36-9D1A-7B0E52C8A613}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Installation par utilisateur : aucun droit administrateur requis
PrivilegesRequired=lowest
DefaultDirName={userpf}\EMAB Console Web
DisableProgramGroupPage=yes
SetupIconFile=assets\logo_emab.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=dist
OutputBaseFilename=EMAB-Console-Web-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; Coché par défaut : la console démarre avec Windows (minimisée, en arrière-plan)
; pour que la synchronisation soit toujours active sans intervention.
Name: "startupicon"; Description: "Démarrer automatiquement avec Windows (synchronisation toujours active)"; GroupDescription: "Synchronisation :"

[Files]
; Mode onedir : on installe le dossier complet (démarrage rapide, pas
; d'auto-extraction à chaque lancement comme en onefile).
Source: "server\dist\EMAB-Console-Web\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Lanceur silencieux placé dans le démarrage Windows si la tâche est cochée.
Source: "installer_assets\EMAB-Console-Web-demarrage.vbs"; DestDir: "{userstartup}"; Tasks: startupicon; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userprograms}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Les données (%LOCALAPPDATA%\EMAB GROUP\ConsoleWeb) sont conservées :
; base, clé secrète et jeton survivent à une réinstallation.
Type: filesandordirs; Name: "{app}"
; Retire le lanceur de démarrage automatique.
Type: files; Name: "{userstartup}\EMAB-Console-Web-demarrage.vbs"
