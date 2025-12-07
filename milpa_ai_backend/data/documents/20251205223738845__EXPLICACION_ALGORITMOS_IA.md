# Explicación Técnica del Sistema RAG - Algoritmos e IA

## 🔍 **Arquitectura del Sistema: Hybrid Retrieval (Recuperación Híbrida)**

### **Aclaración importante:**
**"Hybrid Retrieval" NO es un solo algoritmo**, es el **nombre de la arquitectura** que combina 3 algoritmos diferentes.

### **Los 3 algoritmos que usamos son:**
1. **BM25** - Búsqueda léxica (palabras clave)
2. **Dense Vector Retrieval con Sentence-BERT** - Búsqueda semántica (significado)
3. **RRF (Reciprocal Rank Fusion)** - Fusión de resultados

### **¿Qué es en términos simples?**
Es un sistema que combina **dos formas de buscar información**:
1. **Búsqueda por palabras clave** (algoritmo BM25, como Google tradicional)
2. **Búsqueda por significado** (algoritmo Dense Vector, entendiendo el concepto)

Luego **fusiona ambos resultados** (algoritmo RRF) para dar las mejores respuestas.

---

## ❌ **¿Por qué NO es Árbol de Decisión?**

### **Árbol de Decisión:**
```
¿La pregunta contiene "maíz"?
  ├─ SÍ → ¿Contiene "nitrógeno"?
  │       ├─ SÍ → Respuesta A
  │       └─ NO → Respuesta B
  └─ NO → Pregunta irrelevante
```

**Problemas con árboles de decisión para este caso:**
- ✗ **Inflexible:** Solo funciona con palabras exactas ("maíz" sí, "maiz" sin acento no)
- ✗ **No entiende sinónimos:** "fertilización" ≠ "abono" aunque significan lo mismo
- ✗ **Reglas fijas:** Cada pregunta nueva requiere programar nuevas reglas
- ✗ **No escala:** Con 1000 documentos, necesitarías miles de reglas manuales

### **Nuestro sistema (Hybrid Retrieval):**
- ✓ **Flexible:** Entiende variaciones ("maíz", "maiz", "corn", "Zea mays")
- ✓ **Semántico:** Comprende que "fertilización" ≈ "nutrición" ≈ "abono"
- ✓ **Automático:** Aprende de los documentos sin reglas manuales
- ✓ **Escalable:** Funciona igual con 10 o 10,000 documentos

---

## ⚖️ **Comparación con 2 Algoritmos Similares**

### **1. TF-IDF (Term Frequency-Inverse Document Frequency)**

**Qué es:**
Algoritmo clásico de búsqueda que cuenta cuántas veces aparece cada palabra en documentos.

**Por qué NO lo elegimos como principal:**
- ✗ **Menos preciso que BM25:** No maneja bien documentos de diferente longitud
- ✗ **Saturación de términos:** Si "maíz" aparece 50 veces vs 100 veces, TF-IDF da demasiado peso a la repetición
- ✗ **Sin normalización óptima:** BM25 tiene parámetros (k1, b) que ajustan mejor el ranking

**BM25 es la evolución mejorada de TF-IDF** → Por eso usamos BM25.

---

### **2. FAISS (Facebook AI Similarity Search)**

**Qué es:**
Base de datos vectorial ultra-rápida creada por Facebook para búsqueda de similitud.

**Por qué NO lo elegimos:**
- ✗ **Solo vectorial:** No tiene búsqueda léxica (palabras clave), solo semántica
- ✗ **Más complejo:** Requiere configuración avanzada de índices (IVF, HNSW, PQ)
- ✗ **Overkill para el caso:** ChromaDB es suficiente para nuestro volumen de datos (<100k fragmentos)

**ChromaDB es más simple y hace lo mismo para nuestro caso** → Elegimos simplicidad sin sacrificar calidad.

---

## 📊 **Cómo Trabaja con Datos Numéricos y Categóricos**

### **Datos Numéricos (mayoría del sistema):**

