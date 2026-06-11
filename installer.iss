; Installateur Windows — EMAB GROUP / Gestionnaire Dépôt-Retrait
; Compiler : ISCC.exe installer.iss   (nécessite dist\EMAB-Gestionnaire.exe,
; produit par : python -m PyInstaller EMAB-Gestionnaire.spec)

#define MyAppName "EMAB Gestionnaire"
#define MyAppPublisher "EMAB GROUP"
#define MyAppVersion "1.0.0"
#define MyAppExeName "EMAB-Gestionnaire.exe"

[Setup]
AppId={{8B5F2E4A-9C31-4D7E-A6B8-3F2C61E0D9A4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Installation par utilisateur : aucun droit administrateur requis
PrivilegesRequired=lowest
DefaultDirName={userpf}\EMAB Gestionnaire
DisableProgramGroupPage=yes
; Icône de l'installateur et de la désinstallation
SetupIconFile=assets\logo_emab.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=dist
OutputBaseFilename=EMAB-Gestionnaire-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
; Coché par défaut : raccourci sur le bureau
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Raccourci bureau
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
; Menu Démarrer
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userprograms}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Ne supprime PAS les données (%LOCALAPPDATA%\EMAB GROUP\Gestionnaire) :
; la base, les sauvegardes et exports survivent à une réinstallation.
Type: filesandordirs; Name: "{app}"
