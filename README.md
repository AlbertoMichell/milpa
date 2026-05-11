# MILPA - Sistema RAG Agrícola

Sistema de Recuperación Aumentada por Generación (RAG) especializado en agricultura mexicana (milpa: maíz, frijol, calabaza), con extracción de entidades, búsqueda híbrida BM25 + vectorial y generación de respuestas con citaciones.

## Características

- **Búsqueda híbrida** BM25 + ChromaDB con Reciprocal Rank Fusion (RRF)
- **Extracción de entidades** NER (cultivos, nutrientes, plagas, taxonomía agrícola)
- **Detección de evidencia insuficiente** (evita alucinaciones)
- **OCR** para documentos escaneados (Tesseract, spa+eng)
- **Extracción de tablas** (Camelot lattice/stream)
- **Biblioteca documental** con búsqueda, filtros y detalle
- **Feature flags dinámicos** (sin reiniciar el servicio)
- **Observabilidad** Prometheus + Grafana + OpenTelemetry (opcional vía Docker)

## Requisitos

- **Python 3.11+**
- **Node.js 20+**
- **PowerShell 5.1+** (viene con Windows)

Docker es **opcional** (solo si necesitas ClamAV, Prometheus o Grafana).

## Inicio rápido (local, sin Docker)

**Entrada única recomendada** (levanta los tres servicios):

```powershell
cd C:\ruta\a\milpa
.\start.ps1
```

Equivalente sin tocar ExecutionPolicy del usuario:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

O **doble clic** en `start.bat` (delega en `start.ps1` con Bypass).

El script `start.ps1` automáticamente:
1. Verifica Python y Node.js
2. Aplica migraciones SQLite (yoyo) sobre `milpa_ai_backend/data/milpa_knowledge.db`
3. Crea directorios de datos necesarios
4. Instala dependencias npm del presenter y del frontend (si faltan)
5. Compila TypeScript del presenter (si falta)
6. Recompila `better-sqlite3` del frontend para evitar ABI mismatch
7. Libera puertos 8000 / 8080 / 4000 si estaban ocupados
8. Inicia **backend** (:8000), **presenter** (:8080) y **frontend MILPA** (:4000)
9. Muestra las URLs de acceso

**Depuración puntual:** solo `node frontend/server.js` tiene sentido si el backend ya corre en `:8000`; el arranque normal debe ser siempre `start.ps1` / `start.bat`.

**Mantenerse al día con `git pull`:** `start.ps1` ahora deja el directorio de trabajo en la raíz del repo (las migraciones yoyo ya no dependen de desde dónde ejecutes el script), vuelve a ejecutar `pip install` si cambió `milpa_ai_backend/requirements.txt`, `npm install` si cambió `package-lock.json` del frontend o del presenter, y recompila el presenter con `npm run build` si el código TypeScript es más reciente que `dist/`. Para forzar reinstalación y build en cada arranque: `$env:MILPA_FORCE_SYNC = "1"; .\start.ps1`.

Para detener:

```powershell
.\stop.ps1
```

(o `stop.bat`, que delega en `stop.ps1`)

## URLs de Acceso

| Servicio | Puerto | URL | Descripción |
|----------|--------|-----|-------------|
| **Backend API** | 8000 | http://localhost:8000/health | Healthcheck |
| **API Docs** | 8000 | http://localhost:8000/docs | Documentación OpenAPI |
| **Presenter** | 8080 | http://localhost:8080/ui/library | Catálogo de documentos |
| **Consultas RAG** | 8080 | http://localhost:8080/ui/query | Interfaz de búsqueda |
| **Verificación** | 8080 | http://localhost:8080/ui/checks | Estado del sistema |
| **MILPA Web** | 4000 | http://localhost:4000/login.html | Login y aplicación Express (dashboard, datos, etc.) |

## Arquitectura

```
milpa/
├── milpa_ai_backend/           # Backend Python (FastAPI + uvicorn :8000)
│   ├── api/                    # Endpoints: upload, extract, query, library, flags
│   ├── core/
│   │   ├── config.py           # Configuración centralizada (Pydantic Settings)
│   │   ├── config_flags/       # Feature flags dinámicos (SQLite)
│   │   ├── logic/              # BM25, ChromaDB, embeddings, RAG engine, NER
│   │   ├── extract/            # Pipeline extracción PDF/DOCX/OCR/tablas
│   │   ├── security/           # Integración ClamAV (opcional)
│   │   └── telemetry/          # OpenTelemetry (opcional)
│   ├── data/                   # SQLite, vector_db, bm25_idx, documents/
│   ├── main.py                 # Punto de entrada (uvicorn main:app)
│   └── requirements.txt
├── frontend/                   # Express :4000 — login, MILPA, proxy /api/ai/* → :8000
│   ├── server.js
│   └── MILPA/
├── milpa_presenter/            # Presenter TypeScript (Fastify :8080)
│   ├── src/
│   │   ├── server.ts           # Servidor web, proxy /ai/*, UI embebida
│   │   ├── config.ts           # Configuración (puertos, URLs)
│   │   ├── runtime/            # Scheduler (cola), Circuit breaker
│   │   ├── security/           # Headers CSP, sanitización HTML
│   │   └── telemetry/          # Métricas Prometheus
│   └── package.json
├── docker-compose.yml          # Opcional: stack completo con ClamAV/Prometheus/Grafana
├── start.ps1                   # Iniciar sistema local
├── stop.ps1                    # Detener sistema local
└── README.md
```

## Tecnologías

| Capa | Tecnología | Uso |
|------|-----------|-----|
| Backend API | FastAPI + uvicorn | REST API, async |
| Base de datos | SQLite (WAL) | Documentos, fragmentos, tablas, feature flags |
| Vector store | ChromaDB | Embeddings para búsqueda semántica |
| Índice léxico | Tantivy/Whoosh | BM25 para búsqueda por texto |
| Embeddings | sentence-transformers | paraphrase-multilingual-MiniLM-L12-v2 |
| NER | spaCy + diccionarios | Taxonomía agrícola (cultivos, plagas, nutrientes) |
| PDF | PyMuPDF + Tesseract + Camelot | Extracción texto, OCR, tablas |
| Presenter | Fastify (TypeScript) | Proxy, UI, métricas, seguridad |
| Observabilidad | Prometheus + Grafana + OTEL | Opcional vía Docker |

## Desarrollo

### Agregar documentos al corpus

```powershell
# Subir un PDF via API (con el sistema corriendo)
curl -X POST http://localhost:8000/api/documents/upload -F "file=@mi_documento.pdf" -F "title=Guia de maiz" -F "license=institutional" -F "classification=Publico"

# Extraer contenido (usar el doc_id devuelto)
curl -X POST http://localhost:8000/api/documents/{doc_id}/extract

# Reconstruir índices
curl -X POST http://localhost:8000/api/index/rebuild
```

### Consulta RAG via API

```powershell
curl -X POST http://localhost:8000/api/query -H "Content-Type: application/json" -d '{"query": "fertilizacion de maiz", "k": 5, "mode": "hybrid"}'
```

### Docker (opcional, para stack completo)

```powershell
docker compose up --build -d    # Levanta 5 servicios
docker compose down             # Detener
```

Servicios Docker adicionales: ClamAV (:3310), Prometheus (:9090), Grafana (:3000).

## Base de datos

Una sola base SQLite: `milpa_ai_backend/data/milpa_knowledge.db`

Tablas: `docs`, `fragments`, `fine_refs`, `tables`, `table_cells`, `feature_flags`.

Migraciones automáticas al iniciar (yoyo-migrations).

## Licencia

MIT
