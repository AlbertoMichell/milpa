# Arquitectura Unificada MILPA AI

## Resumen
Sistema de dos capas con frontend/proxy TypeScript y backend Python de IA.

## Componentes

### 1. **milpa_presenter** (Puerto 8080) - FRONTEND ÚNICO
**Tecnología**: TypeScript + Fastify  
**Responsabilidad**: Interfaz de usuario y proxy inteligente

**Endpoints de interfaz**:
- `GET /ui/checks` - Verificaciones del sistema
- `GET /ui/library` - Biblioteca de documentos (listado)
- `GET /ui/library/:docId` - Detalle de documento

**Endpoints de proxy** (reenvía a backend):
- `ALL /ai/*` - Proxy transparente al backend Python
  - `/ai/health` → `http://localhost:8000/health`
  - `/ai/library` → `http://localhost:8000/library`
  - `/ai/query` → `http://localhost:8000/api/query`
  - `/ai/admin/feature-flags` → `http://localhost:8000/admin/feature-flags`

**Características**:
- Circuit breaker para protección
- Rate limiting (60 req/min)
- Queue management (8 concurrentes, 64 en cola)
- Sanitización HTML para seguridad
- Métricas Prometheus en `/metrics`

### 2. **milpa_ai_backend** (Puerto 8000) - BACKEND PURO
**Tecnología**: Python + FastAPI  
**Responsabilidad**: API de IA, RAG, embeddings, extracción

**Endpoints API**:
- `GET /health` - Health check
- `POST /api/query` - RAG queries con generación LLM
- `POST /api/index/rebuild` - Reconstruir índices
- `GET /library` - Lista documentos (con filtros)
- `GET /library/:doc_id` - Detalle documento con tablas
- `GET /library/facets` - Facetas (años, autores)
- `GET /admin/feature-flags` - Lista feature flags
- `PUT /admin/feature-flags/:name` - Actualizar flag

**NO TIENE INTERFAZ HTML** - Solo API REST

## Flujo de datos

```
Usuario → http://localhost:8080/ui/library
         ↓
    milpa_presenter (TypeScript)
         ↓ (renderiza HTML)
    Browser del usuario

Usuario → http://localhost:8080/ui/checks
         ↓ (click "Cargar biblioteca")
    Fetch a /ai/library
         ↓
    milpa_presenter proxy
         ↓
    http://localhost:8000/library
         ↓
    milpa_ai_backend (Python)
         ↓ (retorna JSON)
    milpa_presenter
         ↓ (renderiza en HTML)
    Browser del usuario
```

## Punto de entrada ÚNICO

**URL de acceso**: `http://localhost:8080/ui/checks`

- Toda la interfaz se sirve desde el presenter
- El backend Python solo expone API REST
- El presenter hace proxy transparente a `/ai/*`

## Ventajas de esta arquitectura

1. **Separación de responsabilidades**:
   - Frontend/UX → TypeScript (rápido, tipado, seguro)
   - IA/ML → Python (ecosistema maduro)

2. **Seguridad**:
   - Sanitización HTML en presenter
   - Rate limiting y circuit breaker
   - Backend sin exposición directa al usuario

3. **Escalabilidad**:
   - Presenter puede escalar horizontalmente
   - Backend maneja solo lógica de IA
   - Queue management previene sobrecarga

4. **Mantenibilidad**:
   - Código frontend separado del backend
   - Interfaz HTML en un solo lugar (presenter)
   - Backend enfocado en lógica de negocio

## Diseño visual

**Paleta de colores MILPA**:
- Verde primario: `#2E7D32`
- Verde oscuro: `#1b5e20`
- Verde claro: `#81c784`
- Acento: `#10b981`
- Fondo: `#f4f6f9`
- Cards: `#ffffff`

**Características**:
- Tipografía: Inter con fallback a system fonts
- Shadows suaves: `0 0 15px rgba(0,0,0,0.05)`
- Border radius: `8px`
- Sin emojis (diseño profesional)
- Hover effects: `translateY(-3px)` + shadow aumentada

## Docker Compose

```yaml
services:
  ai:
    build: ./milpa_ai_backend
    ports:
      - "8000:8000"  # Solo para debug, no expuesto en producción
    
  presenter:
    build: ./milpa_presenter
    ports:
      - "8080:8080"  # ÚNICO PUERTO PÚBLICO
    environment:
      - IA_URL=http://ai:8000
    depends_on:
      - ai
```

## Desarrollo

```bash
# Terminal 1: Backend Python
cd milpa_ai_backend
docker-compose up

# Terminal 2: Presenter TypeScript
cd milpa_presenter
npm run dev

# Acceso: http://localhost:8080/ui/checks
```

## Producción

```bash
# Levantar todo el stack
docker-compose up -d

# Acceso: http://localhost:8080/ui/checks
# Backend NO es accesible directamente
```

## Migraciones realizadas

**ELIMINADO del backend Python**:
- ❌ `GET /admin` - Interfaz HTML redundante
- ❌ `GET /` - Redirect a /admin
- ❌ `static/admin.html` - Archivo HTML de 51KB redundante

**CONSERVADO en presenter**:
- ✅ `/ui/checks` - Verificaciones completas
- ✅ `/ui/library` - Biblioteca con filtros
- ✅ `/ui/library/:docId` - Vista detalle con tabs

## Testing

```bash
# Verificar salud del stack
curl http://localhost:8080/health
curl http://localhost:8080/ai/health

# Probar biblioteca
curl http://localhost:8080/ai/library

# Probar RAG
curl -X POST http://localhost:8080/ai/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "fertilización de maíz", "k": 5, "mode": "hybrid"}'
```

## Conclusión

La arquitectura está **UNIFICADA**. Un solo punto de entrada (puerto 8080) sirve toda la interfaz HTML y hace proxy al backend de IA. No hay duplicación de interfaces ni endpoints redundantes.
