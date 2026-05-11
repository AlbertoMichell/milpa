# MILPA - Sistema Inteligente de Recuperación de Información Agrícola
## Análisis Teórico y Arquitectónico

> **Nota sobre la metodología:** Este análisis se fundamenta en el examen exhaustivo del código fuente del sistema, incluyendo: arquitectura documentada (ARQUITECTURA_UNIFICADA.md, ARQUITECTURA_Y_PROCESAMIENTO_DATOS.md), implementaciones de algoritmos (core/logic/rag_engine.py, core/logic/bm25.py, core/logic/embeddings.py, core/logic/vectordb.py), endpoints de API (api/rag.py), configuración de servicios (docker-compose.yml), y documentación técnica de sprints completados (SPRINT_17_20_README.md, SISTEMA_COMPLETO_100_OPERATIVO.md, EXPLICACION_ALGORITMOS_IA.md).

---

## 1. RESUMEN EJECUTIVO

MILPA es un **sistema recomendador basado en Inteligencia Artificial** especializado en el dominio agrícola, que implementa una arquitectura de **Recuperación Aumentada por Generación (RAG)** con búsqueda híbrida. El sistema está diseñado para proporcionar respuestas precisas y contextualizadas a consultas sobre cultivos, nutrientes, plagas, fenología y manejo agronómico, extrayendo información relevante de una base de conocimiento especializada.

**Propósito principal:** Democratizar el acceso al conocimiento agrícola técnico mediante un sistema inteligente que entiende las preguntas en lenguaje natural y recupera información precisa de documentos especializados.

**Objetivo específico:** Superar las limitaciones de los motores de búsqueda tradicionales al combinar búsqueda léxica (palabras exactas) con búsqueda semántica (comprensión del significado), logrando una precisión del 91.7% en la recuperación del fragmento más relevante.

---

## 2. ARQUITECTURA GENERAL DEL SISTEMA

### 2.1 Modelo de Capas

El sistema implementa una arquitectura de **dos capas separadas** que operan de manera coordinada pero independiente:

#### **Capa de Presentación (Presenter)**
- **Tecnología base:** TypeScript con Fastify
- **Puerto de operación:** 8080
- **Responsabilidades:**
  - Servir la interfaz de usuario completa
  - Actuar como proxy inteligente hacia el backend
  - Aplicar seguridad (sanitización HTML, rate limiting)
  - Gestionar cola de peticiones (circuit breaker)
  - Exponer métricas de observabilidad

#### **Capa de Inteligencia Artificial (Backend)**
- **Tecnología base:** Python con FastAPI
- **Puerto de operación:** 8000
- **Responsabilidades:**
  - Procesar consultas mediante algoritmos de IA
  - Gestionar índices de búsqueda (BM25 y vectorial)
  - Extraer y procesar documentos
  - Enriquecer fragmentos con entidades del dominio
  - Generar respuestas aumentadas

### 2.2 Flujo de Comunicación

El sistema opera bajo el principio de **punto de entrada único**: el usuario accede exclusivamente a través del presenter (puerto 8080), que actúa como puerta de enlace controlada hacia el backend de IA. Esta arquitectura garantiza:

1. **Aislamiento de seguridad:** El backend de IA nunca está expuesto directamente al usuario
2. **Control de tráfico:** Implementación de rate limiting y circuit breaker antes de llegar a la IA
3. **Separación de responsabilidades:** La presentación está desacoplada de la lógica de IA

**Patrón de comunicación:**
```
Usuario → Presenter (8080) → Backend IA (8000) → Base de Datos → Backend IA → Presenter → Usuario
```

### 2.3 Flujo Completo de Información: De Origen a Destino

Para comprender completamente el sistema, es esencial trazar el viaje completo que realiza la información desde su fuente original hasta llegar al usuario final como respuesta procesada.

#### **Fase A: Origen de los Datos (Entrada al Sistema)**

**Fuente primaria:** Documentos PDF subidos por administradores del sistema
- Manuales técnicos agronómicos (INIFAP, SAGARPA, universidades)
- Papers científicos de revistas especializadas
- Guías de buenas prácticas agrícolas
- Normativas gubernamentales sobre uso de agroquímicos
- Resultados de ensayos experimentales

**Objetivo de ingesta:** Transformar conocimiento estático (documentos) en conocimiento indexado y buscable mediante procesamiento inteligente.

**Punto de entrada técnico:** Endpoint `POST /api/documents/upload` del backend IA (puerto 8000), accesible vía proxy del presenter (puerto 8080).

#### **Fase B: Transformación y Enriquecimiento (Dentro del Backend IA)**

**Paso 1 - Escaneo de seguridad (ClamAV):**
- **De dónde:** Buffer de memoria con bytes del PDF subido
- **A dónde:** ClamAV daemon (puerto 3310)
- **Por qué:** Prevenir inyección de malware en la base de conocimiento
- **Objetivo:** Garantizar seguridad del sistema antes de procesamiento costoso

