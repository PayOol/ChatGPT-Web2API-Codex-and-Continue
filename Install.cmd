@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Setup.ps1" %*
if errorlevel 1 (echo. & echo Installation interrompue. Consultez le journal affiche ci-dessus. & pause & exit /b 1)
echo.
echo Installation terminee.
pause
