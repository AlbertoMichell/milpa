# 📚 ÍNDICE DE DOCUMENTACIÓN - SISTEMA MILPA

**Fecha**: 17 de octubre de 2025  
**Estado**: Sistema 100% Funcional  

---

## 🎯 GUÍAS DE LECTURA POR PERFIL

### 👨‍💼 Gerente de Proyecto / Product Owner
**Tiempo de lectura**: 5 minutos  
**Leer en este orden**:
1. 📄 `VERIFICACION_FINAL.txt` - Estado actual del sistema
2. 📄 `CORRECCIONES_APLICADAS.md` (sección "Resumen Ejecutivo")
3. 📄 `SPRINT_17_20_COMPLETADO.md` - Features implementadas

**Objetivo**: Entender qué funciona, qué está listo para producción.

---

### 👨‍💻 Desarrollador Nuevo en el Proyecto
**Tiempo de lectura**: 30 minutos  
**Leer en este orden**:
1. 📄 `VERIFICACION_FINAL.txt` - Quick start
2. 📄 `SPRINT_17_20_README.md` - Arquitectura y diseño técnico
3. 📄 `CORRECCIONES_APLICADAS.md` - Problemas conocidos resueltos
4. 📄 `REPORTE_DEBUGGING_COMPLETO.md` (sección "Archivos Modificados")

**Objetivo**: Setup completo del entorno de desarrollo y entender la codebase.

---

### 🔧 DevOps / SRE
**Tiempo de lectura**: 20 minutos  
**Leer en este orden**:
1. 📄 `docker-compose.yml` - Infraestructura de contenedores
2. 📄 `CORRECCIONES_APLICADAS.md` (sección "Verificación Final")
3. 📄 `docs/observability/prometheus.yml` - Configuración de métricas
4. 📄 `docs/observability/grafana/` - Dashboards

**Objetivo**: Deploy y monitoreo del sistema en producción.

---

### 🧪 QA / Tester
**Tiempo de lectura**: 15 minutos  
**Leer en este orden**:
1. 📄 `VERIFICACION_FINAL.txt` - Comandos de verificación
2. 📄 `tests/test_contract_api.py` - Test cases
3. 📄 `REPORTE_DEBUGGING_COMPLETO.md` (sección "Verificación y Pruebas")
4. 📄 Script: `verificar_sistema.ps1` - Ejecutar

**Objetivo**: Ejecutar suite de tests y validar funcionalidad.

---

### 🐛 Debugger / Troubleshooter
**Tiempo de lectura**: 45 minutos  
**Leer en este orden**:
1. 📄 `REPORTE_DEBUGGING_COMPLETO.md` - TODO el documento
2. 📄 `CORRECCIONES_APLICADAS.md` - Errores conocidos
3. 📄 Logs: `docker logs milpa_ai`

**Objetivo**: Resolver problemas conocidos o nuevos errores.

---

## 📂 DOCUMENTOS POR CATEGORÍA

### 🚀 Quick Start (Lectura Rápida)

#### 📄 `VERIFICACION_FINAL.txt`
- **Propósito**: Checklist de estado del sistema
- **Formato**: Texto plano
- **Longitud**: 1 página
- **Actualización**: Cada release
- **Cómo usarlo**:
  ```bash
  cat VERIFICACION_FINAL.txt
  ```

#### 📄 Script: `verificar_sistema.ps1`
- **Propósito**: Verificación automatizada del sistema
- **Formato**: PowerShell script
- **Duración**: 2-3 minutos
- **Cómo usarlo**:
  ```powershell
  .\verificar_sistema.ps1
  ```

#### 📄 Script: `crear_bd_tests.py`
- **Propósito**: Crear BD de tests con schema
- **Formato**: Python script
- **Duración**: 5 segundos
- **Cómo usarlo**:
  ```bash
  python crear_bd_tests.py
  ```

---

### 📋 Resumen Ejecutivo (Para Management)

#### 📄 `CORRECCIONES_APLICADAS.md`
- **Propósito**: Documentar correcciones de debugging
- **Secciones**:
  1. Resumen Ejecutivo
  2. Correcciones Aplicadas (5 errores)
  3. Verificación Final
  4. Próximos Pasos
- **Longitud**: ~200 líneas
- **Audiencia**: Desarrolladores, DevOps, Management
- **Actualización**: Cuando se corrigen errores críticos

