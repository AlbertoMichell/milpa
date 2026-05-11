#requires -Version 5.1
# Encoding del archivo: UTF-8 con BOM (PowerShell 5.1 en Windows; si al guardar
# pierdes el BOM, pueden fallar cadenas con acentos). Cursor/VS Code: guardar como UTF-8 with BOM.
# ============================================================================
# MILPA - Launcher unificado (local, sin Docker)
#
# Uso (elige una):
#   .\start.ps1
#   .\start.bat                    (equivale a ExecutionPolicy Bypass + start.ps1)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
#
# Qué levanta (misma arquitectura; un solo flujo):
#   Puerto 8000  FastAPI + uvicorn  (milpa_ai_backend\main:app vía -m uvicorn)
#   Puerto 8080  Presenter         (milpa_presenter, proxy /ai/*, UI ingesta/biblioteca)
#   Puerto 4000  Frontend Express (frontend\server.js — login, dashboard MILPA, /api,
#                  chat AgroBot vía Socket.IO en el mismo proceso). Si editas server.js,
#                  reinicia el job de Node en :4000 (relanzar este script) para ver cambios.
#
# No hace falta ejecutar "node server.js" a mano en frontend salvo depuración:
#   si solo corres el Express sin el backend, :4000 no tendrá IA (usa AI_BACKEND_URL).
#
# Sincronización con el repo: el script fija el cwd en la raíz del proyecto,
# vuelve a ejecutar pip si cambia requirements.txt, npm si cambia package-lock,
# y recompila el presenter si cualquier .ts bajo milpa_presenter\src es más reciente
# que dist\server.js (evita dist obsoleto; alineado con CI: npm run build).
#
# Variables opcionales:
#   $env:MILPA_FORCE_SYNC = "1"    — fuerza pip + npm + tsc siempre.
#
# Extracción avanzada (backend pydantic-settings; solo si NO están ya definidas):
#   EXTRACT_BLOCK_LEVEL, EXTRACT_TOKEN_CHUNKER, EXTRACT_TARGET_TOKENS,
#   EXTRACT_OVERLAP_TOKENS, EMBED_MODEL — ver milpa_ai_backend/core/config.py
#
#   $env:MILPA_GEN_MANUAL_LECHUGA = "1" — tras migraciones, ejecuta
#                            milpa_ai_backend\tools\gen_manual_lechuga.py
#                            (PDF 2 columnas + TXT en docs\) para alinear
#                            documentación con el extractor block-level / visor.
#
#   $env:MILPA_RUN_E2E    = "<crop>" — al terminar de levantar todo, ejecuta
#                                       tools\e2e_crop.py para ese cultivo y
#                                       publica tools\e2e_<crop>_report.json.
#                                       Ejemplo: $env:MILPA_RUN_E2E = "lechuga"
#   $env:MILPA_E2E_DOC    = ruta a documento técnico .txt para el E2E. Default:
#                            docs\manual_<crop>_milpa_2026.txt
#   $env:MILPA_E2E_STRICT = "1"     — si el E2E falla, detiene los tres servicios
#                                       y sale con el código de salida del script
#                                       (1 = RESULTADO_FINAL MAL, 2 = fallo temprano).
#
#   $env:MILPA_DAEMON_SECONDS = N   — tras el arranque, sale solo tras N segundos
#                                       (smoke test / CI sin Ctrl+C). Ej.: N=90
#
# URLs útiles (extracción / RAG):
#   Visor bbox: http://localhost:4000/MILPA/visor.html
#   Chat en vivo (Socket.IO, mismo origen :4000 + JWT en handshake): dashboard tras login
# ============================================================================
$ErrorActionPreference = 'Stop'
$ROOT = $PSScriptRoot

# Todas las rutas relativas (yoyo, sqlite, etc.) asumen cwd = raíz del repo.
Push-Location $ROOT

