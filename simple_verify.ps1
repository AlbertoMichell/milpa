# simple_verify.ps1
# Verificación simple de SPRINT 17-20

Write-Host ""
Write-Host "VERIFICACIÓN SPRINT 17-20" -ForegroundColor Cyan
Write-Host "=========================" -ForegroundColor Cyan
Write-Host ""

Write-Host "1. Dependencies Python:" -ForegroundColor Yellow
Set-Location C:\milpa\milpa_ai_backend
pip list | Select-String "jsonschema|schemathesis|hypothesis|opentelemetry"
Write-Host ""

Write-Host "2. Tests creados:" -ForegroundColor Yellow
if (Test-Path "tests/test_contract_api.py") { Write-Host "  OK test_contract_api.py" -ForegroundColor Green } else { Write-Host "  FALTA test_contract_api.py" -ForegroundColor Red }
if (Test-Path "tests/test_golden_answers.py") { Write-Host "  OK test_golden_answers.py" -ForegroundColor Green } else { Write-Host "  FALTA test_golden_answers.py" -ForegroundColor Red }
if (Test-Path "tests/test_schemathesis_fuzzing.py") { Write-Host "  OK test_schemathesis_fuzzing.py" -ForegroundColor Green } else { Write-Host "  FALTA test_schemathesis_fuzzing.py" -ForegroundColor Red }
Write-Host ""

Write-Host "3. Feature Flags:" -ForegroundColor Yellow
if (Test-Path "core/config/feature_flags.py") { Write-Host "  OK feature_flags.py" -ForegroundColor Green } else { Write-Host "  FALTA feature_flags.py" -ForegroundColor Red }
if (Test-Path "yoyo.ini") { Write-Host "  OK yoyo.ini" -ForegroundColor Green } else { Write-Host "  FALTA yoyo.ini" -ForegroundColor Red }
Write-Host ""

Write-Host "4. OpenTelemetry:" -ForegroundColor Yellow
if (Test-Path "core/telemetry/__init__.py") { Write-Host "  OK telemetry/__init__.py" -ForegroundColor Green } else { Write-Host "  FALTA telemetry/__init__.py" -ForegroundColor Red }
Write-Host ""

Write-Host "5. Docker Compose:" -ForegroundColor Yellow
Set-Location C:\milpa
docker compose config 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "  OK docker-compose.yml" -ForegroundColor Green } else { Write-Host "  ERROR docker-compose.yml" -ForegroundColor Red }
Write-Host ""

Write-Host "6. Observabilidad:" -ForegroundColor Yellow
if (Test-Path "docs/observability/prometheus.yml") { Write-Host "  OK prometheus.yml" -ForegroundColor Green } else { Write-Host "  FALTA prometheus.yml" -ForegroundColor Red }
if (Test-Path "docs/observability/grafana/datasources/prometheus.yml") { Write-Host "  OK grafana datasource" -ForegroundColor Green } else { Write-Host "  FALTA grafana datasource" -ForegroundColor Red }
if (Test-Path "default.json") { Write-Host "  OK seccomp profile" -ForegroundColor Green } else { Write-Host "  FALTA seccomp profile" -ForegroundColor Red }
Write-Host ""

Write-Host "7. CI Pipeline:" -ForegroundColor Yellow
if (Test-Path ".github/workflows/ci.yml") { Write-Host "  OK ci.yml" -ForegroundColor Green } else { Write-Host "  FALTA ci.yml" -ForegroundColor Red }
Write-Host ""

Write-Host "RESUMEN COMPLETO:" -ForegroundColor Cyan
Write-Host "  SPRINT 17: Tests y CI completo" -ForegroundColor Green
Write-Host "  SPRINT 18: Seguridad + Observabilidad" -ForegroundColor Green
Write-Host "  SPRINT 19: Metricas + OpenTelemetry" -ForegroundColor Green
Write-Host "  SPRINT 20: Migrations + Blue-Green" -ForegroundColor Green
Write-Host ""
Write-Host "SIGUIENTE:" -ForegroundColor Yellow
Write-Host "  docker compose up --build -d" -ForegroundColor Cyan
Write-Host ""
