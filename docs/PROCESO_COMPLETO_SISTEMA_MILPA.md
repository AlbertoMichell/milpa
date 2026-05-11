# Proceso Completo del Sistema MILPA AI
## Documentación Paso a Paso del Flujo de Datos

Este documento describe de forma detallada y secuencial todos los procesos que ocurren en el sistema MILPA AI, desde que un usuario carga un documento hasta que obtiene respuestas a sus preguntas o visualiza la biblioteca de documentos.

---

## PARTE 1: INGESTA DE DOCUMENTOS (Carga y Procesamiento)

### Paso 1: El Usuario Selecciona un Archivo para Subir

El proceso comienza cuando un usuario accede a la interfaz web del sistema MILPA y decide cargar un documento nuevo. El usuario puede subir archivos en tres formatos: PDF, DOCX (documentos de Word) o TXT (archivos de texto plano). Al seleccionar el archivo desde su computadora, el navegador prepara el documento junto con información adicional que el usuario puede proporcionar, como el título del documento, el nombre del autor, el año de publicación, el tipo de licencia del contenido y si el documento es público, interno o restringido.

**Decisión:** El sistema verifica el tipo de archivo. Si el archivo es PDF, DOCX o TXT, el proceso continúa al Paso 2. Si el archivo tiene un formato diferente (por ejemplo, una imagen JPG o un archivo Excel), el sistema rechaza la carga y muestra un mensaje de error indicando que ese tipo de archivo no está permitido.

---

### Paso 2: Validación Inicial del Archivo

Una vez que el archivo llega al servidor del Presenter (el componente que actúa como intermediario entre la interfaz de usuario y el motor de inteligencia artificial), se realiza una primera validación. El sistema verifica que el tipo de contenido del archivo coincida con los formatos permitidos. También comprueba que el tamaño del archivo no exceda el límite configurado, que por defecto es de 50 megabytes.

**Decisión:** Si el archivo pasa las validaciones de tipo y tamaño, el proceso continúa al Paso 3. Si el archivo es demasiado grande, el sistema responde con un error indicando que el archivo excede el límite permitido. Si el tipo de archivo no es reconocido, el sistema responde indicando que el formato no está soportado.

---

### Paso 3: Reenvío al Backend de Inteligencia Artificial

El Presenter actúa como un puente inteligente. No procesa el documento directamente, sino que lo reenvía al Backend de IA (el motor principal del sistema) que se encuentra en otro servicio. El Presenter construye una solicitud HTTP hacia la dirección del backend (típicamente `http://milpa_ai:8000/api/documents/upload`) e incluye el archivo junto con todos los metadatos proporcionados por el usuario.

Durante esta transferencia, el Presenter aplica controles de concurrencia para evitar sobrecargar el backend. Si hay muchas solicitudes simultáneas, las nuevas peticiones se encolan ordenadamente. El sistema también tiene un "circuito de protección" que, si detecta que el backend está fallando repetidamente, deja de enviar solicitudes temporalmente para darle tiempo de recuperarse.

**Decisión:** Si el backend está disponible y responde correctamente, el proceso continúa al Paso 4. Si el backend no responde en un tiempo razonable (30 segundos por defecto), el Presenter informa al usuario que el servicio está temporalmente no disponible.

---

### Paso 4: Persistencia del Archivo Original

El backend de IA recibe el archivo y lo primero que hace es guardarlo en el sistema de archivos del servidor. El archivo se almacena en una carpeta llamada `data/documents/` con un nombre especial que incluye un número basado en el momento exacto de la carga (una "marca de tiempo") seguido del nombre original del archivo. Por ejemplo, si subes un archivo llamado "manual_maiz.pdf" a las 10:30:15 del 7 de diciembre de 2025, el archivo se guardará como algo similar a `1733571015__manual_maiz.pdf`.

El sistema también calcula un código único llamado "hash SHA-256" que funciona como una huella digital del archivo. Este código es una cadena de 64 caracteres que identifica de manera única el contenido exacto del archivo. Si alguien sube el mismo archivo dos veces, el hash será idéntico, lo que permite detectar duplicados.

**Decisión:** Una vez que el archivo está guardado y el hash calculado, el proceso continúa al Paso 5.

---

### Paso 5: Escaneo de Seguridad con Antivirus

Antes de procesar cualquier contenido, el sistema realiza un escaneo de seguridad utilizando ClamAV, un antivirus de código abierto que se ejecuta en un contenedor separado. El escaneo se realiza de dos formas diferentes para mayor seguridad: primero se escanea el archivo por su ruta en disco, y luego se envía el contenido completo al antivirus para un análisis en memoria.

El antivirus compara el archivo contra una base de datos de firmas de malware conocido. Si detecta algo sospechoso, identifica el tipo de amenaza y genera una alerta.

**Decisión:** Si el antivirus no encuentra ninguna amenaza, el proceso continúa al Paso 6. Si el antivirus detecta malware o contenido sospechoso, el sistema rechaza el archivo inmediatamente, elimina la copia guardada y responde al usuario con un mensaje indicando que el archivo fue rechazado por razones de seguridad, sin procesar ningún contenido.

---

### Paso 6: Registro en la Base de Datos

Con el archivo verificado como seguro, el sistema procede a registrar la información del documento en la base de datos SQLite. Se insertan dos registros principales: uno en la tabla `docs` con todos los metadatos del documento (identificador único basado en el hash, título, autor, año, nombre del archivo fuente, tipo de licencia, clasificación de acceso, ruta donde se guardó el archivo, y fecha de creación), y otro en la tabla `licenses` que guarda específicamente la información de licenciamiento.

