@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ". '%~dp0Environment.ps1'; & $env:W2A_CODEX_BINARY login"
pause