#### **1. Embeddings (vectores de 384 dimensiones):**
```
Texto: "Aplicar 120 kg/ha de nitrógeno en maíz"
  ↓
Vector: [0.023, -0.145, 0.891, ..., 0.234]  ← 384 números
```
- Cada fragmento → vector de 384 números decimales
- Cada pregunta → vector de 384 números decimales
- **Similitud de coseno** entre vectores → Score numérico (0.0 a 1.0)

#### **2. Scores BM25:**
```
Relevancia léxica = número decimal (ej: 8.45, 12.3, 5.67)
```
- Calcula qué tan relevante es un documento según palabras clave
- Valores típicos: 0 a 20 (sin límite superior estricto)

#### **3. Scores RRF (fusión):**
```
Score final = 1/(60 + rank_bm25) + 1/(60 + rank_vector)
```
- Combina rankings de ambos sistemas
- Valores típicos: 0.01 a 0.05

---

### **Datos Categóricos (metadatos):**

#### **1. Labels (etiquetas):**
- Categorías: `RECOMENDACION`, `DATO`, `RESULTADO`
- Uso: Filtrar fragmentos por tipo de información

#### **2. Tipos de entidades:**
- Categorías: `CULTIVO`, `PLAGA`, `NUTRIENTE`, `FENOFASE`, `LUGAR`
- Uso: Clasificar menciones en texto

#### **3. Nombres normalizados:**
- Categorías: "maiz", "tomate", "frijol", "nitrogeno", etc.
- Uso: Mapear sinónimos a forma canónica

---

### **Cómo se combinan:**

```
ENTRADA (categórica):
  Pregunta: "¿Cómo fertilizar maíz?"
  Entidades detectadas: CULTIVO=maiz, concepto=fertilización

PROCESAMIENTO (numérico):
  1. Embedding de pregunta → vector[384]
  2. BM25 busca "fertilizar" + "maíz" → scores numéricos
  3. ChromaDB busca vector similar → scores numéricos
  4. RRF fusiona → score final numérico

SALIDA (categórica + numérica):
  Fragmentos recuperados con:
    - doc_id (categórico)
    - score (numérico: 0.033)
    - labels (categórico: RECOMENDACION)
    - entities (categórico: CULTIVO=maiz, NUTRIENTE=nitrogeno)
```

---

## 🤖 **Tipos de IA que Estamos Usando**

### **1. Sentence-BERT (paraphrase-multilingual-MiniLM-L12-v2)**

**Tipo de IA:**
- **Categoría:** Red Neuronal Transformer (aprendizaje profundo)
- **Arquitectura:** 12 capas transformer con attention mechanism
- **Función:** Convertir texto a vectores semánticos (embeddings)

**Por qué esta IA:**
- ✓ **Multilingüe:** Español, inglés, 50+ idiomas
- ✓ **Eficiente:** 384 dimensiones (vs 768 de BERT estándar) → más rápido
- ✓ **Pre-entrenada:** Millones de pares de oraciones similares
- ✓ **Código abierto:** Apache 2.0, sin costo de licencia
- ✓ **Compacta:** 118 MB (cabe en RAM de cualquier servidor)

**Alternativas descartadas:**
- OpenAI text-embedding-3 → Requiere API paga, envía datos a cloud
- BERT base → Más pesado (768 dimensiones), más lento
- Sentence-BERT large → 3x más lento, mejora marginal (~2%)

---

### **2. spaCy NER (es_core_news_sm)**

**Tipo de IA:**
- **Categoría:** Red Neuronal Convolucional (CNN) + reglas
- **Función:** Reconocimiento de Entidades Nombradas (NER)

**Por qué esta IA:**
- ✓ **Especializada en español:** Modelo entrenado con corpus español
- ✓ **Rápida:** Procesa miles de documentos por segundo
- ✓ **Extensible:** Permite agregar reglas custom (EntityRuler)
- ✓ **Ligera:** 12 MB, incluye tokenización y POS tagging
- ✓ **Código abierto:** MIT License

**Alternativas descartadas:**
- Stanza (Stanford NLP) → Más lento, menos flexible para reglas custom
- Flair → Más preciso pero 10x más lento
- Transformers NER → Overkill, necesita GPU para ser rápido

---

### **3. NO estamos usando (pero podríamos):**