El identificador del documento (`doc_id`) es el mismo hash SHA-256 calculado anteriormente, lo que garantiza que cada documento tenga un identificador único y que subir el mismo archivo simplemente actualice el registro existente en lugar de crear duplicados.

**Decisión:** Una vez registrado el documento, el sistema confirma al usuario que la carga fue exitosa y devuelve el identificador del documento junto con los metadatos guardados. El documento ahora está listo para ser procesado, lo cual ocurre en el Paso 7.

---

### Paso 7: Extracción de Contenido del Documento

El usuario o el sistema puede solicitar la extracción del contenido del documento mediante el endpoint `/api/documents/{doc_id}/extract`. Este proceso lee el archivo físico y extrae todo el texto que contiene. La forma de extraer el texto depende del tipo de archivo.

Para archivos PDF, el sistema utiliza una biblioteca llamada PyMuPDF (también conocida como fitz) que puede leer el contenido de cada página del PDF. Por cada página, el sistema intenta obtener el texto "nativo", es decir, el texto que está codificado digitalmente dentro del PDF y que puede seleccionarse con el ratón.

Para archivos DOCX, el sistema utiliza otra biblioteca que entiende el formato de Word y extrae párrafos, encabezados y tablas preservando la estructura del documento.

Para archivos TXT, simplemente se lee el contenido como texto plano, asegurándose de manejar correctamente la codificación de caracteres (normalmente UTF-8).

**Decisión:** Después de intentar la extracción de texto nativo de cada página, el sistema evalúa si obtuvo suficiente contenido. Si una página tiene menos de 40 caracteres de texto útil, el sistema sospecha que podría ser una página escaneada o una imagen, lo cual requiere un tratamiento especial en el Paso 8. Si la página tiene suficiente texto, salta directamente al Paso 9.

---

### Paso 8: Aplicación de OCR para Páginas sin Texto

Cuando el sistema detecta que una página tiene muy poco texto (probablemente porque es una imagen escaneada de un documento físico), activa el sistema de Reconocimiento Óptico de Caracteres (OCR). Este proceso convierte la imagen de la página en texto legible por computadora.

El sistema utiliza Tesseract, un motor de OCR de código abierto desarrollado originalmente por HP y actualmente mantenido por Google. El proceso funciona así: primero, el sistema renderiza la página del PDF como una imagen de alta resolución (300 DPI, que significa 300 puntos por pulgada), creando una imagen clara y nítida. Luego, esta imagen se envía a Tesseract configurado para reconocer texto en español e inglés simultáneamente (`spa+eng`).

Tesseract analiza la imagen buscando patrones que correspondan a letras, números y símbolos. Por cada palabra que reconoce, también calcula un nivel de confianza que indica qué tan seguro está de que la lectura es correcta. El sistema promedia estos niveles de confianza para generar un indicador de calidad del OCR: un valor cercano a 1.0 indica alta confianza, mientras que valores bajos indican que el texto podría tener errores.

**Decisión:** Si el OCR se ejecuta exitosamente, el texto extraído reemplaza al texto nativo vacío o escaso, y el fragmento se marca con origen "ocr" en lugar de "native". Si el OCR falla por alguna razón técnica, el sistema conserva el texto nativo original (aunque sea escaso) y continúa el proceso.

---

### Paso 9: Fragmentación del Texto (Chunking)

El texto completo de un documento puede ser muy largo, y los modelos de inteligencia artificial tienen límites en la cantidad de texto que pueden procesar de una vez. Por eso, el sistema divide el texto en fragmentos más pequeños llamados "chunks" o fragmentos.

El proceso de fragmentación intenta ser inteligente: en lugar de cortar el texto en puntos arbitrarios, busca divisiones naturales como cambios de párrafo (detectados por dobles saltos de línea `\n\n`). El tamaño objetivo por defecto es de aproximadamente 1200 caracteres por fragmento. Si un párrafo es más largo que este límite, el sistema lo subdivide por palabras para no cortar palabras a la mitad.

Para documentos técnicos con ecuaciones o fórmulas matemáticas, el sistema tiene un mecanismo especial de protección: antes de fragmentar, identifica expresiones matemáticas (como ecuaciones en formato LaTeX `$...$` o `\[...\]`, o símbolos matemáticos especiales como ∑, √, ≈) y las reemplaza temporalmente por marcadores especiales del tipo `⟦EQN_abc123⟧`. Después de fragmentar, restaura las ecuaciones originales en cada fragmento para asegurar que las fórmulas no queden cortadas por la mitad.

También se aplica una normalización básica de unidades de medida mediante expresiones regulares: expresiones como "kg / ha" se convierten a la forma canónica "kg/ha", "l / ha" se convierte a "L/ha", y "° C" se convierte a "°C" para consistencia.

**Decisión:** Una vez que el texto está fragmentado, cada fragmento continúa al Paso 10 para enriquecimiento con entidades.

---

### Paso 9.5: Traducción de Texto (Opcional - Si el documento no está en español)

**Nota importante sobre el orden lógico:** Aunque el código actual no invoca la traducción automáticamente, si estuviera habilitada, la traducción **debería ocurrir ANTES de la fragmentación** (entre los Pasos 8 y 9), no después. Esto es porque los modelos de traducción funcionan mejor con contexto completo, mantienen mayor coherencia terminológica, y la memoria de traducción puede aplicarse efectivamente a párrafos completos. Sin embargo, para efectos de la documentación, se describe aquí como Paso 9.5 para mantener la numeración secuencial.

