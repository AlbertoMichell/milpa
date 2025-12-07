$ErrorActionPreference = 'Stop'
Write-Host "[MILPA] Unificando documentos y reindexando..."

# Carpetas fuente potenciales bajo la carpeta madre
$root = "c:\milpa"
$targets = @(
    "$root\milpa_ai_backend\data\documents",
    "$root\data\documents",
    "$root\docs",
    "$root"
)

# Carpeta destino canonica
$dest = "$root\milpa_ai_backend\data\documents"
if (-not (Test-Path -LiteralPath $dest)) { New-Item -ItemType Directory -Path $dest | Out-Null }

# Extensiones a consolidar
$exts = @(".pdf", ".txt", ".md")

# Limpia prefijos acumulados del tipo yyyyMMddHHmmssfff__
function Get-CleanName {
    param([string]$Name)
    return ($Name -replace '^(?:\d{17}__)+', '')
}

# Palabras clave para documentos de cultivo (incluir)
$cultivoKeywords = @(
    'maiz','milpa','cultivo','agronomia','siembra','riego','plagas','nutrientes','fertiliz','suelo','fenologia','peste','region'
)

# Palabras clave a excluir por ser del sistema
$excludeKeywords = @(
    'readme','license','changelog','history','entry_points','requirements','spec','notice','privacy','security','top_level'
)

# Mover/ copiar archivos evitando sobrescrituras y manteniendo trazabilidad
$counter = 0
foreach ($t in $targets) {
    if (-not (Test-Path -LiteralPath $t)) { continue }
    Get-ChildItem -Path $t -Recurse -File | Where-Object { $exts -contains $_.Extension.ToLower() } |
        Where-Object {
            $n = $_.Name.ToLower()
            # Debe contener alguna keyword de cultivo y NO contener ninguna excluida
            ($cultivoKeywords | Where-Object { $n -like "*$_*" }).Count -gt 0 -and
            ($excludeKeywords | Where-Object { $n -like "*$_*" }).Count -eq 0
        } |
        Select-Object -First 12 |
        ForEach-Object {
        $src = $_.FullName
        $name = Get-CleanName -Name $_.Name
        # Prefijo con timestamp para evitar colisiones cuando existan nombres repetidos
        # Usar timestamp seguro en milisegundos (Int64) para evitar overflow
        $stamp = [string](Get-Date -Format "yyyyMMddHHmmssfff")
        $destName = "${stamp}__${name}"
        $destPath = Join-Path $dest $destName
        # Si excede MAX_PATH, acorta nombre base a 100 caracteres
        if ($destPath.Length -gt 259) {
            $base = [System.IO.Path]::GetFileNameWithoutExtension($name)
            $ext = [System.IO.Path]::GetExtension($name)
            if ($base.Length -gt 100) { $base = $base.Substring(0,100) }
            $destName = "${stamp}__${base}${ext}"
            $destPath = Join-Path $dest $destName
        }
        if (-not (Test-Path -LiteralPath $destPath)) {
            try {
                Copy-Item -LiteralPath $src -Destination $destPath -Force
                $counter++
            } catch {
                Write-Warning "No se pudo copiar: `n$src =>`n$destPath ($($_.Exception.Message))"
            }
        }
    }
}

Write-Host "[MILPA] Documentos consolidados: $counter en $dest"

# Probar salud del backend y preparar upload/extract
$backend = "http://localhost:8000"
try {
    $h = Invoke-RestMethod -Uri "$backend/health" -Method GET -TimeoutSec 10
    Write-Host "[MILPA] Backend salud: $($h | ConvertTo-Json -Depth 3)"
} catch {
    Write-Warning "Backend no disponible en $backend. Arranca contenedores antes de reindexar."
    exit 1
}

# Subir y extraer documentos consolidados
Write-Host "[MILPA] Registrando (upload) y extrayendo documentos..."
$processed = 0
$uploaded = 0
$extracted = 0

# Seleccionar archivos PDF/TXT/MD recien consolidados en el destino
$filesAll = Get-ChildItem -Path $dest -File | Where-Object { $exts -contains $_.Extension.ToLower() }

