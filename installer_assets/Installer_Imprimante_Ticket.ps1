# EMAB-SKS - Installation de l'imprimante a tickets (Epson TM-T20III, POS-80, ...)
#
# Lance par Installer_Imprimante_Ticket.cmd. Ce script :
#   1. demande les droits administrateur (necessaires pour installer un pilote) ;
#   2. detecte une imprimante a tickets deja installee (pilote Epson "Receipt", POS...) ;
#   3. sinon, installe l'imprimante USB avec le pilote Windows "Generic / Text Only",
#      qui suffit a EMAB Gestionnaire (impression ESC/POS directe) ;
#   4. ecrit les reglages d'impression pour l'application (print_config.json) ;
#   5. imprime un ticket de test ESC/POS.
#
# Options : -PrinterName "EMAB Ticket"  -PaperWidth 80|58  -NoTest
#
# Pour la console web locale (tickets HTML via Chrome), le pilote Epson
# "Advanced Printer Driver" reste preferable : installez-le avant de lancer ce
# script, il sera detecte et utilise tel quel.

param(
    [string]$PrinterName = "EMAB Ticket",
    [string]$PaperWidth = "80",
    [switch]$NoTest
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "EMAB-SKS - Installation de l'imprimante a tickets"

function Pause-Exit([int]$code) {
    Write-Host ""
    Read-Host "Appuyez sur Entree pour fermer" | Out-Null
    exit $code
}

# ---------------------------------------------------------------- 1. Elevation
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Demande des droits administrateur..."
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PrinterName `"$PrinterName`" -PaperWidth $PaperWidth"
    if ($NoTest) { $args += " -NoTest" }
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit
}

Write-Host "=============================================================="
Write-Host "  EMAB-SKS - Installation de l'imprimante a tickets"
Write-Host "=============================================================="
Write-Host ""

if ($PaperWidth -ne "58") { $PaperWidth = "80" }

# ------------------------------------------- 2. Imprimante a tickets existante
$thermalWords = @("pos", "thermal", "ticket", "receipt", "caisse", "58mm", "80mm",
                  "xprinter", "rongta", "pozer", "tp150",
                  "epson tm", "tm-t", "tm-m", "tm-u", "tm-p", "tm-l")
$virtualWords = @("pdf", "xps", "onenote", "fax", "anydesk", "send to")

function Is-Thermal([string]$name) {
    $n = $name.ToLower()
    foreach ($w in $virtualWords) { if ($n.Contains($w)) { return $false } }
    foreach ($w in $thermalWords) { if ($n.Contains($w)) { return $true } }
    return $false
}

$queues = @(Get-Printer)
$printers = @($queues | Select-Object -ExpandProperty Name)
$existing = @($printers | Where-Object { Is-Thermal $_ })
$chosen = $null

# Imprimante USB branchee mais sans file d'impression (ex. TM-T20III que
# Windows vient de reconnaitre via "Prise en charge d'impression USB") :
# on l'installe sur SON port, meme si une ancienne thermique existe deja.
$newDev = $null
$usbPrintDevs = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
                  Where-Object { $_.InstanceId -like "USBPRINT\*" })
foreach ($d in $usbPrintDevs) {
    if ($d.InstanceId -match "&(USB\d{3})$") {
        $p = $Matches[1]
        $used = @($queues | Where-Object { $_.PortName -eq $p })
        if ($used.Count -eq 0) {
            $model = ($d.InstanceId -split "\\")[1] -replace "^EPSON", "EPSON "
            $newDev = @{ Port = $p; Model = $model }
            break
        }
    }
}

