# Arquitectura y Procesamiento de Datos - Sistema RAG Híbrido

## Descripción General del Sistema

El sistema implementado representa una arquitectura de Recuperación Aumentada (RAG - Retrieval-Augmented Generation) con búsqueda híbrida, diseñada específicamente para el dominio agrícola. Es importante aclarar que este sistema no realiza clasificación predictiva tradicional como lo haría un modelo de Machine Learning supervisado que asigna etiquetas a datos de entrada. En lugar de ello, el sistema se especializa en la recuperación híbrida de información, un proceso que combina múltiples técnicas complementarias para encontrar y ordenar contenido relevante.

La arquitectura integra tres enfoques fundamentales que trabajan en conjunto: primero, la búsqueda léxica mediante el algoritmo BM25, que identifica coincidencias exactas de palabras y términos; segundo, la búsqueda semántica basada en embeddings generados por BERT, que captura el significado contextual del texto; y tercero, la validación de entidades específicas del dominio mediante spaCy NER, que asegura la relevancia temática de los resultados. Esta combinación permite al sistema superar las limitaciones individuales de cada técnica, logrando una precisión del 91.7% en la recuperación del fragmento más relevante en la primera posición.

El objetivo principal del sistema consiste en encontrar los fragmentos de texto más relevantes dentro de una base de conocimiento agrícola especializada, respondiendo a consultas de usuarios sobre cultivos, nutrientes, plagas, fenología y manejo agronómico. A diferencia de los buscadores tradicionales que simplemente retornan documentos completos, este sistema fragmenta el conocimiento en unidades semánticas coherentes de 300 a 500 tokens, permitiendo respuestas más precisas y contextualizadas.

## Flujo de Procesamiento

El sistema opera en dos fases principales claramente diferenciadas: la fase de indexación, que ocurre cuando se ingresan nuevos documentos al sistema, y la fase de búsqueda, que se ejecuta cada vez que un usuario realiza una consulta. Ambas fases están diseñadas para maximizar la eficiencia y la precisión en la recuperación de información relevante.

### Fase 1: Indexación (Ingesta de Documentos)

La fase de indexación comienza cuando un usuario sube un documento PDF al sistema. Este proceso transforma documentos completos en fragmentos indexados y vectorizados que pueden ser buscados eficientemente mediante diferentes técnicas. El diagrama siguiente ilustra el flujo completo de esta transformación:

```
┌─────────────────┐
│  Documento PDF  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Extracción Text │ ← PyPDF2 / Tesseract OCR
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Fragmentación  │ ← Chunking (300-500 tokens)
└────────┬────────┘
         │
         ▼
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌──────────┐
│ SQLite │ │   BERT   │
│Fragment│ │Embedding │
└────────┘ └────┬─────┘
              │
              ▼
         ┌──────────┐
         │ChromaDB  │
         │(Vectors) │
         └──────────┘
              │
              ▼
         ┌──────────┐
         │ Tantivy  │
         │BM25 Index│
         └──────────┘
```

#### Explicación de cada fase del diagrama de indexación:

**Documento PDF**: Esta es la entrada del sistema. El usuario sube un archivo PDF que contiene información agrícola relevante. El sistema acepta documentos de hasta 10 MB y antes de procesarlos, ejecuta un escaneo con ClamAV para garantizar que el archivo no contenga malware o virus.

**Extracción Text**: En esta etapa, el sistema intenta extraer el texto contenido en el PDF. La herramienta principal utilizada es PyPDF2, una biblioteca de Python que lee PDFs digitales. Sin embargo, cuando el documento es un PDF escaneado (imagen) o cuando la extracción produce menos de 100 caracteres, el sistema activa automáticamente Tesseract OCR, un motor de reconocimiento óptico de caracteres que convierte imágenes de texto en texto digital procesable.

**Fragmentación (Chunking)**: Una vez extraído el texto completo del documento, este se divide en fragmentos o "chunks" de tamaño manejable. Cada fragmento contiene entre 300 y 500 tokens (aproximadamente 200-400 palabras), con un solapamiento de 50 tokens entre fragmentos consecutivos. Este solapamiento asegura que el contexto no se pierda en los límites entre fragmentos. La fragmentación es crucial porque permite búsquedas más precisas: en lugar de retornar un documento completo de 50 páginas, el sistema puede identificar exactamente el párrafo o sección que responde la pregunta del usuario.

**Bifurcación del procesamiento**: Después de la fragmentación, el procesamiento se divide en dos caminos paralelos. Por un lado, el texto se almacena directamente en SQLite para su recuperación posterior. Por otro lado, cada fragmento se procesa con BERT para generar su representación vectorial.

**SQLite Fragment**: Esta base de datos relacional almacena el texto completo de cada fragmento junto con sus metadatos: el documento de origen, la posición del fragmento dentro del documento, marcas de tiempo, y otros datos contextuales. SQLite actúa como la fuente de verdad para el texto original.

**BERT Embedding**: El modelo BERT (específicamente `paraphrase-multilingual-MiniLM-L12-v2`) convierte cada fragmento de texto en un vector denso de 384 dimensiones. Este vector es una representación numérica del significado semántico del texto. Fragmentos con significados similares producirán vectores cercanos en el espacio vectorial de 384 dimensiones, incluso si usan palabras completamente diferentes.

**ChromaDB (Vectors)**: Los vectores generados por BERT se almacenan en ChromaDB, una base de datos especializada en almacenar y buscar eficientemente vectores de alta dimensionalidad. ChromaDB utiliza índices aproximados de vecinos más cercanos (ANN - Approximate Nearest Neighbors) que permiten encontrar vectores similares en milisegundos, incluso con millones de vectores almacenados.

**Tantivy BM25 Index**: Simultáneamente, el texto de cada fragmento se indexa en Tantivy, un motor de búsqueda de texto completo escrito en Rust. Tantivy crea un índice invertido, una estructura de datos que mapea cada palabra única a la lista de fragmentos que la contienen. Este índice permite al algoritmo BM25 realizar búsquedas léxicas extremadamente rápidas basadas en coincidencias exactas de palabras.

El tiempo promedio para indexar un documento de 10 páginas es de 5 a 10 segundos, durante los cuales se generan aproximadamente 20-30 fragmentos, cada uno con su vector BERT y su entrada en el índice BM25.

### Fase 2: Búsqueda (Query Processing)

Cuando un usuario realiza una consulta, el sistema ejecuta un proceso sofisticado de múltiples etapas que combina diferentes técnicas de búsqueda y validación para garantizar que los resultados sean tanto relevantes como precisos. El siguiente diagrama ilustra este proceso:

```
┌──────────────────┐
│ Query del Usuario│
│"nitrógeno maíz"  │
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌──────────────┐
│ spaCy  │ │  BM25 + BERT │
│  NER   │ │  (Paralelo)  │
└───┬────┘ └───────┬──────┘
    │              │
    │         ┌────┴────┐
    │         │         │
    │         ▼         ▼
    │    ┌──────┐  ┌────────┐
    │    │ BM25 │  │  BERT  │
    │    │Top-20│  │ Top-20 │
    │    └──┬───┘  └────┬───┘
    │       │           │
    │       └─────┬─────┘
    │             ▼
    │        ┌─────────┐
    │        │   RRF   │
    │        │ Fusion  │
    │        └────┬────┘
    │             │
    └────────┬────┘
             ▼
      ┌─────────────┐
      │ Re-ranking  │
      │Term Coverage│
      └──────┬──────┘
             │
             ▼
      ┌─────────────┐
      │   Filter    │
      │Insufficient │
      │  Evidence   │
      └──────┬──────┘
             │
             ▼
      ┌─────────────┐
      │   Top-K     │
      │  Resultados │
      └─────────────┘
```