El sistema MILPA tiene la capacidad de traducir automáticamente textos que no están en español, aunque esta funcionalidad está configurada como **opcional** y no se activa por defecto en el MVP actual.

Si estuviera habilitada, la traducción funcionaría así (aplicándose al texto completo de cada página ANTES del chunking):

**Detección de idioma:** Primero, el sistema usa la biblioteca `langdetect` (o alternativamente FastText) para determinar en qué idioma está escrito el texto. La función `detect_lang(text)` analiza el texto y devuelve un código de idioma (por ejemplo, "en" para inglés, "es" para español, "pt" para portugués) junto con un nivel de confianza.

**Decisión:** Si el idioma detectado es español ("es"), el texto no necesita traducción y continúa directamente al Paso 10. Si el idioma es diferente (inglés, portugués, francés, etc.), el sistema procede con la traducción.

**Protección de términos que no deben traducirse:** Antes de traducir, el sistema carga un glosario desde el archivo `models/glossary/{version}/glossary.csv` que contiene términos técnicos marcados como "do_not_translate" (no traducir). Esto incluye nombres científicos ("Zea mays"), unidades de medida ("kg/ha", "ppm"), y abreviaturas técnicas. Estos términos se reemplazan temporalmente por marcadores especiales `⟦DNT_0⟧`, `⟦DNT_1⟧`, etc., para que el traductor no los modifique.

**Búsqueda en memoria de traducción:** El sistema verifica si existe una traducción previa del mismo texto en la memoria de traducción (`translation_memory.jsonl`). Si encuentra una coincidencia exacta basada en el hash del contexto, usa la traducción guardada en lugar de volver a traducir, lo que ahorra tiempo y garantiza consistencia.

**Traducción con modelo de IA:** Si no hay traducción en memoria, el sistema usa un modelo de traducción de la familia Transformers de Hugging Face. Por defecto está configurado para usar `Helsinki-NLP/opus-mt-mul-es` (traducción multilingüe a español), aunque puede configurarse para usar otros modelos como M2M100 o NLLB. El modelo se ejecuta localmente, sin enviar datos a servidores externos.

**Restauración de términos protegidos:** Después de la traducción, el sistema reemplaza los marcadores `⟦DNT_X⟧` por los términos originales que no debían traducirse.

**Post-procesado con glosario:** Finalmente, el sistema aplica el glosario para asegurar que ciertos términos queden en su forma canónica en español. Por ejemplo, si el traductor escribió "nitrogen" (que no se tradujo bien), el glosario lo reemplaza por "nitrógeno".

**Métricas de calidad:** El sistema calcula un "Consistency Score" que mide qué porcentaje de los términos del glosario aparecen correctamente en el texto traducido. Esto permite detectar traducciones de baja calidad.

**Nota sobre el estado actual:** En la implementación actual del MVP, la traducción está implementada pero **no se invoca automáticamente** durante la ingesta. Los documentos se procesan asumiendo que están en español. Para activar la traducción automática, se necesitaría modificar el flujo de extracción para llamar a `translate_to_es()` sobre el texto completo de cada página ANTES de la fragmentación (entre los pasos de OCR y chunking).

**Decisión:** Una vez traducido el texto completo de la página (o si el texto ya estaba en español), el proceso continúa al Paso 9 para fragmentar el texto, y luego al Paso 10 para enriquecimiento con entidades.

---

### Paso 10: Extracción de Entidades (NER - Named Entity Recognition)

Cada fragmento de texto pasa por un proceso de análisis inteligente que identifica menciones de conceptos importantes para el dominio agrícola. Este proceso se llama Reconocimiento de Entidades Nombradas (NER por sus siglas en inglés).

**Importante: El sistema NER NO viene preentrenado con inteligencia artificial para agricultura.** En lugar de usar un modelo de machine learning entrenado con millones de textos agrícolas, MILPA utiliza un enfoque basado en diccionarios y taxonomías curadas manualmente. Esto significa que el sistema solo reconoce los términos que están explícitamente listados en los archivos de taxonomía, no "aprende" ni "infiere" nuevos conceptos por sí solo.

**Origen de las taxonomías:** Los catálogos de términos agrícolas fueron elaborados mediante un proceso de investigación y análisis del dominio agronómico mexicano. El equipo de desarrollo realizó una revisión de literatura técnica agrícola, manuales de extensionismo rural, guías de fertilización de instituciones como INIFAP (Instituto Nacional de Investigaciones Forestales, Agrícolas y Pecuarias), y documentación técnica de SAGARPA/SADER. A partir de este análisis, se identificaron los términos más frecuentes y relevantes para el contexto de recomendaciones agrícolas en México, organizándolos en categorías semánticas específicas. Los sinónimos y variantes regionales se recopilaron considerando tanto la nomenclatura científica internacional como los nombres comunes utilizados en diferentes regiones del país.

Las taxonomías resultantes son archivos CSV simples ubicados en la carpeta `models/taxonomy/2025.09.10/` (la fecha indica la versión del catálogo). Cada archivo contiene una lista de términos validados por el análisis:

