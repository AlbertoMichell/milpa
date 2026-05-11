param(
  [string]$BackendUrl = 'http://127.0.0.1:8000',
  [string]$ReportPath = 'tools\rag_audit_report.json'
)

$simple = @(
  'Maíz',
  'Lechuga',
  'Frijol',
  'Calabaza',
  'Pepino',
  'Tomate',
  'Riego',
  'Fertilización',
  'Plagas',
  'Suelo'
)

$compound = @(
  'Temperatura ideal para la lechuga',
  'pH óptimo del suelo para maíz',
  'Dosis de nitrógeno por hectárea en maíz',
  '¿Cómo se controla el gusano cogollero del maíz?',
  '¿Cuándo regar la lechuga en clima cálido?',
  'Ciclo de cultivo del frijol en sistema milpa',
  'Distancia de siembra recomendada para calabaza',
  '¿Qué humedad de suelo necesita el pepino?',
  'Variedades de tomate resistentes a sequía',
  'Manejo integrado de plagas en lechuga'
)

function Run-Query([string]$q, [string]$kind) {
  $payload = @{ query = $q; k = 5; mode = 'hybrid' }
  $body = $payload | ConvertTo-Json -Compress
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
  $res = $null
  $err = $null
  $start = Get-Date
  try {
    $resp = Invoke-WebRequest -Uri "$BackendUrl/api/query" -Method POST -Headers @{ 'Content-Type' = 'application/json; charset=utf-8' } -Body $bytes -UseBasicParsing -TimeoutSec 90
    $res = $resp.Content | ConvertFrom-Json
  } catch { $err = $_.Exception.Message }
  $elapsed = ((Get-Date) - $start).TotalMilliseconds

  $docIds = @()
  $titles = @()
  if ($res -and $res.fragments) {
    foreach ($f in $res.fragments) {
      if ($f.doc_id) { $docIds += $f.doc_id }
      if ($f.doc_title) { $titles += $f.doc_title }
    }
  }
  $unique = ($docIds | Select-Object -Unique).Count
  $obj = [pscustomobject]@{
    kind             = $kind
    query            = $q
    elapsed_ms       = [int]$elapsed
    insufficient     = ($res.insufficient_evidence -as [bool])
    answer_mode      = $res.answer_mode
    n_fragments      = ($res.fragments.Count)
    unique_doc_ids   = $unique
    answer_first_120 = ($res.answer -replace '\s+', ' ').Trim()
    titles           = ($titles -join ' || ')
    error            = $err
  }
  if ($obj.answer_first_120 -and $obj.answer_first_120.Length -gt 200) {
    $obj.answer_first_120 = $obj.answer_first_120.Substring(0,200) + '…'
  }
  return $obj
}

$results = @()
foreach ($q in $simple)  { $results += Run-Query $q 'simple' }
foreach ($q in $compound){ $results += Run-Query $q 'compound' }

$results | Format-Table kind, query, elapsed_ms, insufficient, n_fragments, unique_doc_ids, answer_first_120 -AutoSize -Wrap

$results | ConvertTo-Json -Depth 5 | Set-Content -Path $ReportPath -Encoding utf8
Write-Host ""
Write-Host "Reporte: $ReportPath"
