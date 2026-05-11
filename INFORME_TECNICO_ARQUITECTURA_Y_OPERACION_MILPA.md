# Informe Técnico de Arquitectura y Operación del Sistema MILPA

## Objetivo del informe

Este documento resume el análisis técnico del sistema MILPA a nivel de código, arranque, dependencias operativas, distribución de responsabilidades y deuda técnica. El propósito es describir cómo funciona realmente el sistema hoy, qué partes constituyen el núcleo operativo, qué zonas están dispersas o heredadas, y qué problemas concretos provoca esa situación.

## Resumen ejecutivo

El sistema principal de MILPA no está mal concebido desde el punto de vista lógico. Existe una arquitectura central reconocible, compuesta por un backend de inteligencia artificial en Python con FastAPI, un presenter en TypeScript con Fastify y un conjunto de mecanismos de recuperación híbrida basados en SQLite, BM25, ChromaDB, embeddings y enriquecimiento por entidades. Sin embargo, el repositorio en su estado actual transmite una complejidad operativa mayor a la que realmente debería existir. Esa percepción se origina menos en el diseño del núcleo y más en la acumulación de scripts auxiliares, documentación de distintas etapas del proyecto, rutas de arranque paralelas, componentes heredados y convenciones inconsistentes.

En términos prácticos, el sistema debería poder operar desde un camino principal relativamente claro: orquestación con Docker Compose, backend en el servicio ai, presenter en el servicio presenter, y datos persistidos dentro del backend. No obstante, alrededor de ese camino oficial existe una periferia amplia de scripts, utilidades, documentos de sprint, pruebas manuales, rutas alternativas y referencias a estados antiguos del sistema que hacen que el mantenimiento y el arranque parezcan mucho más fragmentados de lo que conceptualmente son.

La conclusión principal es la siguiente: el motor central del sistema es razonablemente modular, pero el repositorio como producto de ingeniería está disperso, heterogéneo y con señales claras de evolución incremental no consolidada. El problema dominante no es una mala idea arquitectónica, sino la falta de consolidación operacional y documental.

## Arquitectura real del sistema

### Núcleo principal identificado

El núcleo operativo actual está formado por los siguientes componentes:

1. Backend IA en Python con FastAPI.
2. Presenter en TypeScript con Fastify.
3. Persistencia relacional con SQLite.
4. Recuperación vectorial con ChromaDB.
5. Recuperación léxica con BM25, priorizando Tantivy y con fallback a Whoosh o memoria.
6. Embeddings con Sentence Transformers.
7. Enriquecimiento por entidades mediante spaCy y diccionarios del dominio.
8. Orquestación general mediante Docker Compose.

El backend se construye a partir de la fábrica de aplicación definida en milpa_ai_backend/api/server.py, expuesta por milpa_ai_backend/main.py. El presenter se arranca desde milpa_presenter/src/server.ts y actúa como proxy y capa de interfaz hacia el backend.

### Flujo funcional principal

El flujo esperado del sistema es:

1. El usuario entra por el presenter en el puerto 8080.
2. El presenter renderiza la interfaz web y reenvía llamadas al backend mediante rutas /ai/*.
3. El backend procesa consultas, extracción documental, reconstrucción de índices y acceso a biblioteca.
4. SQLite almacena texto y metadatos.
5. ChromaDB almacena embeddings.
6. BM25 indexa texto para recuperación léxica.
7. El backend fusiona resultados y devuelve respuesta estructurada al presenter.

Este flujo es coherente y técnicamente defendible. El problema no es el flujo central, sino la cantidad de caminos laterales que coexisten alrededor de él.

## Cómo debería arrancar el sistema

La ruta oficial de arranque está bastante clara cuando se sigue la implementación real:

1. docker-compose.yml define los servicios principales.
2. run_all.ps1 automatiza el arranque, las verificaciones de salud, la reconstrucción de índices y una consulta de prueba.

Los servicios declarados en Docker Compose son:

1. clamav
2. ai
3. presenter
4. prometheus
5. grafana

De esos, los estrictamente esenciales para la operación funcional básica del sistema RAG son ai y presenter. SQLite, ChromaDB y BM25 no se levantan como servicios externos separados, porque forman parte del backend. Esto significa que el sistema no necesita, en teoría, una gran cantidad de procesos independientes encendidos manualmente para responder consultas o servir la biblioteca. Esa es una observación importante: la complejidad operativa percibida es mayor que la complejidad real del núcleo.

## Por qué el sistema se siente más complejo de lo que debería

Aunque el núcleo principal es razonable, el repositorio contiene muchos elementos que multiplican la fricción operativa:

1. Documentación de varias etapas del proyecto que no describe exactamente el mismo estado del sistema.
2. Scripts en la raíz que interactúan con la API de forma directa.
3. Scripts que acceden directamente a SQLite, bypassando la API.
4. Scripts que asumen rutas de base de datos distintas.
5. Referencias a frontends o servicios no pertenecientes al camino principal actual.
6. Diferencias entre lo que la arquitectura declarada promete y lo que el despliegue permite realmente.

El resultado es que el sistema parece requerir muchos pasos manuales: backend, presenter, reconstrucción de índices, carga de biblioteca, verificación de datos, monitoreo, etc. En parte esto es real, pero en gran parte es consecuencia de que los estados del sistema, la documentación y las herramientas auxiliares no convergen en una sola forma de operar.

## Hallazgos principales

### 1. La lógica central está mejor organizada que la operación del repositorio

La parte de recuperación híbrida está relativamente bien separada:

1. core/logic/rag_engine.py concentra la fusión y la lógica híbrida.
2. core/logic/bm25.py concentra la búsqueda léxica y sus fallbacks.
3. core/logic/vectordb.py encapsula ChromaDB.
4. core/logic/embeddings.py encapsula embeddings.
5. core/logic/db.py centraliza el acceso relacional básico.

Eso da una base modular razonable. En cambio, la operación del repositorio está mucho menos ordenada: hay muchos scripts y muchos documentos que actúan como fuentes parciales de verdad.

### 2. La capa presenter está muy cargada en un solo archivo

El presenter funciona, pero está altamente concentrado en milpa_presenter/src/server.ts. En ese archivo conviven:

1. arranque del servidor
2. middlewares de seguridad
3. proxy al backend
4. métricas
5. circuit breaker
6. control de concurrencia y cola
7. páginas HTML completas para checks, biblioteca y query
8. JavaScript incrustado para comportamiento de cliente
9. estado runtime

Esto no significa que el presenter esté roto, pero sí que está desequilibrado. La separación por módulos es baja para una pieza que ya cumple múltiples responsabilidades. El riesgo es de mantenibilidad: cualquier expansión futura incrementará la fricción para modificar o depurar esa capa.

### 3. Existe una carpeta frontend ajena al flujo principal actual

En el repositorio existe una carpeta frontend con Express, MongoDB, Socket.IO, JWT, modelos Mongoose y un servidor independiente. Ese código no corresponde al stack principal actual basado en Fastify presenter más backend FastAPI. Su presencia introduce ruido técnico por varias razones:

1. hace pensar que hay otro frontend activo
2. sugiere dependencia de MongoDB y Socket.IO en el sistema actual
3. compite mentalmente con milpa_presenter como posible punto de entrada
4. complica la lectura del repositorio para nuevos mantenedores

Esto es una señal clara de legado no consolidado. Aunque no participe del camino principal, sí ensucia la arquitectura percibida.

### 4. La documentación no está alineada con el estado real del código

El repositorio contiene múltiples documentos de arquitectura, sprint, reportes de debugging, resúmenes de hallazgos e instrucciones. El problema no es tener documentación abundante, sino que varias piezas describen estados diferentes del sistema. Ejemplos de deriva documental:

1. se habla de main.db en varios documentos, pero el backend principal usa por defecto milpa_knowledge.db
2. se describen flujos blue-green y /ui/v2 que no aparecen integrados realmente en el presenter principal
3. se mencionan tecnologías heredadas o configuraciones que ya no son el camino más fiel
4. hay scripts de verificación y notas de sprint que siguen funcionando como pseudo-manuales paralelos

Esto provoca que para entender el sistema no baste con leer un README. Hay que inferir cuál documento refleja el estado real y cuál describe una fase previa del proyecto.

### 5. Hay inconsistencia grave en las rutas y nombres de base de datos

Este es uno de los problemas más importantes detectados.

Actualmente conviven varias referencias distintas a la base relacional:

1. data/milpa_knowledge.db
2. data/main.db
3. data/milpa.db

El backend principal obtiene la ruta de SQLite desde core/config.py, cuyo valor por defecto apunta a data/milpa_knowledge.db. Sin embargo:

1. yoyo.ini apunta a data/main.db
2. core/config_flags/feature_flags.py usa data/main.db por defecto
3. varios scripts de diagnóstico usan milpa_knowledge.db
4. algunos documentos y scripts antiguos usan milpa.db

Los problemas que provoca esta inconsistencia son serios:

1. diferentes subsistemas pueden estar leyendo bases distintas sin que el operador lo perciba
2. los feature flags pueden no residir en la misma base que usa la lógica principal
3. las migraciones pueden aplicarse en una base distinta a la base real del backend
4. scripts auxiliares pueden reportar información válida, pero de otra base
5. debugging y validación se vuelven confusos porque no existe una única fuente inequívoca de persistencia

Este hallazgo por sí solo explica parte de la sensación de que hay demasiadas piezas manuales: no siempre está claro qué estado de datos está usando cada componente.

### 6. La arquitectura declarada dice punto de entrada único, pero en la práctica no está cerrada así

Conceptualmente, el presenter debería ser el único acceso del usuario y el backend debería quedar detrás de él. Sin embargo, Docker Compose expone también el backend en el puerto 8000. Además, muchos scripts del repositorio consultan directamente la API del backend en localhost:8000.

Los efectos de esto son:

1. se rompe parcialmente la disciplina de un único punto de entrada
2. se vuelve normal bypassar el presenter para debug, pruebas y uso manual
3. se duplican las rutas mentales de acceso al sistema
4. aumenta la probabilidad de que ciertas validaciones, protecciones o comportamientos del presenter no formen parte de pruebas manuales habituales

En otras palabras, la arquitectura formal y la operación cotidiana no coinciden completamente.

### 7. El proceso de datos pesa más que el levantamiento de servicios

Una parte relevante de la complejidad percibida no proviene de procesos vivos, sino del pipeline de datos. Para que el sistema resulte útil no basta con levantar backend y presenter; además debe existir un estado consistente de:

1. documentos cargados
2. extracción realizada
3. fragmentos persistidos
4. índices reconstruidos
5. biblioteca visible desde la UI

Cuando ese ciclo no se ha ejecutado de forma coherente, el sistema arranca pero no parece operativo. Esto lleva al operador a sentir que “falta prender algo más”, cuando a veces lo que falta no es otro servicio sino completar la preparación de datos e índices.

### 8. Hay código aparentemente implementado pero no integrado del todo

El módulo de blue-green deployment en milpa_presenter/src/services/blue_green.ts es un ejemplo claro. El archivo define:

1. consulta de feature flags desde el backend
2. cálculo de rollout canario
3. middleware de redirección a /ui/v2
4. helpers de configuración

Sin embargo, en el presenter principal no se observa integración real de ese middleware en el flujo de arranque. Eso sugiere una funcionalidad planificada o parcialmente desarrollada, pero no consolidada. Este patrón aumenta deuda técnica porque deja piezas aparentemente avanzadas pero sin efecto real sobre el sistema operativo principal.

### 9. Hay inconsistencias de contrato entre frontend y backend

Se detectó al menos una incoherencia visible: la interfaz del presenter ofrece modos de búsqueda llamados hybrid, bm25 y vector, mientras que el backend maneja hybrid, dense y lex. Este tipo de desalineación indica que el contrato entre capas no está completamente cerrado y revisado.

Los problemas derivados son:

1. comportamiento inesperado en consultas
2. necesidad de traducir mentalmente nombres de modos
3. mayor probabilidad de bugs silenciosos
4. evidencia de evolución paralela entre frontend y backend sin suficiente consolidación final

### 10. El empaquetado y los imports muestran señales de fragilidad

En el backend coexisten imports del tipo milpa_ai_backend.core... con otros del tipo core.... Esto puede funcionar por cómo está montado el PYTHONPATH o por la forma en que el paquete se instala dentro del contenedor, pero no es una señal de empaquetado limpio.

El setup.py también es mínimo y poco robusto, lo que sugiere que la ejecución depende más de la disposición actual de carpetas y del entorno del contenedor que de una estructura de paquete particularmente madura.

Esto provoca:

1. mayor sensibilidad a cambios de ruta o despliegue
2. más probabilidad de errores al ejecutar fuera del camino previsto
3. menor portabilidad del código a otros entornos o pipelines

## Evaluación de centralización versus dispersión

### Aspectos relativamente centralizados

1. La construcción del backend.
2. La configuración base del backend.
3. La lógica de recuperación híbrida.
4. La encapsulación de BM25, embeddings, vector store y DB.
5. La orquestación oficial mediante Docker Compose y run_all.ps1.

### Aspectos claramente dispersos

1. Los puntos de entrada humanos al sistema.
2. La documentación técnica.
3. Los scripts de apoyo en la raíz.
4. Las rutas de persistencia y nombres de base.
5. La convivencia de componentes activos y heredados.
6. Las herramientas de verificación y depuración.
7. Los contratos y convenciones entre capas.

La conclusión es que la lógica central está más centralizada de lo que parece, pero la experiencia de operar y entender el repositorio es muy dispersa.

## El código está sucio o no

La respuesta matizada es esta:

### No parece especialmente sucio en el núcleo

El motor principal del sistema no se ve improvisado en su esencia. Hay una intención arquitectónica clara y varios módulos muestran una separación razonable de responsabilidades.

### Sí está sucio en la periferia del proyecto

El repositorio como producto total sí se ve cargado de residuos de evolución:

1. scripts de comprobación en la raíz
2. documentación histórica mezclada con documentación vigente
3. componentes heredados paralelos
4. referencias a distintos estados de persistencia
5. rutas operativas múltiples para hacer casi la misma tarea

Esto no vuelve inútil al sistema, pero sí encarece su mantenimiento y reduce la claridad para cualquier persona que quiera operarlo o extenderlo.

## Problemas concretos que provoca la situación actual

### Problemas operativos

1. Dificultad para saber cuál es el procedimiento correcto de arranque.
2. Mayor dependencia de conocimiento tácito del desarrollador principal.
3. Riesgo de levantar componentes correctos sobre datos incorrectos o desfasados.
4. Riesgo de reconstruir índices en una base distinta a la consultada por el backend.
5. Mayor tiempo de onboarding para nuevos colaboradores.

### Problemas de mantenimiento

1. Cambios pequeños pueden requerir revisar demasiados archivos dispersos.
2. Es difícil establecer una única fuente de verdad documental.
3. El presenter puede volverse más difícil de sostener si sigue creciendo dentro de un solo archivo.
4. El legado no consolidado introduce dudas permanentes sobre qué carpetas o scripts siguen siendo relevantes.
5. El debugging se complica cuando hay artefactos múltiples para una misma responsabilidad.

### Problemas de arquitectura y calidad

1. La exposición directa del backend debilita la idea de punto de entrada único.
2. La inconsistencia de rutas de base de datos debilita la integridad operacional.
3. Los módulos parcialmente integrados incrementan deuda técnica silenciosa.
4. La desalineación entre backend y UI sugiere contratos poco consolidados.
5. La diferencia entre arquitectura declarada y arquitectura usada reduce confianza en la documentación.

### Problemas de escalabilidad del proyecto

1. A medida que el sistema crezca, la dispersión actual amplificará la complejidad.
2. Cada nueva feature corre el riesgo de añadir otra capa documental o script paralelo.
3. Si no se consolida el núcleo operativo, el costo de cambio aumentará más rápido que la funcionalidad.
4. El sistema puede seguir funcionando, pero el equipo cargará cada vez más deuda contextual.

## Diagnóstico final

MILPA no parece ser un sistema mal diseñado en su centro. El backend híbrido, el presenter como proxy e interfaz, y la combinación de SQLite, ChromaDB, BM25 y enriquecimiento semántico forman una base técnicamente válida. El principal problema no está en la idea, sino en la consolidación del proyecto como repositorio y como producto operable.

Actualmente el sistema muestra una diferencia clara entre arquitectura lógica y experiencia real de operación. La primera es bastante más ordenada que la segunda. El operador percibe que necesita encender demasiadas cosas porque el repositorio comunica múltiples caminos, múltiples estados y múltiples fuentes parciales de verdad. Esa dispersión produce fricción, dudas y dependencia de conocimiento histórico.

En síntesis:

1. El núcleo no está mal.
2. La operación está demasiado dispersa.
3. El presenter está funcional pero monolítico.
4. La persistencia está conceptualmente centralizada, pero materialmente inconsistente en nombres y rutas.
5. Hay legado sin consolidar.
6. La documentación no converge en un solo estado del sistema.
7. El principal riesgo no es un colapso técnico inmediato, sino la acumulación de deuda de claridad, mantenimiento y gobernanza del código.

## Conclusión práctica

Si se pregunta si hoy el sistema depende realmente de demasiados procesos manuales, la respuesta estricta es no: el camino oficial es más simple de lo que parece. Pero si se pregunta si el proyecto, tal como está organizado, hace que parezca necesario prender demasiadas cosas y recordar demasiadas rutas, entonces la respuesta es sí.

Lo que genera esa sensación no es únicamente el número de servicios, sino la suma de:

1. caminos alternos de arranque
2. scripts auxiliares numerosos
3. documentación histórica mezclada con la vigente
4. componentes heredados dentro del mismo repo
5. inconsistencias en bases de datos, contratos y convenciones

Por ello, el problema dominante del sistema actual puede formularse así: la arquitectura central existe y funciona, pero el proyecto necesita consolidación operativa y reducción de ambigüedad estructural para que su uso, mantenimiento y evolución estén a la altura de la calidad técnica de su núcleo.