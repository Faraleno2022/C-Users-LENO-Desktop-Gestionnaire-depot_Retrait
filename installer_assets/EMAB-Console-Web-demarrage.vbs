' Demarrage automatique de la console web EMAB GROUP avec Windows.
' Lance le serveur local minimise dans la barre des taches, sans ouvrir
' le navigateur. La replication vers le serveur en ligne demarre toute seule.
Set sh = CreateObject("WScript.Shell")
sh.Environment("Process")("EMAB_NO_BROWSER") = "1"
exePath = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\EMAB Console Web\EMAB-Console-Web.exe"
If CreateObject("Scripting.FileSystemObject").FileExists(exePath) Then
    ' 7 = fenetre minimisee, sans prendre le focus
    sh.Run """" & exePath & """", 7, False
End If
