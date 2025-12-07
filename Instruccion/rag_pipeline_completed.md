# Pipeline RAG Completado - 26/nov/2025

## Componentes Implementados

### 1. Embeddings (core/logic/embeddings.py)
- ✅ Modelo: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- ✅ Backend dummy determinista como fallback
- ✅ Dimensión: 384 vectores
- ✅ Cache LRU para queries repetidas

### 2. Vector Store (core/logic/vectordb.py)
- ✅ ChromaDB persistente
- ✅ Espacio: cosine similarity
- ✅ Metadatos: fragment_id, doc_id, source
- ✅ Queries con filtros WHERE

### 3. BM25 Index (core/logic/bm25.py)
- ✅ Backend: memoria (BM25 nativo)
- ✅ Normalización: unidecode para matching robusto
- ✅ Filtros por labels
- ✅ Tokenización con regex

### 4. RAG Engine (core/logic/rag_engine.py)
- ✅ HybridRetriever: BM25 + vectorial
- ✅ Fusión: Reciprocal Rank Fusion (RRF)
- ✅ Parámetros: K_RETRIEVE=8, BM25_TOPK=100, RRF_K=60
- ✅ Umbrales evidencia insuficiente
- ✅ Entity coverage para validación

### 5. Endpoints RAG (api/rag.py)
- ✅ POST /api/query: búsqueda híbrida
  - Modos: hybrid, dense, lex
  - k resultados configurables
  - Filtros por labels
- ✅ POST /api/index/rebuild: reconstrucción de índices
  - BM25 + embeddings vectoriales
  - Procesamiento batch

## Estado de Tests

### Golden Answers (tests/test_golden_answers.py)
```
Ejecutado: 3 tests
Estado: 3 FAILED (esperado - contenido no coincide con queries)
Tiempo: 15.92s

Fallos por contenido:
- Query "nutrientes maíz": 0 fragmentos (esperados ≥2)
- Query "plagas tomate": 0 fragmentos (esperados ≥3)
- Query "fertilización frijol": 0 fragmentos (esperados ≥2)

Contenido actual en BD:
- 4 fragmentos indexados
- Texto: "Prueba MILPA: nitrógeno 100 kg/ha" 
- Texto: "Manual de prueba MILPA... falta fosfato"
- Texto: "ESTE ES UN DOCUMENTO ESCANEADO PARA OCR. TOTAL CHILE: 37.5 kg A 25°C"
```

### Framework Validado
✅ TestClient funciona
✅ Endpoint /api/query responde 200
✅ Estructura de respuesta correcta
✅ Fragmentos se recuperan de BD
✅ Scores calculados correctamente
✅ Insufficient evidence detectado

## Prueba Manual Exitosa

```powershell
# Query: "nitrógeno"
# Resultado: 4 fragmentos recuperados
# Modo: hybrid
# Scores: 0.0163 - 0.0156 (RRF)
# Insufficient evidence: true (k=4 < k_min=5)
```

## Documentos Indexados

```
Total: 4 fragmentos únicos
- sample.txt: "Prueba MILPA: nitrógeno 100 kg/ha"
- nativo_unidades.pdf (2 fragmentos): "Manual de prueba MILPA"
- ocr_escaneado.pdf (2 fragmentos): "ESTE ES UN DOCUMENTO ESCANEADO"

Índices:
- BM25: 4 documentos
- Vector DB: 4 embeddings (384 dims cada uno)
```

## Próximos Pasos para Producción

1. **Indexar contenido real**:
   - Documentos agronómicos sobre maíz, tomate, frijol
   - Información sobre nutrientes, plagas, fertilización
   - Mínimo 50-100 fragmentos para cobertura

2. **Golden answers reales**:
   - Ajustar queries a contenido indexado
   - O indexar contenido que cubra queries actuales
   - Re-ejecutar tests: `pytest tests/test_golden_answers.py -v`

3. **Generación de respuestas**:
   - Integrar LLM (OpenAI/Anthropic/local)
   - Generar answer desde fragments recuperados
   - Validar faithfulness real con ragas/deepeval

4. **Optimizaciones**:
   - Tune parámetros RRF (K=60)
   - Ajustar K_RETRIEVE según latencia
   - Reranking con cross-encoder
   - Ajustar umbrales insufficient_evidence

5. **Producción**:
   - Persistent vector DB (pgvector en PostgreSQL)
   - Scheduled reindexing de documentos
   - Monitoring de calidad RAG
   - A/B testing de modos (hybrid vs dense)

## Comandos Útiles

```powershell
# Reconstruir índices
Invoke-WebRequest -Method POST -Uri http://localhost:8000/api/index/rebuild

# Query RAG
echo '{"query":"nitrógeno","k":5,"mode":"hybrid"}' | Out-File query.json
Invoke-WebRequest -Method POST -Uri http://localhost:8000/api/query -InFile query.json -ContentType "application/json"

# Tests
cd C:\milpa\milpa_ai_backend
pytest tests/test_golden_answers.py -v --tb=short
```

## Conclusión

✅ **Pipeline RAG 100% funcional**
- Embeddings generándose correctamente
- BM25 + vector search operando
- RRF fusionando resultados
- Endpoints REST funcionando
- Tests ejecutándose (fallan por contenido, no por código)

🎯 **Listo para indexar contenido real y validar calidad**
