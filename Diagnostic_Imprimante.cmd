<# : Diagnostic de l'imprimante a tickets (fichier autonome)
@echo off
rem ============================================================
rem  Diagnostic de l'imprimante a tickets (Epson TM-T20III, POS-80...)
rem
rem  Double-cliquez : le fichier controle le service d'impression,
rem  les imprimantes installees, le cable USB, les travaux bloques
rem  et les reglages de l'application, puis ecrit un rapport
rem  diagnostic_imprimante.txt sur le Bureau.
rem
rem  CE FICHIER SE SUFFIT A LUI-MEME : copiez-le seul sur le poste.
rem
rem  Options : Diagnostic_Imprimante.cmd -Test       imprime un ticket de test
rem            Diagnostic_Imprimante.cmd -Repair     vide la file et relance le spouleur (admin)
rem            Diagnostic_Imprimante.cmd -PrinterName "EPSON TM-T20III Ticket"
rem ============================================================
setlocal
set "EMAB_SELF=%~f0"
set "ARGS=%*"
if defined ARGS set "ARGS=%ARGS:"='%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create([IO.File]::ReadAllText($env:EMAB_SELF))) %ARGS%"
endlocal & exit /b %ERRORLEVEL%
#>
# Diagnostic de l'imprimante a tickets - script PowerShell embarque dans le .cmd.

param(
    [switch]$Test,
    [switch]$Repair,
    [switch]$NoPause,
    [string]$PrinterName = ""
)

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "Diagnostic de l'imprimante a tickets"

$report = New-Object System.Collections.Generic.List[string]
$problems = New-Object System.Collections.Generic.List[string]

function Say([string]$text, [string]$color = "") {
    if ($color) { Write-Host $text -ForegroundColor $color } else { Write-Host $text }
    $report.Add($text)
}
function Section([string]$title) { Say ""; Say ("=== " + $title + " ===") "Cyan" }
function Problem([string]$text) { $problems.Add($text); Say ("[PROBLEME] " + $text) "Red" }
function Ok([string]$text) { Say ("[OK] " + $text) "Green" }

function Finish([int]$code) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $path = Join-Path $desktop "diagnostic_imprimante.txt"
    try { [IO.File]::WriteAllLines($path, $report.ToArray(), (New-Object Text.UTF8Encoding $true)) } catch { $path = "(rapport non enregistre : $($_.Exception.Message))" }
    Write-Host ""
    Write-Host "Rapport enregistre : $path" -ForegroundColor Yellow
    if (-not $NoPause) {
        Write-Host ""
        try { Read-Host "Appuyez sur Entree pour fermer" | Out-Null } catch {}
    }
    exit $code
}

# ------------------------------------------------------------- elevation (reparation)
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Repair -and -not $isAdmin) {
    Write-Host "La reparation demande les droits administrateur..."
    $self = $env:EMAB_SELF
    $inner = "& ([scriptblock]::Create([IO.File]::ReadAllText('" + $self.Replace("'", "''") + "'))) -Repair"
    if ($Test) { $inner += " -Test" }
    if ($PrinterName) { $inner += " -PrinterName '" + $PrinterName.Replace("'", "''") + "'" }
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"$inner`""
    exit
}

$thermalWords = @("pos", "thermal", "ticket", "receipt", "caisse", "58mm", "80mm",
                  "xprinter", "rongta", "pozer", "tp150",
                  "epson tm", "tm-t", "tm-m", "tm-u", "tm-p", "tm-l")
$virtualWords = @("pdf", "xps", "onenote", "fax", "anydesk", "send to")
function Is-Virtual([string]$name) { $n = $name.ToLower(); foreach ($w in $virtualWords) { if ($n.Contains($w)) { return $true } }; return $false }
function Is-Thermal([string]$name) {
    if (Is-Virtual $name) { return $false }
    $n = $name.ToLower(); foreach ($w in $thermalWords) { if ($n.Contains($w)) { return $true } }; return $false
}

Say "=============================================================="
Say "  Diagnostic de l'imprimante a tickets"
Say "=============================================================="

