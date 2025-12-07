# MILPA - Sistema RAG Agrícola

Sistema de Recuperación Aumentada por Generación (RAG) especializado en agricultura, con extracción de entidades (cultivos, nutrientes, plagas) y búsqueda híbrida BM25 + vectorial.

## Características

- ✅ **Extracción de entidades** con NER (25/37 fragmentos con cultivos, nutrientes, plagas identificados)
- ✅ **Búsqueda híbrida** BM25 + ChromaDB con Reciprocal Rank Fusion
- ✅ **Detección de evidencia insuficiente** (evita alucinaciones)
- ✅ **OCR** para documentos escaneados (Tesseract)
- ✅ **Extracción de tablas** (Camelot)
- ✅ **Métricas** Prometheus + Grafana
- ✅ **Trazas distribuidas** OpenTelemetry

## Requisitos

- **Docker Desktop** (Windows/Mac/Linux)
- **PowerShell** 5.1+ (viene con Windows)

## Instalación y Ejecución

```powershell
# Clonar repositorio
git clone https://github.com/TU-USUARIO/milpa.git
cd milpa

# Levantar toda la plataforma (construye, indexa, verifica)
.\run_all.ps1
```

El script `run_all.ps1` automáticamente:
1. Construye imágenes Docker
2. Levanta servicios (backend, presenter, prometheus, grafana)
3. Espera a que estén listos
4. Reconstruye índices BM25 y vectoriales **con entidades**
5. Ejecuta consulta de verificación
6. Muestra URLs de acceso

## URLs de Acceso

- **Backend API**: http://localhost:8000
  - Health: http://localhost:8000/health
  - Docs: http://localhost:8000/docs
  - Biblioteca: http://localhost:8000/library

- **Presenter (UI)**: http://localhost:8080
  - Consultas: http://localhost:8080/ui/query
  - Biblioteca: http://localhost:8080/ui/library
  - Checks: http://localhost:8080/ui/checks

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000

## Arquitectura

```
milpa/
├── milpa_ai_backend/        # Backend Python (FastAPI)
│   ├── api/                 # Endpoints RAG
│   ├── core/
│   │   ├── logic/          # BM25, vectorDB, NER, embeddings
│   │   ├── extract/        # Pipeline extracción PDF/DOCX/OCR
│   │   └── security/       # Antivirus ClamAV
│   └── models/taxonomy/    # Cultivos, plagas, nutrientes
├── milpa_presenter/         # Frontend Node.js (Express)
├── prometheus/              # Configuración métricas
├── grafana/                 # Dashboards
├── docker-compose.yml       # Orquestación servicios
└── run_all.ps1             # Script de despliegue automático
```

## Tecnologías

### Backend
- **FastAPI** - API REST
- **ChromaDB** - Vector store (embeddings)
- **Whoosh** - BM25 búsqueda léxica
- **sentence-transformers** - Embeddings multilingües
- **spaCy** - NER extracción entidades
- **PyMuPDF** - Extracción PDF
- **Tesseract** - OCR
- **ClamAV** - Antivirus
- **SQLite** - Base de datos documentos/fragmentos

### Frontend
- **Express** - Servidor web
- **EJS** - Templates
- **Axios** - Cliente HTTP

### Observabilidad
- **Prometheus** - Métricas
- **Grafana** - Visualización
- **OpenTelemetry** - Trazas distribuidas

## Desarrollo

### Agregar nuevos documentos

```powershell
# Copiar PDF/DOCX a milpa_ai_backend/data/documents/
docker-compose exec ai python -m milpa_ai_backend.extract_all_docs

# Reconstruir índices
curl -X POST http://localhost:8000/api/index/rebuild
```

### Ver logs

```powershell
docker-compose logs -f ai        # Backend
docker-compose logs -f presenter # Frontend
```

### Detener servicios

```powershell
docker-compose down
```

## Licencia

MIT
