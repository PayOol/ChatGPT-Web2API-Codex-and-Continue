@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Doctor.ps1" %*
pause
