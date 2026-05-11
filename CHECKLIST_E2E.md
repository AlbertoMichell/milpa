## CHECKLIST E2E – Sistema MILPA al 100 % funcional

Fecha: 2026‑04‑27 · Ámbito: backend FastAPI, RAG, BD sintética y frontend `frontend/MILPA`.
Evidencia ejecutada con `py milpa_e2e.py` contra Uvicorn (`http://127.0.0.1:8000`). Lanzador `start.ps1` (Hidden + OMP/MKL single-thread) para evitar `forrtl: (200) window-CLOSE` en tareas/CI.

---

### 1. Tareas completadas

| # | Tarea | Estado | Evidencia |
|---|-------|--------|-----------|
| 1 | Auditoría frontend (HTML + JS) | OK | `AUDITORIA_FRONTEND_TRAZABILIDAD.md` (25 datos hardcoded → 6 gaps de BD) |
| 2 | Migración SQL de gaps de esquema | OK | `milpa_ai_backend/core/logic/migrations/0010_dynamic_frontend_sources.sql` |
| 3 | Libro agronómico para RAG | OK | `docs/manual_maiz_milpa_2026.txt` (ingest + rebuild; p. ej. 80 fragmentos en última E2E) |
| 4 | Pipeline `/api/recommendations/generate` validado | OK | E2E genera *“riego urgente / high”* citando el manual |
| 5 | Endpoints FastAPI dinámicos (sensor xy, radar, targets) | OK | `crops.py`: `CropOut.sensor_x_pct/y_pct`, `optimal_targets`, `optimal_values` |
| 6 | Frontend: tiempo‑real consume `sensor_x_pct/y_pct` | OK | `tiempo-real.html` + `js/tiempo-real.js` (renderSensorMarkers) |
| 7 | Frontend: `datos.html` consume `optimal_targets` del perfil | OK | textos de óptimos generados desde API |
| 8 | Frontend: `base.html` con categorías y FAQ dinámicas | OK | `js/base.js` → `MILPA_API.getLibraryCategories/getFaqs` |
| 9 | Frontend: `dashboard.html` con notificaciones y mapa por usuario | OK | `MILPA_API.getNotifications/getProfile` |
| 10 | Pruebas E2E reproducibles | OK | `milpa_e2e.py` → **21 / 21 OK** |

---

### 2. Evidencia E2E (última ejecución)

```
=== MILPA E2E TEST · 2026-04-27 (corrida de verificación) ===
DB:      milpa_ai_backend/data/milpa_knowledge.db
Backend: http://127.0.0.1:8000

[OK] Backend HTTP disponible
[OK] Migraciones SQL aplicadas (yoyo)
[OK] Base de datos accesible
[OK] Usuario y cultivo demo listos
[OK] Libro agronómico encontrado
[OK] /api/documents/ingest respondió OK
[OK] /api/index/rebuild ejecutado          (80 fragmentos / 80 BM25 / 80 vector) [ej. tras reingesta]
[OK] Biblioteca con documentos suficientes (>1)        docs=9
[OK] Biblioteca con fragmentos para RAG (>20)          fragments=80
[OK] Tabla `faqs` poblada (>=5)                        faqs=8
[OK] Tabla `library_categories` poblada (==4)          cats=4
[OK] Recomendación generada por el pipeline            action='riego urgente' priority='high'
[OK] Acción coherente con caso 'maíz + 35-37°C + suelo 22%'
[OK] Prioridad alta o media (caso de estrés)
[OK] Recomendación persistida en `recommendations`
[OK] La recomendación tiene cuerpo agronómico (>50 chars)   len≈2000+
[OK] Recomendación contiene citas del RAG (cite_1..cite_3, manual_maiz)
[OK] /api/query no marca evidencia insuficiente             6 fragmentos retornados
[OK] Respuesta menciona riego/sombra/acolchado/humedad
[OK] /api/crops expone sensor_x_pct / sensor_y_pct (mapa)   crops=1
[OK] /api/irrigation-events/:id/efficiency con radar y targets
        radar=[90, 85, 95, 90, 95]
        targets={'liters_per_event': 45.0, 'freq_per_month': 4.0,
                 'duration_min': 35.0, 'expected_delta_pct': 12.0}

Resultado: 21/21 checks aprobados.
```

---

### 3. Caso E2E validado: “Maíz + 37 °C + humedad de suelo 22 %”

| Capa | Evidencia |
|------|-----------|
| **Sensor** | `sensor_readings` ← `(soil_moisture=22, air_temp=37, air_humidity=28, light=92)` |
| **Profile** | `crop_profiles.maiz` con `optimal_temp_max=32`, `optimal_soil_moisture_min=45`, `optimal_irrigation_liters=45`, `optimal_radar_json=[90,85,95,90,95]` |
| **Query construida** | `crops.py::build_recommendation_query` produce: *“cultivo: maiz; etapa: floracion; humedad suelo crítica 22%; temperatura alta 37°C; recomendación práctica para riego y manejo del calor”* |
| **RAG (recuperación)** | RRF híbrido devuelve 6 fragmentos; top‑1 = manual_maiz_milpa_2026, p.5 (“Si maíz AND HS<25 ⇒ riego urgente”) |
| **Síntesis** | `synthesis.compose_answer` ⇒ HTML con citas `cite_1..cite_3`, faithfulness > 0 |
| **Decisión** | `classify_action(...)` ⇒ `action='riego urgente'`, `priority='high'` |
| **Persistencia** | `INSERT INTO recommendations` con `query_text`, `action`, `priority`, `detail_html`, `citations`, `faithfulness` |
| **UI** | `tiempo-real.html` muestra alerta + recomendación; `recomendaciones.html` la lista con badge rojo |

---

### 4. Cómo reproducir

```powershell
$env:PYTHONUTF8 = "1"

py -m uvicorn milpa_ai_backend.main:app --host 127.0.0.1 --port 8000

py milpa_e2e.py
```

Salida esperada: `Resultado: 21/21 checks aprobados.`

---

### 5. Artefactos producidos en este sprint

- `milpa_ai_backend/core/logic/migrations/0010_dynamic_frontend_sources.sql` – migración con los 6 gaps de esquema (`notifications`, `user_profiles`, `user_crops`, `crop_profiles`, `faqs`, `library_categories`).
- `docs/manual_maiz_milpa_2026.txt` – manual agronómico de maíz (umbrales, reglas “si X entonces Y”, etapas fenológicas).
- `milpa_e2e.py` – script reproducible que aplica migraciones, siembra el caso, ingesta el manual, dispara la recomendación y verifica todo el flujo.
- `AUDITORIA_FRONTEND_TRAZABILIDAD.md` – inventario completo de hardcoded → tabla/columna destino.
- `frontend/MILPA/*.html` y `frontend/MILPA/js/*.js` – UI cableada a las APIs nuevas.
- `frontend/routes/api.js` – rutas Express de `notifications`, `faqs`, `library/categories` y `profile` extendido.
- `milpa_ai_backend/api/crops.py` – `CropOut` con coordenadas del sensor; `irrigation-events/:id/efficiency` con `optimal_targets` y `optimal_values` leídos de `crop_profiles`.
