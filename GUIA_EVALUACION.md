# 📚 GUÍA DE USO - Sistema de Evaluación RAG

## 🎯 Descripción

Este sistema de evaluación implementa métricas estándar de la industria para medir la **confiabilidad y fiabilidad** del pipeline RAG de MILPA AI.

---

## 📁 Archivos del Sistema

### 1. Dataset de Evaluación
```
evaluation_dataset.json
```
- **12 queries de test** con ground truth anotado
- Cada query incluye:
  - Pregunta
  - Respuesta esperada
  - Keywords relevantes
  - Fragmentos esperados
  - Categoría (nutrición, descriptivo, comparativo, etc.)

### 2. Scripts de Evaluación

#### `evaluate_rag_metrics.py`
**Script principal de evaluación completa**

Calcula:
- ✅ **Precision@K** (K=1,3,5): ¿Cuántos de los K resultados son relevantes?
- ✅ **Recall@K**: ¿Cuántos fragmentos relevantes se encontraron?
- ✅ **MRR** (Mean Reciprocal Rank): ¿En qué posición aparece el primer resultado relevante?
- ✅ **Faithfulness Score**: ¿Los fragmentos son fieles al documento original?
- ✅ **Success Rate**: ¿Cuántas queries devuelven resultados?

**Uso:**
```powershell
python evaluate_rag_metrics.py
```

**Salida:**
- Reporte en consola con métricas agregadas
- Archivo `evaluation_results_hybrid.json` con resultados detallados

---

#### `generate_metrics_report.py`
**Genera reporte visual detallado**

Incluye:
- Barras de progreso visuales para cada métrica
- Análisis por categoría de pregunta
- Top 5 queries con mejor rendimiento
- Queries problemáticas identificadas
- Interpretación de resultados

**Uso:**
```powershell
python generate_metrics_report.py
```

**Ejemplo de salida:**
```
🎯 PRECISION@K (¿Cuántos de los K resultados son relevantes?)
────────────────────────────────────────────────────────────
  P@1: ████████████████████████████████████░░░░  91.7% (0.917)
  P@3: ██████████████████████████████████░░░░░░  86.1% (0.861)
  P@5: █████████████████████████████░░░░░░░░░░░  73.3% (0.733)
```

---

#### `compare_search_modes.py`
**Compara modos de búsqueda: lex, dense, hybrid**

Evalúa:
- **lex**: BM25 solo (búsqueda léxica/keywords)
- **dense**: Vectorial solo (búsqueda semántica)
- **hybrid**: BM25 + vectorial + RRF + re-ranking

**Uso:**
```powershell
python compare_search_modes.py
```

**Salida:**
- Tabla comparativa de Success Rate, MRR, P@5
- Análisis de mejora porcentual
- Recomendación de modo óptimo
- Archivo `mode_comparison.json`

---

#### `executive_summary.py`
**Resumen ejecutivo en formato de tabla**

Para presentaciones y reportes ejecutivos.

**Uso:**
```powershell
python executive_summary.py
```

**Salida:**
```
┌─────────────────────────────────┬──────────┬─────────────────────────────┐
│ MÉTRICA                         │  VALOR   │ INTERPRETACIÓN              │
├─────────────────────────────────┼──────────┼─────────────────────────────┤
│ Success Rate                    │  100.0% │ EXCELENTE                   │
│ Mean Reciprocal Rank (MRR)      │  0.917  │ EXCELENTE                   │
│ Precision@1                     │   91.7% │ EXCELENTE                   │
│ Precision@5                     │   73.3% │ BUENO                       │
│ Faithfulness Score              │   66.1% │ BUENO                       │
└─────────────────────────────────┴──────────┴─────────────────────────────┘
```

---

## 🚀 Flujo de Uso Completo

### Paso 1: Ejecutar evaluación completa
```powershell
python evaluate_rag_metrics.py
```

**Qué hace:**
- Ejecuta 12 queries de test contra el API RAG
- Calcula todas las métricas
- Guarda resultados en `evaluation_results_hybrid.json`

**Tiempo estimado:** 30-60 segundos (2-5 segundos por query)

---

### Paso 2: Generar reporte visual
```powershell
python generate_metrics_report.py
```

**Qué hace:**
- Lee `evaluation_results_hybrid.json`
- Genera visualización con barras de progreso
- Identifica problemas y top performers
- Proporciona interpretación

**Tiempo estimado:** <1 segundo

---

### Paso 3: Comparar modos (opcional)
```powershell
python compare_search_modes.py
```

**Qué hace:**
- Ejecuta mismas queries en lex, dense, hybrid
- Compara rendimiento
- Identifica modo óptimo

**Tiempo estimado:** 1-2 minutos (ejecuta 36 queries)

---

### Paso 4: Generar resumen ejecutivo
```powershell
python executive_summary.py
```

**Qué hace:**
- Tabla compacta para presentaciones
- Recomendaciones prioritarias
- Evaluación general del sistema

**Tiempo estimado:** <1 segundo

---

## 📊 Interpretación de Métricas

### Success Rate
```
100% → ✅ EXCELENTE - Todas las queries devuelven resultados
 80% → ✓  BUENO - La mayoría devuelve resultados
 50% → ⚠️  MEJORABLE - Muchas queries rechazadas
```

### Mean Reciprocal Rank (MRR)
```
0.9+ → ✅ EXCELENTE - Primer resultado casi siempre relevante (posición ~1.1)
0.7+ → ✓  BUENO - Primer relevante en top-2 generalmente
0.5+ → ⚠️  ACEPTABLE - Hay resultados relevantes pero no primero
0.3- → ❌ MEJORABLE - Resultados relevantes aparecen tarde
```