if ($env:MILPA_FORCE_SYNC -eq "1") {
    Write-Host '  MILPA_FORCE_SYNC=1 - invalidando cache pip y npm, forzando build presenter...' -ForegroundColor Yellow
    Remove-Item (Join-Path $ROOT "milpa_ai_backend\.milpa_requirements.sha256") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $ROOT "milpa_presenter\.milpa_packagelock.sha256") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $ROOT "frontend\.milpa_packagelock.sha256") -ErrorAction SilentlyContinue
}

function Get-Sha256File([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Read-StoredHash([string]$StorePath) {
    if (-not (Test-Path $StorePath)) { return $null }
    return (Get-Content -LiteralPath $StorePath -Raw -ErrorAction SilentlyContinue).Trim()
}

function Write-StoredHash([string]$StorePath, [string]$Hash) {
    $dir = Split-Path -Parent $StorePath
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Set-Content -LiteralPath $StorePath -Value $Hash -Encoding utf8 -NoNewline
}

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Green
Write-Host "  MILPA - Sistema RAG Agricola" -ForegroundColor Green
Write-Host '  (8000 API | 8080 Presenter | 4000 MILPA Web)' -ForegroundColor DarkGray
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""

# --- Helpers -----------------------------------------------------------------

function Stop-PortProcess([int]$Port) {
    try {
        $listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listen) {
            $pids = $listen | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($pidToStop in $pids) {
                if ($pidToStop -and $pidToStop -ne $PID) {
                    Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
                    Write-Host ('  Puerto ' + $Port + ' liberado (PID ' + $pidToStop + ')') -ForegroundColor Gray
                }
            }
        }
    } catch { }
}

# --- 1. Verificar dependencias -----------------------------------------------

Write-Host "[1/5] Verificando dependencias..." -ForegroundColor Cyan

# Python - resolver ejecutable real (evitar alias Microsoft Store)
$PYTHON = $null
# Intentar 'py -3' (Windows Launcher, siempre apunta al Python real)
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $testPy = & py -3 --version 2>&1
    if ($LASTEXITCODE -eq 0) { $PYTHON = "py" }
}
# Fallback: buscar python.exe real (no el alias de WindowsApps)
if (-not $PYTHON) {
    $realPython = Get-Command python -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike "*WindowsApps*" } |
        Select-Object -First 1
    if ($realPython) { $PYTHON = $realPython.Source }
}
# Ultimo recurso: python generico
if (-not $PYTHON) {
    $PYTHON = "python"
}
# Verificar que funciona
try {
    $pyVer = & $PYTHON --version 2>&1
    if ($pyVer -match "Python (\d+\.\d+)") {
        Write-Host ('  Python: ' + $pyVer + ' (' + $PYTHON + ')') -ForegroundColor Gray
    } else {
        throw "no version"
    }
} catch {
    Write-Host "  ERROR: Python no encontrado. Instala Python 3.11+." -ForegroundColor Red
    Write-Host "  Desactiva el alias de Microsoft Store en:" -ForegroundColor Red
    Write-Host '  Configuracion > Aplicaciones > Alias de ejecucion de aplicaciones' -ForegroundColor Red
    Pop-Location
    exit 1
}

# Node
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "  ERROR: Node.js no encontrado. Instala Node 20+." -ForegroundColor Red
    Pop-Location
    exit 1
}
$nodeVer = node --version 2>&1
Write-Host "  Node:   $nodeVer" -ForegroundColor Gray

# Dependencias Python — sincronizar cuando cambia requirements.txt (hash SHA256)
$reqFile = Join-Path $ROOT "milpa_ai_backend\requirements.txt"
$reqHashStore = Join-Path $ROOT "milpa_ai_backend\.milpa_requirements.sha256"

# Argumentos base para py launcher vs python directo
$pyBase = @()
if ($PYTHON -eq "py") { $pyBase = @("-3") }