# ------------------------------------------------------------------ 1. Systeme
Section "1. Poste"
$os = ""
try { $os = (Get-CimInstance Win32_OperatingSystem).Caption } catch {}
Say ("Date        : " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Say ("Poste       : " + $env:COMPUTERNAME + "  (utilisateur " + $env:USERNAME + ")")
Say ("Windows     : " + $os)
Say ("Administrateur : " + $(if ($isAdmin) { "oui" } else { "non" }))

# -------------------------------------------------------------- 2. Spouleur
Section "2. Service d'impression (spouleur)"
$spooler = Get-Service -Name Spooler -ErrorAction SilentlyContinue
if (-not $spooler) {
    Problem "Le service d'impression Windows (Spooler) est introuvable."
} elseif ($spooler.Status -ne "Running") {
    Problem ("Le service d'impression est " + $spooler.Status + ". Lancez : Diagnostic_Imprimante.cmd -Repair")
} else {
    Ok "Service d'impression en marche."
}

# ----------------------------------------------------------- 3. Imprimantes
Section "3. Imprimantes installees"
$printers = @()
try { $printers = @(Get-Printer -ErrorAction Stop) } catch { Problem ("Impossible de lister les imprimantes : " + $_.Exception.Message) }
$cim = @{}
try { Get-CimInstance Win32_Printer | ForEach-Object { $cim[$_.Name] = $_ } } catch {}
foreach ($p in $printers) {
    $tag = ""
    if (Is-Virtual $p.Name) { $tag = " [virtuelle]" } elseif (Is-Thermal $p.Name) { $tag = " [TICKET]" }
    $offline = ""
    if ($cim.ContainsKey($p.Name) -and $cim[$p.Name].WorkOffline) { $offline = "  HORS CONNEXION" }
    $default = ""
    if ($cim.ContainsKey($p.Name) -and $cim[$p.Name].Default) { $default = "  (par defaut)" }
    Say ("- " + $p.Name + $tag + $default)
    Say ("    pilote : " + $p.DriverName + "   port : " + $p.PortName + "   etat : " + $p.PrinterStatus + $offline)
}
$thermal = @($printers | Where-Object { Is-Thermal $_.Name })
if ($thermal.Count -eq 0) {
    Problem "Aucune imprimante a tickets installee. Lancez Installer_Imprimante_Ticket.cmd (imprimante branchee et allumee)."
}
# (l'etat de l'imprimante retenue est controle plus bas, apres sa selection)

# ------------------------------------------------------------ 4. USB
Section "4. Peripheriques USB d'impression"
$usb = @()
try { $usb = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object { $_.InstanceId -like "USBPRINT\*" -or $_.InstanceId -like "USB\VID_04B8*" }) } catch {}
if ($usb.Count -eq 0) {
    Problem "Aucune imprimante USB detectee par Windows : verifiez le cable, l'alimentation (voyant allume), un autre port USB (de preference directement sur le PC, sans hub)."
} else {
    foreach ($d in $usb) { Say ("- " + $d.Status + "  " + $d.FriendlyName + "   " + $d.InstanceId) }
    $bad = @($usb | Where-Object { $_.Status -ne "OK" })
    if ($bad.Count -gt 0) { Problem "Un peripherique USB d'impression est en erreur : debranchez/rebranchez l'imprimante, ou changez de port USB." }
    foreach ($d in $usb) {
        if ($d.InstanceId -match "&(USB\d{3})$") {
            $port = $Matches[1]
            $owner = @($printers | Where-Object { $_.PortName -eq $port })
            if ($owner.Count -eq 0) {
                Problem ("L'imprimante USB est sur le port " + $port + " mais aucune file d'impression ne l'utilise. Lancez Installer_Imprimante_Ticket.cmd.")
            } else {
                Ok ("Port " + $port + " relie a la file : " + $owner[0].Name)
            }
        }
    }
}

# --------------------------------------------------- 5. Imprimante choisie
Section "5. Imprimante utilisee par l'application"
$appDir = Join-Path $env:LOCALAPPDATA "EMAB GROUP\Gestionnaire"
$consoleDir = Join-Path $env:LOCALAPPDATA "EMAB GROUP\ConsoleWeb"
$requested = $PrinterName
foreach ($f in @("print_config.json", "print_config.applied.json")) {
    $path = Join-Path $appDir $f
    if (Test-Path $path) {
        $raw = (Get-Content $path -Raw -ErrorAction SilentlyContinue)
        Say ("Fichier " + $f + " : " + ($raw -replace "\s+", " ").Trim())
        if (-not $requested) {
            try { $requested = ($raw | ConvertFrom-Json).receipt_printer } catch {}
        }
    }
}
$consoleCfg = Join-Path $consoleDir "printer_config.json"
if (Test-Path $consoleCfg) { Say ("Console web locale (printer_config.json) : " + ((Get-Content $consoleCfg -Raw) -replace "\s+", " ").Trim()) }
if (-not (Test-Path $appDir)) { Say "Dossier de l'application introuvable : EMAB Gestionnaire n'a jamais ete lance sur ce compte Windows." }