#### 📄 `SPRINT_17_20_COMPLETADO.md`
- **Propósito**: Resumen de features implementadas en SPRINT 17-20
- **Secciones**:
  1. Componentes Implementados
  2. Checklist de Completitud
  3. Próximos Pasos
- **Longitud**: ~100 líneas
- **Audiencia**: Product Owners, Stakeholders
- **Actualización**: Al finalizar cada sprint

---

### 🔧 Documentación Técnica Detallada

#### 📄 `SPRINT_17_20_README.md`
- **Propósito**: Guía técnica completa de SPRINT 17-20
- **Secciones**:
  1. Tests (contract, golden, fuzzing)
  2. Docker Hardening
  3. Prometheus/Grafana
  4. OpenTelemetry
  5. Métricas Custom
  6. Migraciones
  7. Feature Flags
  8. Blue-Green Deployment
- **Longitud**: ~300 líneas
- **Audiencia**: Desarrolladores, Arquitectos
- **Código de ejemplo**: ✅ Incluido
- **Diagramas**: ⚠️ Texto (considerar agregar visuales)
- **Actualización**: Cada iteración de desarrollo

#### 📄 `REPORTE_DEBUGGING_COMPLETO.md`
- **Propósito**: Documentación exhaustiva de sesión de debugging
- **Secciones**:
  1. Contexto Inicial
  2. Errores Reportados (5)
  3. Proceso de Debugging
  4. Archivos Modificados (7, orden cronológico)
  5. Archivos Creados (5, nuevos)
  6. Verificación y Pruebas
  7. Conclusiones y Lecciones Aprendidas
- **Longitud**: ~800 líneas
- **Audiencia**: Desarrolladores avanzados, Auditores, Documentalistas
- **Detalle**: Máximo (incluye justificaciones técnicas)
- **Actualización**: Cuando hay sesiones de debugging mayores

---

### 📖 Documentación Narrativa

#### 📄 `Instruccion/avance_17_20.txt`
- **Propósito**: Reporte narrativo estilo establecido del proyecto
- **Formato**: Texto plano narrativo
- **Secciones**:
  1. Resumen de actividades
  2. Componentes implementados
  3. Logros principales
  4. Desafíos enfrentados
- **Longitud**: ~150 líneas
- **Audiencia**: Archivo histórico, reportes de progreso
- **Estilo**: Narrativo, storytelling
- **Actualización**: Al finalizar milestones importantes

---

### 🏗️ Configuración de Infraestructura

#### 📄 `docker-compose.yml`
- **Propósito**: Orquestación de servicios Docker
- **Servicios Definidos**:
  1. `clamav` - Antivirus (port 3310)
  2. `ai` - Backend FastAPI (port 8000)
  3. `presenter` - Frontend Fastify (port 8080)
  4. `prometheus` - Métricas (port 9090)
  5. `grafana` - Dashboards (port 3000)
- **Hardening**: ✅ Aplicado (non-root, read-only, seccomp)
- **Networks**: `milpa_net` (bridge)
- **Volumes**: `prometheus_data`, `grafana_data`
- **Última modificación**: Corrección de `user: 65534:65534` en prometheus
- **Cómo usarlo**:
  ```bash
  docker compose up --build -d
  docker compose ps
  docker compose logs -f
  ```

#### 📄 `docs/observability/prometheus.yml`
- **Propósito**: Configuración de scraping de métricas
- **Targets**:
  - `ai:8000/metrics` (Backend)
  - `presenter:8080/metrics` (Frontend)
- **Scrape interval**: 10s
- **Retention**: 15 días
- **Cómo probarlo**:
  ```bash
  curl http://localhost:9090/api/v1/targets
  ```

#### 📄 `docs/observability/grafana/datasources/prometheus.yml`
- **Propósito**: Provisioning automático de datasource Prometheus
- **URL**: `http://prometheus:9090`
- **Access**: `proxy`
- **Default**: true

#### 📄 `docs/observability/grafana/dashboards/*.json`
- **Propósito**: Dashboards pre-configurados para MILPA
- **Dashboards disponibles**:
  - Dashboard 1: Latencias RAG
  - Dashboard 2: Top cultivos/plagas
  - Dashboard 3: Métricas de calidad
- **Cómo acceder**: http://localhost:3000 (admin/milpa_grafana_2025)

---

### 🧪 Tests y Calidad

