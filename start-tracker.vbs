' Starts the time tracker silently (no console window).
' Uses the script's own directory, so it works wherever you put the repo.
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = scriptDir
sh.Run "pythonw tracker.py", 0, False