$names = @($printers | Select-Object -ExpandProperty Name)
$selected = $null
if ($requested) {
    $match = @($names | Where-Object { $_ -ieq $requested })
    if ($match.Count -gt 0) { $selected = $match[0]; Ok ("Imprimante demandee trouvee : " + $selected) }
    else { Problem ("L'imprimante demandee '" + $requested + "' n'existe pas dans Windows. Choisissez la bonne dans Administration > Impression des tickets, ou relancez Installer_Imprimante_Ticket.cmd.") }
}
if (-not $selected -and $thermal.Count -gt 0) {
    $default = @($thermal | Where-Object { $cim.ContainsKey($_.Name) -and $cim[$_.Name].Default })
    if ($default.Count -gt 0) { $selected = $default[0].Name } else { $selected = $thermal[0].Name }
    Say ("Detection automatique : " + $selected)
}
if (-not $selected) { Say "Aucune imprimante a tickets retenue." }
if ($selected) {
    $sel = @($printers | Where-Object { $_.Name -eq $selected })
    if ($sel.Count -gt 0) {
        $sp = $sel[0]
        if ($cim.ContainsKey($sp.Name) -and $cim[$sp.Name].WorkOffline) {
            Problem ("'" + $sp.Name + "' est en mode HORS CONNEXION. Parametres > Imprimantes > " + $sp.Name + " > Ouvrir la file d'attente > menu Imprimante > decocher 'Utiliser l'imprimante hors connexion'.")
        } elseif ($sp.PrinterStatus.ToString() -notin @("Normal", "Idle", "Printing")) {
            Problem ("'" + $sp.Name + "' signale l'etat : " + $sp.PrinterStatus + " (papier, capot ouvert, imprimante eteinte ou debranchee ?).")
        } else {
            Ok ("'" + $sp.Name + "' est prete (etat : " + $sp.PrinterStatus + ").")
        }
    }
}

$ver = $null
try {
    $key = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8B5F2E4A-9C31-4D7E-A6B8-3F2C61E0D9A4}_is1" -ErrorAction Stop
    $ver = $key.DisplayVersion
} catch {}
if ($ver) {
    Say ("EMAB Gestionnaire installe : version " + $ver)
    try { if ([version]$ver -lt [version]"1.1.14") { Problem "Version trop ancienne : avant la 1.1.14, l'application n'imprime PAS directement sur l'imprimante a tickets. Ouvrez EMAB Gestionnaire (mise a jour telechargee au demarrage, installee au demarrage suivant) ou installez la derniere version depuis la page des releases." } } catch {}
} else {
    Say "EMAB Gestionnaire : version non trouvee (non installe pour ce compte Windows ?)."
}

# ---------------------------------------------------------- 6. File d'attente
Section "6. Travaux en attente"
$jobsTotal = 0
foreach ($p in $thermal) {
    $jobs = @()
    try { $jobs = @(Get-PrintJob -PrinterName $p.Name -ErrorAction Stop) } catch {}
    $jobsTotal += $jobs.Count
    if ($jobs.Count -eq 0) { Say ("- " + $p.Name + " : file vide") }
    else {
        Say ("- " + $p.Name + " : " + $jobs.Count + " travail(aux)")
        foreach ($j in $jobs) { Say ("    #" + $j.Id + "  " + $j.DocumentName + "  " + $j.JobStatus) }
        Problem "Des travaux restent bloques dans la file : les tickets suivants ne sortent pas. Lancez : Diagnostic_Imprimante.cmd -Repair"
    }
}