$reqHashNow = Get-Sha256File $reqFile
$reqHashWas = Read-StoredHash $reqHashStore
if ($reqHashNow -and $reqHashNow -ne $reqHashWas) {
    Write-Host "  requirements.txt cambió o primera instalación — pip install..." -ForegroundColor Yellow
    & $PYTHON @pyBase -m pip install -r $reqFile --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Fallo al instalar dependencias. Revisa requirements.txt" -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Write-StoredHash $reqHashStore $reqHashNow
    Write-Host "  Dependencias Python al día." -ForegroundColor Green
} else {
    $ErrorActionPreference = 'Continue'
    & $PYTHON @pyBase -c "import fastapi, chromadb, uvicorn" 2>$null
    $importOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = 'Stop'
    if (-not $importOk) {
        Write-Host "  Paquetes faltantes — pip install..." -ForegroundColor Yellow
        & $PYTHON @pyBase -m pip install -r $reqFile --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Fallo pip install." -ForegroundColor Red
            Pop-Location
            exit 1
        }
        if ($reqHashNow) { Write-StoredHash $reqHashStore $reqHashNow }
        Write-Host "  Dependencias Python instaladas." -ForegroundColor Green
    } else {
        Write-Host '  Dependencias Python: OK (sin cambios en requirements.txt)' -ForegroundColor Gray
    }
}

# --- 2. Preparar directorios + migraciones -----------------------------------

Write-Host "[2/5] Preparando datos y aplicando migraciones..." -ForegroundColor Cyan

$dataDir = Join-Path $ROOT "milpa_ai_backend\data"
$docsDir = Join-Path $dataDir "documents"
$tmpDir  = Join-Path $dataDir "tmp"

foreach ($d in @($dataDir, $docsDir, $tmpDir)) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Write-Host "  Creado: $d" -ForegroundColor Gray
    }
}

# Aplicar migraciones yoyo (rutas relativas a $ROOT — cwd ya está en raíz del repo)
Write-Host '  Aplicando migraciones SQL (yoyo)...' -ForegroundColor Gray
$migLog = Join-Path $ROOT "logs\milpa\yoyo.last.log"
New-Item -ItemType Directory -Path (Split-Path $migLog) -Force | Out-Null
$migErr = & $PYTHON @pyBase -c "from yoyo import read_migrations, get_backend; b=get_backend('sqlite:///milpa_ai_backend/data/milpa_knowledge.db'); ms=read_migrations('milpa_ai_backend/core/logic/migrations'); b.apply_migrations(b.to_apply(ms)); print('migrations: OK')" 2>&1
$migErr | Set-Content -Path $migLog -Encoding utf8
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: No se pudieron aplicar migraciones yoyo. Ver: $migLog" -ForegroundColor Red
    Get-Content $migLog -Tail 20
    Pop-Location
    exit 1
}
Write-Host "  Migraciones: OK" -ForegroundColor Gray

# --- 2.b · Manual técnico Lechuga (PDF+TXT) opcional -------------------------
if ($env:MILPA_GEN_MANUAL_LECHUGA -eq "1") {
    $genLechuga = Join-Path $ROOT "milpa_ai_backend\tools\gen_manual_lechuga.py"
    if (Test-Path $genLechuga) {
        Write-Host '[2.b] MILPA_GEN_MANUAL_LECHUGA=1 — generando docs\manual_lechuga_milpa_2026.{pdf,txt}...' -ForegroundColor Cyan
        $genOut = & $PYTHON @pyBase $genLechuga 2>&1
        $genOut | ForEach-Object { Write-Host ("    " + $_) -ForegroundColor Gray }
        if ($LASTEXITCODE -ne 0) {
            Write-Host '  WARN: gen_manual_lechuga.py terminó con error (el sistema igual arranca).' -ForegroundColor Yellow
        }
    } else {
        Write-Host ('  WARN: No existe ' + $genLechuga) -ForegroundColor Yellow
    }
}

# --- 3. Instalar dependencias Node si faltan ---------------------------------

Write-Host "[3/5] Verificando presenter..." -ForegroundColor Cyan

$presenterDir = Join-Path $ROOT "milpa_presenter"
$presenterLock = Join-Path $presenterDir "package-lock.json"
$presenterLockStore = Join-Path $presenterDir ".milpa_packagelock.sha256"
$nodeModules  = Join-Path $presenterDir "node_modules"

