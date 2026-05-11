@echo off
REM ============================================================================
REM MILPA — Punto de entrada unificado (delega en start.ps1)
REM Misma lógica que:  Set-ExecutionPolicy -Scope Process Bypass; .\start.ps1
REM Puertos: Backend :8000 | Presenter :8080 | Frontend :4000
REM ============================================================================
setlocal
cd /d "%~dp0"
title MILPA - iniciando...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "EXITCODE=%ERRORLEVEL%"
endlocal & exit /b %EXITCODE%