#### 📄 `tests/test_contract_api.py`
- **Propósito**: Tests de contrato con validación de esquemas JSON
- **Tests Definidos**: 6
  - `test_health_contract` ✅ PASSED
  - `test_library_list_contract` ✅ PASSED
  - `test_library_list_with_filters_contract` ✅ PASSED
  - `test_library_facets_contract` ⏭️ SKIPPED (404 aceptable)
  - `test_library_detail_contract` ✅ PASSED
  - `test_health_snapshot` ⏭️ SKIPPED (snapshot no creado)
- **Framework**: pytest + jsonschema
- **Cómo ejecutar**:
  ```bash
  pytest tests/test_contract_api.py -v
  ```

#### 📄 `tests/test_golden_answers.py`
- **Propósito**: Tests de respuestas esperadas (golden answers)
- **Thresholds**:
  - `faithfulness` ≥ 0.85
  - `citation_coverage` ≥ 95%
- **Cómo ejecutar**:
  ```bash
  pytest tests/test_golden_answers.py -v
  ```

#### 📄 `tests/test_schemathesis_fuzzing.py`
- **Propósito**: Fuzzing del API con generación automática de requests
- **Framework**: schemathesis + hypothesis
- **Requiere**: Servidor corriendo
- **Cómo ejecutar**:
  ```bash
  # Levantar servidor
  docker compose up -d ai
  # Ejecutar fuzzing
  pytest tests/test_schemathesis_fuzzing.py -v
  ```

#### 📄 `tests/conftest.py`
- **Propósito**: Configuración global de fixtures para tests
- **Fixtures Principales**:
  - `test_db_path()` - Ruta BD de tests
  - `setup_test_database()` - Aplicar migraciones
  - `sample_fragments()` - Datos sintéticos
  - `bm25_index()` - Índice BM25 en memoria
  - `embedder()` - Modelo de embeddings
  - `vector_store()` - VectorStore de pruebas
- **Scope**: session (ejecuta una vez)
- **Autouse**: true (automático)

---

### 🗄️ Base de Datos

#### 📄 `core/logic/migrations/0001_init.sql`
- **Propósito**: Schema inicial de BD
- **Tablas Creadas**: 8
  - `docs` - Metadatos de documentos
  - `fragments` - Fragmentos de texto
  - `fine_refs` - Referencias finas (coordenadas)
  - `tables` - Tablas detectadas
  - `table_cells` - Celdas de tabla
  - `figures` - Figuras detectadas
  - `licenses` - Licencias de documentos
- **Índices**: 3 (docs.created_at, tables.doc_id, fine_refs.fragment_id)

#### 📄 `core/logic/migrations/0002_add_stored_path.sql`
- **Propósito**: Agregar columna `stored_path` a tabla `docs`
- **Migración**: ALTER TABLE

#### 📄 `core/logic/migrations/0003_indexes_extraction.sql`
- **Propósito**: Índices adicionales para optimización de queries
- **Índices**: fragments.doc_id, figures.doc_id

#### 📄 `core/logic/migrations/0004_add_feature_flags_table.sql`
- **Propósito**: Tabla para feature flags dinámicos
- **Tabla**: `feature_flags` (flag_name, enabled, config_json)
- **Rows Iniciales**: 5 flags (USE_RERANKER, EMBEDDINGS_MODEL, etc.)

---

### 🚦 CI/CD

#### 📄 `.github/workflows/ci.yml`
- **Propósito**: Pipeline de CI/CD para GitHub Actions
- **Jobs**: 6
  1. `lint` - Ruff linter
  2. `type-check` - MyPy type checking
  3. `test-unit` - Tests unitarios
  4. `test-contract` - Tests de contrato
  5. `test-fuzzing` - Fuzzing con schemathesis
  6. `security-scan` - Bandit security scan
- **Triggers**:
  - Push a `main`
  - Pull requests
- **Cómo probarlo localmente**:
  ```bash
  # Ejecutar equivalente local
  ruff check .
  mypy core/ api/
  pytest tests/
  ```

---

### ⚙️ Configuración

#### 📄 `milpa_ai_backend/requirements.txt`
- **Propósito**: Dependencies de Python para backend
- **Categorías**:
  - Web: fastapi, uvicorn
  - Métricas: prometheus-fastapi-instrumentator
  - OpenTelemetry: 10 packages (api, sdk, instrumentation)
  - Tests: pytest, schemathesis, hypothesis, jsonschema
  - OCR/Extracción: pymupdf, tesseract, camelot
  - ML: transformers, sentence-transformers, spacy
  - Vector DB: chromadb
  - BM25: whoosh