$prLockHash = Get-Sha256File $presenterLock
$prLockWas = Read-StoredHash $presenterLockStore
if ($prLockHash -and $prLockHash -ne $prLockWas) {
    Write-Host "  package-lock del presenter cambió — npm install..." -ForegroundColor Yellow
    Push-Location $presenterDir
    npm install --silent 2>&1 | Out-Null
    Pop-Location
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  ERROR: npm install (presenter) falló.' -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Write-StoredHash $presenterLockStore $prLockHash
} elseif (-not (Test-Path $nodeModules)) {
    Write-Host '  Instalando dependencias npm (presenter)...' -ForegroundColor Yellow
    Push-Location $presenterDir
    npm install --silent 2>&1 | Out-Null
    Pop-Location
    if ($prLockHash) { Write-StoredHash $presenterLockStore $prLockHash }
}

# Compilar TypeScript si falta dist o cualquier fuente .ts es más reciente que dist\server.js
$distDir = Join-Path $presenterDir "dist"
$distServer = Join-Path $distDir "server.js"
$srcRoot = Join-Path $presenterDir "src"
$needsTsc = $false
if (-not (Test-Path $distServer)) {
    $needsTsc = $true
} elseif (Test-Path $srcRoot) {
    $newestSrc = Get-ChildItem -LiteralPath $srcRoot -Filter "*.ts" -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newestSrc -and $newestSrc.LastWriteTime -gt (Get-Item $distServer).LastWriteTime) {
        $needsTsc = $true
    }
}
if ($env:MILPA_FORCE_SYNC -eq "1") { $needsTsc = $true }
if ($needsTsc) {
    Write-Host '  Compilando presenter (npm run build)...' -ForegroundColor Yellow
    Push-Location $presenterDir
    npm run build --silent 2>&1 | Out-Null
    $buildOk = ($LASTEXITCODE -eq 0)
    if (-not $buildOk) {
        Write-Host '  ERROR: npm run build falló. Salida del compilador:' -ForegroundColor Red
        npm run build 2>&1 | ForEach-Object { Write-Host ("    " + $_) -ForegroundColor Red }
    }
    Pop-Location
    if (-not $buildOk) {
        Write-Host '  Corrige TypeScript o ejecuta manualmente: cd milpa_presenter; npm run build' -ForegroundColor Red
        Pop-Location
        exit 1
    }
    if (-not (Test-Path $distServer)) {
        Write-Host '  ERROR: No se generó dist/server.js tras el build.' -ForegroundColor Red
        Pop-Location
        exit 1
    }
}

# Frontend Express — sincronizar si cambia package-lock.json
$frontendDir = Join-Path $ROOT "frontend"
$frontendLock = Join-Path $frontendDir "package-lock.json"
$frontendLockStore = Join-Path $frontendDir ".milpa_packagelock.sha256"
$frontendNodeModules = Join-Path $frontendDir "node_modules"

$feLockHash = Get-Sha256File $frontendLock
$feLockWas = Read-StoredHash $frontendLockStore
if ($feLockHash -and $feLockHash -ne $feLockWas) {
    Write-Host "  package-lock del frontend cambió — npm install..." -ForegroundColor Yellow
    Push-Location $frontendDir
    npm install --silent 2>&1 | Out-Null
    Pop-Location
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  ERROR: npm install (frontend) falló.' -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Write-StoredHash $frontendLockStore $feLockHash
} elseif (-not (Test-Path $frontendNodeModules)) {
    Write-Host "  Instalando dependencias frontend..." -ForegroundColor Yellow
    Push-Location $frontendDir
    npm install --silent 2>&1 | Out-Null
    Pop-Location
    if ($feLockHash) { Write-StoredHash $frontendLockStore $feLockHash }
}

# Logs (stderr/stdout de servicios + build nativo)
$logDir = Join-Path $ROOT "logs\milpa"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$rebuildLog = Join-Path $logDir "rebuild-better-sqlite3.log"