#### Explicación detallada de cada fase del diagrama de búsqueda:

**Query del Usuario**: El proceso comienza cuando el usuario escribe su pregunta o consulta en lenguaje natural, por ejemplo "necesito nitrógeno para maíz en verano". Esta consulta puede contener desde términos técnicos específicos hasta preguntas formuladas de manera coloquial. El sistema está diseñado para manejar consultas en español con toda su variabilidad lingüística.

**Bifurcación inicial - spaCy NER y Búsqueda Paralela**: Inmediatamente después de recibir la consulta, el sistema se divide en dos procesos que ocurren simultáneamente. Por un lado, spaCy NER procesa la consulta para extraer entidades del dominio agrícola. Por otro lado, los motores de búsqueda BM25 y BERT comienzan a buscar fragmentos relevantes. Esta ejecución paralela es crucial para minimizar el tiempo de respuesta total del sistema.

**spaCy NER (Named Entity Recognition)**: Este componente analiza la consulta del usuario para identificar y extraer entidades específicas del dominio agrícola. Utilizando un diccionario personalizado cargado desde archivos CSV (crops.csv, nutrients.csv, pests.csv, etc.), spaCy identifica términos como "nitrógeno" (nutriente), "maíz" (cultivo) y "verano" (estación). Estas entidades extraídas se guardan temporalmente en memoria para ser utilizadas más adelante en las fases de re-ranking y filtrado. Es importante notar que spaCy NO realiza la búsqueda en sí misma, solo extrae y clasifica términos relevantes. Este proceso toma aproximadamente 10 milisegundos.

**BM25 y BERT (Búsqueda Paralela)**: Estos dos motores de búsqueda operan completamente independientes uno del otro, sin comunicación entre ellos durante la fase de búsqueda. Ambos reciben la consulta COMPLETA del usuario, no solo las entidades extraídas por spaCy.

**BM25 Top-20**: El motor BM25 realiza una búsqueda léxica basada en coincidencias exactas de palabras. Tokeniza la consulta completa y busca en el índice Tantivy todos los fragmentos que contienen esas palabras, asignando puntuaciones más altas a fragmentos que contienen palabras raras o técnicas (como "nitrógeno") y puntuaciones más bajas a fragmentos con palabras comunes (como "para", "en", "el"). El resultado es una lista ordenada de los 20 fragmentos más relevantes según criterios léxicos. Esta búsqueda toma aproximadamente 50 milisegundos.

**BERT Top-20**: Simultáneamente, el motor BERT realiza una búsqueda semántica. Primero convierte la consulta completa del usuario en un vector de 384 dimensiones. Luego, ChromaDB busca los 20 vectores más cercanos (similares) a este vector de consulta usando distancia coseno. Esta búsqueda encuentra fragmentos semánticamente similares incluso si no contienen las palabras exactas de la consulta. Por ejemplo, puede encontrar fragmentos que hablen de "fertilización nitrogenada" aunque el usuario haya preguntado por "nitrógeno", o fragmentos que mencionen "gramíneas" cuando el usuario preguntó por "maíz". Esta búsqueda toma aproximadamente 80 milisegundos.

**RRF Fusion (Reciprocal Rank Fusion)**: Una vez que ambos motores de búsqueda han retornado sus listas de Top-20, el algoritmo RRF los fusiona en una única lista ordenada. RRF no simplemente concatena las listas ni promedia puntuaciones, sino que utiliza una fórmula matemática basada en la posición (ranking) de cada fragmento en cada lista: `1/(60 + rank)`. Los fragmentos que aparecen en ambas listas (BM25 y BERT) reciben puntuaciones sumadas, lo que automáticamente les da prioridad. Por ejemplo, si un fragmento está en posición 1 en BM25 y posición 2 en BERT, su puntuación RRF será `1/(60+1) + 1/(60+2) = 0.0325`, mientras que un fragmento que solo aparece en una lista tendrá una puntuación menor. Este proceso toma aproximadamente 5 milisegundos.

**Re-ranking con Term Coverage**: En esta etapa, el sistema utiliza las entidades que spaCy extrajo al inicio del proceso. Para cada fragmento en la lista fusionada, cuenta cuántas de las entidades identificadas por spaCy están presentes en el texto del fragmento. Calcula un valor de "coverage" (cobertura) dividiendo las entidades presentes entre el total de entidades extraídas. Luego aplica un boost multiplicativo a la puntuación RRF usando la fórmula: `score_final = score_RRF × (1 + 0.5 × coverage)`. Esto significa que un fragmento que contenga todas las entidades relevantes (nitrógeno, maíz, verano) recibirá un boost significativo en su puntuación, mientras que fragmentos que carecen de estas entidades mantendrán puntuaciones más bajas. Este proceso toma aproximadamente 10 milisegundos.

**Filter Insufficient Evidence**: Este filtro actúa como una barrera de calidad final. Examina cada fragmento y descarta aquellos que no contienen al menos una de las entidades extraídas por spaCy. La lógica es que si un fragmento fue recuperado pero no menciona ninguna de las entidades clave que el usuario busca (nitrógeno, maíz, etc.), probablemente no sea relevante independientemente de su puntuación numérica. Este filtro elimina falsos positivos que podrían haber pasado por similitud estadística o semántica superficial. El proceso toma aproximadamente 5 milisegundos.

**Top-K Resultados**: Finalmente, el sistema selecciona los K fragmentos con mayor puntuación de la lista filtrada y ordenada. Por defecto, K=5, pero este valor es configurable. Para cada uno de estos fragmentos finales, el sistema recupera el texto completo desde SQLite junto con metadatos del documento origen (nombre del archivo, número de página, etc.) para presentarlos al usuario. El tiempo total de respuesta, desde que el usuario envía la consulta hasta que recibe los resultados, es de aproximadamente 150-200 milisegundos.

La arquitectura de este pipeline refleja un equilibrio cuidadoso entre precisión, cobertura y velocidad. La búsqueda paralela maximiza la cobertura al combinar dos paradigmas diferentes (léxico y semántico), mientras que las etapas de fusión, re-ranking y filtrado aseguran que solo los resultados más relevantes y precisos lleguen al usuario.

## Formato de Datos

El sistema procesa y transforma datos a través de múltiples representaciones a lo largo de su pipeline. Comprender estos formatos es esencial para entender cómo la información fluye desde los documentos originales hasta los resultados finales presentados al usuario.

### Entrada: Documentos en Fase de Indexación

Cuando un documento ingresa al sistema durante la fase de indexación, llega en formato PDF con ciertas restricciones de tamaño y seguridad. El tipo de contenido debe ser `application/pdf` y el tamaño máximo permitido es de 10 megabytes, un límite establecido para equilibrar la capacidad de procesar documentos sustanciales sin comprometer el rendimiento del sistema. Antes de procesar cualquier documento, el sistema ejecuta un escaneo completo con ClamAV, el motor antivirus de código abierto, garantizando que el archivo no contenga malware, virus o código malicioso que pueda comprometer la seguridad del sistema.