# -------------------------------------------------------------- 7. Reparation
if ($Repair) {
    Section "7. Reparation"
    $answer = "n"
    try { $answer = Read-Host "Vider TOUTES les files d'impression et redemarrer le service ? (o/n)" } catch {}
    if ($answer -match "^[oOyY]") {
        try {
            Stop-Service -Name Spooler -Force -ErrorAction Stop
            Get-ChildItem (Join-Path $env:SystemRoot "System32\spool\PRINTERS") -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
            Start-Service -Name Spooler -ErrorAction Stop
            Ok "Files videes et service d'impression redemarre. Reessayez d'imprimer."
        } catch { Problem ("Reparation impossible : " + $_.Exception.Message) }
    } else { Say "Reparation annulee." }
}

# ------------------------------------------------------------- 8. Ticket test
if ($Test) {
    Section "8. Ticket de test (ESC/POS direct)"
    if (-not $selected) { Problem "Pas d'imprimante a tickets a tester." }
    else {
        $code = @"
using System;
using System.Runtime.InteropServices;
public class EmabRawPrint {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DOCINFO { public string pDocName; public string pOutputFile; public string pDataType; }
    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool OpenPrinter(string n, out IntPtr h, IntPtr d);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool ClosePrinter(IntPtr h);
    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)] static extern int StartDocPrinter(IntPtr h, int level, ref DOCINFO di);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool EndDocPrinter(IntPtr h);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool StartPagePrinter(IntPtr h);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool EndPagePrinter(IntPtr h);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool WritePrinter(IntPtr h, byte[] b, int n, out int w);
    public static string Send(string printer, byte[] data) {
        IntPtr h;
        if (!OpenPrinter(printer, out h, IntPtr.Zero)) return "OpenPrinter a echoue (code " + Marshal.GetLastWin32Error() + ")";
        var di = new DOCINFO { pDocName = "Ticket test", pDataType = "RAW" };
        string result = "ok";
        if (StartDocPrinter(h, 1, ref di) == 0) { result = "StartDocPrinter a echoue (code " + Marshal.GetLastWin32Error() + ")"; }
        else {
            StartPagePrinter(h);
            int w;
            if (!WritePrinter(h, data, data.Length, out w) || w != data.Length) result = "WritePrinter incomplet " + w + "/" + data.Length + " (code " + Marshal.GetLastWin32Error() + ")";
            EndPagePrinter(h);
            EndDocPrinter(h);
        }
        ClosePrinter(h);
        return result;
    }
}
"@
        try {
            if (-not ("EmabRawPrint" -as [type])) { Add-Type -TypeDefinition $code -ErrorAction Stop }
            $ESC = [char]27; $GS = [char]29
            $txt  = "$ESC@" + "$ESC" + "t" + [char]19
            $txt += "$ESC" + "a" + [char]1 + "$ESC" + "E" + [char]1 + "TICKET DE TEST`n" + "$ESC" + "E" + [char]0
            $txt += (Get-Date -Format "yyyy-MM-dd HH:mm") + "`n" + ("-" * 40) + "`n"
            $txt += "Imprimante : $selected`nAccents : " + [char]0xE9 + [char]0xE8 + [char]0xE0 + [char]0xE7 + "`n`n`n"
            $txt += "$GS" + "V" + [char]66 + [char]3
            $bytes = [Text.Encoding]::GetEncoding(858).GetBytes($txt)
            $res = [EmabRawPrint]::Send($selected, $bytes)
            if ($res -eq "ok") { Ok ("Ticket de test envoye a '" + $selected + "'. Il doit sortir et etre coupe dans quelques secondes.") }
            else { Problem ("Envoi impossible a '" + $selected + "' : " + $res) }
        } catch { Problem ("Ticket de test impossible : " + $_.Exception.Message) }
    }
}

# ---------------------------------------------------------------- Conclusion
Section "Resultat"
if ($problems.Count -eq 0) {
    Ok "Aucun probleme detecte cote Windows."
    if (-not $Test) { Say "Etape suivante : lancez   Diagnostic_Imprimante.cmd -Test   pour imprimer un ticket de test." }
    else { Say "Si le ticket de test est sorti, la configuration Windows est bonne : verifiez ensuite Administration > Impression des tickets dans l'application." }
} else {
    Say ($problems.Count.ToString() + " probleme(s) detecte(s) :") "Yellow"
    $i = 1; foreach ($pb in $problems) { Say ("  " + $i + ". " + $pb); $i++ }
}
Finish 0