# Recompilar better-sqlite3 para evitar ABI mismatch entre versiones de Node
Push-Location $frontendDir
Write-Host ("  Recompilando better-sqlite3 para Node actual (log: " + $rebuildLog + ")...") -ForegroundColor Gray
$ErrorActionPreference = 'Continue'
$rebuildOut = npm rebuild better-sqlite3 2>&1
$rebuildOut | Set-Content -Path $rebuildLog -Encoding utf8
$ErrorActionPreference = 'Stop'
$rebuildOk = ($LASTEXITCODE -eq 0)
if (-not $rebuildOk) {
    Write-Host ("  WARN: npm rebuild better-sqlite3 fallo. Detalle en log: " + $rebuildLog) -ForegroundColor Yellow
    Write-Host '  Reintentando descarga e instalacion de binario precompilado...' -ForegroundColor Gray
    $ErrorActionPreference = 'Continue'
    $installOut = npm install better-sqlite3@^11.7.0 2>&1
    $installLog = Join-Path $logDir "install-better-sqlite3.log"
    $installOut | Set-Content -Path $installLog -Encoding utf8
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -eq 0) {
        Write-Host ("  better-sqlite3 reinstalado (revisar " + $installLog + " si hay dudas).") -ForegroundColor Green
    } else {
        Write-Host ("  WARN: Sigue fallando. Instala Desktop development with C++ (VS Build Tools) o usa Node 20/22 LTS. Log: " + $installLog) -ForegroundColor Yellow
    }
}
Pop-Location

# --- 4. Lanzar servicios -----------------------------------------------------

Write-Host "[4/5] Iniciando servicios..." -ForegroundColor Cyan

# Limpiar puertos previamente ocupados
Stop-PortProcess -Port 8000
Stop-PortProcess -Port 8080
Stop-PortProcess -Port 4000
Start-Sleep -Seconds 1

# Variables de entorno para ejecucion local
$env:ALLOWED_ORIGIN = "http://localhost:8080"
$env:AV_OPTIONAL    = "true"
$env:CLAMAV_HOST    = "localhost"
# Numpy/MKL/OMP: en consola "sintetica" (tareas CI) o con -WindowStyle Minimized, a veces aparece
# forrtl: error (200) window-CLOSE. Limitar hilos evita partes de la pila en situaciones anomalas.
if (-not $env:OMP_NUM_THREADS)  { $env:OMP_NUM_THREADS  = "1" }
if (-not $env:MKL_NUM_THREADS) { $env:MKL_NUM_THREADS = "1" }
if (-not $env:OPENBLAS_NUM_THREADS) { $env:OPENBLAS_NUM_THREADS = "1" }

# Extracción PDF block-level + chunker HF + modelo embedder (pydantic-settings).
# Solo fijamos valores por defecto si el usuario no definió ya la variable
# (permite sobreescribir desde sesión o .env del backend).
if (-not $env:EXTRACT_BLOCK_LEVEL)       { $env:EXTRACT_BLOCK_LEVEL = "true" }
if (-not $env:EXTRACT_TOKEN_CHUNKER)     { $env:EXTRACT_TOKEN_CHUNKER = "true" }
if (-not $env:EXTRACT_TARGET_TOKENS)     { $env:EXTRACT_TARGET_TOKENS = "110" }
if (-not $env:EXTRACT_OVERLAP_TOKENS)    { $env:EXTRACT_OVERLAP_TOKENS = "16" }
if (-not $env:EMBED_MODEL) {
    $env:EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
}

# Backend: uvicorn en el directorio correcto
$backendDir = Join-Path $ROOT "milpa_ai_backend"