**LLM Generativo (ChatGPT/Claude/Llama):**
- **Estado actual:** Fallback (concatenación simple de fragmentos)
- **Uso futuro planeado:** Generar respuestas en lenguaje natural a partir de fragmentos recuperados
- **Por qué no activo aún:**
  - Sistema funciona sin él (RAG puro)
  - Evita costos de API
  - Evita riesgo de alucinaciones
  - Privacidad total (sin enviar datos fuera)

---

## 📈 **Resumen de Decisiones Técnicas**

| Componente | Tecnología Elegida | Por Qué |
|------------|-------------------|---------|
| **Búsqueda léxica** | BM25 (Whoosh) | Mejor que TF-IDF, estándar de industria |
| **Búsqueda semántica** | ChromaDB + Sentence-BERT | Simple, eficiente, open-source |
| **Fusión** | RRF | Combina rankings sin normalizar scores |
| **NER** | spaCy CNN | Rápido, extensible, español nativo |
| **Embeddings** | MiniLM-L12-v2 | Multilingüe, compacto, preciso |
| **Base de datos** | SQLite | Sin servidor, portable, suficiente para caso |
| **Generación** | Fallback (concatenar) | Evita dependencias externas, privacidad |

---

## ✅ **Conclusión Técnica**

Usamos la **arquitectura Hybrid Retrieval** que combina 3 algoritmos:

**Algoritmo 1 - BM25 (búsqueda léxica):**
- Encuentra documentos por palabras clave exactas
- Evolución mejorada de TF-IDF
- Maneja frecuencia y rareza de términos

**Algoritmo 2 - Dense Vector Retrieval (búsqueda semántica):**
- Convierte texto a vectores de 384 dimensiones usando Sentence-BERT
- Encuentra documentos por similitud de significado
- Usa similitud de coseno en espacio vectorial

**Algoritmo 3 - RRF (fusión):**
- Combina rankings de BM25 y Dense Vector
- Fórmula: `Score = 1/(60 + rank_BM25) + 1/(60 + rank_Vector)`
- Da más peso a documentos que aparecen arriba en ambas listas

**Por qué esta combinación:**
1. **Complementariedad:** BM25 encuentra coincidencias exactas, Dense Vector encuentra conceptos similares
2. **No es árbol de decisión:** Es búsqueda por similitud matemática, no reglas fijas
3. **Supera a TF-IDF:** BM25 es su evolución mejorada
4. **Más simple que FAISS:** ChromaDB es suficiente y más fácil de mantener
5. **Datos numéricos (95%):** Vectores, scores, similitudes
6. **Datos categóricos (5%):** Labels, entidades, nombres normalizados
7. **IA especializada:** Sentence-BERT (embeddings) + spaCy (NER), ambas open-source y eficientes

**El sistema es escalable, verificable y 100% local** - ideal para documentos privados donde la trazabilidad es crítica.



🧠 Algoritmos que usa (nombres técnicos):
1. Búsqueda Vectorial (Dense Retrieval)
Algoritmo: Sentence Transformers con modelo paraphrase-multilingual-MiniLM-L12-v2
Tecnología: ChromaDB (base de datos vectorial)
Cómo funciona: Convierte tu pregunta en un vector de números (embedding de 384 dimensiones) y busca fragmentos con vectores similares usando similitud de coseno
NO es árbol de decisión, es búsqueda por similitud vectorial en espacio de alta dimensión
2. Búsqueda Léxica (Lexical/Sparse Retrieval)
Algoritmo: BM25 (Best Matching 25) - es la evolución de TF-IDF
Tecnología: Whoosh (motor de búsqueda en Python)
Cómo funciona: Busca coincidencias de palabras clave considerando frecuencia y rareza del término (como Google tradicional)
Tipo: Algoritmo de ranking estadístico basado en frecuencias de términos
3. Fusión Híbrida
Algoritmo: RRF (Reciprocal Rank Fusion)
Fórmula: RRF_score = Σ(1 / (k + rank)) donde k=60
Cómo funciona: Combina los resultados de BM25 y búsqueda vectorial, dando más peso a los que aparecen arriba en ambas listas
Tipo: Algoritmo de fusión de rankings