**Paso 2 - Extracción textual (PyPDF2/Tesseract):**
- **De dónde:** Archivo PDF validado por antivirus
- **A dónde:** String de texto plano en memoria Python
- **Por qué:** PDFs son binarios no procesables directamente; necesitamos texto plano
- **Objetivo:** Obtener contenido textual sin formato, preservando estructura semántica

**Paso 3 - Fragmentación semántica (Chunking):**
- **De dónde:** String de texto completo del documento (potencialmente miles de palabras)
- **A dónde:** Lista de fragmentos de 300-500 tokens con solapamiento de 50 tokens
- **Por qué:** Búsqueda granular requiere unidades semánticas coherentes; documento completo es demasiado amplio
- **Objetivo:** Crear unidades de conocimiento atómicas que puedan recuperarse individualmente según relevancia específica

**Paso 4 - Enriquecimiento con entidades (spaCy NER):**
- **De dónde:** Cada fragmento de texto plano
- **A dónde:** Estructura enriquecida: `{text: str, entities: {crops: [...], nutrients: [...], pests: [...]}}`
- **Por qué:** Metadatos semánticos permiten filtrado temático y validación de relevancia
- **Objetivo:** Anotar conocimiento con taxonomía del dominio agrícola para búsquedas especializadas

**Paso 5 - Persistencia relacional (SQLite):**
- **De dónde:** Objetos Python en memoria (fragmentos enriquecidos)
- **A dónde:** Tabla `fragments` en base de datos SQLite (data/milpa.db)
- **Por qué:** Persistencia duradera, ACID compliance, recuperación rápida de texto original
- **Objetivo:** Fuente de verdad para el contenido textual y metadatos estructurados
- **Implementación:** Código en `core/logic/db.py`, método `insert_fragment()`

**Paso 6 - Vectorización (Sentence-BERT):**
- **De dónde:** Texto plano de cada fragmento
- **A dónde:** Vector numérico denso de 384 dimensiones (array de floats)
- **Por qué:** Representación matemática del significado semántico para búsqueda por similitud
- **Objetivo:** Permitir matching conceptual más allá de palabras exactas
- **Implementación:** `core/logic/embeddings.py`, modelo `paraphrase-multilingual-MiniLM-L12-v2`

**Paso 7 - Indexación vectorial (ChromaDB):**
- **De dónde:** Vectores de 384 dimensiones en memoria Python
- **A dónde:** Base de datos vectorial ChromaDB (data/vector_db/)
- **Por qué:** Búsqueda eficiente de vecinos más cercanos (ANN) en espacio de alta dimensionalidad
- **Objetivo:** Recuperación sub-segundo de fragmentos semánticamente similares a consulta
- **Implementación:** `core/logic/vectordb.py`, método `add(ids, embeddings, metadatas)`

**Paso 8 - Indexación léxica (Tantivy/BM25):**
- **De dónde:** Texto plano de cada fragmento
- **A dónde:** Índice invertido Tantivy (data/bm25_index/)
- **Por qué:** Búsqueda ultrarrápida por palabras clave exactas
- **Objetivo:** Recuperación precisa de fragmentos que contienen terminología técnica específica
- **Implementación:** `core/logic/bm25.py`, método `index_many(documents)`

#### **Fase C: Recuperación en Tiempo Real (Query Processing)**

