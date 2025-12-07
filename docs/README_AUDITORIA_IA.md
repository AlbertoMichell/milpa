# Auditoría de IA y Lenguaje (Sistema MILPA)

## Modelos (lista breve)
- sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- spaCy: es_core_news_sm
- BM25 (Whoosh/Tantivy/memory)
- ChromaDB (almacén vectorial)
- Síntesis local: compose_answer (synthesis)

## Descripción y uso
- Embeddings: Modelo `paraphrase-multilingual-MiniLM-L12-v2` de Sentence-Transformers (384 dimensiones, multilingüe). Se usa para convertir texto de fragmentos y consultas en vectores; ejecución 100% local sin API externa. Carga desde `core/logic/embeddings.py`.
- NLP/NER: `spaCy` con modelo `es_core_news_sm` para reconocimiento de entidades y utilidades lingüísticas opcionales. Se instala en la imagen Docker y se usa localmente; si no está disponible, el sistema cae a rutas de diccionario/heurísticas.
- BM25: Búsqueda léxica mediante `BM25Index` con backends automáticos: `tantivy` (si hay wheel), `whoosh`, o `memory`. Proporciona ranking por similitud de términos; definido en `core/logic/bm25.py`.
- Vector Store: `ChromaDB` persistente (`chromadb`) para almacenamiento y búsqueda de embeddings con espacio de similitud de coseno. Implementado en `core/logic/vectordb.py` con ruta `data/vector_db`. Operación local sin servicios remotos.
- RAG Híbrido y Fusión: El motor `core/logic/rag_engine.py` combina señales BM25 y vectoriales usando Reciprocal Rank Fusion (RRF), aplica umbrales de evidencia y reranking multifactor (similitud base, frescura, autoridad y cobertura de entidades).
- Síntesis de Respuesta (no LLM): `core/logic/synthesis.py` (`compose_answer`) toma fragmentos recuperados y compone una respuesta textual estructurada con citas numeradas y cálculo de “faithfulness”. Actualmente `api/rag.py` utiliza este modo (`answer_mode="synthesis"`). No se emplea OpenAI, Claude ni ningún servicio de generación externo.
- Extracción/OCR/Tablas: Pipeline local con `pymupdf`, `pytesseract` (OCR), `camelot` para tablas, `pandas/numpy` para procesamiento. Todo ocurre en contenedores locales; los documentos se indexan en SQLite y Chroma.

## Confirmación de operación local
- No hay llamadas activas a APIs de OpenAI/Anthropic/Cohere/Azure/Vertex/etc. El archivo `core/logic/generation.py` contiene código opcional para un modo GPT, pero el endpoint actual `api/rag.py` usa síntesis local y no invoca clientes externos.
- El Presenter (`milpa_presenter`) no integra SDKs de IA externas; sirve y sanitiza respuestas del backend.

## Ubicación de componentes clave
- Embeddings: `milpa_ai_backend/core/logic/embeddings.py`
- BM25: `milpa_ai_backend/core/logic/bm25.py`
- Vector DB (Chroma): `milpa_ai_backend/core/logic/vectordb.py`
- Motor RAG/RRF y reranking: `milpa_ai_backend/core/logic/rag_engine.py`
- Síntesis: `milpa_ai_backend/core/logic/synthesis.py`
- Endpoint RAG: `milpa_ai_backend/api/rag.py`