- **crops.csv** - Catálogo de cultivos prioritarios: maíz, frijol, calabaza (la milpa tradicional), trigo, tomate, entre otros cultivos de importancia agrícola nacional.
- **pests.csv** - Catálogo de plagas y enfermedades: gusano cogollero, pulgón, roya, minador, mosca blanca, y otras amenazas fitosanitarias documentadas.
- **nutrients.csv** - Catálogo de nutrientes y elementos: nitrógeno (N), fósforo (P), potasio (K), y sus variantes de nomenclatura.
- **phenology.csv** - Catálogo de etapas fenológicas: germinación, macollaje, floración, llenado de grano, cosecha, siguiendo la terminología estándar de agronomía.
- **regions.csv** - Catálogo de regiones agrícolas mexicanas: estados productores como Oaxaca, Puebla, Veracruz, Jalisco, Guanajuato.

Además existe un archivo **synonyms.json** que mapea variantes ortográficas, nombres científicos y términos en inglés hacia el término canónico en español. Este diccionario de sinónimos fue construido para manejar la diversidad de formas en que un mismo concepto puede aparecer en la literatura técnica:
```json
{
  "zea mays": "maiz",
  "nitrogen": "nitrógeno",
  "macollage": "macollaje",
  "roya amarilla": "roya"
}
```

Antes de buscar coincidencias, tanto el texto del fragmento como los términos de las taxonomías se normalizan usando la biblioteca `unidecode`: se convierten a minúsculas, se eliminan acentos (maíz se convierte en maiz), y se colapsan espacios múltiples. Esta normalización asegura que "Maíz", "MAIZ" y "maiz" coincidan correctamente.

La búsqueda de entidades funciona así: el sistema recorre cada término de cada taxonomía y usa expresiones regulares para buscarlo dentro del texto normalizado, respetando límites de palabra (el patrón `\bmaiz\b` coincide con "maiz" pero no con "maizal"). Por cada coincidencia encontrada, se crea un objeto Entity con cinco campos: el tipo de entidad (CULTIVO, PLAGA, NUTRIENTE, FENOFASE o LUGAR), el valor canónico normalizado, el texto original tal como apareció, y las posiciones de inicio y fin donde se encontró en el texto.

Si el sistema tiene instalada la biblioteca spaCy con el modelo de español (`es_core_news_md` o `es_core_news_sm`), puede complementar el análisis por diccionario añadiendo un EntityRuler que busca los mismos patrones pero aprovechando el análisis lingüístico de spaCy. Sin embargo, esto es opcional y el sistema funciona correctamente solo con diccionarios.

**Decisión:** Las entidades extraídas se serializan como una cadena JSON para almacenamiento. El formato es una lista de objetos donde cada objeto tiene dos campos: `type` (el tipo de entidad) y `value` (el valor canónico). Por ejemplo:
```json
[{"type":"CULTIVO","value":"maiz"},{"type":"NUTRIENTE","value":"nitrogeno"},{"type":"FENOFASE","value":"macollaje"}]
```
Esta cadena JSON se prepara para guardarse en la base de datos junto con el fragmento.

---

### Paso 11: Persistencia de Fragmentos en SQLite

Cada fragmento procesado se guarda en la base de datos SQLite en la tabla `fragments`. La inserción se realiza mediante una sentencia SQL que incluye los siguientes campos:

```sql
INSERT INTO fragments
(fragment_id, doc_id, fragment_uid, section_id, page_start, page_end, text, text_es, source, entities, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'));
```

Cada campo tiene un propósito específico:
- **fragment_id**: Un identificador único de 32 caracteres hexadecimales generado con `uuid.uuid4().hex`. Por ejemplo: `"a1b2c3d4e5f67890a1b2c3d4e5f67890"`
- **doc_id**: El hash SHA-256 del documento padre, que vincula el fragmento con su documento original
- **fragment_uid**: Un identificador alternativo (puede ser nulo)
- **section_id**: Identificador de sección dentro del documento (puede ser nulo)
- **page_start**: El número de página donde comienza el fragmento (entero, ej: 1, 2, 3)
- **page_end**: El número de página donde termina el fragmento (igual a page_start para fragmentos de una sola página)
- **text**: El texto completo del fragmento tal como se extrajo
- **text_es**: El texto traducido al español (si aplica traducción, de lo contrario es nulo)
- **source**: Una cadena que indica el origen: `"native"` si se extrajo directamente del PDF, o `"ocr"` si se procesó con Tesseract
- **entities**: La cadena JSON con las entidades extraídas. Por ejemplo: `"[{\"type\":\"CULTIVO\",\"value\":\"maiz\"}]"`
- **created_at**: La fecha y hora de creación en formato SQLite: `"2025-12-07 15:30:45"`

El código que realiza esta inserción primero genera el identificador único, luego extrae las entidades del texto llamando a `extract_entities(text)`, serializa la lista de entidades a JSON con `json.dumps(entities_list)`, y finalmente ejecuta la sentencia SQL con todos los valores.

Este almacenamiento permite que el sistema pueda recuperar los fragmentos posteriormente para búsquedas, para mostrarlos en la biblioteca, o para reconstruir los índices de búsqueda.

**Decisión:** Una vez guardados todos los fragmentos de todas las páginas, el sistema continúa al Paso 12 para verificar si hay tablas que extraer. Tanto los fragmentos como las tablas se confirman en la base de datos dentro de la misma transacción.

---

### Paso 12: Extracción de Tablas (Opcional)

Después de procesar e insertar los fragmentos de texto, el sistema verifica si el documento contiene tablas que deban ser extraídas. Si el documento es un PDF y la opción de extracción de tablas está habilitada, el sistema utiliza Camelot, una biblioteca especializada en detectar y extraer tablas de documentos PDF.

