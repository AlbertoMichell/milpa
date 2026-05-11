#requires -Version 5.1
# ============================================================================
# MILPA - Detener todos los servicios (por puerto; compatible con start.ps1)
# Uso: .\stop.ps1
# Puertos: 8000 backend | 8080 presenter | 4000 frontend Express
# ============================================================================
Write-Host "[MILPA] Deteniendo servicios..." -ForegroundColor Yellow

function Stop-PortProcess([int]$Port) {
    try {
        $listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listen) {
            $pids = $listen | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($pidToStop in $pids) {
                if ($pidToStop -and $pidToStop -ne $PID) {
                    Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
                    Write-Host "  Puerto $Port liberado (PID $pidToStop)" -ForegroundColor Gray
                }
            }
        }
    } catch { }
}

foreach ($port in @(8000, 8080, 4000)) {
    Stop-PortProcess -Port $port
}

Write-Host "[MILPA] Servicios detenidos." -ForegroundColor Green