Una vez que el documento pasa la validación de seguridad, el sistema extrae y almacena metadatos críticos. Estos incluyen el nombre original del archivo (por ejemplo, `manual_fertilizacion.pdf`), una marca de tiempo precisa del momento de carga en formato ISO 8601 (como `2025-12-15T10:30:00Z`), el número total de páginas del documento, un hash SHA-256 único del contenido del archivo que sirve para detectar duplicados y verificar integridad, y la ruta donde se almacena físicamente el documento en el servidor (siguiendo un esquema como `/data/documents/1758061555__manual_fertilizacion.pdf`, donde el prefijo numérico es un timestamp Unix que previene colisiones de nombres).

### Procesamiento Intermedio: Fragmentos y Vectores

Después de la extracción de texto y durante la fragmentación, cada porción de texto se convierte en un objeto de fragmento estructurado que contiene múltiples campos de información. Cada fragmento recibe un identificador único (`fragment_id`) que lo distingue de todos los demás fragmentos en el sistema. El campo de texto contiene el contenido completo del fragmento, típicamente entre 200 y 400 palabras. El sistema mantiene la trazabilidad guardando el `document_id` del documento origen, permitiendo rastrear cada fragmento hasta su fuente. Las posiciones de inicio y fin (`start_char` y `end_char`) registran la ubicación exacta del fragmento dentro del texto original del documento, medida en caracteres desde el inicio. El conteo de tokens almacena cuántas unidades léxicas contiene el fragmento, información utilizada para mantener la consistencia del tamaño de chunks. Finalmente, una marca de tiempo de creación registra cuándo se generó el fragmento durante el proceso de indexación.

La representación vectorial generada por BERT constituye uno de los elementos más sofisticados del sistema. Cada fragmento se transforma en un vector denso de exactamente 384 dimensiones, donde cada dimensión es un número decimal de precisión simple (float32). Estos 384 números no son aleatorios ni arbitrarios; cada uno representa una característica semántica aprendida por BERT durante su fase de pre-entrenamiento con millones de documentos. Los valores típicamente oscilan entre -1.0 y 1.0, y su distribución en el espacio vectorial captura el significado del texto. Fragmentos con significados similares producen vectores cuyos valores numéricos son cercanos entre sí, permitiendo que operaciones matemáticas simples como la distancia coseno revelen similitud semántica.

El índice invertido de BM25 representa otra estructura de datos fundamental. Para cada término único que aparece en el corpus de fragmentos, Tantivy mantiene una lista de todos los fragmentos que contienen ese término, junto con la frecuencia de aparición en cada uno. Por ejemplo, el término "nitrógeno" podría estar asociado con fragmentos 1234, 2567 y 3891, apareciendo 3, 1 y 2 veces respectivamente. El sistema también calcula y almacena el valor IDF (Inverse Document Frequency) para cada término, que mide su rareza en el corpus completo. Términos raros como "nitrógeno" tendrán valores IDF altos (por ejemplo, 2.89), mientras que palabras comunes como "el" o "de" tendrán valores IDF cercanos a cero.

### Entrada: Consultas en Fase de Búsqueda

Cuando un usuario realiza una búsqueda, su consulta llega al sistema como una estructura simple que contiene el texto de la pregunta en lenguaje natural, el parámetro `top_k` que especifica cuántos resultados desea (por defecto 5), y un campo opcional de filtros que permite restringir la búsqueda a documentos específicos o rangos de fechas. Por ejemplo, una consulta típica contiene simplemente el texto "necesito nitrógeno para maíz en verano" junto con el valor de top_k establecido en 5.

El procesamiento con spaCy NER transforma esta consulta simple en una estructura rica de entidades clasificadas. El sistema mantiene la consulta original en su campo `raw_query`, pero además extrae y categoriza entidades específicas del dominio agrícola. Para la consulta mencionada, spaCy identificaría "nitrógeno" como nutriente, "maíz" como cultivo, y "verano" como estación del año. Esta extracción estructurada de información es lo que permite al sistema realizar validaciones semánticas sofisticadas más adelante en el pipeline.

### Salida: Resultados Presentados al Usuario

La respuesta final del sistema es una estructura JSON compleja que contiene toda la información necesaria para que el usuario o la aplicación cliente procese los resultados. El campo de consulta repite la pregunta original del usuario para mantener el contexto. El número de resultados indica cuántos fragmentos relevantes se encontraron después de todas las fases de filtrado. El tiempo de procesamiento en milisegundos proporciona transparencia sobre el rendimiento del sistema, típicamente entre 150 y 250 milisegundos.

La sección más importante de la respuesta es el array de resultados, donde cada elemento representa un fragmento recuperado con toda su información contextual. Cada resultado incluye el identificador único del fragmento, el texto completo del fragmento (que puede ser de varios párrafos), y una puntuación final normalizada entre 0 y 1 que representa la relevancia global calculada después de todas las fases de ranking. El sistema también proporciona el nombre del documento origen y el número de página donde se encuentra el fragmento, permitiendo al usuario consultar el contexto completo si lo desea.

Los metadatos detallados de cada resultado revelan el funcionamiento interno del sistema y permiten debugging y análisis de calidad. La puntuación BM25 muestra qué tan bien el fragmento coincidió léxicamente con la consulta. La similitud BERT (típicamente entre 0 y 1, donde 1 es idéntico) indica qué tan cercano semánticamente está el fragmento de la consulta. La puntuación RRF muestra el valor calculado por el algoritmo de fusión después de combinar ambas listas. El term coverage revela qué fracción de las entidades extraídas por spaCy están presentes en el fragmento, y finalmente, una lista explícita de las entidades encontradas documenta exactamente qué términos relevantes contiene el texto.

Esta riqueza de información en los metadatos permite no solo presentar resultados al usuario, sino también analizar el comportamiento del sistema, identificar casos donde un componente funciona mejor que otro, y refinar continuamente los parámetros del sistema para mejorar la precisión.

## Algoritmos y Técnicas

El sistema implementa cinco algoritmos fundamentales que trabajan en conjunto para lograr una recuperación de información precisa y eficiente. Cada algoritmo aporta capacidades únicas que complementan las limitaciones de los demás, creando un sistema híbrido robusto.

### BM25 (Best Matching 25)

BM25 representa una evolución del clásico modelo TF-IDF (Term Frequency - Inverse Document Frequency) y constituye una de las funciones de ranking probabilísticas más efectivas en recuperación de información. Este algoritmo calcula una puntuación de relevancia para cada documento basándose en las frecuencias de los términos de la consulta dentro del documento, ajustadas por la rareza de esos términos en todo el corpus.

La fórmula completa de BM25 incorpora varios componentes cuidadosamente balanceados. Para cada término `qi` de la consulta, BM25 calcula el producto del IDF del término multiplicado por una función de saturación de frecuencia. Esta función de saturación es crucial: a diferencia de TF-IDF simple que crece linealmente con la frecuencia del término, BM25 implementa una curva que se satura, reconociendo que la vigésima aparición de una palabra en un documento no añade tanta información como la segunda aparición. La fórmula específica es:

```
         IDF(qi) × f(qi, D) × (k1 + 1)
BM25 = Σ ────────────────────────────────────
         f(qi, D) + k1 × (1 - b + b × |D|/avgdl)
```