# Preferir una sola copia por baseName (evitar múltiples prefijos del mismo archivo)
$grouped = $filesAll | Group-Object { $_.Name.ToLower().Replace("\n"," ") -replace '^(?:\d{17}__)+','' }
$toProcess = @()
foreach ($g in $grouped) {
    # Priorizar el archivo SIN prefijo si existe; si no, tomar el más reciente
    $clean = $g.Group | Where-Object { $_.Name -notmatch '^(?:\d{17}__)' }
    if ($clean -and $clean.Count -gt 0) {
        $toProcess += $clean[0]
    } else {
        $toProcess += ($g.Group | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    }
}
{$toProcess} | Sort-Object LastWriteTime -Descending | Out-Null

# Cargar ensamblado System.Net.Http para PowerShell 5.1
try { Add-Type -AssemblyName System.Net.Http } catch { }

# Helper: subir archivo como multipart/form-data en PowerShell 5.1
function Upload-DocumentMultipart {
    param(
        [string]$BackendBase,
        [string]$FilePath,
        [string]$FileName,
        [string]$ContentType,
        [hashtable]$FormFields
    )
    $client = New-Object System.Net.Http.HttpClient
    $mp = New-Object System.Net.Http.MultipartFormDataContent

    $fs = [System.IO.File]::OpenRead($FilePath)
    $fileContent = New-Object System.Net.Http.StreamContent($fs)
    $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse($ContentType)
    $mp.Add($fileContent, "file", $FileName)

    foreach ($k in $FormFields.Keys) {
        $val = [string]$FormFields[$k]
        $strContent = New-Object System.Net.Http.StringContent($val)
        $mp.Add($strContent, $k)
    }

    $url = "$BackendBase/api/documents/upload"
    $resp = $client.PostAsync($url, $mp).Result
    $body = $resp.Content.ReadAsStringAsync().Result
    $fs.Dispose()
    if (-not $resp.IsSuccessStatusCode) {
        throw "Upload fallo: $($resp.StatusCode) $body"
    }
    return ($body | ConvertFrom-Json)
}

foreach ($f in $toProcess) {
    $full = $f.FullName
    $ext = $f.Extension.ToLower()
    $contentType = switch ($ext) {
        ".pdf" { "application/pdf" }
        ".txt" { "text/plain" }
        ".md"  { "text/plain" }
        default { "application/octet-stream" }
    }

    try {
        # Upload: registra en BD con stored_path y doc_id
        # Metadatos más limpios
        $form = @{ license = "institutional"; classification = "Interno"; title = ($f.BaseName -replace '^(?:\d{17}__)+',''); author = "Equipo Milpa"; year = (Get-Date).Year }
        $jsonUpload = Upload-DocumentMultipart -BackendBase $backend -FilePath $full -FileName $f.Name -ContentType $contentType -FormFields $form
        $docId = $jsonUpload.doc_id
        if (-not $docId) { throw "Upload sin doc_id devuelto" }
        $uploaded++

        # Extract: procesa texto/OCR/tablas y fragmenta
        $respExtract = Invoke-WebRequest -Uri "$backend/api/documents/$docId/extract" -Method Post -TimeoutSec 300
        $jsonExtract = $respExtract.Content | ConvertFrom-Json
        $fragCount = $jsonExtract.fragments_count; if (-not $fragCount) { $fragCount = $jsonExtract.fragmentsCount }
        $tabCount = $jsonExtract.tables_count; if (-not $tabCount) { $tabCount = $jsonExtract.tablesCount }
        $extracted++

        $processed++
        Write-Host "[MILPA] OK $($f.Name) => doc_id=$($docId.Substring(0,12))... fragments=$fragCount tables=$tabCount"
    } catch {
        Write-Warning "[MILPA] Fallo procesando $($f.Name): $($_.Exception.Message)"
    }
}

# Llamar al rebuild
try {
    Write-Host "[MILPA] Reconstruyendo indices (BM25 + Vector)..."
    $rebuild = Invoke-RestMethod -Uri "$backend/api/index/rebuild" -Method POST -TimeoutSec 180
    Write-Host ($rebuild | ConvertTo-Json -Depth 5)
} catch {
    Write-Warning "Fallo al reconstruir índices: $_"
}

Write-Host "[MILPA] Resumen: consolidados=$counter, subidos=$uploaded, extraidos=$extracted"
Write-Host "[MILPA] Listo. Verifica en Presenter: http://localhost:8080/ui/library"