if ($newDev) {
    $port = $newDev.Port
    if ($PrinterName -eq "EMAB Ticket") { $PrinterName = "$($newDev.Model) Ticket" }
    Write-Host "Imprimante USB detectee sans pilote : $($newDev.Model) sur $port"
    if (-not (Get-PrinterDriver -Name "Generic / Text Only" -ErrorAction SilentlyContinue)) {
        Write-Host "Installation du pilote Windows 'Generic / Text Only'..."
        Add-PrinterDriver -Name "Generic / Text Only"
    }
    if (Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue) {
        Remove-Printer -Name $PrinterName
    }
    Add-Printer -Name $PrinterName -DriverName "Generic / Text Only" -PortName $port
    $chosen = $PrinterName
    Write-Host "[OK] Imprimante '$PrinterName' installee sur $port."
} elseif ($existing.Count -gt 0) {
    # Le pilote constructeur (ex. "EPSON TM-T20III Receipt") est prioritaire sur
    # une eventuelle installation generique precedente.
    $vendor = @($existing | Where-Object { $_ -ne $PrinterName })
    if ($vendor.Count -gt 0) { $chosen = $vendor[0] } else { $chosen = $existing[0] }
    Write-Host "[OK] Imprimante a tickets deja installee : $chosen"
} else {
    # ----------------------------------------------------- 3. Port USB + pilote
    $usbPorts = @(Get-PrinterPort | Where-Object { $_.Name -like "USB*" } | Select-Object -ExpandProperty Name | Sort-Object)
    if ($usbPorts.Count -eq 0) {
        Write-Host "[ERREUR] Aucun port USB d'imprimante detecte."
        Write-Host "         Branchez l'imprimante en USB, allumez-la, attendez 10 secondes"
        Write-Host "         que Windows la reconnaisse, puis relancez ce fichier."
        Pause-Exit 1
    }
    # Ports deja utilises par une autre imprimante : on prefere un port libre.
    $usedPorts = @(Get-Printer | Select-Object -ExpandProperty PortName)
    $free = @($usbPorts | Where-Object { $usedPorts -notcontains $_ })
    if ($free.Count -gt 0) { $port = $free[-1] } else { $port = $usbPorts[-1] }
    Write-Host "Port USB retenu : $port  (ports USB disponibles : $($usbPorts -join ', '))"

    if (-not (Get-PrinterDriver -Name "Generic / Text Only" -ErrorAction SilentlyContinue)) {
        Write-Host "Installation du pilote Windows 'Generic / Text Only'..."
        Add-PrinterDriver -Name "Generic / Text Only"
    }
    if (Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue) {
        Remove-Printer -Name $PrinterName
    }
    Add-Printer -Name $PrinterName -DriverName "Generic / Text Only" -PortName $port
    $chosen = $PrinterName
    Write-Host "[OK] Imprimante '$PrinterName' installee sur $port."
}

# ------------------------------------------ 4. Reglages pour EMAB Gestionnaire
$appDir = Join-Path $env:LOCALAPPDATA "EMAB GROUP\Gestionnaire"
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
$cfg = [ordered]@{
    receipt_printer = $chosen
    paper_width     = $PaperWidth
    auto_print      = $true
}
$cfgPath = Join-Path $appDir "print_config.json"
[IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
Write-Host "[OK] Reglages ecrits : $cfgPath"
Write-Host "     (appliques au prochain demarrage d'EMAB Gestionnaire, version 1.1.14 ou plus)"

# --------------------------------------------------------- 5. Ticket de test
if (-not $NoTest) {
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
    public static bool Send(string printer, byte[] data) {
        IntPtr h;
        if (!OpenPrinter(printer, out h, IntPtr.Zero)) return false;
        var di = new DOCINFO { pDocName = "Ticket test EMAB-SKS", pDataType = "RAW" };
        bool ok = false;
        if (StartDocPrinter(h, 1, ref di) != 0) {
            StartPagePrinter(h);
            int w;
            ok = WritePrinter(h, data, data.Length, out w) && w == data.Length;
            EndPagePrinter(h);
            EndDocPrinter(h);
        }
        ClosePrinter(h);
        return ok;
    }
}
"@
    try {
        Add-Type -TypeDefinition $code -ErrorAction Stop
        $ESC = [char]27; $GS = [char]29
        $cols = if ($PaperWidth -eq "58") { 32 } else { 48 }
        $sep = "-" * $cols
        $txt  = "$ESC@" + "$ESC" + "t" + [char]19 + "$ESC" + "R" + [char]1
        $txt += "$ESC" + "a" + [char]1
        $txt += "$ESC" + "E" + [char]1 + "$GS" + "!" + [char]0x11 + "EMAB-SKS`n" + "$GS" + "!" + [char]0 + "$ESC" + "E" + [char]0
        $txt += "TICKET DE TEST`n" + (Get-Date -Format "yyyy-MM-dd HH:mm") + "`n" + $sep + "`n"
        $txt += "$ESC" + "a" + [char]0
        $txt += "Imprimante : $chosen`nLargeur    : $PaperWidth mm`nAccents    : " + [char]0xE9 + [char]0xE8 + [char]0xE0 + [char]0xE7 + " " + [char]0x20AC + "`n" + $sep + "`n"
        $txt += "$ESC" + "a" + [char]1 + "Si ce ticket est lisible et coupe,`nl'imprimante est prete.`n`n`n"
        $txt += "$GS" + "V" + [char]66 + [char]3
        $bytes = [Text.Encoding]::GetEncoding(858).GetBytes($txt)
        if ([EmabRawPrint]::Send($chosen, $bytes)) {
            Write-Host "[OK] Ticket de test envoye a '$chosen'."
        } else {
            Write-Host "[ATTENTION] Le ticket de test n'a pas pu etre envoye (imprimante eteinte ?)."
        }
    } catch {
        Write-Host "[ATTENTION] Ticket de test impossible : $($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "Termine. Dans EMAB Gestionnaire : Administration > Impression des tickets"
Write-Host "pour verifier ou modifier (imprimante : $chosen, papier : $PaperWidth mm)."
Pause-Exit 0
