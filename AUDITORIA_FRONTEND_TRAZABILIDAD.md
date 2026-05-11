# Auditoría Frontend MILPA — Inventario hardcoded + matriz de trazabilidad

Fecha: 2026‑04‑27 · Alcance: `frontend/MILPA/*.html` y `frontend/MILPA/js/*.js`.
Fuente cruzada: `milpa_ai_backend/api/*` y `milpa_ai_backend/core/logic/migrations/*.sql`.

> **Convención**
> · *FE-fixed*: dato literal en HTML/JS sin origen en API.
> · *FE-fallback*: dato puesto solo si la API no responde (aceptable, pero documentado).
> · *Estado BD*: `ok` (existe campo) · `falta` (no existe) · `no-usado` (existe pero el FE no lo lee).

---

## 1. Inventario de datos hardcoded por archivo

### 1.1 `dashboard.html`

| # | Dato fijo | Línea | Representa | Origen ideal | Estado BD |
|---|-----------|-------|------------|--------------|-----------|
| 1 | `Nueva recomendación disponible` (notification dropdown item) | ~340-345 | Texto de notificación | `notifications.title/message` filtrado por `user_id` | **falta** `user_id` en `notifications` |
| 2 | `Alerta de clima: posible sequía` | ~340-345 | Notificación clima | `notifications` (tipo `alert`) por usuario | **falta** `user_id` |
| 3 | iframe OSM `bbox=-96.9512,19.6478,-96.9225,19.6591` y `marker=-96.936838,19.653445` | ~420-426 | Coordenadas geo del usuario | `user_profiles.lat/lon` | **falta** columnas |
| 4 | `>= 35` umbral estrés térmico | 612 | Threshold UI | `user_settings.max_temperature` | ok (no usado en este check) |
| 5 | `elementos/Campesinos.jpg` avatar fallback | varios | Avatar default | `user_profiles.avatar_path` o asset fallback | ok (es fallback) |

### 1.2 `tiempo-real.html` + `js/tiempo-real.js`

| # | Dato fijo | Línea | Representa | Origen ideal | Estado BD |
|---|-----------|-------|------------|--------------|-----------|
| 6 | `top:30%; left:25%`, `top:20%; right:30%`, `bottom:25%; left:30%`, `bottom:30%; right:20%` | tiempo-real.html 378-381 | Posición XY de los marcadores de sensor por cultivo | `user_crops.sensor_x_pct` / `sensor_y_pct` | **falta** columnas |
| 7 | `elementos/mapa.jpg` | ~382 | Imagen de fondo del mapa | Asset estático aceptable | ok (asset) |
| 8 | `?? 40, ?? 35, ?? 50, ?? 90, 35, 90` (rangos defaults) | js/tiempo-real.js 116-135 | Defaults cuando no hay settings | `user_settings.*` y `crop_profiles.*` | parcial (falta exposición de profile en tiempo-real) |
| 9 | Status text `"óptimo"`, `"alta"`, `"ideal"`, `"baja"` iniciales | tiempo-real.html 320,333,346,359 | Estado inicial antes de cargar datos | `sensor_readings` + `user_settings` | ok |

### 1.3 `recomendaciones.html`

| # | Dato fijo | Línea | Representa | Origen ideal | Estado BD |
|---|-----------|-------|------------|--------------|-----------|
| 10 | Lista de cultivos del filtro (`Maíz`, `Frijol`, `Calabaza`, `Chile`, `Tomate`) | 393-397 | Catálogo de cultivos | `crop_profiles.crop_name` | ok (no consumido) |
| 11 | Lista de tipos de acción (`riego`, `fertilización`, ...) | 404-408 | Taxonomía de acciones | Constante UI o tabla `taxonomy` | aceptable hardcoded |
| 12 | Iconos por cultivo (`bi-flower`, `bi-tree`, etc.) | renderRecommendationCards | Mapping visual | Constante UI mapeada por `crop_name` | ok (UI mapping) |

### 1.4 `datos.html`

| # | Dato fijo | Línea | Representa | Origen ideal | Estado BD |
|---|-----------|-------|------------|--------------|-----------|
| 13 | `optimal_values: [90,85,95,90,95]` para radar | datos.html 662 / crops.py 899 | Valores óptimos (suelo, temp, humedad, luz, precipitación) | `crop_profiles.optimal_radar_json` | **falta** columna |
| 14 | `OPTIMAL_LITERS = 45.0`, `OPTIMAL_FREQ = 4`, `EXPECTED_DELTA = 12.0`, `OPTIMAL_DUR = 35.0` | crops.py 845-877 | Targets de eficiencia de riego | `crop_profiles.opt_irrigation_*` | **falta** columnas |
| 15 | `(avgMoisture / 70) * 95` umbral 70/95 | datos.html 632 | Threshold UI | `crop_profiles.optimal_soil_moisture_*` | ok (no usado) |
| 16 | Texto fijo *“óptimo de 45L”*, *“se recomiendan 4”*, *“meta: ~35 min”* | datos.html 764-777 | Constantes texto | Derivar del profile | igual al #14 |

### 1.5 `base.html` (Biblioteca / Conocimiento)