**Paso 1 - Recepción de consulta del usuario:**
- **De dónde:** Formulario web en browser del usuario (http://localhost:8080/ui/query)
- **A dónde:** Presenter TypeScript (puerto 8080), endpoint `/ai/query` (proxy)
- **Por qué:** Punto de entrada único con seguridad y rate limiting
- **Objetivo:** Capturar intención del usuario en lenguaje natural
- **Implementación:** `milpa_presenter/src/server.ts`, línea ~404, formulario HTML con input text

**Paso 2 - Proxy seguro:**
- **De dónde:** Request HTTP al presenter
- **A dónde:** Backend IA, endpoint `POST /api/query`, puerto 8000
- **Por qué:** Aislamiento de seguridad; backend IA nunca expuesto directamente
- **Objetivo:** Aplicar circuit breaker, rate limiting (60 req/min), sanitización antes de IA
- **Implementación:** `milpa_presenter/src/server.ts`, proxy con `axios` y `fastify-circuit-breaker`

**Paso 3 - Extracción de entidades de consulta (spaCy NER):**
- **De dónde:** String de consulta del usuario ("nitrógeno para maíz en verano")
- **A dónde:** Lista de entidades extraídas: `{crops: ['maíz'], nutrients: ['nitrógeno'], seasons: ['verano']}`
- **Por qué:** Identificar elementos clave para validación posterior de relevancia
- **Objetivo:** Capturar términos críticos del dominio para filtrado y re-ranking
- **Implementación:** `core/logic/enrichment.py`, función `extract_entities(text)`

**Paso 4 - Búsqueda dual paralela:**

**4a. Búsqueda vectorial (BERT):**
- **De dónde:** String de consulta
- **A dónde:** Vector de consulta (384 dims) → ChromaDB → Top-20 fragmentos más similares
- **Por qué:** Encontrar conocimiento conceptualmente relevante aunque use palabras diferentes
- **Objetivo:** Máximo recall (cobertura) en búsqueda semántica
- **Tiempo:** ~80ms
- **Implementación:** `core/logic/rag_engine.py`, método `HybridRetriever.dense_search()`

**4b. Búsqueda léxica (BM25):**
- **De dónde:** String de consulta
- **A dónde:** Índice Tantivy → Top-100 fragmentos con mayor puntuación BM25
- **Por qué:** Encontrar fragmentos con terminología técnica exacta de la consulta
- **Objetivo:** Máxima precisión en matching de términos especializados
- **Tiempo:** ~50ms
- **Implementación:** `core/logic/bm25.py`, método `BM25Index.search(query, topk=100)`

**Paso 5 - Fusión matemática (RRF):**
- **De dónde:** Dos listas ordenadas (20 de BERT + 100 de BM25)
- **A dónde:** Lista única fusionada y re-ordenada por score RRF
- **Por qué:** Combinar fortalezas de ambos métodos; consenso = alta confianza
- **Objetivo:** Maximizar precisión y recall simultáneamente
- **Fórmula:** `RRF_score = Σ(1 / (60 + rank_en_lista_i))`
- **Implementación:** `core/logic/rag_engine.py`, función `reciprocal_rank_fusion(vec_hits, bm25_hits, K=60)`

**Paso 6 - Re-ranking por cobertura de entidades:**
- **De dónde:** Lista fusionada RRF + entidades extraídas en Paso 3
- **A dónde:** Lista re-ordenada con boost por cobertura temática
- **Por qué:** Priorizar fragmentos que hablan exactamente de lo que el usuario pregunta
- **Objetivo:** Elevar fragmentos con alta densidad de términos relevantes del dominio
- **Fórmula:** `score_final = score_RRF × (1 + 0.5 × coverage)`, donde `coverage = entidades_presentes / entidades_totales`
- **Implementación:** `core/logic/rag_engine.py`, función `rerank_by_term_coverage()`

**Paso 7 - Filtrado de evidencia insuficiente:**
- **De dónde:** Lista re-rankeada
- **A dónde:** Lista validada o respuesta de "evidencia insuficiente"
- **Por qué:** Evitar respuestas con información tangencial o irrelevante
- **Objetivo:** Mantener confianza del usuario mediante honestidad sobre limitaciones del conocimiento
- **Criterios:**
  - Mínimo 5 fragmentos recuperados
  - Cobertura de entidades ≥ 65%
  - Score promedio ≥ 0.35
  - Mínimo 2 documentos fuente distintos
- **Implementación:** `core/logic/rag_engine.py`, función `insufficient_evidence(query, hits, thresholds)`

**Paso 8 - Recuperación de texto completo:**
- **De dónde:** IDs de fragmentos seleccionados (Top-K, típicamente 5-8)
- **A dónde:** Query a SQLite: `SELECT text, doc_id, page_num FROM fragments WHERE fragment_id IN (...)`
- **Por qué:** ChromaDB y Tantivy solo almacenan IDs y scores; texto completo está en SQLite
- **Objetivo:** Obtener contenido textual original para presentar al usuario
- **Implementación:** `core/logic/db.py`, función `get_fragments_by_ids()`

#### **Fase D: Presentación al Usuario (Salida del Sistema)**

**Paso 1 - Construcción de respuesta estructurada:**
- **De dónde:** Lista de fragmentos con texto, scores, metadatos
- **A dónde:** Objeto JSON con estructura: `{query, fragments: [{text, score, source, page}], answer, citations}`
- **Por qué:** Formato estandarizado para consumo por frontend
- **Objetivo:** Proveer no solo fragmentos sino contexto completo (fuente, citación, confianza)
- **Implementación:** `api/rag.py`, endpoint `POST /api/query`, retorna `QueryResponse` (Pydantic model)

**Paso 2 - Retorno al presenter:**
- **De dónde:** Backend IA responde con JSON estructurado
- **A dónde:** Presenter recibe respuesta del proxy
- **Por qué:** Flujo inverso del request inicial
- **Objetivo:** Preparar respuesta para renderizado en UI

**Paso 3 - Renderizado visual:**
- **De dónde:** JSON de respuesta
- **A dónde:** HTML renderizado dinámicamente en browser del usuario
- **Por qué:** Usuarios no consumen JSON; necesitan interfaz visual amigable
- **Objetivo:** Presentar información de manera legible con citaciones claras
- **Elementos visuales:**
  - Fragmentos relevantes con highlighting de términos de consulta
  - Badges de score/confianza
  - Links a documento origen y página específica
  - Metadatos de entidades detectadas (cultivos, nutrientes, plagas)
- **Implementación:** `milpa_presenter/src/server.ts`, línea ~440, renderizado con JavaScript en cliente

**Paso 4 - Trazabilidad completa (Observabilidad):**
- **De dónde:** Toda la cadena de procesamiento
- **A dónde:** Métricas Prometheus (puerto 9090) y trazas OpenTelemetry
- **Por qué:** Visibilidad operacional, debugging, optimización continua
- **Objetivo:** Monitorear salud del sistema, tiempos de respuesta, calidad de resultados
- **Métricas capturadas:**
  - Latencia end-to-end (P50, P95, P99)
  - Fragmentos recuperados por consulta
  - Scores promedio de relevancia
  - Tasa de "evidencia insuficiente"
  - Top cultivos/nutrientes consultados
- **Implementación:** Instrumentación automática FastAPI + Prometheus client + OpenTelemetry SDK

#### **Resumen del Flujo: Transformaciones Clave**

```
PDF subido → Texto plano → Fragmentos → Fragmentos enriquecidos → Tripleta de persistencia:
                                                                    ├→ SQLite (texto + metadatos)
                                                                    ├→ ChromaDB (vectores 384d)
                                                                    └→ Tantivy (índice invertido)

Consulta usuario → Entidades extraídas → Búsqueda dual paralela → Fusión RRF → Re-ranking → Filtrado → 
                                         (BM25 + BERT)             (matemática)  (entidades)  (calidad)

Lista de IDs → SQLite lookup → JSON estructurado → HTML renderizado → Usuario visualiza respuesta
```

**Tiempo total típico:** 150-200ms desde que usuario presiona "Buscar" hasta visualizar resultados

**Objetivos cumplidos del flujo completo:**
1. **Transformar conocimiento estático en recuperable:** PDFs → Índices buscables
2. **Comprender intención del usuario:** Lenguaje natural → Entidades + vectores + términos
3. **Recuperar conocimiento relevante:** Múltiples técnicas complementarias → Consenso de métodos
4. **Validar calidad de respuesta:** Evidencia insuficiente → Honestidad sobre limitaciones
5. **Proveer trazabilidad completa:** Citaciones → Usuario puede verificar fuente original

---

## 3. COMPRENSIÓN HÍBRIDA: EL CORAZÓN DEL SISTEMA

### 3.1 Concepto de Recuperación Híbrida

El sistema MILPA implementa lo que se denomina **"Hybrid Retrieval"** o Recuperación Híbrida, que constituye su diferenciador tecnológico principal. Esta no es un algoritmo único, sino una **arquitectura que combina dos formas complementarias de comprender y buscar información**:

#### **Primera Comprensión: Búsqueda Léxica (BM25)**
Representa la "comprensión literal" del sistema. Funciona mediante coincidencias exactas de palabras y términos técnicos. Cuando un usuario pregunta por "nitrógeno en maíz", el sistema busca fragmentos que contengan exactamente esas palabras.

**Fortalezas:**
- Extremadamente preciso con terminología técnica especializada
- Rápido computacionalmente (50 milisegundos típicos)
- No requiere entrenamiento previo
- Ideal para consultas con términos científicos específicos

**Limitaciones:**
- No entiende sinónimos o conceptos relacionados
- Falla con variaciones ortográficas o regionalismos
- No comprende el contexto semántico de la consulta

#### **Segunda Comprensión: Búsqueda Semántica (Dense Vector con BERT)**
Representa la "comprensión conceptual" del sistema. Transforma texto en representaciones matemáticas multidimensionales (vectores de 384 números) que capturan el significado profundo del contenido.

**Fortalezas:**
- Encuentra información relevante incluso con palabras diferentes
- Comprende relaciones conceptuales ("fertilización" ≈ "nutrición" ≈ "abonado")
- Maneja sinónimos, paráfrasis y expresiones coloquiales
- Identifica semejanza temática más allá de palabras exactas

**Limitaciones:**
- Más costoso computacionalmente (80 milisegundos típicos)
- Puede generar falsos positivos por similitud superficial
- Requiere modelos de lenguaje pre-entrenados

### 3.2 Fusión Inteligente (RRF)

El tercer componente de la arquitectura híbrida es el **algoritmo de fusión Reciprocal Rank Fusion (RRF)**, que combina los resultados de ambas comprensiones de manera matemáticamente óptima.

**Principio de operación:**
En lugar de promediar puntuaciones o concatenar listas, RRF utiliza un enfoque basado en posiciones relativas. Un fragmento que aparece en ambas listas (comprensión léxica Y semántica) recibe automáticamente prioridad, ya que satisface múltiples criterios de relevancia.

**Ventajas del enfoque RRF:**
- No requiere normalización de puntuaciones heterogéneas
- Robusto ante outliers (valores extremos en una sola lista)
- Favorece consenso entre métodos diferentes
- Parámetro único de configuración (K=60)

---

## 4. PROCESAMIENTO DE INFORMACIÓN

### 4.1 Fase de Indexación (Preparación del Conocimiento)

Cuando un documento nuevo ingresa al sistema, atraviesa un pipeline de transformación sofisticado que lo convierte de un archivo PDF estático en conocimiento indexado y buscable:

#### **Etapa 1: Extracción de Contenido**
El sistema extrae el texto del documento utilizando técnicas avanzadas. Para PDFs digitales, lee directamente el contenido textual. Para documentos escaneados (imágenes), activa automáticamente OCR (Reconocimiento Óptico de Caracteres) mediante Tesseract, convirtiendo imágenes de texto en texto procesable.

#### **Etapa 2: Fragmentación Semántica**
El texto completo se divide en fragmentos coherentes de 300-500 palabras con solapamiento de 50 palabras entre fragmentos consecutivos. Este solapamiento es crucial para mantener contexto en las fronteras entre fragmentos.

**Razón estratégica:** La fragmentación permite precisión granular. En lugar de retornar un documento completo de 50 páginas, el sistema identifica exactamente el párrafo o sección que responde la pregunta específica del usuario.

#### **Etapa 3: Enriquecimiento con Entidades**
Cada fragmento se procesa mediante Named Entity Recognition (NER) especializado en agricultura, que identifica y clasifica:
- Cultivos (maíz, frijol, tomate, etc.)
- Nutrientes (nitrógeno, fósforo, potasio, etc.)
- Plagas y enfermedades
- Etapas fenológicas
- Prácticas de manejo

#### **Etapa 4: Doble Indexación**
Cada fragmento se indexa simultáneamente en dos sistemas complementarios:

**Índice BM25 (Tantivy):** Crea un índice invertido que mapea cada palabra única a los fragmentos que la contienen, optimizado para búsquedas léxicas ultrarrápidas.

**Base de Datos Vectorial (ChromaDB):** Convierte cada fragmento en un vector denso de 384 dimensiones mediante el modelo BERT multilingüe. Estos vectores se almacenan en estructuras especializadas que permiten búsquedas de similitud en milisegundos.

### 4.2 Fase de Búsqueda (Recuperación Inteligente)

Cuando un usuario realiza una consulta, el sistema ejecuta un proceso de múltiples etapas diseñado para maximizar relevancia y precisión:

#### **Etapa 1: Análisis de la Consulta**
La consulta del usuario se procesa en paralelo por dos componentes:
- **spaCy NER:** Extrae entidades clave (cultivos, nutrientes, etc.)
- **Motores de Búsqueda:** Inician búsqueda en índices BM25 y vectorial

#### **Etapa 2: Búsqueda Dual Paralela**
Ambos motores operan simultáneamente sin comunicarse entre sí:
- El motor BM25 recupera los 20 fragmentos más relevantes según criterios léxicos
- El motor BERT recupera los 20 fragmentos más similares semánticamente

**Tiempo de operación:** Total ~130 milisegundos (50ms BM25 + 80ms BERT, en paralelo)

#### **Etapa 3: Fusión Matemática**
Los resultados de ambas búsquedas se fusionan mediante RRF, creando una lista única ordenada donde los fragmentos que aparecen en ambas listas reciben puntuación combinada.

#### **Etapa 4: Re-ranking por Cobertura**
El sistema utiliza las entidades extraídas en la Etapa 1 para re-puntuar los resultados fusionados. Fragmentos que contienen más entidades relevantes identificadas en la consulta reciben boost multiplicativo en su puntuación.

#### **Etapa 5: Filtrado de Calidad**
Se aplica un filtro de "evidencia insuficiente" que descarta fragmentos que, pese a tener puntuación alta, no contienen ninguna de las entidades clave. Este filtro elimina falsos positivos por similitud estadística superficial.

#### **Etapa 6: Presentación de Resultados**
Los K fragmentos finales (típicamente 5-8) se enriquecen con metadatos completos: documento origen, número de página, puntuación, entidades detectadas, y se presentan al usuario con citaciones estructuradas.

**Tiempo total de respuesta:** 150-200 milisegundos desde consulta hasta resultado

---

## 5. MODELOS DE INTELIGENCIA ARTIFICIAL IMPLEMENTADOS

### 5.1 Sentence-BERT (paraphrase-multilingual-MiniLM-L12-v2)

**Tipo:** Modelo de lenguaje transformador multilingüe especializado en embeddings de oraciones.

**Función en el sistema:** Genera representaciones vectoriales densas (embeddings) de fragmentos de texto y consultas, capturando significado semántico en un espacio vectorial de 384 dimensiones.

**Por qué se seleccionó:**
- **Multilingüismo:** Maneja español con calidad comparable a inglés
- **Eficiencia computacional:** Modelo "MiniLM" optimizado para equilibrar precisión y velocidad
- **Pre-entrenamiento específico:** Entrenado en tareas de paráfrasis, ideal para matching semántico
- **Dimensionalidad óptima:** 384 dimensiones balancean capacidad expresiva y eficiencia de búsqueda

**Alternativas descartadas:**
- **BERT base (768 dims):** Demasiado pesado, 2x más lento para ganancia marginal en precisión
- **GPT embeddings:** Requiere API externa, latencia impredecible y costos por uso
- **Word2Vec/FastText:** No capturan contexto oracional, solo palabras individuales

### 5.2 spaCy NER con Diccionario Personalizado

**Tipo:** Sistema de Reconocimiento de Entidades Nombradas con matching basado en diccionarios especializados del dominio agrícola.

**Función en el sistema:** Identifica y clasifica términos técnicos del dominio (cultivos, nutrientes, plagas, fenología) tanto en consultas como en fragmentos indexados, permitiendo validación temática y re-ranking por cobertura de entidades.

**Por qué se seleccionó:**
- **Dominio cerrado:** Agricultura tiene vocabulario técnico bien definido y acotado
- **Precisión determinista:** Dictionary matching evita falsos positivos de modelos estadísticos
- **Cero entrenamiento:** No requiere corpus anotado para entrenar
- **Actualización simple:** Agregar nueva terminología es edición de CSV

**Alternativas descartadas:**
- **NER estadístico (CRF/BiLSTM):** Requiere corpus anotado extenso, overhead computacional
- **LLM-based NER (GPT):** Latencia alta, costos, resultados no deterministas
- **Regex puro:** Inflexible ante variaciones morfológicas, no maneja jerarquías taxonómicas

---

## 6. GESTIÓN DE DATOS: NUMÉRICOS Y CATEGÓRICOS

### 6.1 Datos Numéricos (Procesamiento Cuantitativo)

El sistema opera predominantemente con **representaciones numéricas continuas** en múltiples escalas:

#### **Embeddings Vectoriales**
Cada fragmento de texto se representa como un vector de 384 números decimales en rango [-1, 1]. Estos números no tienen significado individual; su valor surge de las relaciones geométricas entre vectores (distancias, ángulos).

**Operación fundamental:** Similitud de coseno entre vectores de consulta y vectores de fragmentos, produciendo scores en rango [0, 1] donde 1 = idéntico semánticamente.

#### **Puntuaciones BM25**
Scores léxicos calculados mediante fórmula probabilística que considera:
- Frecuencia de término en fragmento (tf)
- Rareza del término en corpus (idf)
- Longitud del fragmento normalizada

Valores típicos: 0 a 20, sin límite superior estricto.

#### **Scores RRF (Fusionados)**
Combinación de rankings mediante fórmula: `1/(60 + posición_BM25) + 1/(60 + posición_Vector)`

Valores típicos: 0.01 a 0.05, donde mayor = más relevante.

#### **Métricas de Cobertura**
Proporción de entidades de consulta presentes en fragmento: `entidades_presentes / entidades_totales`

Valores: 0.0 a 1.0 (0% a 100% de cobertura)

### 6.2 Datos Categóricos (Procesamiento Cualitativo)

El sistema también maneja **información discreta estructurada** para filtrado y validación:

#### **Etiquetas de Fragmento (Labels)**
Clasificación manual del tipo de contenido:
- `RECOMENDACION`: Instrucciones operativas, buenas prácticas
- `DATO`: Información factual, estadísticas
- `RESULTADO`: Estudios, experimentos, evidencia experimental
- `NORMATIVA`: Regulaciones, estándares obligatorios

**Uso:** Filtrado previo a búsqueda según intención de consulta (operativa vs. informativa)

#### **Entidades del Dominio**
Categorías extraídas por spaCy NER:
- **Cultivos:** maíz, frijol, tomate, chile, etc.
- **Nutrientes:** nitrógeno, fósforo, potasio, calcio, etc.
- **Plagas:** gusano cogollero, mosca blanca, roya, etc.
- **Fenología:** germinación, floración, madurez, cosecha, etc.

**Uso:** Validación de relevancia temática, re-ranking, filtrado de evidencia insuficiente

#### **Metadatos Documentales**
- **Autor**: Fuente del documento
- **Año**: Temporalidad de la información
- **Tipo de documento**: Manual, paper científico, guía técnica
- **Licencia**: libre, normativa, propietaria

**Uso:** Trazabilidad, citaciones, preferencia por fuentes normativas

---

## 7. CARACTERÍSTICAS AVANZADAS DEL SISTEMA

### 7.1 Feature Flags Dinámicos

El sistema implementa **configuración en caliente sin reinicio** mediante una tabla de feature flags persistida en base de datos. Esto permite activar/desactivar funcionalidades complejas en producción sin downtime.

**Flags implementados:**
- **RERANKER_ENABLED:** Activa/desactiva capa adicional de re-ranking con cross-encoder
- **EMBEDDINGS_MODEL:** Permite cambiar modelo de embeddings dinámicamente
- **RAG_MODE:** Configura pesos de fusión híbrida (100% BM25, 100% vector, o híbrido)
- **OCR_ENABLED:** Controla activación de OCR para documentos escaneados
- **ENRICHMENT_ENABLED:** Activa/desactiva enriquecimiento con entidades NER

**Valor estratégico:** Experimentación A/B en producción, rollback rápido ante issues, configuración por cliente

### 7.2 Detección de Evidencia Insuficiente

El sistema implementa **validación activa de calidad de respuesta** mediante umbrales configurables que detectan cuando la base de conocimiento no contiene información suficiente para responder con confianza.

**Criterios de insuficiencia:**
- Menos de K fragmentos recuperados (típicamente K < 5)
- Cobertura de entidades menor a 65% (fragmentos no hablan de lo que pregunta el usuario)
- Score promedio menor a 0.35 (relevancia general baja)
- Menos de 2 documentos distintos (falta diversidad de fuentes)

**Respuesta del sistema:** En lugar de forzar respuesta con información tangencial, notifica explícitamente "evidencia insuficiente" con diagnóstico transparente del por qué no puede responder con confianza.

**Valor estratégico:** Evita alucinaciones y respuestas incorrectas; mantiene confianza del usuario

### 7.3 Seguridad Multi-Capa

El sistema implementa **defensa en profundidad** con múltiples capas de seguridad:

#### **Capa 1: Validación de Entrada (Presenter)**
- Sanitización HTML obligatoria
- Rate limiting: 60 peticiones por minuto por IP
- Queue management: máximo 8 peticiones concurrentes, 64 en cola
- Circuit breaker: detiene tráfico si backend falla repetidamente

#### **Capa 2: Escaneo Antivirus (ClamAV)**
Todo documento subido se escanea con ClamAV antes de procesamiento. Documentos infectados se rechazan y cuarentenizan automáticamente.

#### **Capa 3: Hardening de Contenedores**
- Ejecución non-root (usuario sin privilegios)
- Filesystem read-only (excepto directorios temporales específicos)
- Capabilities mínimas (CAP_DROP ALL, solo habilita lo esencial)
- Seccomp profile restrictivo (bloquea syscalls peligrosas)

#### **Capa 4: Aislamiento de Red**
Backend de IA no tiene exposición directa a internet; solo accesible vía presenter en red interna Docker.

### 7.4 Observabilidad y Monitoreo

El sistema implementa **telemetría completa** para visibilidad operacional:

#### **Métricas de Negocio (Prometheus)**
- **RAG Quality Metrics:** Tiempo de respuesta, fragmentos recuperados, scores promedio
- **Top Entities:** Cultivos más consultados, nutrientes más buscados, plagas más frecuentes
- **Recommendation Metrics:** Tasa de aceptación, severidad promedio

#### **Trazas Distribuidas (OpenTelemetry)**
Instrumentación automática de todas las peticiones con:
- Sampling inteligente (10% de peticiones para evitar overhead)
- Enriquecimiento de spans con contexto de negocio (doc_id, fragment_ids, entidades)
- Correlación de trazas entre presenter y backend

#### **Dashboards Visuales (Grafana)**
Dashboards pre-configurados con:
- Health y disponibilidad de servicios
- Latencias (P50, P95, P99)
- Throughput de peticiones
- Tasas de error por endpoint
- Métricas de calidad RAG

---

## 8. VENTAJAS ARQUITECTÓNICAS

### 8.1 Separación de Responsabilidades

La arquitectura de dos capas desacopla completamente la presentación de la inteligencia:

**Ventaja 1: Desarrollo Independiente**
Los equipos de frontend pueden iterar en UX/UI sin tocar código de IA, y viceversa.

**Ventaja 2: Tecnología Óptima por Capa**
TypeScript para seguridad y velocidad en frontend; Python para ecosistema ML/IA en backend.

**Ventaja 3: Escalado Diferenciado**
Presenter puede escalarse horizontalmente (múltiples instancias) sin escalar el backend computacionalmente costoso.

### 8.2 Precisión Híbrida

La combinación de dos comprensiones complementarias supera las limitaciones individuales:

**Ventaja 1: Cobertura Completa**
Consultas técnicas exactas → BM25 brilla
Consultas conceptuales o coloquiales → BERT brilla
Consultas mixtas → Híbrido supera a ambos

**Ventaja 2: Robustez ante Variaciones**
El sistema responde correctamente ante errores ortográficos, regionalismos, sinónimos, y variaciones expresivas.

**Ventaja 3: Validación Cruzada**
Fragmentos que aparecen en ambos rankings tienen alta confianza de relevancia (consenso de métodos).

### 8.3 Escalabilidad del Conocimiento

El sistema escala linealmente con el tamaño de la base de conocimiento:

**50,000 fragmentos:** ~77 MB de vectores, búsquedas en 150ms
**100,000 fragmentos:** ~154 MB de vectores, búsquedas en 180ms
**500,000 fragmentos:** ~770 MB de vectores, búsquedas en 250ms

Escalado horizontal mediante:
- Sharding de ChromaDB por año/cultivo
- Réplicas read-only de índices BM25
- Caching de embeddings frecuentes

---

## 9. CASOS DE USO PRIORITARIOS

### 9.1 Consultas Técnicas Especializadas

**Caso:** Ingeniero agrónomo busca dosis específica de fertilizante nitrogenado para maíz en etapa V6.

**Flujo:** Query "dosis nitrógeno maíz V6" → BM25 identifica fragmentos con términos exactos → BERT complementa con contexto fenológico → Sistema retorna fragmentos de manuales técnicos con dosis recomendadas, citando fuente y página.

**Valor:** Acceso instantáneo a información técnica que tradicionalmente requiere consultar múltiples manuales.

### 9.2 Consultas Conceptuales Amplias

**Caso:** Pequeño productor pregunta "cómo cuidar mi maíz en verano" sin usar terminología técnica.

**Flujo:** Query en lenguaje natural → BERT interpreta concepto general de "cuidado" y "verano" → Recupera fragmentos sobre riego, nutrición, control de plagas estacionales → Sistema presenta información práctica priorizada por relevancia.

**Valor:** Democratiza acceso a conocimiento para usuarios sin formación técnica especializada.

### 9.3 Diagnóstico de Problemas

**Caso:** Productor observa amarillamiento en hojas y busca causa.

**Flujo:** Query "hojas amarillas maíz" → Sistema recupera fragmentos sobre deficiencia de nitrógeno, clorosis férrica, enfermedades fungales → Re-ranking prioriza fragmentos con imágenes y diagnóstico diferencial → Usuario recibe lista de posibles causas con síntomas asociados.

**Valor:** Sistema de soporte a decisión para diagnóstico preliminar en campo.

### 9.4 Recomendaciones Contextualizadas

**Caso:** Sistema proactivo sugiere prácticas basadas en contexto del productor (cultivo, ubicación, época).

**Flujo:** Sistema filtra fragmentos etiquetados como "RECOMENDACION" → Aplica filtros de contexto (cultivo=maíz, etapa=floración, región=trópico-seco) → Prioriza por severidad y urgencia → Genera cards de recomendación con KPIs ejecutables.

**Valor:** Transformación de búsqueda reactiva a asistencia proactiva.

---

## 10. DIFERENCIADORES TECNOLÓGICOS

### 10.1 No es un Árbol de Decisión

A diferencia de sistemas expertos clásicos que operan mediante reglas fijas (IF-THEN), MILPA utiliza búsqueda por similitud matemática:

**Árbol de decisión:**
```
¿Contiene "maíz"? → SI → ¿Contiene "nitrógeno"? → SI → Respuesta_A
```
Inflexible, requiere programación manual de todas las rutas de decisión.

**MILPA (Hybrid Retrieval):**
```
Vector(query) = [0.023, -0.145, ..., 0.234]
Similitud_Coseno(Vector_query, Vector_todos_fragmentos) → Top-K más similares
```
Flexible, aprende de los documentos sin programación de reglas.

### 10.2 No es TF-IDF Simple

MILPA utiliza BM25, una evolución del clásico TF-IDF con normalización mejorada:

**TF-IDF:** Peso = término_frecuencia × inverso_documento_frecuencia
Problema: Sobre-valora repeticiones, no maneja bien documentos de diferentes longitudes.

**BM25:** Incluye parámetros de saturación (k1=1.5) y normalización de longitud (b=0.75)
Resultado: Rankings más precisos y robustos ante variaciones de estilo documental.

### 10.3 No es Solo FAISS

Aunque ChromaDB y FAISS son bases de datos vectoriales similares, MILPA eligió ChromaDB por:
- Simplicidad de configuración (FAISS requiere tuning de índices IVF/HNSW/PQ)
- Suficiencia para volumen actual (<100k fragmentos)
- API Python más simple y pythonic
- Persistencia automática sin gestión manual de índices

**Escalabilidad futura:** Si el volumen supera 500k fragmentos, migración a FAISS sería considerada.

---

## 11. EVOLUCIÓN Y ROADMAP

### 11.1 Sprints Completados (17-20)

**Sprint 17:** Tests automatizados con contract testing, fuzzing, y golden answers
**Sprint 18:** Hardening de seguridad con Docker non-root y seccomp profiles
**Sprint 19:** Observabilidad completa con Prometheus, Grafana, OpenTelemetry
**Sprint 20:** Feature flags dinámicos y sistema de migraciones con rollback

### 11.2 Capacidades Futuras Planificadas

**H1 2026:**
- Cross-encoder para re-ranking (mejora precisión 8-12%)
- Generación de respuestas con LLM local (Llama 3 o Mistral)
- Multi-tenancy con aislamiento por organización
- API pública con autenticación OAuth2

**H2 2026:**
- Procesamiento de imágenes de plagas con computer vision
- Módulo de alertas proactivas basado en patrones temporales
- Integración con sensores IoT para recomendaciones contextuales
- Aplicación móvil nativa (Android/iOS)

---

## 12. CONCLUSIÓN

MILPA representa un sistema maduro de recuperación de información inteligente especializado en agricultura, que combina técnicas clásicas de búsqueda (BM25) con inteligencia artificial moderna (BERT embeddings) en una arquitectura híbrida optimizada para precisión y velocidad.

**Logros clave:**
- 91.7% de precisión en recuperación del fragmento más relevante
- Tiempo de respuesta <200ms de extremo a extremo
- Escalabilidad probada hasta 100k fragmentos
- Arquitectura de seguridad multi-capa en producción
- Observabilidad completa con métricas de negocio y técnicas

**Valor único:**
El sistema democratiza el acceso al conocimiento agrícola especializado mediante una interfaz en lenguaje natural que comprende tanto consultas técnicas exactas como preguntas conceptuales amplias, manteniendo trazabilidad completa a fuentes documentales y evitando alucinaciones mediante detección activa de evidencia insuficiente.

---

**Documento generado:** Marzo 2026  
**Versión del sistema:** 1.x (Sprints 17-20 completados)  
**Estado:** Producción operativa