Write-Host '  Backend  -> http://localhost:8000' -ForegroundColor Yellow
# Por defecto sin --reload (un solo proceso, menos consolas). Dev: $env:MILPA_UVICORN_RELOAD="1"
$uvicornExtra = @()
if ($env:MILPA_UVICORN_RELOAD -eq "1") { $uvicornExtra = @("--reload") }
$pyArgs = @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") + $uvicornExtra
if ($PYTHON -eq "py") { $pyArgs = @("-3") + $pyArgs }
$beOut = Join-Path $logDir "backend.stdout.log"
$beErr = Join-Path $logDir "backend.stderr.log"
# Hidden, no Minimized: Minimized a veces gatilla forrtl (200) window-CLOSE (numpy/MKL) al cerrar consola
$backendJob = Start-Process -FilePath $PYTHON `
    -ArgumentList $pyArgs `
    -WorkingDirectory $backendDir `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $beOut -RedirectStandardError $beErr

# Esperar a que el backend levante
Write-Host "  Esperando backend..." -ForegroundColor Gray
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -Method GET -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch { }
}

if (-not $ready) {
    Write-Host '  ADVERTENCIA: Backend no respondio en 60s (puede estar cargando modelos)' -ForegroundColor Yellow
}

# Presenter: node
Write-Host '  Presenter -> http://localhost:8080' -ForegroundColor Yellow

$env:PORT = "8080"
$env:IA_URL = "http://127.0.0.1:8000"
$env:ALLOWED_ORIGINS = "http://localhost:8080"

$prOut = Join-Path $logDir "presenter.stdout.log"
$prErr = Join-Path $logDir "presenter.stderr.log"
$presenterJob = Start-Process -FilePath "node" `
    -ArgumentList (Join-Path $presenterDir "dist\server.js") `
    -WorkingDirectory $presenterDir `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $prOut -RedirectStandardError $prErr

Start-Sleep -Seconds 2

