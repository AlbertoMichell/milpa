@echo off
REM ============================================================================
REM MILPA — Detener servicios (delega en stop.ps1)
REM ============================================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo.
pause
