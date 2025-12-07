#requires -Version 5.1
$ErrorActionPreference = 'Stop'

Write-Host "[MILPA] Construyendo y levantando toda la plataforma..." -ForegroundColor Cyan

# 1) Levantar/actualizar servicios en segundo plano SIN reconstruir imágenes
Write-Host "[MILPA] Levantando servicios (sin build)…" -ForegroundColor DarkCyan
docker-compose --project-directory "$PSScriptRoot" up -d

# 3) Espera activa por salud de servicios
$backendUrl    = "http://localhost:8000"
$presenterUrl  = "http://localhost:8080"
$prometheusUrl = "http://localhost:9090"
$grafanaUrl    = "http://localhost:3000"

function Wait-HttpReady {
    param(
        [Parameter(Mandatory)] [string] $Url,
        [Parameter()] [int] $Retries = 30,
        [Parameter()] [int] $DelaySec = 2
    )
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec 10
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Host "[READY] $Url" -ForegroundColor Green
                return $true
            }
        } catch {
            Write-Host "[WAIT] $Url (intento $i/$Retries)" -ForegroundColor Yellow
        }
        Start-Sleep -Seconds $DelaySec
    }
    throw "Timeout esperando $Url"
}

Write-Host "[MILPA] Esperando Backend (health)..." -ForegroundColor DarkCyan
Wait-HttpReady -Url "$backendUrl/health"

Write-Host "[MILPA] Esperando Presenter (metrics)..." -ForegroundColor DarkCyan
Wait-HttpReady -Url "$presenterUrl/metrics"

Write-Host "[MILPA] Esperando Prometheus (ready)..." -ForegroundColor DarkCyan
Wait-HttpReady -Url "$prometheusUrl/-/ready"

Write-Host "[MILPA] Esperando Grafana (health)..." -ForegroundColor DarkCyan
Wait-HttpReady -Url "$grafanaUrl/api/health"

# 4) Comprobaciones rápidas
Write-Host "[MILPA] Comprobaciones rápidas de métricas y salud" -ForegroundColor Cyan
Invoke-RestMethod -Uri "$backendUrl/health" -Method GET -TimeoutSec 10 | ConvertTo-Json -Depth 4 | Write-Output
Invoke-RestMethod -Uri "$backendUrl/metrics" -Method GET -TimeoutSec 10 | Select-String -Pattern "http_requests_total" | Write-Output
Invoke-RestMethod -Uri "$presenterUrl/metrics" -Method GET -TimeoutSec 10 | Select-String -Pattern "milpa_proxy_total|nodejs_version_info" | Write-Output
Invoke-RestMethod -Uri "$prometheusUrl/-/ready" -Method GET -TimeoutSec 10 | Write-Output
Invoke-RestMethod -Uri "$grafanaUrl/api/health" -Method GET -TimeoutSec 10 | ConvertTo-Json -Depth 4 | Write-Output

# 4.1) Reconstrucción de índices (BM25 + Vector) con entidades
Write-Host "[MILPA] Reconstruyendo índices (BM25 + vector) con entidades…" -ForegroundColor Cyan
try {
    $rebuild = Invoke-WebRequest -Uri "$backendUrl/api/index/rebuild" -Method POST -TimeoutSec 120
    ($rebuild.Content | ConvertFrom-Json) | ConvertTo-Json -Depth 4 | Write-Output
} catch {
    Write-Warning "[MILPA] Falló la reconstrucción de índices: $($_.Exception.Message)"
}

# 5) Consulta RAG de verificación (UTF-8 bytes para PowerShell)
Write-Host "[MILPA] Ejecutando consulta RAG de verificación..." -ForegroundColor Cyan
$payload = @{ query = "Fertilizacion recomendada de N para maiz en macollaje"; k = 8; mode = "hybrid" } | ConvertTo-Json -Depth 4
$bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
$resp = Invoke-WebRequest -Uri "$backendUrl/api/query" -Method POST -ContentType "application/json" -Body $bytes -TimeoutSec 30
($resp.Content | ConvertFrom-Json) | Select-Object query, mode, answer_mode, total_retrieved, insufficient_evidence | Format-List

# 6) Mostrar URL útiles
Write-Host "[MILPA] URLs de acceso" -ForegroundColor Cyan
Write-Host "  Backend (health):      $backendUrl/health" -ForegroundColor White
Write-Host "  Backend (metrics):     $backendUrl/metrics" -ForegroundColor White
Write-Host "  Backend (biblioteca):  $backendUrl/library" -ForegroundColor Yellow
Write-Host "  Presenter (checks):    $presenterUrl/ui/checks" -ForegroundColor White
Write-Host "  Presenter (biblioteca):$presenterUrl/ui/library" -ForegroundColor Yellow
Write-Host "  Presenter (consultas): $presenterUrl/ui/query" -ForegroundColor Yellow
Write-Host "  Prometheus:            $prometheusUrl" -ForegroundColor White
Write-Host "  Grafana:               $grafanaUrl" -ForegroundColor White

Write-Host "`n[MILPA] Plataforma operativa. Abre la biblioteca en: $presenterUrl/ui/library" -ForegroundColor Green