# Frontend Express :4000 (MILPA web + proxy /api/ai/* hacia :8000)
Write-Host '  Frontend  -> http://localhost:4000' -ForegroundColor Yellow
$env:PORT = "4000"
$env:AI_BACKEND_URL = "http://127.0.0.1:8000"
$feOut = Join-Path $logDir "frontend.stdout.log"
$feErr = Join-Path $logDir "frontend.stderr.log"
$frontendJob = Start-Process -FilePath "node" `
    -ArgumentList "server.js" `
    -WorkingDirectory $frontendDir `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $feOut -RedirectStandardError $feErr

Start-Sleep -Seconds 2
# Fastify a veces tarda unos segundos más en abrir 8080
Start-Sleep -Seconds 3

# Comprobación rápida (diagnóstico; no bloquea si tarda)
Write-Host '  Comprobando http en puertos (puede mostrar FALLO si aun inicia)...' -ForegroundColor Gray
try {
    $c4000 = (Invoke-WebRequest -Uri 'http://127.0.0.1:4000/login.html' -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue).StatusCode
    if ($c4000 -eq 200) { Write-Host '  Frontend: OK - codigo 200 en /login.html (MILPA Web + Socket.IO / AgroBot en frontend\server.js)' -ForegroundColor Green }
} catch { Write-Host ("  Frontend: aun no responde. Ver log: " + $feErr) -ForegroundColor DarkYellow }
try {
    $c8080 = (Invoke-WebRequest -Uri 'http://127.0.0.1:8080' -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue).StatusCode
    if ($c8080) { Write-Host '  Presenter: OK' -ForegroundColor Green }
} catch { Write-Host ("  Presenter: aun no responde. Ver log: " + $prErr) -ForegroundColor DarkYellow }

# --- 5. Mostrar estado -------------------------------------------------------

Write-Host ""
Write-Host "[5/5] Sistema iniciado" -ForegroundColor Green
Write-Host ""
Write-Host "  MILPA Web:   http://localhost:4000/login.html" -ForegroundColor Cyan
Write-Host "  Dashboard:   http://localhost:4000/dashboard.html" -ForegroundColor Cyan
Write-Host "  Ingesta:     http://localhost:8080/ui/ingesta" -ForegroundColor Cyan
Write-Host "  Biblioteca:  http://localhost:8080/ui/library" -ForegroundColor Cyan
Write-Host "  Consultas:   http://localhost:8080/ui/query" -ForegroundColor Cyan
Write-Host "  Backend API: http://localhost:8000/health" -ForegroundColor Cyan
Write-Host "  Verificar:   http://localhost:8080/ui/checks" -ForegroundColor Cyan
Write-Host "  Visor bbox:  http://localhost:4000/MILPA/visor.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Para detener: Cierra esta ventana o presiona Ctrl+C" -ForegroundColor Gray
Write-Host "  PIDs: Backend=$($backendJob.Id)  Presenter=$($presenterJob.Id)  Frontend=$($frontendJob.Id)" -ForegroundColor Gray
Write-Host "  Logs:   $logDir" -ForegroundColor Gray
Write-Host ""

# --- 5.b · E2E booleano opcional (post-arranque) -----------------------------
# Si $env:MILPA_RUN_E2E está definido, ejecuta tools\e2e_crop.py contra el
# backend ya levantado y escribe tools\e2e_<crop>_report.json y logs\milpa\e2e_<crop>.log
# Con MILPA_E2E_STRICT=1 un fallo detiene los tres servicios y propaga el código de salida.
$script:E2eExitCode = $null
if ($env:MILPA_RUN_E2E) {
    $e2eCrop = $env:MILPA_RUN_E2E.Trim().ToLower()
    if ($e2eCrop) {
        Write-Host ('[5.b] E2E booleano para cultivo "' + $e2eCrop + '"...') -ForegroundColor Cyan
        if ($env:MILPA_E2E_DOC) {
            $e2eDoc = $env:MILPA_E2E_DOC
        } else {
            $e2eDoc = Join-Path $ROOT ('docs\manual_' + $e2eCrop + '_milpa_2026.txt')
        }
        $e2eReport = Join-Path $ROOT ('tools\e2e_' + $e2eCrop + '_report.json')
        $e2eLog = Join-Path $logDir ('e2e_' + $e2eCrop + '.log')
        if (-not (Test-Path $e2eDoc)) {
            Write-Host ('  WARN: documento E2E no encontrado: ' + $e2eDoc) -ForegroundColor Yellow
            if ($env:MILPA_E2E_STRICT -eq "1") {
                Write-Host '  MILPA_E2E_STRICT: abortando (sin documento).' -ForegroundColor Red
                Stop-Process -Id $backendJob.Id -Force -ErrorAction SilentlyContinue
                Stop-Process -Id $presenterJob.Id -Force -ErrorAction SilentlyContinue
                Stop-Process -Id $frontendJob.Id -Force -ErrorAction SilentlyContinue
                Pop-Location
                exit 2
            }
        } else {
            $e2eArgs = @("tools\e2e_crop.py","--crop",$e2eCrop,"--doc",$e2eDoc,"--report-json",$e2eReport)
            if ($PYTHON -eq "py") { $e2eArgs = @("-3") + $e2eArgs }
            $ErrorActionPreference = 'Continue'
            $e2eOut = & $PYTHON @e2eArgs 2>&1
            $script:E2eExitCode = $LASTEXITCODE
            $e2eOut | Set-Content -Path $e2eLog -Encoding utf8
            $ErrorActionPreference = 'Stop'
            $e2eTail = ($e2eOut | Select-Object -Last 16) -join "`n"
            Write-Host $e2eTail -ForegroundColor Gray
            Write-Host ('  Reporte E2E: ' + $e2eReport + '  código salida: ' + $script:E2eExitCode) -ForegroundColor Gray
            if ($env:MILPA_E2E_STRICT -eq "1" -and $script:E2eExitCode -ne 0) {
                Write-Host ('  MILPA_E2E_STRICT: E2E falló (código ' + $script:E2eExitCode + '). Deteniendo servicios...') -ForegroundColor Red
                Stop-Process -Id $backendJob.Id -Force -ErrorAction SilentlyContinue
                Stop-Process -Id $presenterJob.Id -Force -ErrorAction SilentlyContinue
                Stop-Process -Id $frontendJob.Id -Force -ErrorAction SilentlyContinue
                Pop-Location
                exit $script:E2eExitCode
            }
        }
    }
}