- **Total packages**: ~40
- **Última actualización**: Agregado opentelemetry-instrumentation-fastapi

#### 📄 `milpa_ai_backend/core/config.py`
- **Propósito**: Settings centralizados con pydantic-settings
- **Clase**: `Settings`
- **Configuraciones**:
  - `SQLITE_PATH` (default: data/milpa_knowledge.db)
  - `CHROMA_DIR` (default: data/vector_db)
  - `MODELS_DIR` (default: models/)
  - `TAXONOMY_VERSION` (default: 2025.09.10)
  - `ALLOWED_ORIGIN` (CORS)
  - `MAX_UPLOAD_MB` (default: 25)
- **Instancia global**: `settings`

#### 📄 `milpa_ai_backend/core/config_flags/feature_flags.py`
- **Propósito**: Feature flags dinámicos desde BD
- **Clase**: `FeatureFlags`
- **Flags disponibles**: 5
  - `USE_RERANKER` - Activar reranker (default: false)
  - `EMBEDDINGS_MODEL` - Modelo de embeddings
  - `ENABLE_TRANSLATION` - Traducción automática
  - `USE_TAXONOMY_ENRICHMENT` - Enriquecimiento con taxonomía
  - `ENABLE_OCR_FALLBACK` - OCR como fallback
- **Métodos**:
  - `is_enabled(flag_name)` - Verificar si flag activo
  - `get_config(flag_name)` - Obtener configuración JSON
  - `update(flag_name, enabled, config)` - Actualizar flag

---

### 📊 Métricas y Observabilidad

#### 📄 `milpa_ai_backend/core/telemetry.py`
- **Propósito**: Configuración de OpenTelemetry
- **Función**: `instrument_fastapi(app)`
- **Configuración**:
  - Service name: "milpa-backend-ia"
  - Sampling: 10% (ParentBasedTraceIdRatio)
  - Exporter: OTLP (Jaeger/Tempo) o Console
  - Resource attributes: service.name, deployment.environment
- **Spans enriquecidos**: request_id, user_agent, custom attributes

#### 📄 `milpa_presenter/src/telemetry/metrics.ts`
- **Propósito**: Métricas custom para Presenter (Frontend)
- **Métricas**: 6
  1. `milpa_chat_requests_total` - Contador de mensajes
  2. `milpa_chat_latency_seconds` - Histogram de latencias
  3. `milpa_rag_quality_score` - Gauge de calidad RAG
  4. `milpa_top_cultivos` - Counter de cultivos consultados
  5. `milpa_top_plagas` - Counter de plagas consultadas
  6. `milpa_citation_completeness` - Gauge de completitud de citas
- **Endpoint**: `/metrics` (compatible con Prometheus)

---

## 🗺️ MAPA DE NAVEGACIÓN

### Flujo: Setup Inicial de Desarrollador

```
1. VERIFICACION_FINAL.txt
   ↓ (Leer estado del sistema)
   
2. verificar_sistema.ps1
   ↓ (Ejecutar verificación automatizada)
   
3. crear_bd_tests.py
   ↓ (Crear BD de tests)
   
4. SPRINT_17_20_README.md
   ↓ (Entender arquitectura)
   
5. docker compose up --build -d
   ↓ (Levantar servicios)
   
6. pytest tests/test_contract_api.py -v
   ↓ (Ejecutar tests)
   
✅ Listo para desarrollar
```

### Flujo: Troubleshooting de Error

```
1. Observar error en terminal/logs
   ↓
   
2. CORRECCIONES_APLICADAS.md
   ↓ (Buscar si es error conocido)
   
3. REPORTE_DEBUGGING_COMPLETO.md
   ↓ (Buscar en "Errores Reportados")
   
4. Aplicar solución documentada
   ↓
   
5. Ejecutar verificación:
   - docker compose config --quiet
   - pytest tests/ -v
   ↓
   
✅ Error resuelto
```

### Flujo: Deploy a Producción

```
1. CORRECCIONES_APLICADAS.md
   ↓ (Verificar sistema funcional)
   
2. docker-compose.yml
   ↓ (Revisar configuración de servicios)
   
3. docs/observability/
   ↓ (Configurar Prometheus/Grafana)
   
4. .github/workflows/ci.yml
   ↓ (Configurar CI/CD pipeline)
   
5. docker compose up -d
   ↓ (Deploy)
   
6. Verificar endpoints:
   - http://localhost:8000/health
   - http://localhost:9090 (Prometheus)
   - http://localhost:3000 (Grafana)
   ↓
   
✅ Sistema en producción
```

