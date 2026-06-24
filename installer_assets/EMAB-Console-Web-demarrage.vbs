' Demarrage automatique de la console web EMAB GROUP avec Windows.
'   1) Applique une mise a jour en attente, si presente (sans toucher aux donnees).
'   2) Lance la console minimisee, sans ouvrir le navigateur.
' La replication vers le serveur en ligne demarre toute seule.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

dataDir = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\EMAB GROUP\ConsoleWeb"
flag = dataDir & "\update_pending.flag"

' --- Mise a jour en attente ? (telechargee lors d'une session precedente) ---
If fso.FileExists(flag) Then
    On Error Resume Next
    installer = ""
    Set f = fso.OpenTextFile(flag, 1)
    If Not (f Is Nothing) Then
        installer = Trim(f.ReadAll)
        f.Close
    End If
    If installer <> "" And fso.FileExists(installer) Then
        ' La console n'est pas encore lancee : l'exe n'est pas verrouille.
        ' /VERYSILENT installe sans rien demander ; les donnees (dossier
        ' EMAB GROUP\ConsoleWeb) ne sont jamais touchees par l'installateur.
        sh.Run """" & installer & """ /VERYSILENT /SUPPRESSMSGBOXES /NORESTART", 0, True
        fso.DeleteFile installer, True
    End If
    If fso.FileExists(flag) Then fso.DeleteFile flag, True
    On Error GoTo 0
End If

' --- Lancement de la console ---
sh.Environment("Process")("EMAB_NO_BROWSER") = "1"
exePath = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\EMAB Console Web\EMAB-Console-Web.exe"
If fso.FileExists(exePath) Then
    ' 0 = fenetre cachee (la console est de toute facon compilee en mode
    ' fenetre : aucune fenetre noire ne s'affiche pour l'utilisateur).
    sh.Run """" & exePath & """", 0, False
End If