Camelot tiene dos modos de operación: "lattice" (enrejado), que funciona mejor con tablas que tienen líneas visibles dibujadas entre las celdas, y "stream" (flujo), que detecta tablas basándose en el espaciado del texto cuando no hay líneas visibles. Por defecto, el sistema intenta ambos modos para capturar el máximo de tablas posible.

Por cada tabla detectada, el sistema convierte el contenido a formato CSV (valores separados por comas), calcula estadísticas como el número de filas y columnas, y guarda toda esta información en la tabla `tables` de la base de datos. Opcionalmente, también puede guardar cada celda individual en una tabla `table_cells` para permitir búsquedas más granulares.

**Decisión:** Una vez procesadas todas las tablas (o si no había tablas que procesar), la fase de extracción se completa. El documento está ahora fragmentado, enriquecido con entidades y listo para ser indexado. Todos los cambios (fragmentos y tablas) se confirman en la base de datos mediante commit al finalizar la transacción.

---

## PARTE 2: INDEXACIÓN PARA BÚSQUEDA

### Paso 13: Reconstrucción de Índices

Después de que uno o varios documentos han sido procesados, el sistema necesita actualizar sus índices de búsqueda para que los nuevos fragmentos sean encontrables. Esto se hace llamando al endpoint `/api/index/rebuild` que reconstruye tanto el índice de búsqueda por palabras como el índice de búsqueda por similitud semántica.

El proceso comienza cargando todos los fragmentos desde la base de datos SQLite, incluyendo el texto, el identificador del documento padre, la fuente original del documento, y las entidades extraídas.

**Decisión:** Si no hay fragmentos en la base de datos, el proceso se detiene y devuelve un error. Si hay fragmentos disponibles, el proceso continúa al Paso 14.

---

### Paso 14: Indexación BM25 (Búsqueda por Palabras Clave)

El primer tipo de índice que se construye es el índice BM25, que permite buscar documentos por palabras clave de forma similar a como funciona un motor de búsqueda tradicional.

BM25 (Best Matching 25) es un algoritmo que calcula qué tan relevante es un documento para una consulta basándose en cuántas veces aparecen las palabras buscadas, qué tan raras son esas palabras en el conjunto completo de documentos (las palabras raras son más significativas), y la longitud del documento (los documentos muy largos no deberían tener ventaja injusta solo por ser más largos).

El sistema puede usar diferentes motores para este índice: Tantivy (una biblioteca de búsqueda muy rápida escrita en Rust), Whoosh (una biblioteca de búsqueda escrita en Python), o una implementación en memoria propia si las anteriores no están disponibles. El sistema detecta automáticamente qué opciones están instaladas y usa la mejor disponible.

Para cada fragmento, el sistema indexa el texto completo, el identificador del fragmento, el identificador del documento padre, y las etiquetas o categorías si las tiene. El índice se guarda en disco en la carpeta `data/bm25_index/` para persistir entre reinicios del servidor.

**Decisión:** Una vez construido el índice BM25, el proceso continúa al Paso 15 para construir el índice vectorial.

---

### Paso 15: Generación de Embeddings (Representaciones Vectoriales)

El segundo tipo de índice utiliza una técnica más avanzada llamada "embeddings" o "representaciones vectoriales". En lugar de buscar coincidencias exactas de palabras, este método convierte cada fragmento de texto en una lista de números (un "vector") que representa el significado del texto en un espacio matemático multidimensional.

El sistema utiliza un modelo de inteligencia artificial llamado "paraphrase-multilingual-MiniLM-L12-v2" de la familia Sentence Transformers. Este modelo fue entrenado con millones de pares de textos en múltiples idiomas para aprender a generar vectores donde textos con significados similares quedan matemáticamente cerca unos de otros.

El proceso funciona así: el modelo tiene un "tokenizador" que convierte cada texto en una secuencia de tokens (unidades básicas que el modelo entiende). Luego, una red neuronal profunda procesa estos tokens y produce un vector de 384 números que resume el significado del texto completo.

Por ejemplo, los textos "Aplicar nitrógeno en maíz durante la floración" y "Fertilización nitrogenada para maíz en fase de floración" generarían vectores muy similares porque hablan esencialmente de lo mismo, aunque usen palabras diferentes.

Si el modelo de Sentence Transformers no está disponible (por ejemplo, en entornos de prueba), el sistema tiene un modo "dummy" que genera vectores deterministas basados en el hash del texto. Estos vectores dummy no capturan significado real pero permiten que el sistema funcione para pruebas.

**Decisión:** Una vez generados los embeddings para todos los fragmentos, el proceso continúa al Paso 16 para guardarlos en la base de datos vectorial.

---

### Paso 16: Almacenamiento en ChromaDB (Base de Datos Vectorial)

Los embeddings generados se almacenan en ChromaDB, una base de datos especializada en almacenar y buscar vectores de alta dimensionalidad. ChromaDB permite encontrar rápidamente los vectores más similares a un vector de consulta usando algoritmos optimizados.

Por cada fragmento, se almacena el identificador del fragmento (que sirve como clave), el vector de 384 dimensiones generado por el modelo, y metadatos adicionales como el identificador del documento, la fuente, y las entidades extraídas serializadas como texto JSON.

ChromaDB utiliza internamente un algoritmo llamado HNSW (Hierarchical Navigable Small World) que organiza los vectores en una estructura de grafo que permite búsquedas eficientes incluso con millones de vectores.