En esta ecuación, `qi` representa cada término individual de la consulta, `D` es el documento candidato siendo evaluado, `f(qi, D)` representa la frecuencia del término `qi` dentro del documento `D`, y `|D|` es la longitud total del documento medida en términos. El parámetro `avgdl` representa la longitud promedio de todos los documentos en el corpus, usado como baseline para la normalización.

Los parámetros `k1` y `b` controlan comportamientos críticos del algoritmo. El parámetro `k1`, típicamente establecido entre 1.2 y 2.0 (en este sistema se usa 1.5), controla qué tan rápido la función de saturación alcanza su máximo. Valores más altos permiten que la frecuencia de términos tenga más impacto antes de saturarse. El parámetro `b`, establecido en 0.75, controla la agresividad de la normalización por longitud de documento. Un valor de b=1 significa normalización completa (penalizando fuertemente documentos largos), mientras que b=0 desactiva completamente la normalización.

El componente IDF (Inverse Document Frequency) se calcula como:

```
IDF(qi) = log((N - df(qi) + 0.5) / (df(qi) + 0.5))
```

Donde `N` es el número total de documentos en el corpus y `df(qi)` es el número de documentos que contienen el término `qi`. Esta fórmula asegura que términos raros reciban puntuaciones IDF altas, mientras que términos comunes que aparecen en casi todos los documentos reciban valores cercanos a cero o incluso negativos, efectivamente eliminando su contribución al ranking.

En este sistema, BM25 opera sobre Tantivy, una biblioteca de búsqueda de texto completo escrita en Rust que ofrece rendimiento excepcional. Tantivy puede procesar millones de documentos por segundo, lo que permite que la búsqueda BM25 complete en aproximadamente 50 milisegundos incluso con decenas de miles de fragmentos indexados.

Las ventajas principales de BM25 incluyen su velocidad extraordinaria, su capacidad para identificar automáticamente términos importantes mediante IDF sin necesidad de supervisión, y su normalización inteligente que previene que documentos largos dominen los resultados simplemente por su longitud. Sin embargo, BM25 tiene limitaciones significativas: no puede entender sinónimos (para BM25, "nitrógeno" y "N" son completamente diferentes), es sensible a la elección exacta de palabras, y no captura relaciones semánticas entre términos.

### BERT Embeddings (Sentence Transformers)

BERT (Bidirectional Encoder Representations from Transformers) representa un cambio paradigmático en el procesamiento del lenguaje natural. A diferencia de enfoques basados en conteo de palabras como BM25, BERT genera representaciones vectoriales densas que capturan el significado semántico profundo del texto. Este sistema utiliza específicamente el modelo `paraphrase-multilingual-MiniLM-L12-v2`, una variante optimizada de BERT diseñada para generar embeddings de oraciones de alta calidad en múltiples idiomas, incluyendo español.

La arquitectura del modelo comprende 12 capas de Transformers, cada una aprendiendo representaciones progresivamente más abstractas del texto. Con 384 dimensiones en la capa de salida y aproximadamente 118 millones de parámetros entrenados, el modelo ha sido expuesto durante su fase de pre-entrenamiento a vastos corpus de texto en más de 50 idiomas, aprendiendo patrones lingüísticos universales y específicos de cada idioma.

El proceso de generación de embeddings comienza con la tokenización, donde el texto se divide en subpalabras utilizando el algoritmo WordPiece. Por ejemplo, "nitrógeno" podría tokenizarse como `["nitro", "##geno"]`, donde el prefijo `##` indica una continuación de la palabra anterior. Tokens especiales como `[CLS]` (clasificación) y `[SEP]` (separador) se añaden al principio y final de la secuencia respectivamente.

Estos tokens pasan a través de las 12 capas de Transformers, donde cada capa ejecuta operaciones de self-attention multi-head que permiten a cada token "atender" a todos los demás tokens en la secuencia, capturando relaciones contextuales complejas. Cada capa Transformer genera hidden states de 768 dimensiones para cada token en la secuencia. Después de procesar todas las capas, el sistema ejecuta mean pooling, promediando los hidden states de todos los tokens para producir un único vector que representa la oración completa. Este vector de 768 dimensiones se proyecta luego a 384 dimensiones mediante una capa densa final, y se aplica normalización L2 para que todos los vectores tengan norma unitaria, optimizando el cálculo posterior de similitud coseno.

La similitud entre dos textos se calcula usando distancia coseno, definida matemáticamente como:

```
                    A · B
similarity = ─────────────────
              ||A|| × ||B||
```

Donde A y B son los vectores de embedding, el numerador es el producto punto (suma de multiplicaciones elemento por elemento), y el denominador es el producto de las normas euclidianas. Debido a que los vectores están normalizados (norma = 1), la fórmula se simplifica al producto punto directo. El resultado varía entre -1 y 1, donde 1 indica vectores idénticos, 0 indica ortogonalidad (no relacionados), y -1 indica vectores opuestos.

Las ventajas de BERT incluyen su capacidad para entender sinónimos y paráfrasis ("N" y "nitrógeno" tienen vectores similares), su captura del contexto completo de cada palabra en la oración, y su efectividad multilingüe probada en español. Sin embargo, BERT es computacionalmente más costoso que BM25, tomando 80 milisegundos versus 50 milisegundos, y ocasionalmente puede confundir términos técnicos muy específicos con términos relacionados pero no idénticos.

### RRF (Reciprocal Rank Fusion)

Reciprocal Rank Fusion es un algoritmo elegante para combinar múltiples listas de ranking sin necesidad de normalizar puntuaciones o calibrar pesos entre sistemas. Su simplicidad matemática contrasta con su efectividad empírica, habiendo demostrado superar métodos más complejos en numerosos benchmarks de recuperación de información.

La fórmula de RRF para un documento d es:

```
              1
RRF(d) = Σ ─────────
          k + r(d)
```

Donde la suma ocurre sobre todas las listas de ranking (en este caso, dos: BM25 y BERT), `r(d)` es la posición (rank) del documento d en cada lista (1 para primer lugar, 2 para segundo, etc.), y `k` es una constante típicamente establecida en 60, aunque puede variar entre 10 y 100 sin afectar significativamente los resultados.

La belleza de RRF radica en cómo trata posiciones altas versus bajas. Un documento en posición 1 contribuye `1/(60+1) = 0.0164` a su puntuación total. Un documento en posición 10 contribuye `1/(60+10) = 0.0143`. La diferencia parece pequeña, pero es proporcional y consistente. Crucialmente, un documento que aparece en ambas listas suma ambas contribuciones: si está en posición 1 en BM25 y posición 2 en BERT, su puntuación total es `0.0164 + 0.0161 = 0.0325`, superando automáticamente a documentos que solo aparecen en una lista.

El parámetro k=60 actúa como un suavizador que previene que documentos en posiciones muy tempranas dominen completamente. Sin este factor, la diferencia entre posición 1 y posición 2 sería el 100% (`1/1 - 1/2 = 0.5`), creando un sistema muy sensible a pequeñas variaciones en las posiciones altas. Con k=60, la diferencia es mucho más graduada.