---

## 🔍 BÚSQUEDA RÁPIDA

### "¿Cómo ejecuto...?"

| Necesidad | Documento | Comando |
|-----------|-----------|---------|
| Verificar sistema | VERIFICACION_FINAL.txt | `.\verificar_sistema.ps1` |
| Crear BD tests | crear_bd_tests.py | `python crear_bd_tests.py` |
| Levantar Docker | docker-compose.yml | `docker compose up -d` |
| Ejecutar tests | test_contract_api.py | `pytest tests/test_contract_api.py -v` |
| Ver métricas | prometheus.yml | `curl localhost:9090/metrics` |
| Acceder Grafana | grafana/ | http://localhost:3000 |

### "¿Dónde encuentro...?"

| Información | Documento | Sección |
|------------|-----------|---------|
| Lista de errores corregidos | CORRECCIONES_APLICADAS.md | "Resumen de Correcciones" |
| Cómo probar cada corrección | REPORTE_DEBUGGING_COMPLETO.md | "Archivos Modificados" → "Cómo Probarlo" |
| Features implementadas | SPRINT_17_20_README.md | "Componentes Implementados" |
| Configuración Docker | docker-compose.yml | Todo el archivo |
| Feature flags disponibles | feature_flags.py | Clase FeatureFlags |
| Endpoints API | endpoints.py | @router decorators |

### "¿Por qué se cambió...?"

| Cambio | Documento | Sección |
|--------|-----------|---------|
| user: 65534:65534 | REPORTE_DEBUGGING_COMPLETO.md | "Archivo #3: docker-compose.yml" → "Justificación" |
| config/ → config_flags/ | REPORTE_DEBUGGING_COMPLETO.md | "Archivo #4: core/config_flags/" → "Justificación" |
| +app = build_app() | REPORTE_DEBUGGING_COMPLETO.md | "Archivo #2: api/server.py" → "Justificación" |

---

## 📞 SOPORTE Y CONTACTO

### Para Reportar Errores
1. Verificar si error ya está documentado en `CORRECCIONES_APLICADAS.md`
2. Si es nuevo, crear issue con:
   - Descripción del error
   - Comando ejecutado
   - Output completo
   - Entorno (OS, Python version, Docker version)

### Para Sugerir Mejoras
1. Revisar "Mejoras Futuras Sugeridas" en `REPORTE_DEBUGGING_COMPLETO.md`
2. Si no está listado, crear propuesta con:
   - Problema actual
   - Solución propuesta
   - Beneficio esperado

---

## ✅ CHECKLIST DE DOCUMENTACIÓN

### ¿Está todo documentado?

- [x] **Arquitectura**: SPRINT_17_20_README.md
- [x] **Correcciones**: CORRECCIONES_APLICADAS.md
- [x] **Debugging**: REPORTE_DEBUGGING_COMPLETO.md
- [x] **Estado actual**: VERIFICACION_FINAL.txt
- [x] **Scripts helper**: crear_bd_tests.py, verificar_sistema.ps1
- [x] **Tests**: test_*.py con docstrings
- [x] **Configuración**: docker-compose.yml comentado
- [x] **Feature flags**: feature_flags.py documentado
- [x] **Métricas**: telemetry.py, metrics.ts
- [x] **Migraciones**: *.sql con comentarios

### ¿Es fácil de seguir?

- [x] **Índices**: Este documento (INDICE_DOCUMENTACION.md)
- [x] **Guías por perfil**: Sección "Guías de Lectura"
- [x] **Mapas de navegación**: Sección "Mapa de Navegación"
- [x] **Búsqueda rápida**: Sección "Búsqueda Rápida"
- [x] **Ejemplos de código**: En documentos técnicos
- [x] **Comandos copy-paste**: En todos los docs

---

**Última actualización**: 17 de octubre de 2025  
**Mantenedor**: Equipo MILPA  
**Versión de documentación**: 1.0

---

Para agregar nuevos documentos a este índice:
1. Crear el documento
2. Agregar entrada en la categoría apropiada
3. Actualizar mapas de navegación si es necesario
4. Actualizar checklist de documentación
5. Commit con mensaje: "docs: agregar [nombre-documento]"