Los datos se persisten en disco en la carpeta `data/vector_db/` para mantener el índice entre reinicios del servidor.

**Decisión:** Una vez completada la indexación vectorial, el sistema está listo para responder consultas. El proceso de indexación devuelve un resumen indicando cuántos fragmentos se indexaron en cada índice.

---

## PARTE 3: CONSULTAS RAG (Preguntas y Respuestas)

### Paso 17: El Usuario Formula una Pregunta

Cuando un usuario quiere obtener información del sistema, accede a la interfaz de consultas y escribe una pregunta en lenguaje natural, por ejemplo: "¿Cuál es la fertilización recomendada de nitrógeno para maíz en etapa de macollaje?"

La interfaz envía esta pregunta al Presenter, que a su vez la reenvía al Backend de IA al endpoint `/api/query`. La solicitud incluye la pregunta del usuario, el número de resultados deseados (por defecto 8), el modo de búsqueda (híbrido, solo vectorial, o solo por palabras clave), y opcionalmente filtros por categorías de contenido.

**Decisión:** Si la solicitud es válida y contiene una pregunta, el proceso continúa al Paso 18.

---

### Paso 18: Extracción de Entidades de la Consulta

Antes de buscar en los índices, el sistema analiza la pregunta del usuario usando el mismo proceso de extracción de entidades descrito en el Paso 10. Esto permite identificar qué conceptos agrícolas menciona el usuario: cultivos, nutrientes, plagas, fases fenológicas o regiones.

Para nuestro ejemplo ("fertilización de nitrógeno para maíz en macollaje"), el sistema identificaría: CULTIVO: "maiz", NUTRIENTE: "nitrogeno", FENOFASE: "macollaje".

Esta información es crucial para evaluar posteriormente si los fragmentos recuperados realmente hablan de los mismos temas que el usuario pregunta.

**Decisión:** Si la consulta no contiene ninguna entidad del dominio agrícola, el sistema podría determinar que la pregunta está fuera del alcance del sistema. Si contiene al menos una entidad relevante, el proceso continúa al Paso 19.

---

### Paso 19: Búsqueda Híbrida (BM25 + Vectorial)

El modo de búsqueda por defecto es "híbrido", que combina dos estrategias complementarias para encontrar los fragmentos más relevantes.

La búsqueda BM25 (Paso 19A) toma la pregunta del usuario y busca en el índice de palabras clave los fragmentos que contienen los términos de la consulta. Esta búsqueda es buena para encontrar coincidencias exactas de palabras específicas y términos técnicos. El sistema recupera los 100 mejores resultados según el algoritmo BM25, ordenados por relevancia.

La búsqueda vectorial (Paso 19B) convierte la pregunta del usuario en un embedding usando el mismo modelo que se usó para indexar los fragmentos. Luego, busca en ChromaDB los fragmentos cuyos vectores están más cerca del vector de la pregunta en el espacio multidimensional. Esta búsqueda es buena para encontrar fragmentos que hablan del mismo tema aunque usen palabras diferentes. El sistema recupera los 8 mejores resultados según similitud de coseno.

**Decisión:** Con los resultados de ambas búsquedas, el proceso continúa al Paso 20 para fusionarlos.

---

### Paso 20: Fusión de Resultados (Reciprocal Rank Fusion)

El sistema tiene ahora dos listas de resultados: una del BM25 y otra de la búsqueda vectorial. Para combinarlas de forma inteligente, utiliza un algoritmo llamado "Reciprocal Rank Fusion" (RRF).

RRF funciona así: por cada fragmento que aparece en cualquiera de las listas, calcula un puntaje basado en su posición. Un fragmento en la posición 1 recibe más puntos que uno en la posición 10. Si un fragmento aparece en ambas listas, sus puntos se suman, lo que significa que los fragmentos encontrados por ambos métodos reciben una bonificación.

La fórmula exacta es: para cada lista, el puntaje de un documento en posición r es 1/(K+r), donde K es una constante (por defecto 60). Los puntajes de todas las listas se suman para obtener el puntaje RRF final.

El resultado es una lista única de fragmentos ordenados por su puntaje RRF combinado, donde los fragmentos más relevantes según ambos métodos aparecen primero.

**Decisión:** Con la lista fusionada y ordenada, el proceso continúa al Paso 21 para evaluar si hay suficiente evidencia.

---

### Paso 21: Evaluación de Evidencia Suficiente

Antes de generar una respuesta, el sistema evalúa si los fragmentos recuperados realmente contienen información relevante para responder la pregunta. Este es un paso crucial para evitar que el sistema "alucine" respuestas cuando no tiene información suficiente.

El sistema aplica varios criterios de evaluación. Primero, verifica que haya un número mínimo de fragmentos con puntaje significativo (por defecto al menos 3). Fragmentos con puntajes muy bajos se filtran porque probablemente no son relevantes. Segundo, calcula la "cobertura de entidades": qué porcentaje de las entidades mencionadas en la pregunta del usuario también aparecen en las entidades de los fragmentos recuperados. Si la pregunta menciona "maíz" y "nitrógeno" pero los fragmentos solo hablan de "trigo" y "fósforo", la cobertura sería baja. Tercero, verifica que los fragmentos provengan de al menos una fuente documental (idealmente múltiples fuentes para mayor confiabilidad). Cuarto, verifica que el puntaje promedio de los fragmentos supere un umbral mínimo.

