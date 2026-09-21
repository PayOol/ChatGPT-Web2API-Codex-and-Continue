@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\installer\Setup.ps1" -InstallRoot "%~dp0." %*
pause