### Precision@5
```
80%+ → ✅ EXCELENTE - 4-5 de los top-5 son relevantes
60%+ → ✓  BUENO - 3+ de los top-5 son relevantes
40%+ → ⚠️  ACEPTABLE - 2 de los top-5 son relevantes
20%- → ❌ MEJORABLE - Demasiado ruido
```

### Faithfulness Score
```
80%+ → ✅ EXCELENTE - Fragmentos muy fieles al documento
60%+ → ✓  BUENO - Fragmentos contienen info correcta
40%+ → ⚠️  ACEPTABLE - Correspondencia parcial
20%- → ❌ MEJORABLE - Fragmentos pueden no ser fieles
```

---

## 🔧 Personalización

### Agregar nuevas queries de test

Editar `evaluation_dataset.json`:

```json
{
  "id": 13,
  "query": "¿Cuál es el pH óptimo del suelo para maíz?",
  "expected_answer": "6.0-7.0",
  "relevant_keywords": ["pH", "suelo", "maíz", "óptimo"],
  "relevant_fragments": [
    "El pH óptimo del suelo para maíz está entre 6.0 y 7.0"
  ],
  "category": "suelo"
}
```

### Modificar valores de K

En `evaluate_rag_metrics.py`:

```python
K_VALUES = [1, 3, 5, 10]  # Agregar K=10
```

### Cambiar criterio de relevancia

En `evaluate_rag_metrics.py`, función `is_fragment_relevant()`:

```python
# Cambiar threshold de 60% a 70%
keyword_ratio = matched_keywords / len(expected_keywords)
return keyword_ratio >= 0.7  # Era 0.6
```

---

## 📈 Casos de Uso

### 1. Evaluación antes de deploy
```powershell
# Ejecutar suite completa
python evaluate_rag_metrics.py
python generate_metrics_report.py

# Verificar MRR >= 0.8 y P@5 >= 0.6
# Si cumple → Deploy a producción
# Si no → Investigar queries problemáticas
```

### 2. Comparación de versiones
```powershell
# Versión actual
python evaluate_rag_metrics.py
copy evaluation_results_hybrid.json evaluation_v1.json

# Hacer cambios (e.g., ajustar re-ranking)
# Ejecutar nuevamente
python evaluate_rag_metrics.py
copy evaluation_results_hybrid.json evaluation_v2.json

# Comparar MRR y P@5 entre v1 y v2
```

### 3. Identificar problemas específicos
```powershell
# Ejecutar reporte detallado
python generate_metrics_report.py

# Revisar sección "QUERIES PROBLEMÁTICAS"
# Investigar cada query con MRR < 0.5 o P@5 < 0.5
```

### 4. Validación de cambios en chunking
```powershell
# Antes de cambiar chunking
python evaluate_rag_metrics.py
copy evaluation_results_hybrid.json before_chunking.json

# Cambiar estrategia de chunking
# Re-extraer documentos
# Re-construir índices

# Después del cambio
python evaluate_rag_metrics.py
copy evaluation_results_hybrid.json after_chunking.json

# Comparar P@5 por categoría (especialmente "descriptivo")
```

---

## 🐛 Troubleshooting

### Error: "404 Not Found"
```
❌ Error consultando RAG: 404 Client Error: Not Found
```

**Solución:**
- Verificar que el API esté corriendo: `docker-compose ps`
- Verificar endpoint correcto: `http://localhost:8000/api/query`
- Reiniciar contenedor si es necesario: `docker-compose restart milpa_ai`

---

### Error: "insufficient_evidence: True" en todas las queries
```
⚠️  Insufficient evidence (12/12 queries)
```

**Solución:**
- Verificar que hay fragmentos indexados:
  ```powershell
  python -c "from milpa_ai_backend.core.logic.db import get_conn; print(get_conn().execute('SELECT COUNT(*) FROM fragments').fetchone())"
  ```
- Reconstruir índices si es necesario:
  ```powershell
  curl -X POST http://localhost:8000/api/index/rebuild
  ```

---

### Métricas muy bajas (MRR < 0.5, P@5 < 0.4)

**Posibles causas:**
1. **Chunking inadecuado**: Fragmentos muy grandes o muy pequeños
2. **Índices desactualizados**: Re-ejecutar rebuild
3. **Ground truth incorrecto**: Revisar `evaluation_dataset.json`
4. **Re-ranking no aplicado**: Verificar modo `hybrid`

**Solución:**
- Revisar log del API: `docker logs milpa_ai --tail 100`
- Validar que re-ranking está activo en `rag.py`
- Ajustar boost factor en `rag_engine.py`

---

## 📚 Referencias

### Artículos académicos
- **MRR**: Voorhees, E. M. (1999). "The TREC-8 Question Answering Track Report"
- **Precision/Recall**: Manning, C. D., et al. (2008). "Introduction to Information Retrieval"
- **Faithfulness**: RAG evaluation frameworks (LangChain, LlamaIndex)

### Implementaciones similares
- LangChain RAG evaluation
- LlamaIndex evaluation metrics
- BEIR benchmark (Information Retrieval)

---

## ✅ Checklist de Evaluación

Antes de deploy a producción:

- [ ] Success Rate = 100% (o >= 90%)
- [ ] MRR >= 0.8
- [ ] Precision@5 >= 0.6
- [ ] Faithfulness >= 0.6
- [ ] Queries problemáticas < 20%
- [ ] Modo hybrid supera lex y dense
- [ ] Todas las categorías tienen P@5 >= 0.5
- [ ] Re-ranking activado y funcionando
- [ ] Índices actualizados con todos los documentos

---

**Última actualización:** 8 de diciembre de 2025  
**Versión:** 1.0  
**Autor:** Sistema de Evaluación MILPA AI