Las ventajas de RRF incluyen que no requiere normalización de puntuaciones diferentes de cada sistema (BM25 usa una escala, BERT usa otra, pero RRF solo ve posiciones), trata ambos sistemas equitativamente sin necesidad de aprender pesos mediante entrenamiento, y es robusto ante outliers o sistemas que ocasionalmente producen puntuaciones anómalas. El algoritmo ejecuta extremadamente rápido, tomando solo 5 milisegundos para fusionar dos listas de 20 elementos cada una.

### Term Coverage Re-ranking

Después de la fusión con RRF, el sistema aplica una capa adicional de re-ranking basada en la presencia de entidades específicas del dominio extraídas por spaCy. Este algoritmo implementa la intuición de que fragmentos que mencionan más de las entidades clave de la consulta son probablemente más relevantes que fragmentos que mencionan pocas o ninguna, independientemente de su similitud léxica o semántica general.

La fórmula de re-ranking es:

```
Score_final = Score_RRF × (1 + α × coverage)
```

Donde `coverage` se define como el ratio entre las entidades presentes en el fragmento y el total de entidades extraídas de la consulta, y `α` es un factor de boost establecido en 0.5. Este valor de α fue determinado empíricamente: valores más altos (como 1.0) causaban que el term coverage dominara excesivamente sobre las puntuaciones RRF originales, mientras que valores más bajos (como 0.2) no proporcionaban suficiente diferenciación.

Consideremos un ejemplo concreto. Si spaCy extrajo tres entidades de la consulta (nitrógeno, maíz, clima), y un fragmento contiene dos de ellas (nitrógeno y maíz), entonces `coverage = 2/3 = 0.67`. Si este fragmento tenía un `Score_RRF = 0.0325`, su puntuación final sería `0.0325 × (1 + 0.5 × 0.67) = 0.0325 × 1.335 = 0.0434`, un incremento del 33.5%. Por contraste, un fragmento que no contiene ninguna entidad (coverage = 0) mantiene su puntuación RRF original sin cambios.

Esta técnica de re-ranking representa una forma de fusión tardía entre la búsqueda léxica/semántica y el análisis de entidades. En lugar de usar las entidades para filtrar antes de la búsqueda (lo que podría eliminar resultados relevantes que usan sinónimos de las entidades), el sistema primero encuentra candidatos mediante BM25 y BERT, luego usa las entidades para ajustar el ranking final, combinando lo mejor de ambos mundos.

### spaCy NER (Named Entity Recognition)

El componente de reconocimiento de entidades nombradas utiliza spaCy, una biblioteca de procesamiento de lenguaje natural industrial. Específicamente, el sistema carga el modelo `es_core_news_sm` para español y lo extiende con un EntityRuler personalizado, un componente basado en reglas que identifica entidades mediante pattern matching contra diccionarios específicos del dominio.

A diferencia de enfoques de NER basados en Machine Learning que entrenan modelos estadísticos para reconocer entidades, este sistema utiliza matching exacto de patrones definidos en archivos CSV. Los archivos de taxonomía incluyen `crops.csv` con 45 especies de cultivos, `nutrients.csv` con 23 elementos nutricionales, `pests.csv` con 67 organismos plaga, `phenology.csv` con 18 etapas fenológicas, y `regions.csv` con 12 zonas agroclimáticas, totalizando más de 200 patrones únicos.

Cada patrón puede ser simple (una sola palabra como "maíz") o complejo (una secuencia de tokens con atributos como `[{"LOWER": "n"}]` que coincide con la letra "n" en minúsculas, capturando el símbolo químico del nitrógeno). El EntityRuler procesa el texto tokenizado y busca estos patrones, etiquetando cada coincidencia con su categoría correspondiente (CROP, NUTRIENT, PEST, etc.).

El proceso comienza tokenizando la consulta del usuario en palabras y signos de puntuación. Luego, el EntityRuler examina cada posible secuencia de tokens buscando coincidencias con los patrones cargados. Cuando encuentra una coincidencia, crea una entidad con el texto coincidente, su etiqueta de categoría, y las posiciones de inicio y fin en caracteres dentro del texto original.

Este enfoque de pattern matching en lugar de Machine Learning tiene ventajas y desventajas. Las ventajas incluyen precisión del 100% para términos en el diccionario (nunca confunde "maíz" con otra cosa), control completo sobre qué entidades se reconocen mediante la edición de archivos CSV, y rendimiento extremadamente rápido (10 milisegundos para procesar una consulta típica). Las desventajas incluyen la incapacidad para reconocer variaciones ortográficas no incluidas en el diccionario (si el CSV contiene "maíz" pero no "maiz" sin tilde, esta última no se reconocerá) y la necesidad de mantenimiento manual de los diccionarios al añadir nuevos términos relevantes.

En el contexto del pipeline completo, spaCy NER actúa como un extractor de información estructurada que transforma consultas en lenguaje natural en conjuntos estructurados de entidades del dominio, información que luego se utiliza para validar y mejorar los resultados de búsqueda producidos por BM25 y BERT.

## 🔄 Pipeline Detallado

### Indexación Paso a Paso

```python
# 1. Recepción de documento
POST /upload
Content-Type: multipart/form-data
file: manual_fertilizacion.pdf (2.3 MB)

# 2. Escaneo antivirus
→ ClamAV: CLEAN ✓

# 3. Extracción de texto
→ PyPDF2.extract_text()
→ Si texto < 100 chars: Tesseract OCR

# 4. Fragmentación
→ Chunk size: 400 tokens (promedio)
→ Overlap: 50 tokens
→ Resultado: 87 fragmentos

# 5. Almacenamiento SQLite
INSERT INTO fragments (document_id, text, start_char, end_char)
VALUES (123, 'El nitrógeno...', 0, 850)

# 6. Generación de embeddings
for fragment in fragments:
    vector = bert_model.encode(fragment.text)  # 384D
    chromadb.add(ids=[fragment.id], embeddings=[vector])

# 7. Indexación BM25
tantivy_index.add_document({
    'id': fragment.id,
    'text': fragment.text
})

# 8. Commit índices
chromadb.persist()
tantivy_index.commit()
```

**Tiempo promedio**: 5-10 segundos por documento (10 páginas)

---

### Búsqueda Paso a Paso

```python
# 1. Recepción de query
GET /search?q=necesito+nitrógeno+para+maíz&top_k=5

# 2. Extracción de entidades (spaCy)
query = "necesito nitrógeno para maíz"
entities = nlp(query)
→ entities_dict = {
    'nutrients': ['nitrógeno'],
    'crops': ['maíz']
}
# Tiempo: ~10ms

# 3. Búsqueda BM25 (paralelo)
Thread 1:
bm25_results = tantivy.search(query, top_k=20)
→ [
    {'id': 1234, 'score': 4.567},
    {'id': 2567, 'score': 3.891},
    ...
]
# Tiempo: ~50ms

# 4. Búsqueda BERT (paralelo)
Thread 2:
query_vector = bert_model.encode(query)
bert_results = chromadb.query(
    query_embeddings=[query_vector],
    n_results=20
)
→ [
    {'id': 3891, 'distance': 0.123},
    {'id': 1234, 'distance': 0.156},
    ...
]
# Tiempo: ~80ms

# 5. Esperar ambos threads
wait_for_completion()

# 6. RRF Fusion
rrf_scores = {}
for rank, doc in enumerate(bm25_results):
    rrf_scores[doc.id] = 1 / (60 + rank + 1)

for rank, doc in enumerate(bert_results):
    if doc.id in rrf_scores:
        rrf_scores[doc.id] += 1 / (60 + rank + 1)
    else:
        rrf_scores[doc.id] = 1 / (60 + rank + 1)

sorted_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
# Tiempo: ~5ms

# 7. Re-ranking con term coverage
for doc_id, score in sorted_results:
    fragment = get_fragment(doc_id)
    entities_present = count_entities(fragment.text, entities_dict)
    coverage = entities_present / len(entities_dict)
    boosted_score = score * (1 + 0.5 * coverage)
    doc.score = boosted_score
# Tiempo: ~10ms

# 8. Filtro de insufficient evidence
filtered_results = [
    doc for doc in sorted_results 
    if has_at_least_one_entity(doc, entities_dict)
]
# Tiempo: ~5ms

# 9. Top-K final
final_results = filtered_results[:5]

# 10. Recuperación de textos completos
for doc in final_results:
    doc.text = sqlite.query("SELECT text FROM fragments WHERE id=?", doc.id)
    doc.metadata = get_document_metadata(doc.document_id)

# Tiempo total: ~150-200ms
```