| # | Dato fijo | Línea | Representa | Origen ideal | Estado BD |
|---|-----------|-------|------------|--------------|-----------|
| 17 | 4 categorías (Técnicas, Plagas, Agua, Calendario lunar) con `data-query` fijo | 262-299 | Atajos de búsqueda guiada | Tabla `library_categories` o constante UI | aceptable UI |
| 18 | 3 FAQ con pregunta y respuesta literal | 327-396 | Preguntas frecuentes | Tabla `faqs` | **falta** tabla |
| 19 | `default search query = "milpa"` | 305 | Query por defecto del buscador | Constante UI | ok |

### 1.6 `calendario.html` + `js/calendario.js`

| # | Dato fijo | Línea | Representa | Origen ideal | Estado BD |
|---|-----------|-------|------------|--------------|-----------|
| 20 | `eventTypeMeta` (sowing, harvest, maintenance, pest, other) con labels y badges | calendario.js | Catálogo de tipos | Constante UI | ok (UI mapping) |
| 21 | `<option>` literales en `event_type` | calendario.html 264-269 | Taxonomía calendario | Constante UI | ok |

### 1.7 `configuracion.html` + `js/configuracion.js`

> Casi todos son **valores `value=` por defecto** del HTML, sobrescritos por `fillProfile()` y `fillSettings()` desde la API. Son aceptables pero pueden inducir a error si la API falla.

| # | Dato fijo | Línea | Representa | Origen ideal | Estado BD |
|---|-----------|-------|------------|--------------|-----------|
| 22 | `value="Juan"`, `value="Pérez"`, bio "Agricultor tradicional...", `value="Coatepec,Veracruz"` | 284-296 | Defaults del HTML | `user_profiles.*` | ok (campos existen) |
| 23 | `juan.perez@example.com`, `+52 241 123 4567` | 423-427 | Defaults de cuenta | `user_profiles.email/phone` | ok |
| 24 | `min_soil_moisture=40`, `max_temperature=35`, `min_air_humidity=50`, `pest_threshold=3` (rangos) | 569-597 | Umbrales por defecto | `user_settings.*` | ok (campos existen) |
| 25 | `elementos/default.jpg` para preview de planta | 167 | Imagen fallback | `user_crops.image_path` | ok |

---

## 2. Resumen de gaps de esquema (lo que **falta** en la BD)

| Gap | Tabla | Columnas / Propuesta | Justificación |
|-----|-------|----------------------|---------------|
| G1 | `notifications` | `+ user_id INTEGER`, `+ user_crop_id INTEGER`, `+ link_url TEXT`, `+ read_at TEXT` | Hoy son globales y sin segmentar por usuario; el dashboard las pinta hardcoded. |
| G2 | `user_profiles` | `+ lat REAL`, `+ lon REAL`, `+ geo_zoom INTEGER` | El mapa del dashboard usa coords fijas de Coatepec. |
| G3 | `user_crops` | `+ sensor_x_pct REAL`, `+ sensor_y_pct REAL` | Posición visual del marcador de sensor en el mapa de tiempo-real. |
| G4 | `crop_profiles` | `+ optimal_irrigation_liters REAL`, `+ optimal_irrigation_freq_per_month REAL`, `+ optimal_irrigation_duration_min REAL`, `+ expected_irrigation_delta_pct REAL`, `+ optimal_radar_json TEXT` | Hoy estos óptimos están hardcoded en backend (`crops.py`) y frontend (`datos.html`). |
| G5 | nueva `faqs` | `id`, `category`, `crop_name`, `question`, `answer`, `related_doc_id`, `priority`, `created_at` | El bloque FAQ de `base.html` está completamente literal. |
| G6 | nueva `library_categories` | `id`, `slug`, `title`, `description`, `query_example`, `icon`, `priority` | Las 4 tarjetas de `base.html` son literales. |

---

## 3. Estado de **contenido** (no solo esquema)

| Tabla | Filas hoy | Necesidad | Acción |
|-------|-----------|-----------|--------|
| `users` | 7 | usuario demo `milpa_demo` | crear si falta |
| `user_crops` | 10 | cultivo maíz “estrés térmico” | crear vía seed |
| `sensor_readings` | 228 | última lectura con `air_temp=37 °C, soil_moisture=22%, air_humidity=28%` | inyectar |
| `crop_profiles` | 5 | añadir óptimos riego + radar | UPDATE en migración |
| `notifications` | 3 globales | 1 por usuario (recomendación + clima) | seed después de migrar |
| `calendar_events` | 0 | 2 eventos demo de maíz | seed |
| `docs` / `fragments` | 7 / 22 | **libro agronómico de maíz** completo | ingest vía `/api/documents/ingest` |
| `recommendations` | 3 | una recomendación generada del caso “maíz + 35 °C” con fuentes del libro | E2E test |
| `faqs` | — (tabla nueva) | 5–10 FAQ con `crop_name`, `category`, `answer` | seed |
| `library_categories` | — (tabla nueva) | 4 categorías base | seed |

---

## 4. Conclusión del audit

- 25 puntos detectados; 17 sin origen real en BD, 8 son fallbacks/UI aceptables.
- 6 gaps de esquema que cubrirá la migración **`0010_dynamic_frontend_sources.sql`**.
- El gap mayor es el **contenido documental**: con solo 22 fragmentos en la biblioteca, el RAG no puede sostener recomendaciones agronómicas de calidad. Por eso el siguiente paso es ingestar el “libro” de maíz (`docs/manual_maiz_milpa_2026.txt`) para que `compose_answer()` tenga material agronómico real.