**Decisión:** Si los fragmentos pasan todos los criterios de evaluación, el proceso continúa al Paso 22 para generar la respuesta. Si los fragmentos no alcanzan los umbrales requeridos, el sistema determina que hay "evidencia insuficiente" y responde al usuario indicando que no encontró información suficiente para responder la pregunta, sin inventar contenido. En este caso, también incluye un diagnóstico indicando qué criterio falló (pocas fuentes, baja cobertura de entidades, puntajes bajos, etc.).

---

### Paso 22: Carga de Textos Completos desde la Base de Datos

Los fragmentos recuperados de los índices contienen principalmente identificadores y puntajes. Para generar una respuesta útil, el sistema necesita cargar el texto completo de cada fragmento desde la base de datos SQLite.

Por cada fragmento en la lista filtrada, el sistema ejecuta una consulta a la base de datos que obtiene el texto completo del fragmento, el identificador y título del documento padre, y los números de página de inicio y fin. Esta información permite construir citas precisas que indiquen de dónde proviene cada pieza de información.

**Decisión:** Con los textos completos cargados, el proceso continúa al Paso 23 para sintetizar la respuesta.

---

### Paso 23: Síntesis de Respuesta con Anti-Alucinación

El sistema compone una respuesta basándose exclusivamente en los fragmentos recuperados. El módulo de síntesis toma los tres fragmentos más relevantes y construye una respuesta estructurada que presenta la información encontrada junto con sus fuentes.

El proceso incluye varias medidas anti-alucinación. Primero, la respuesta solo incluye información que está explícitamente presente en los fragmentos recuperados. Segundo, cada pieza de información se vincula a una cita que indica el documento y página de origen. Tercero, el sistema calcula un puntaje de "fidelidad" (faithfulness) que mide qué tan bien respaldada está la respuesta por los fragmentos originales. Este puntaje se calcula verificando que las oraciones de la respuesta contengan palabras clave presentes en los fragmentos fuente.

Las citas se construyen con información fina cuando está disponible: el identificador del documento, el número de página, y opcionalmente las coordenadas del texto en la página (bbox) para poder resaltar el texto exacto en un visor de documentos.

El sistema también sanitiza cualquier HTML en la respuesta para evitar enlaces a sitios externos: cualquier URL que comience con "http://" o "https://" se reemplaza por un marcador seguro.

**Decisión:** Si el puntaje de fidelidad es bajo (menor a 0.85), el sistema incluye una advertencia indicando que la respuesta podría no estar completamente respaldada por las fuentes. En cualquier caso, la respuesta se construye y se prepara para enviar al usuario en el Paso 24.

---

### Paso 24: Respuesta al Usuario

El sistema empaqueta toda la información en una respuesta estructurada que incluye la pregunta original del usuario, la lista de fragmentos recuperados con sus textos, puntajes y metadatos, el número total de fragmentos encontrados, el modo de búsqueda utilizado (híbrido, denso o léxico), un indicador de si había evidencia suficiente, la respuesta sintetizada en formato de texto, el modo de generación usado (síntesis normal o fallback), y la lista de citas con referencias a documentos y páginas.

Esta respuesta viaja de regreso a través del Presenter hasta la interfaz de usuario, donde se muestra de forma amigable al usuario con la respuesta destacada, los fragmentos fuente expandibles, y las citas clickeables que podrían abrir el documento original en la página correspondiente.

**Decisión:** El proceso de consulta ha terminado. El usuario puede hacer más preguntas, que iniciarán nuevamente desde el Paso 17, o puede explorar los documentos fuente en la biblioteca.

---

## PARTE 4: BIBLIOTECA DE DOCUMENTOS

### Paso 25: Listado de Documentos en la Biblioteca

Cuando el usuario accede a la sección "Biblioteca" de la interfaz, el sistema solicita la lista de documentos disponibles al endpoint `/library`. Esta solicitud puede incluir parámetros de filtrado como palabras clave de búsqueda, filtro por año de publicación, filtro por autor, y parámetros de paginación (cuántos resultados mostrar y desde qué posición).

El sistema consulta la tabla `docs` en SQLite aplicando los filtros solicitados. Si hay un término de búsqueda, el sistema busca coincidencias tanto en los metadatos del documento (título, autor, nombre del archivo) como en el contenido de los fragmentos asociados.

Para cada documento, el sistema extrae el identificador, el título (o el nombre del archivo si no tiene título), el autor, el año, el tipo de documento (derivado de la extensión del archivo: pdf, docx, txt), y la fuente original. El sistema también calcula el total de documentos que coinciden con los filtros para permitir la paginación.

**Decisión:** La lista de documentos se devuelve al Presenter y luego a la interfaz de usuario para mostrarse en formato de tabla o tarjetas, permitiendo al usuario navegar por su colección de documentos.

---

### Paso 26: Visualización de Detalle de un Documento

Cuando el usuario hace clic en un documento específico de la biblioteca, el sistema solicita los detalles completos de ese documento al endpoint `/library/{doc_id}`.

El sistema carga de la base de datos todos los metadatos del documento: identificador, título, autor, año, tipo, clasificación de acceso, licencia, idioma original, y la ruta del archivo fuente. También carga las tablas extraídas de ese documento (si existen), incluyendo para cada tabla el identificador, la página donde se encontró, el número de filas y columnas, los encabezados, y las filas de datos. Adicionalmente, carga los primeros fragmentos de texto del documento (hasta 20) para dar una vista previa del contenido.

Esta información permite que la interfaz muestre una página de detalle con toda la información del documento: una ficha con los metadatos, una visualización de las tablas extraídas con formato de tabla HTML, y una lista de fragmentos de texto que el usuario puede expandir.