# --- 5.c · Salida automática tras N segundos (smoke / CI) --------------------
$script:DaemonDeadline = $null
if ($env:MILPA_DAEMON_SECONDS -match '^[0-9]+$') {
    $ds = [int]$env:MILPA_DAEMON_SECONDS
    if ($ds -gt 0) {
        $script:DaemonDeadline = (Get-Date).AddSeconds($ds)
        Write-Host ('[5.c] MILPA_DAEMON_SECONDS=' + $ds + ' — salida automática tras ' + $ds + ' s.') -ForegroundColor DarkGray
    }
}

# Mantener el script vivo y limpiar al cerrar (avisos 1x por servicio, sin spam)
$script:ExitUnhealthy = $false
$script:UserStopped = $false
$warnBackend = $false; $warnPresenter = $false; $warnFrontend = $false
try {
    Write-Host "  Presiona Ctrl+C para detener todos los servicios..." -ForegroundColor DarkGray
    while ($true) {
        try { Start-Sleep -Seconds 5 } catch { $script:UserStopped = $true; break }
        if ($script:UserStopped) { break }
        if ($null -ne $script:DaemonDeadline -and (Get-Date) -ge $script:DaemonDeadline) {
            Write-Host '  MILPA_DAEMON_SECONDS: tiempo cumplido, cerrando servicios...' -ForegroundColor DarkGray
            break
        }
        if ($backendJob.HasExited) {
            if (-not $warnBackend) {
                $warnBackend = $true
                $script:ExitUnhealthy = $true
                $ecB = if ($null -ne $backendJob.ExitCode) { $backendJob.ExitCode } else { "?" }
                Write-Host ("  WARN: Backend proceso terminado. Codigo salida: " + $ecB + ". Stderr log: " + $beErr) -ForegroundColor Yellow
                if (Test-Path $beErr) { Get-Content -Path $beErr -Tail 6 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
            }
        }
        if ($presenterJob.HasExited) {
            if (-not $warnPresenter) {
                $warnPresenter = $true
                $script:ExitUnhealthy = $true
                $ecP = if ($null -ne $presenterJob.ExitCode) { $presenterJob.ExitCode } else { "?" }
                Write-Host ("  WARN: Presenter proceso terminado. Codigo salida: " + $ecP + ". Log: " + $prErr) -ForegroundColor Yellow
                if (Test-Path $prErr) { Get-Content -Path $prErr -Tail 5 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
            }
        }
        if ($frontendJob.HasExited) {
            if (-not $warnFrontend) {
                $warnFrontend = $true
                $script:ExitUnhealthy = $true
                $ecF = if ($null -ne $frontendJob.ExitCode) { $frontendJob.ExitCode } else { "?" }
                Write-Host ("  WARN: Frontend proceso terminado. Codigo salida: " + $ecF + ". Log: " + $feErr) -ForegroundColor Yellow
                if (Test-Path $feErr) { Get-Content -Path $feErr -Tail 8 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
            }
        }
        if ($backendJob.HasExited -and $presenterJob.HasExited -and $frontendJob.HasExited) {
            Write-Host "  Todos los servicios terminaron. Diagnóstico en: $logDir" -ForegroundColor Red
            break
        }
    }
} finally {
    Write-Host "`n  Deteniendo servicios..." -ForegroundColor Yellow
    if (-not $backendJob.HasExited) { Stop-Process -Id $backendJob.Id -Force -ErrorAction SilentlyContinue }
    if (-not $presenterJob.HasExited) { Stop-Process -Id $presenterJob.Id -Force -ErrorAction SilentlyContinue }
    if (-not $frontendJob.HasExited) { Stop-Process -Id $frontendJob.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "  Servicios detenidos." -ForegroundColor Green
    Pop-Location
}

# Código de salida: 1 = procesos terminaron solos (CI); 0 = Ctrl+C o cierre limpio
if ($script:UserStopped) { exit 0 }
elseif ($script:ExitUnhealthy) { exit 1 }
else { exit 0 }