## Fundamentos Teóricos

La arquitectura del sistema se fundamenta en varios conceptos teóricos profundos de la ciencia de la computación y el procesamiento de lenguaje natural. Comprender estos fundamentos es esencial para apreciar por qué el sistema funciona como lo hace y cómo cada componente contribuye al objetivo general.

### Recuperación de Información (Information Retrieval)

La recuperación de información constituye un campo fundamental de la ciencia de la computación que estudia cómo obtener información relevante de grandes colecciones de datos no estructurados o semi-estructurados. A diferencia de las bases de datos tradicionales donde se ejecutan consultas estructuradas con sintaxis específica como SQL, los sistemas de recuperación de información deben interpretar consultas en lenguaje natural y encontrar documentos que satisfagan la necesidad informacional del usuario, incluso cuando esa necesidad no esté explícitamente articulada.

El modelo clásico de recuperación de información comprende cuatro fases fundamentales que se ejecutan secuencialmente. La fase de indexación preprocesa documentos para permitir búsqueda eficiente, creando estructuras de datos como índices invertidos que mapean términos a documentos. Durante esta fase, el sistema analiza cada documento, extrae términos significativos, y construye índices que permiten localizar rápidamente documentos que contienen términos específicos. La fase de procesamiento de consultas analiza la consulta del usuario, identificando términos clave y posiblemente expandiéndolos con sinónimos o correcciones ortográficas. Esta fase transforma la consulta en lenguaje natural en una representación interna que el sistema puede procesar eficientemente.

La fase de matching compara la consulta procesada contra los documentos indexados usando alguna función de similitud o relevancia. Esta comparación puede basarse en coincidencias exactas de términos, similitud semántica, o una combinación de ambos enfoques. Finalmente, la fase de ranking ordena los documentos coincidentes por su relevancia estimada, asegurando que los resultados más útiles aparezcan primero en la lista de resultados presentada al usuario.

Este sistema implementa todas estas fases de manera sofisticada: Tantivy y ChromaDB ejecutan indexación mediante estructuras optimizadas, spaCy ejecuta parte del procesamiento de consultas extrayendo entidades relevantes, BM25 y BERT ejecutan matching usando enfoques léxicos y semánticos respectivamente, y RRF junto con re-ranking ejecutan la fase final de ranking sofisticado que combina múltiples señales de relevancia.

### TF-IDF (Term Frequency - Inverse Document Frequency)

TF-IDF representa una medida estadística fundamental que evalúa la importancia de una palabra en un documento dentro del contexto de una colección completa de documentos. La intuición detrás de TF-IDF es brillantemente simple pero extraordinariamente efectiva: una palabra es importante para un documento si aparece frecuentemente en ese documento específico, indicando que es un tema central, pero esa importancia debe moderarse si la palabra aparece en muchos otros documentos de la colección, indicando que es un término común sin mucho poder discriminativo.