**Decisión:** El usuario puede desde esta vista volver a la lista de documentos, o potencialmente descargar el documento original, ver el PDF renderizado, o ejecutar una consulta RAG enfocada en este documento específico.

---

### Paso 27: Búsqueda por Facetas

El sistema también expone el endpoint `/library/facets` que devuelve las opciones disponibles para filtrar documentos: la lista de autores únicos presentes en la colección (ordenados alfabéticamente) y la lista de años de publicación disponibles (ordenados de más reciente a más antiguo).

Esta información permite que la interfaz muestre filtros tipo "dropdown" o "checkbox" que el usuario puede usar para refinar su búsqueda en la biblioteca sin necesidad de escribir texto.

**Decisión:** Las facetas se actualizan automáticamente cuando se agregan nuevos documentos, reflejando siempre el estado actual de la colección.

---

## PARTE 5: LECTURA DE INSTRUCCIONES DEL SISTEMA

### Paso 28: El Backend Lee y Procesa el Archivo de Instrucciones

El sistema MILPA incluye un archivo de texto llamado `instruccion.txt` ubicado en la carpeta `Instruccion/`. Este archivo contiene la documentación completa del diseño del sistema: el propósito y objetivos estratégicos, la justificación técnica y organizativa, el alcance funcional del MVP (Producto Mínimo Viable), los principios de diseño, la arquitectura lógica y de despliegue, y el flujo detallado de datos.

Este archivo sirve como referencia para los desarrolladores y para el propio sistema cuando necesita contexto sobre cómo debe comportarse. El contenido incluye especificaciones como los criterios de éxito (95% de ingestión correcta, 90% de respuestas con al menos 2 citas, latencia P50 menor a 800ms), los principios de diseño (desacoplamiento, contratos versionados, evidencia primero, taxonomías canónicas, privacidad local), y las rutas de escalabilidad futura.

**Decisión:** El archivo de instrucciones es leído por las herramientas de desarrollo y documentación para mantener consistencia entre lo diseñado y lo implementado.

---

## PARTE 6: OBSERVABILIDAD Y MONITOREO

### Paso 29: Recolección de Métricas con Prometheus

El sistema expone métricas de rendimiento y operación que son recolectadas por Prometheus, un sistema de monitoreo de código abierto. Las métricas incluyen contadores de solicitudes procesadas (totales, exitosas, fallidas), histogramas de latencia (cuánto tiempo toma cada operación), métricas de la cola de procesamiento (cuántas solicitudes están en espera, cuántas en proceso), y contadores de errores específicos (timeouts, circuit breaker activado, cola llena).

Prometheus consulta los endpoints de métricas de cada servicio cada 15 segundos por defecto, almacena los datos en su base de datos de series temporales, y permite hacer consultas sobre el estado histórico y actual del sistema.

**Decisión:** Las métricas recolectadas pueden visualizarse en dashboards de Grafana para monitorear la salud del sistema en tiempo real y detectar problemas antes de que afecten a los usuarios.

---

### Paso 30: Visualización en Grafana

Grafana se conecta a Prometheus como fuente de datos y permite crear dashboards visuales con gráficas, tablas y alertas. Los dashboards típicos muestran la tasa de solicitudes por segundo, la latencia promedio y percentiles (P50, P95, P99), la tasa de errores, el uso de recursos (CPU, memoria), y el estado de los índices (número de documentos indexados).

Los usuarios con acceso al panel de administración pueden ver estos dashboards para entender el comportamiento del sistema y diagnosticar problemas.

**Decisión:** Si las métricas muestran degradación del rendimiento o aumento de errores, los operadores del sistema pueden tomar acciones correctivas como escalar recursos, reiniciar servicios, o investigar la causa raíz.

---

## RESUMEN DEL FLUJO COMPLETO

El sistema MILPA AI funciona como una cadena de procesamiento donde cada paso transforma los datos y los prepara para el siguiente:

1. **Ingesta**: Los documentos entran al sistema, se validan, se escanean por seguridad, y se registran en la base de datos.

2. **Extracción**: El contenido de los documentos se extrae (texto nativo u OCR), se fragmenta en piezas manejables, y se enriquece identificando entidades del dominio agrícola.

3. **Indexación**: Los fragmentos se indexan tanto para búsqueda por palabras clave (BM25) como para búsqueda semántica (embeddings vectoriales), permitiendo encontrar información relevante de múltiples formas.

4. **Consulta**: Cuando un usuario hace una pregunta, el sistema busca en ambos índices, fusiona los resultados, evalúa si hay suficiente evidencia, y genera una respuesta basada únicamente en los fragmentos recuperados con citas precisas.

5. **Biblioteca**: Los usuarios pueden explorar los documentos disponibles, ver sus metadatos, tablas extraídas, y fragmentos de texto, permitiendo una navegación tradicional además de la búsqueda inteligente.

6. **Observabilidad**: Todo el proceso es monitoreado continuamente, generando métricas que permiten entender el rendimiento del sistema y detectar problemas proactivamente.

Este diseño garantiza que las respuestas del sistema siempre estén respaldadas por evidencia documental, evitando las "alucinaciones" comunes en sistemas de inteligencia artificial, y proporcionando trazabilidad completa desde la pregunta del usuario hasta el documento fuente original.

---

*Documento generado el 7 de diciembre de 2025*
*Sistema MILPA AI - Versión documentada del flujo completo*