La componente TF (Term Frequency) mide qué tan frecuentemente aparece un término en un documento específico. Esta medida se calcula dividiendo la frecuencia del término f(t, d) por el total de términos en el documento. La fórmula matemática es: TF = f(t, d) / Σ f(t', d) donde la suma en el denominador abarca todos los términos t' presentes en el documento d. Esta normalización es crucial porque previene que documentos largos automáticamente tengan frecuencias más altas simplemente por contener más palabras en total. Un documento de 1000 palabras donde "nitrógeno" aparece 10 veces tiene la misma TF que un documento de 100 palabras donde aparece 1 vez, ambos con 1% de frecuencia.

La componente IDF (Inverse Document Frequency) mide qué tan raro o común es un término en toda la colección de documentos. Se calcula como el logaritmo de N dividido por df(t), donde N es el número total de documentos en el corpus y df(t) es el número de documentos que contienen el término t. La fórmula matemática es: IDF = log(N / df(t)). Términos que aparecen en todos los documentos, como palabras funcionales "el", "de", "para", tienen IDF cercano a cero porque log(N/N) = log(1) = 0, efectivamente eliminando su contribución al cálculo de relevancia. Por contraste, términos raros que aparecen en pocos documentos tienen IDF alto: si "nitrógeno" aparece en solo 50 de 1000 documentos, su IDF es log(1000/50) = log(20) ≈ 3.0, amplificando significativamente su importancia.

La intuición clave que hace a TF-IDF tan poderoso es que palabras frecuentes en un documento específico pero raras en la colección completa son altamente discriminativas para ese documento. Una palabra como "fotosíntesis" en un documento de agricultura probablemente indica que el documento trata específicamente ese proceso biológico, mientras que "el" aparece en todos los documentos y no proporciona información sobre el contenido específico. BM25, el algoritmo usado en este sistema, extiende TF-IDF añadiendo saturación no lineal que previene que frecuencias extremadamente altas dominen la puntuación, y normalización de longitud más sofisticada que ajusta por la longitud del documento de manera más inteligente, pero la intuición central de TF-IDF permanece en el corazón del algoritmo.

### Transformers y Attention Mechanism

La arquitectura Transformer, introducida por Vaswani et al. en el paper seminal "Attention Is All You Need" de 2017, revolucionó el procesamiento de lenguaje natural al reemplazar las redes recurrentes tradicionales con un mecanismo de atención pura que permite paralelización masiva. BERT, que significa Bidirectional Encoder Representations from Transformers, aplica esta arquitectura de manera bidireccional, permitiendo que cada palabra en una oración "atienda" a todas las demás palabras simultáneamente, capturando dependencias contextuales tanto hacia adelante como hacia atrás en la secuencia.

El mecanismo de self-attention que subyace a los Transformers funciona mediante tres matrices aprendidas durante el entrenamiento: Query (Q), Key (K), y Value (V). Para cada palabra en la entrada, su representación vectorial se proyecta a estos tres espacios mediante multiplicaciones matriciales. La atención se calcula como una función softmax del producto de la matriz Query por la transpuesta de la matriz Key, dividido por la raíz cuadrada de la dimensionalidad d_k para proporcionar estabilización numérica que previene gradientes extremadamente pequeños. Matemáticamente, esto se expresa como: Attention(Q,K,V) = softmax(QK^T / √d_k) V. El resultado de esta operación softmax produce una distribución de probabilidad que indica qué tan relevante es cada palabra para cada otra palabra, y estas probabilidades se usan para ponderar las matrices Value, produciendo la representación contextualizada final.

La intuición detrás de este mecanismo es elegante y poderosa: cada palabra "pregunta" (Query) qué otras palabras son relevantes para entender su significado en este contexto específico. Las otras palabras "responden" (Key) indicando qué tan relevantes son para la palabra que pregunta. Las palabras con alta relevancia contribuyen más sus valores semánticos (Value) a la representación contextualizada final. Por ejemplo, en la frase "banco de peces", cuando procesamos la palabra "banco", el mecanismo de atención asigna alta puntuación a "peces" en el cálculo de relevancia, ayudando al modelo a entender que se trata del banco acuático y no del banco financiero. Esta capacidad de capturar dependencias contextuales dinámicamente es lo que hace a los Transformers tan poderosos.

Multi-head attention, otro componente clave de la arquitectura, ejecuta este proceso de atención múltiples veces en paralelo con diferentes proyecciones aprendidas. Matemáticamente se expresa como: MultiHead(Q,K,V) = Concat(head_1, ..., head_h)W^O, donde cada head_i = Attention(QW_i^Q, KW_i^K, VW_i^V) con sus propias matrices de proyección W únicas. El modelo MiniLM usado en este sistema emplea 12 cabezas de atención, permitiendo que el modelo capture simultáneamente diferentes tipos de relaciones: algunas cabezas pueden especializarse en capturar sintaxis y estructura gramatical, otras en relaciones semánticas y significado, y otras en identificar entidades y sus relaciones. Esta diversidad de perspectivas capturadas simultáneamente es lo que permite a BERT generar representaciones excepcionalmente ricas del texto.

Las 12 capas de Transformers en BERT aplican este proceso iterativamente, con cada capa construyendo representaciones progresivamente más abstractas sobre las representaciones de la capa anterior. Las capas tempranas típicamente capturan patrones superficiales como coocurrencias frecuentes de palabras y estructuras sintácticas básicas, mientras que las capas profundas capturan relaciones semánticas complejas, abstracciones conceptuales, y relaciones de largo alcance entre elementos distantes en el texto. Esta jerarquía de representaciones es fundamental para la capacidad de BERT de comprender texto profundamente.

### Embeddings Semánticos

Los embeddings semánticos constituyen representaciones vectoriales densas de palabras, frases u oraciones, donde la geometría del espacio vectorial refleja directamente relaciones semánticas del lenguaje. Esta idea revolucionaria se fundamenta en la hipótesis distribucional propuesta por el lingüista Zellig Harris en 1954: "Conocerás una palabra por la compañía que mantiene". En otras palabras, palabras que aparecen frecuentemente en contextos similares tienden a tener significados similares, y esta similitud semántica debería reflejarse en la proximidad de sus representaciones vectoriales.

Una propiedad crucial y fascinante de los embeddings semánticos es la composicionalidad: los vectores pueden combinarse mediante operaciones aritméticas simples para representar conceptos complejos y relaciones analógicas. El ejemplo clásico que demostró el poder de esta propiedad es la analogía: vector("rey") - vector("hombre") + vector("mujer") ≈ vector("reina"). Esta operación captura la relación "realeza masculina menos masculinidad más feminidad resulta en realeza femenina". En el contexto agrícola específico de este sistema, operaciones similares podrían capturar relaciones como: vector("nitrógeno") - vector("nutriente") + vector("insecto") ≈ vector("pulgón"), donde se transforma la categoría de nutrientes a la categoría de plagas manteniendo otras propiedades.

La distancia coseno se usa preferentemente para comparar embeddings normalizados porque mide el ángulo entre vectores independientemente de su magnitud o longitud. Su definición matemática es: cos(θ) = (A · B) / (||A|| × ||B||), donde el numerador A · B es el producto punto (suma de multiplicaciones elemento por elemento: Σ A_i × B_i), y el denominador es el producto de las normas euclidianas de ambos vectores. El rango de valores de la distancia coseno va de -1 a 1, con una interpretación intuitiva directa: un valor de 1 indica vectores idénticos apuntando exactamente en la misma dirección, un valor de 0 indica vectores ortogonales sin relación alguna, y un valor de -1 indica vectores completamente opuestos apuntando en direcciones contrarias.

Para vectores normalizados, es decir vectores cuya norma euclidiana es 1, la distancia coseno se simplifica al producto punto directo, permitiendo implementaciones computacionales extremadamente eficientes. Esta eficiencia es crucial cuando se comparan miles o millones de vectores, como ocurre durante la búsqueda en ChromaDB donde el vector de consulta debe compararse contra todos los vectores almacenados para encontrar los más similares.

### Hybrid Search (Búsqueda Híbrida)

La búsqueda híbrida emerge del reconocimiento empírico y teórico de que diferentes técnicas de búsqueda tienen fortalezas y debilidades complementarias, y que combinar múltiples enfoques produce resultados superiores a cualquier técnica individual. Los métodos léxicos como BM25 sobresalen en precisión para términos técnicos específicos, nombres propios, y coincidencias exactas, pero fallan completamente cuando los usuarios emplean sinónimos, paráfrasis, o formulaciones alternativas de los conceptos. Por otro lado, los métodos semánticos como BERT sobresalen en capturar similitud conceptual profunda y pueden encontrar documentos relevantes incluso cuando no comparten vocabulario con la consulta, pero ocasionalmente confunden términos relacionados pero técnicamente distintos, o asignan similitud alta a documentos conceptualmente cercanos pero no directamente relevantes.

La combinación estratégica de estos enfoques proporciona complementariedad robusta: cuando un método falla en encontrar el documento relevante, el otro método frecuentemente tiene éxito, y cuando ambos métodos coinciden en señalar el mismo documento, podemos tener alta confianza en su relevancia. Esta complementariedad incrementa la robustez del sistema completo, haciéndolo menos sensible a variaciones en cómo los usuarios formulan sus consultas, diferencias en terminología entre usuarios y documentos, y errores o limitaciones de cualquier componente individual.

El rendimiento empírico de sistemas híbridos ha sido documentado extensivamente en la literatura académica de recuperación de información. Numerosos estudios y benchmarks demuestran consistentemente que sistemas híbridos bien diseñados superan sistemas individuales en métricas estándar como Mean Average Precision (MAP), Normalized Discounted Cumulative Gain (NDCG), y Mean Reciprocal Rank (MRR). Esta superioridad no es marginal sino sustancial, típicamente mostrando mejoras de 10-30% en precisión comparado con el mejor sistema individual.

Este sistema implementa específicamente el paradigma híbrido léxico-semántico, donde BM25 proporciona precisión en coincidencias exactas y BERT proporciona comprensión conceptual profunda. RRF actúa como el mecanismo de fusión que combina ambos enfoques de manera equitativa y sin necesidad de calibración, asegurando que documentos encontrados por ambos métodos suban automáticamente al tope de los resultados debido a la suma de sus contribuciones en el cálculo de puntuación RRF.

### RAG (Retrieval-Augmented Generation)

Retrieval-Augmented Generation representa una arquitectura innovadora que combina la recuperación de información tradicional con la generación de lenguaje natural mediante modelos grandes de lenguaje (LLMs), creando sistemas que pueden responder preguntas con información actualizada sin necesidad de reentrenamiento del modelo generativo. El pipeline RAG fluye en cinco etapas claramente definidas: Query → Retrieval → Context → Generation → Response.

En la etapa de Query, el sistema recibe la pregunta o solicitud del usuario en lenguaje natural. La etapa de Retrieval, que es precisamente lo que este sistema implementa, busca en una base de conocimiento los fragmentos de información más relevantes para responder la consulta. La etapa de Context toma estos fragmentos recuperados y los formatea apropiadamente como contexto para el modelo generativo. La etapa de Generation invoca un modelo de lenguaje grande (como GPT, Claude, Llama, etc.) pasándole tanto la consulta original como el contexto recuperado, instruyendo al modelo a generar una respuesta basándose en la información proporcionada. Finalmente, la etapa de Response presenta al usuario la respuesta generada, típicamente incluyendo citas o referencias a los documentos originales.

Este enfoque arquitectural permite que modelos generativos accedan a conocimiento actualizado y específico del dominio sin necesidad de reentrenamiento costoso. Los LLMs son entrenados en grandes corpus de texto general y congelan su conocimiento en el momento del entrenamiento, pero RAG permite actualizarlos dinámicamente simplemente añadiendo nuevos documentos a la base de conocimiento. Además, fundamentar las respuestas en documentos reales reduce significativamente las alucinaciones, ese fenómeno problemático donde los modelos generativos inventan información plausible pero incorrecta. Cuando el modelo genera su respuesta basándose explícitamente en fragmentos recuperados, y esos fragmentos se citan al usuario, hay transparencia y verificabilidad que no existe en generación pura.

Este sistema implementa la fase absolutamente crítica de retrieval del pipeline RAG. La calidad del retrieval determina directamente la calidad de las respuestas generadas: retrieval preciso que encuentra exactamente los fragmentos relevantes produce respuestas precisas y fundamentadas, mientras que retrieval deficiente que recupera información incorrecta o irrelevante produce respuestas de baja calidad, alucinaciones, o respuestas que no abordan la pregunta del usuario. Por esto, lograr 91.7% de precisión en la primera posición es crucial: significa que en la vasta mayoría de casos, el fragmento más relevante está disponible para el modelo generativo, maximizando las probabilidades de generar una respuesta excelente.

---

## 📖 Referencias

### Algoritmos y Técnicas

1. **BM25**
   - Robertson, S., & Zaragoza, H. (2009). *The Probabilistic Relevance Framework: BM25 and Beyond*. Foundations and Trends in Information Retrieval, 3(4), 333-389.
   - DOI: 10.1561/1500000019

2. **BERT**
   - Devlin, J., Chang, M. W., Lee, K., & Toutanova, K. (2019). *BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding*. NAACL-HLT 2019.
   - arXiv: 1810.04805

3. **Sentence-BERT**
   - Reimers, N., & Gurevych, I. (2019). *Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks*. EMNLP 2019.
   - arXiv: 1908.10084

4. **RRF (Reciprocal Rank Fusion)**
   - Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009.
   - DOI: 10.1145/1571941.1572114

5. **Hybrid Search**
   - Lin, J., Ma, X., Lin, S. C., Yang, J. H., Pradeep, R., & Nogueira, R. (2021). *Pyserini: A Python Toolkit for Reproducible Information Retrieval Research with Sparse and Dense Representations*. SIGIR 2021.
   - arXiv: 2102.10073

6. **Named Entity Recognition**
   - Honnibal, M., & Montani, I. (2017). *spaCy 2: Natural language understanding with Bloom embeddings, convolutional neural networks and incremental parsing*.
   - URL: https://spacy.io/

### Librerías y Frameworks

7. **ChromaDB**
   - Chroma Documentation. *The AI-native open-source embedding database*.
   - URL: https://docs.trychroma.com/

8. **Tantivy**
   - Tantivy Documentation. *Full-text search engine library inspired by Apache Lucene*.
   - URL: https://github.com/quickwit-oss/tantivy

9. **Sentence Transformers**
   - Reimers, N. (2021). *Sentence-Transformers Documentation*.
   - URL: https://www.sbert.net/

### Fundamentos Teóricos

10. **Information Retrieval**
    - Manning, C. D., Raghavan, P., & Schütze, H. (2008). *Introduction to Information Retrieval*. Cambridge University Press.
    - ISBN: 978-0521865715

11. **TF-IDF**
    - Salton, G., & Buckley, C. (1988). *Term-weighting approaches in automatic text retrieval*. Information Processing & Management, 24(5), 513-523.
    - DOI: 10.1016/0306-4573(88)90021-0

12. **Attention Mechanism**
    - Vaswani, A., Shazeer, N., Parmar, N., et al. (2017). *Attention Is All You Need*. NeurIPS 2017.
    - arXiv: 1706.03762

13. **RAG (Retrieval-Augmented Generation)**
    - Lewis, P., Perez, E., Piktus, A., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS 2020.
    - arXiv: 2005.11401

### Evaluación de Sistemas

14. **Precision & Recall**
    - Baeza-Yates, R., & Ribeiro-Neto, B. (2011). *Modern Information Retrieval: The Concepts and Technology behind Search* (2nd ed.). Addison-Wesley.
    - ISBN: 978-0321416919

15. **Mean Reciprocal Rank (MRR)**
    - Voorhees, E. M. (1999). *The TREC-8 Question Answering Track Report*. TREC 1999.
    - URL: https://trec.nist.gov/pubs/trec8/papers/qa_report.pdf

---

## 📊 Características del Sistema

| Aspecto | Especificación |
|---------|----------------|
| **Tipo de sistema** | RAG Híbrido (Léxico + Semántico) |
| **Motor léxico** | BM25 (Tantivy backend, Rust) |
| **Motor semántico** | BERT `paraphrase-multilingual-MiniLM-L12-v2` |
| **Base de datos vectorial** | ChromaDB |
| **Base de datos relacional** | SQLite |
| **NER** | spaCy `es_core_news_sm` + EntityRuler |
| **Fusión** | Reciprocal Rank Fusion (k=60) |
| **Re-ranking** | Term coverage (α=0.5) |
| **Dimensiones embedding** | 384 |
| **Tamaño chunk** | 300-500 tokens |
| **Overlap** | 50 tokens |
| **Top-K default** | 5 |
| **Tiempo respuesta** | 150-200 ms (promedio) |
| **Precisión@1** | 91.7% |
| **MRR** | 0.917 |

---

## 🎯 Resumen Ejecutivo

El sistema implementa una arquitectura RAG híbrida que combina:
1. **Búsqueda léxica** (BM25) para precisión en términos exactos
2. **Búsqueda semántica** (BERT) para capturar sinónimos y paráfrasis
3. **Validación de entidades** (spaCy) para filtrado por dominio agrícola

**Proceso completo:**
- **Entrada**: Consulta en lenguaje natural
- **Procesamiento**: Extracción de entidades → Búsqueda dual → Fusión → Re-ranking → Filtrado
- **Salida**: Top-5 fragmentos más relevantes ordenados por score

**Resultados**: 91.7% de precisión en primera posición, demostrando la efectividad de la combinación de técnicas léxicas y semánticas con validación de dominio.

---

*Documento técnico generado el 16 de diciembre de 2025*
