# Documentación Técnica — Triaje IA

**Estado del documento:** actualizado 2026-05-25  
**Propósito:** referencia técnica completa + guía de comprensión del código para la defensa.

---

## Visión general — antes de entrar en el código

### El problema que resuelve

Cuando alguien llega a urgencias, un enfermero tiene que decidir en segundos si esa persona necesita atención inmediata o puede esperar. Ese proceso se llama **triaje**. El Sistema de Triaje Manchester tiene 5 niveles: desde C1 (actuación inmediata, riesgo vital) hasta C5 (puede esperar 4 horas, consulta leve).

Tu proyecto automatiza ese triaje a partir de la conversación entre el médico y el paciente.

### El problema de los datos

El proyecto parte de **272 transcripciones** de entrevistas médico-paciente (ficheros `.txt` en `text/`). El problema fundamental: **nadie les puso etiqueta**. No hay ningún fichero que diga "este caso es C2, este es C3". Son texto libre, sin más.

Para entrenar un modelo de Machine Learning necesitas ejemplos etiquetados. Como no los tienes, los generas tú: usas un **LLM para leer cada transcripción y asignarle un nivel Manchester** junto con las características clínicas del caso. A partir de esas etiquetas automáticas, entrenas un Random Forest que aprende a clasificar casos nuevos.

### Las tres fases del sistema

```
FASE 1 — "Aprende" (batch, se ejecuta una sola vez)
   272 textos → LLM los etiqueta y extrae features → Random Forest aprende

FASE 2 — "Predice" (a demanda, vía API)
   Texto nuevo → LLM extrae features → RF predice el nivel → respuesta JSON

FASE 3 — "Muéstralo" (interfaz clínica)
   Audio o texto → Whisper transcribe → Streamlit muestra el resultado con colores
```

La Fase 1 ya está ejecutada: el modelo entrenado vive en MinIO. Las Fases 2 y 3 son las que usa el médico.

### Qué hace exactamente el LLM (y qué no)

El LLM no clasifica directamente el caso. Hace algo más concreto: **lee la transcripción en lenguaje coloquial y rellena un formulario estructurado**.

Le das texto libre:
> "Llevo dos horas con un dolor muy fuerte en el pecho, me cuesta respirar, ya tuve un infarto hace tres años..."

Y devuelve un JSON con los datos extraídos:
```json
{
  "nivel_triaje": 2,
  "score_urgencia": 91,
  "score_ansiedad": 0.3,
  "dolor_intensidad": 8,
  "disnea": true,
  "antecedentes_cardiacos": true,
  "edad": 67
}
```

Eso es normalización: "me cuesta respirar" → `disnea: true`, "dolor muy fuerte" → `dolor_intensidad: 8`. El LLM actúa como un médico que rellena una ficha clínica estandarizada a partir de lo que el paciente describió con sus propias palabras.

### ¿Para qué el Random Forest si el LLM ya da el nivel?

Es la pregunta más importante del proyecto. El LLM sí asigna un `nivel_triaje`, pero ese valor tiene tres limitaciones en un contexto clínico real:

1. **No es reproducible.** Con temperatura > 0, el mismo texto puede producir resultados distintos en llamadas distintas. En medicina necesitas que el sistema sea determinista.
2. **No es auditable.** En clínica, cuando el sistema dice C2, debes poder explicar *por qué*. El RF tiene importancia de features: "decidió C2 principalmente por `dolor_intensidad=8` y `antecedentes_cardiacos=true`". Un LLM no te da eso.
3. **No aprende de los datos históricos.** El RF entrena con los 272 casos y aprende los patrones estadísticos reales: si históricamente los pacientes de 65+ con disnea y antecedentes casi siempre son C2, el RF interioriza ese patrón sin que nadie se lo diga explícitamente.

En resumen: el **LLM entiende el texto y extrae estructura**, el **RF toma la decisión estadística y auditable**.

### La infraestructura — por qué tantas piezas

El proyecto no es un script Python. Es un sistema con varios servicios que necesitan coordinarse:

- **Airflow** — orquesta el pipeline. Si el procesamiento de la transcripción número 143 falla, Airflow lo reintenta desde el 143, no desde el 1. También gestiona dependencias: el entrenamiento no puede empezar hasta que todas las transcripciones estén enriquecidas.
- **FastAPI** — expone los microservicios (preprocesado, LLM, entrenamiento, predicción) como endpoints HTTP. Así Airflow y la Streamlit pueden llamarlos sin acoplar el código.
- **Postgres** — fuente de verdad del estado de cada caso. Cada transcripción tiene un estado (`INGESTED → ENRICHED → COMPLETADA`) y un historial de timestamps.
- **MinIO** — almacenamiento de objetos (como S3 de AWS pero local). Guarda los textos originales, los datasets CSV y los modelos `.pkl`. Todos los contenedores Docker lo comparten — si el texto estuviera en disco, el contenedor API no podría leerlo.

---

## Sistema de Triaje Manchester (MTS)

El proyecto clasifica urgencias según el **Sistema de Triaje Manchester (MTS)**, estándar internacional de 5 niveles codificados por color:

| Código | Color | Tiempo máx. atención | Descripción |
|--------|-------|----------------------|-------------|
| C1 | Rojo | Inmediato | Compromiso vital inmediato |
| C2 | Naranja | 10 min | Emergencia — riesgo vital próximo |
| C3 | Amarillo | 60 min | Urgente — deterioro posible |
| C4 | Verde | 120 min | Menos urgente — estable |
| C5 | Azul | 240 min | No urgente — consulta diferible |

Internamente el sistema almacena el nivel como entero 1-5 (`nivel_triaje`). La Streamlit lo traduce a `C1`–`C5` con su color. El valor numérico es clave para el entrenamiento del RF: las clases son 1, 2, 3, 4, 5 y el modelo aprende que acertar en C2 tiene más coste que acertar en C3 (ver `class_weight` en §Entrenamiento).

### Cómo se distingue un nivel de otro en la práctica

Memorizar los colores no es suficiente — lo importante es entender qué señales clínicas separan un nivel del siguiente, porque eso es exactamente lo que el LLM tiene que detectar en el texto.

**C1 — Inmediato:** compromiso vital activo ahora mismo. Parada cardíaca, parada respiratoria, inconsciencia, convulsión en curso. Si no actúas en segundos, hay muerte o daño irreversible. Es el nivel más infrecuente en los datos (casi inexistente entre las 272 transcripciones) pero el más crítico.

**C2 — 10 minutos:** riesgo vital *próximo*, no inmediato. El paciente puede hablar, pero el deterioro puede llegar rápido. El patrón más frecuente: dolor torácico + disnea + antecedentes cardíacos → posible síndrome coronario agudo (infarto). Solo hay 9 casos C2 en los 272. Es el nivel más peligroso de clasificar mal: si el modelo lo trata como C3, el paciente puede deteriorarse en la sala de espera.

**C3 — 60 minutos:** urgente pero estable. Puede esperar sin deterioro significativo. Es el nivel más común en urgencias reales y en los datos: ~200 de 272 casos (73%). Un esguince moderado, fiebre sin signos de sepsis, dolor abdominal leve. El paciente puede estar asustado, pero clínicamente no hay riesgo inminente.

**C4/C5 — puede esperar:** patología leve. Podría haber ido al médico de cabecera.

### El problema clínico que complica la clasificación

Un paciente C2 muy ansioso puede *parecer* C3 porque describe su pánico más que sus síntomas objetivos. Un paciente C3 que exagera el dolor puede *parecer* C2. El LLM tiene que aprender a separar la señal emocional (ansiedad) de la señal clínica (síntomas objetivos), y el prompt tiene ejemplos concretos de ambas situaciones para calibrar ese criterio.

Esta dificultad es también la razón de la auditoría ética: cuando el RF baja el nivel respecto al LLM en un paciente con ansiedad alta, no está claro quién tiene razón — y eso merece revisión clínica.

---

## Airflow — el orquestador del pipeline

### El problema que resuelve

Imagina que el procesamiento de las 272 transcripciones fuera un script Python que va una a una. Si el script falla en la número 143 (porque el LLM tardó demasiado y dio timeout), tienes dos opciones malas: relanzas todo desde el 1 perdiendo el trabajo hecho, o añades lógica manual de checkpointing al script.

Airflow resuelve esto. Un **DAG** (Directed Acyclic Graph) es un conjunto de tareas con dependencias entre ellas. Airflow ejecuta cada tarea, guarda su estado (éxito, fallo, en ejecución), y si una falla puede reintentarla o dejarte relanzarla manualmente desde ese punto exacto — sin tocar las que ya terminaron.

### Los DAGs del proyecto y su orden

```
dag_text_ingestion  →  dag_llm_enrichment  →  dag_dataset_builder  →  dag_model_training  →  dag_evaluation

dag_prediction_phase_2   (independiente, Fase 2 a demanda)
```

Cada DAG llama a microservicios FastAPI vía HTTP. Airflow no procesa los datos él mismo — coordina quién los procesa y en qué orden.

### Por qué no un script Python normal

1. **Reintentos automáticos.** Si OpenRouter devuelve 429 en el caso 87, Airflow reintenta con backoff sin intervención manual.
2. **Estado por entrevista.** Postgres registra el estado de cada transcripción. Si relanzas `dag_llm_enrichment`, solo procesa las que están en `INGESTED` o `ERROR_ENRICHMENT`, no las que ya están `ENRICHED`.
3. **UI de monitorización.** En `http://localhost:8088` ves qué tareas están corriendo, cuáles fallaron y sus logs individuales.

---

## Diagrama de arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                     FASE 1 — batch (Airflow)                        │
│                                                                     │
│  text/*.txt ──► [dag_text_ingestion]                                │
│                        │                                            │
│               Postgres (INGESTED) + MinIO (textos-originales/)      │
│                        │                                            │
│                        ▼                                            │
│               [dag_llm_enrichment]                                  │
│                        │                                            │
│                        ▼                                            │
│                 [service: llm_enrichment]                           │
│                        │                                            │
│                        ▼                                            │
│               LLM (Ollama host / OpenRouter API)                    │
│                        │                                            │
│         entidades + nivel_triaje + score_urgencia                   │
│         + score_ansiedad + features clínicas                        │
│                        │                                            │
│                        ▼                                            │
│              [dag_dataset_builder] ──► CSV en MinIO (datasets/)     │
│                        │                                            │
│                        ▼                                            │
│              [dag_model_training] ──► modelo.pkl en MinIO (modelos/)│
│                        │                                            │
│                        ▼                                            │
│               [dag_evaluation] ──► métricas + artefactos            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                  FASE 2 — a demanda (FastAPI)                       │
│                                                                     │
│  Cliente ──► POST /predecir/ (ml_predictor)                         │
│                   │                                                 │
│                   ├──► MinIO (guarda fase2/<guid>.txt)              │
│                   ├──► Postgres (crea registro GUID, origen=simul.) │
│                   ├──► llm_enrichment (preprocess + LLM)            │
│                   ├──► carga modelo .pkl desde MinIO                │
│                   ├──► predicción (nivel 1-5 + confianza)           │
│                   ├──► valoración automática (0-10)                 │
│                   └──► Postgres (estado COMPLETADA)                 │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│              FASE 3 — aplicación clínica (Streamlit)                │
│                                                                     │
│  Médico ──► Streamlit UI (app/streamlit_app.py)                     │
│                   │                                                 │
│                   ├── Sube audio .wav/.mp3                          │
│                   │       │                                         │
│                   │       ▼                                         │
│                   │   [Whisper] ──► texto transcrito                │
│                   │   (app/whisper_utils.py, faster-whisper)        │
│                   │                                                 │
│                   ├── O pega texto directamente                     │
│                   │                                                 │
│                   ▼                                                 │
│               POST /predecir/ ──► nivel Manchester (C1-C5)          │
│                   │                                                 │
│                   ├──► Badge color Manchester + score_urgencia      │
│                   ├──► score_ansiedad (badge de alerta)             │
│                   ├──► entidades normalizadas como chips            │
│                   ├──► alerta under-triage si RF < LLM              │
│                   └──► tabla de auditoría ética (/metricas/auditoria)│
└─────────────────────────────────────────────────────────────────────┘

Capa de persistencia transversal:
┌──────────────────────┐    ┌────────────────────────────────────┐
│      Postgres        │    │               MinIO                │
│                      │    │  textos-originales/                │
│  Entrevista          │    │  datasets/                         │
│  Entidad             │    │  modelos/                          │
│  ResultadoML         │    └────────────────────────────────────┘
└──────────────────────┘
```

---

## Pipeline de estados

Cada entrevista lleva un `GUID_Entrevista` único (UUID4) que la identifica en Postgres, MinIO, los logs de Airflow y la respuesta JSON de la API. El estado avanza en orden:

```
Fase 1 (batch):
INGESTED → ENRICHING → ENRICHED → DATASET_READY → MODEL_TRAINED → EVALUATED

Fase 2 (a demanda):
INGESTED → ENRICHING → ENRICHED → COMPLETADA

Estados de error:
ERROR_ENRICHMENT  — fallo LLM (reintentable relanzando dag_llm_enrichment)
ERROR_INGESTION   — fallo lectura .txt individual (no bloquea el batch)
```

---

## Estado actual del proyecto (2026-05-25)

| Componente | Estado |
|-----------|--------|
| Ingesta 272 transcripciones | Hecho |
| Enriquecimiento LLM (272/272) | Hecho |
| `score_ansiedad` en prompt + BD + modelo | Hecho |
| Dataset CSV en MinIO | Hecho |
| Entrenamiento RF con `class_weight='balanced'` | Hecho (CV F1 macro 0.850 ± 0.069) |
| Evaluación CV 5-fold | Hecho |
| Endpoint `/predecir/` Fase 2 | Hecho (valoración + COMPLETADA) |
| Endpoint `/metricas/` y `/metricas/auditoria` | Hecho |
| `dag_prediction_phase_2` | Hecho |
| Streamlit front-end (Fase 3) | Hecho |
| Whisper (transcripción audio) | Hecho |
| Auditoría ética (under-triage) | Hecho |

---

## Guía de comprensión del código — flujo completo

Esta sección traza el recorrido completo de los datos desde un fichero `.txt` hasta el badge de color en Streamlit. Para cada paso: primero la explicación conceptual de qué está pasando y por qué, luego el fichero exacto y las funciones concretas.

---

### PASO 1 — El dato de origen: `text/RES0001.txt`

Los 272 ficheros de `text/` son transcripciones de entrevistas médico-paciente en inglés con prefijo de especialidad: `CAR` (cardiología), `RES` (respiratorio), `MSK` (musculoesquelético), etc. Son el único dato de entrada de la Fase 1. Texto plano, sin etiquetas, sin estructura.

**¿Por qué en inglés si el sistema habla español?**  
El LLM entiende ambos idiomas de forma nativa. El prompt está en español y el LLM responde en español independientemente del idioma de la transcripción. La Fase 3 acepta entrevistas en español directamente — el pipeline no cambia nada.

---

### PASO 2 — Ingesta: `dags/dag_text_ingestion.py`

**El GUID: el hilo que atraviesa todo el sistema**

Lo primero que hace el DAG es generar un **GUID** (UUID4) por fichero, algo como `3f7b-a291-4dc8-91bc-...`. Este identificador acompaña al caso durante toda su vida: en Postgres, en MinIO, en los logs de Airflow y en la respuesta JSON de la API. Es el hilo que conecta todas las piezas.

¿Por qué UUID4 y no el nombre del fichero? Porque en la Fase 2 llegan casos sin nombre de fichero — el médico pega texto directamente. Con UUID4, todos los casos tienen el mismo tipo de identificador y el sistema los trata de forma uniforme.

**Lo que hace el DAG:**
- Itera sobre todos los `.txt` de `text/`.
- Genera un `GUID_Entrevista` (UUID4) por fichero.
- Sube el fichero a MinIO en `textos-originales/<especialidad>/<nombre>.txt`.
- Inserta una fila en `Entrevista` con estado `INGESTED`, `origen='dataset'` y la especialidad del prefijo (`CAR`, `RES`…).

**Estado de Postgres tras este paso:**
```
GUID_Entrevista: "3f7b-..."
Estado: "INGESTED"
origen: "dataset"
especialidad: "CAR"
nombre_fichero: "CAR0001.txt"
URL_Texto_Original: "s3://textos-originales/CAR/CAR0001.txt"
```

**¿Por qué MinIO y no disco?**  
Todos los contenedores Docker comparten MinIO pero no el sistema de ficheros. Si el texto solo existiera en el disco del contenedor Airflow, el contenedor API no podría leerlo. MinIO actúa como disco compartido compatible con S3.

**El campo `origen` — por qué importa**  
Distingue los 272 casos de entrenamiento (`'dataset'`) de las predicciones Fase 2 (`'simulacion'`). Si algún día re-entrenas el modelo, no quieres incluir predicciones que el propio modelo generó — sería aprender de sí mismo. El campo `origen` permite filtrar esos casos fuera del dataset.

---

### PASO 3 — Enriquecimiento LLM: `dags/dag_llm_enrichment.py`

Este es el paso más importante del proyecto. El DAG consulta todos los registros en estado `INGESTED` (o `ERROR_ENRICHMENT`) y para cada uno llama al microservicio FastAPI en `POST /enriquecer/`. Ese microservicio hace tres cosas en cadena:

```
texto bruto → preprocesado → LLM → persistencia en Postgres
```

#### 3a. Preprocesado: `services/preprocessor/service.py`

**Función:** `preprocess(guid, texto) -> dict`

Una transcripción típica tiene esta forma:
```
D: ¿Cuánto tiempo lleva con el dolor?
P: Dos horas, es muy fuerte, en el pecho...
D: ¿Tiene dificultad para respirar?
P: Sí, me cuesta mucho...
```

El preprocesador extrae solo las líneas `P:` (el paciente). El médico hace preguntas neutras que no aportan información clínica; el paciente describe sus síntomas. Si no hay separación clara, usa el texto completo. El resultado se pasa directamente al LLM.

```python
prep = preprocess(guid, texto)
texto_llm = prep["texto_paciente"] or prep["texto_completo"]
```

#### 3b. Llamada al LLM: `services/llm_enrichment/client.py`

**Función:** `call_llm(texto) -> dict`

Según `LLM_PROVIDER` en `.env`, llama a:
- **Ollama** (`http://host.docker.internal:11434`) — modelo local en el host, sin rate limits, datos sin salir del equipo. Ideal para el batch de 272 casos.
- **OpenRouter** (`https://openrouter.ai/api/v1`) — API externa. Útil en portátil sin GPU para la demo. Modelo `google/gemini-2.0-flash-001` gratuito.

En ambos casos: `temperature=0` (sin aleatoriedad — la misma entrada siempre produce el mismo JSON) y `format=json` (el LLM está obligado a responder con JSON válido).

`temperature=0` es una decisión de diseño clínica: en un sistema de soporte a decisiones médicas, el mismo texto no puede producir resultados distintos según el momento del día. La reproducibilidad es un requisito, no una optimización.

**Reintentos (OpenRouter):** ante HTTP 429 (rate limit), el cliente reintenta con backoff exponencial hasta `LLM_MAX_RETRIES=4` veces con base `LLM_RETRY_BASE_SEC=15`. En Ollama local no hay 429.

#### 3c. El prompt clínico: `services/llm_enrichment/prompt.py`

**Concepto clave antes del código:** el LLM no sabe por defecto qué es el Sistema de Triaje Manchester ni cuándo algo es C2 en lugar de C3. Hay que enseñárselo en el propio prompt, igual que le darías un manual a un médico nuevo antes de que empiece a trabajar. El prompt es ese manual: define los criterios de cada nivel, da ejemplos concretos y establece reglas de comportamiento ante la incertidumbre.

**Función:** `build_messages(texto) -> list[dict]`

El prompt tiene cuatro secciones. El orden importa: primero el contexto (quién es el LLM y qué criterios usa), luego la calibración (ejemplos concretos), luego la pregunta (clasifica esto).

**Sección 1 — Rol y criterios Manchester:**

Le dice al LLM quién es ("eres un sistema experto en triaje médico de urgencias hospitalarias") y le da los criterios clínicos de cada nivel. Esto ancla su criterio al estándar MTS en lugar de dejarlo operar con el conocimiento difuso de sus datos de entrenamiento.

Al final está la **"regla de oro"**: *cuando hay duda entre dos niveles, asigna siempre el más urgente.* Decisión clínica deliberada: un falso positivo (tratar algo como más urgente de lo que es) tiene consecuencias leves. Un falso negativo puede ser fatal. La regla hace que el LLM sea conservador por defecto.

**Sección 2 — Definición de `score_ansiedad`:**

El prompt define explícitamente que `score_ansiedad` mide el pánico percibido en el paciente (0.0-1.0), **independientemente de la gravedad clínica**. Y añade: *un paciente puede estar muy ansioso (0.9) por un problema leve (C4). La ansiedad no determina el nivel de triaje — los síntomas clínicos objetivos sí.*

Sin esta instrucción, el LLM tiende a correlacionar ansiedad con urgencia. Eso es un sesgo que hay que corregir de forma explícita.

**Sección 3 — Dos ejemplos few-shot:**

En lugar de describir los criterios en abstracto, le das al LLM dos casos ya resueltos. No son aleatorios — están elegidos para enseñar la distinción más peligrosa del sistema:

- **Caso C2 (cardíaco):** paciente de 67 años, dolor torácico intenso, disnea, antecedente de infarto. `score_urgencia=91`, `score_ansiedad=0.3`. El paciente está algo asustado pero la urgencia viene de la clínica, no de la ansiedad.
- **Caso C3 (ansiedad alta, clínica leve):** paciente joven, dolor inespecífico, respiración agitada, muy nervioso. `score_urgencia=41`, `score_ansiedad=0.92`. Ansiedad extrema pero síntomas leves → C3, no C2.

Juntos enseñan que la misma sensación de ahogo puede ser C2 (disnea real con antecedentes) o C3 (hiperventilación por pánico). El LLM aprende por contraste, igual que un médico aprende de casos reales. Sin ejemplos (zero-shot), el LLM tiende a clasificar los casos ambiguos como C3 por ser la clase más frecuente.

**Sección 4 — JSON de salida (14 campos):**

```json
{
  "nivel_triaje": 2,
  "score_urgencia": 91.0,
  "score_ansiedad": 0.3,
  "motivo_consulta": "Dolor torácico con disnea y antecedente de infarto",
  "entidades": ["dolor pecho", "cuesta respirar"],
  "entidades_normalizadas": ["dolor torácico", "disnea"],
  "edad": 67,
  "sexo": "M",
  "dolor_intensidad": 8,
  "disnea": true,
  "fiebre": false,
  "perdida_consciencia": false,
  "irradiacion": false,
  "antecedentes_cardiacos": true,
  "fumador": false,
  "justificacion": "Alta sospecha SCA. Nivel 2 según MTS."
}
```

Hay dos tipos de datos mezclados en la misma respuesta:
- **Features del RF**: `edad`, `sexo`, `dolor_intensidad`, los booleanos, `score_urgencia`, `score_ansiedad` → van al modelo ML
- **Metadatos clínicos**: `motivo_consulta`, `entidades`, `entidades_normalizadas`, `justificacion` → van a Postgres y se muestran en Streamlit

El LLM rellena todo en una sola llamada. El código los separa después y los guarda donde corresponde.

#### 3d. Persistencia post-LLM: `services/llm_enrichment/service.py`

**Función:** `enrich(guid, texto) -> dict`

Tras recibir el JSON del LLM:
1. Borra entidades previas de `Entidad` para ese GUID (permite re-enriquecer sin duplicar).
2. Inserta cada par `(entidad_raw, entidad_normalizada)` en la tabla `Entidad`.
3. Hace un UPSERT en `ResultadoML` con todos los campos (edad, sexo, dolor_intensidad, booleanos, scores, nivel_triaje, motivo_consulta, justificacion).
4. Actualiza el estado de `Entrevista` a `ENRICHED` con timestamps de inicio/fin.

El UPSERT usa `ON CONFLICT (GUID_Entrevista) DO UPDATE` — si el DAG se re-ejecuta (porque algún caso quedó en `ERROR_ENRICHMENT`), no duplica filas.

---

### PASO 4 — Codificación de features: `services/ml_features.py`

**Concepto clave antes del código:** el LLM devuelve un JSON con valores como `"edad": 67`, `"disnea": true` o `"edad": null` (si no se mencionó). El Random Forest no entiende JSON ni valores nulos — necesita un array de números. Este módulo hace esa traducción, y las reglas de traducción son decisiones de diseño importantes: ¿qué pones cuando falta un dato? ¿Cómo codificas el sexo? Estas decisiones afectan directamente a lo que aprende el modelo.

Este módulo es el **punto de acoplamiento** entre el LLM (que produce JSON) y el modelo ML (que necesita un array numérico). Lo usan tanto el entrenamiento como la predicción Fase 2 — es la única fuente de verdad para la codificación.

**Lista canónica de features:**
```python
FEATURES = [
    "edad", "sexo", "dolor_intensidad",
    "disnea", "fiebre", "perdida_consciencia",
    "irradiacion", "antecedentes_cardiacos", "fumador",
    "score_urgencia", "score_ansiedad"
]
```

**Funciones de codificación:**

| Función | Propósito |
|---------|-----------|
| `encode_optional_int(v)` | `null → -1`, entero → entero. Para edad, dolor_intensidad. |
| `as_bool(v)` | `null/False/"false" → False`, cualquier truthy → True. Para los booleanos clínicos. |
| `encode_sexo(v)` | `"M" → 1`, `"F" → 0`, `null → -1`. |
| `row_from_llm_result(resultado, esp)` | Construye el dict completo con todas las features a partir del JSON del LLM. |

**¿Por qué -1 para desconocidos y no 0?**  
Porque 0 tiene significado clínico: `dolor_intensidad=0` significa "el paciente no tiene dolor". `dolor_intensidad=-1` significa "la transcripción no menciona dolor". Son situaciones distintas y el modelo debe aprender esa diferencia. Con -1, el RF trata "dato no disponible" como una categoría propia — lo cual es la realidad clínica (no siempre se recoge toda la información en urgencias).

**¿Por qué -1 en edad y no la media?**  
Imputar la media contamina el modelo con un valor artificial. -1 es honesto: el RF aprende a tomar decisiones sin ese dato, igual que haría el médico. Descartar las filas sin edad dejaría ~4 casos entrenables de 272.

---

### PASO 5 — Construcción del dataset: `dags/dag_dataset_builder.py`

Consulta todos los registros `ENRICHED` de Postgres, aplica la codificación de `ml_features.py` y genera un CSV versionado:

```
datasets/dataset_entrenamiento_20260524_143512.csv
```

Columnas: `guid`, `especialidad`, `origen`, + las 11 features de `FEATURES` + `nivel_triaje` (target).

El CSV se sube a MinIO. El estado de cada entrevista avanza a `DATASET_READY`.

**¿Por qué versionar el CSV y no re-generarlo siempre?**  
Permite reproducibilidad total: el modelo entrenado en un CSV concreto puede ser re-evaluado en el mismo CSV aunque el estado de Postgres cambie después. También es útil para el tribunal: se puede señalar exactamente con qué datos se entrenó el modelo.

---

### PASO 6 — Entrenamiento: `services/ml_trainer/service.py`

**Concepto clave antes del código:** el problema más difícil del entrenamiento no es el algoritmo — es el desbalanceo de datos. Tienes ~200 casos C3 y solo 9 casos C2. Si entrenas sin más, el modelo aprende un atajo: "si digo siempre C3 acierto el 73% de las veces". Acertaría mucho, pero sería inútil clínicamente — precisamente los casos C2 (los más peligrosos) los ignoraría. La solución es decirle al modelo que cada error en C2 cuenta mucho más que un error en C3.

**Función principal:** `train() -> dict`

**Flujo:**
1. Carga el CSV más reciente de MinIO (`datasets/dataset_entrenamiento_*.csv`).
2. Separa `X` (las 11 features) e `y` (nivel_triaje 1-5).
3. Split 80/20 estratificado por nivel_triaje (`stratify=y`).
4. Calcula `class_weight='balanced'`:

```python
from sklearn.utils.class_weight import compute_class_weight
class_weights = compute_class_weight("balanced", classes=classes, y=y)
cw_dict = dict(zip(classes, class_weights))
# Resultado típico: {1: 45.0, 2: 15.0, 3: 0.68, 4: 3.1, 5: 5.0}
```

5. Entrena **Random Forest** con esos pesos:

```python
rf = RandomForestClassifier(
    n_estimators=200,
    class_weight=cw_dict,
    random_state=42,
    n_jobs=-1
)
rf.fit(X_train, y_train)
```

6. Entrena también una **Regresión Logística** como baseline para comparar.
7. Evaluación CV 5-fold estratificada:

```python
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
scores = cross_val_score(rf, X, y, cv=cv, scoring="f1_macro")
# → 0.850 ± 0.069 (modelo actual, prompt Manchester + score_ansiedad)
```

8. Serializa el modelo: `modelo_<timestamp>.pkl` → MinIO `modelos/`.
9. Registra métricas en Postgres.

**¿Por qué `class_weight='balanced'` y no `class_weight=None`?**  
El dataset tiene un desbalanceo extremo: ~200 casos C3, 9 casos C2. Sin pesos, el RF aprende a predecir siempre C3 (acertaría el 73 % del tiempo sin aprender nada). Con `'balanced'`, cada error en C2 penaliza ~15 veces más que un error en C3, forzando al modelo a prestar atención a los casos críticos. El recall de C2 pasó de ~0.3 a 1.0 tras añadir este parámetro.

**¿Por qué Random Forest y no XGBoost / red neuronal?**  
- Con 272 muestras y 11 features, los modelos profundos sobreajustan.
- RF es interpretable: la importancia de features es defendible ante el tribunal.
- No requiere GPU para inferencia en Fase 2.
- Es robusto con datos tabulares mixtos (enteros, floats, booleanos, -1 como categoría).
- XGBoost habría sido la siguiente opción — resultados similares pero sin la interpretabilidad nativa de feature importance.

**¿Por qué `random_state=42`?**  
Reproducibilidad: el mismo CSV siempre produce el mismo modelo. Para la defensa, se puede ejecutar el entrenamiento de nuevo y obtener idénticos resultados.

---

### PASO 7 — Evaluación: `dags/dag_evaluation.py`

Carga el modelo más reciente de MinIO, ejecuta CV 5-fold y genera:
- Matriz de confusión (JSON + imagen PNG).
- Classification report por clase.
- Artefactos en MinIO `modelos/evaluacion/`.

**Métricas actuales (modelo `modelo_20260525_114431.pkl`, prompt Manchester + score_ansiedad):**

| Métrica | Valor |
|---------|-------|
| CV F1 macro (5-fold) | 0.850 ± 0.069 |
| Recall C2 (Naranja) | 0.970 |
| F1 C2 (Naranja) | 0.985 |
| F1 C3 (Amarillo) | 0.983 |
| F1 C4 (Verde) | 0.977 |
| F1 C5 (Azul) | 0.933 |
| F1 C1 (Rojo) | 0.000 (sin casos en dataset — ver nota) |

**¿Por qué el F1 macro es 0.850 si los F1 por clase son todos ≥ 0.933?**

El F1 macro hace la media aritmética de los F1 de todas las clases sin ponderar por tamaño. C1 tiene soporte 0 en el dataset — su F1 es 0.0 — y ese cero arrastra la media hacia abajo. Si se excluye C1, el F1 macro sobre las clases operativas es **0.969**.

| Clases incluidas | F1 macro |
|-----------------|----------|
| C1 + C2 + C3 + C4 + C5 (sklearn, oficial) | 0.850 |
| C2 + C3 + C4 + C5 (clases con datos reales) | **0.969** |

**¿Por qué no hay casos C1 en el dataset y eso es correcto?**

C1 en Manchester es reanimación inmediata: paradas cardiorrespiratorias, traumatismos graves, inconsciencia. Estos pacientes no generan transcripciones porque no hay entrevista posible — llegan sin capacidad de comunicación y el triaje se hace por observación directa. El sistema procesa texto hablado por el paciente, por lo que C1 está fuera del alcance de diseño. La ausencia de C1 en el dataset no es un gap de datos — es una característica correcta del dominio.

El recall C2 = 0.970 es el resultado más importante: el modelo casi no pierde casos de emergencia (falla 1 de cada 33 en validación cruzada). En triaje clínico, un falso negativo en C2 (clasificar como C3 a un paciente que es C2) puede costar una vida.

---

### PASO 8 — Predicción Fase 2: `services/ml_predictor/service.py`

**Función:** `predict(texto, filename) -> dict`

Este es el corazón de la Fase 2. Lo que ejecuta `POST /predecir/`:

```
Cliente → FastAPI /predecir/ → predict()
```

**Pipeline interno (con referencias de código):**

```python
# 1. GUID nuevo + registro en Postgres
guid = new_guid()  # UUID4
pg_execute("INSERT INTO Entrevista ... VALUES (%s, %s, ...)", (guid, "INGESTED", ...))

# 2. Subir texto a MinIO (trazabilidad)
url_texto = minio_upload_text(BUCKET_TEXTOS, f"fase2/{guid}.txt", texto)

# 3. Enriquecer con LLM (reutiliza toda la cadena de Fase 1)
resultado_llm = enrich(guid, texto)
# → enrich() llama a preprocess() + call_llm() + persiste en Entidad + ResultadoML

# 4. Cargar el modelo más reciente de MinIO
model, model_name = load_latest_model()
# load_latest_model(): lista objetos "modelo_*" en MinIO, ordena alfabéticamente,
# carga el último con joblib.load()

# 5. Construir vector de features y predecir
X = pd.DataFrame([row_from_llm_result(resultado_llm, especialidad)])[FEATURES]
pred      = int(model.predict(X)[0])          # nivel 1-5
proba     = model.predict_proba(X)[0]
confianza = float(max(proba))                  # prob. de la clase predicha

# 6. Valoración automática (0-10)
nivel_llm    = resultado_llm.get("nivel_triaje") or pred
discrepancia = abs(pred - nivel_llm)
valoracion   = round(max(0.0, confianza - discrepancia * 0.25) * 10, 1)

# 7. Guardar predicción + COMPLETADA
pg_execute("UPDATE ResultadoML SET prediccion_modelo=%s, confianza=%s ...", ...)
pg_execute("UPDATE Entrevista SET Estado='COMPLETADA' ...", ...)
```

**Fórmula de valoración — justificación:**

```
valoracion = max(0, confianza - |pred_RF - nivel_LLM| × 0.25) × 10
```

- Si el RF predice C2 con 96 % de confianza y el LLM también dice C2 → `(0.96 - 0) × 10 = 9.6`
- Si el RF predice C3 (0.85 confianza) pero el LLM dice C2 (discrepancia=1) → `(0.85 - 0.25) × 10 = 6.0`
- Si el RF predice C4 (0.80 confianza) pero el LLM dice C2 (discrepancia=2) → `(0.80 - 0.50) × 10 = 3.0`

La valoración combina dos señales: la certeza interna del modelo y su acuerdo con el criterio del LLM. Una valoración baja indica que el médico debe revisar el caso.

**Respuesta JSON completa:**
```json
{
  "GUID": "f3a2-91bc-...",
  "nivel_triaje_predicho": 2,
  "nivel_manchester": "C2",
  "nivel_triaje_llm": 2,
  "score_urgencia": 91.0,
  "score_ansiedad": 0.3,
  "confianza": 0.93,
  "valoracion": 9.3,
  "motivo_consulta": "Dolor torácico intenso con disnea en paciente con antecedente de infarto",
  "justificacion": "Alta sospecha de SCA. Nivel 2 según MTS.",
  "entidades_normalizadas": ["dolor torácico", "disnea", "taquicardia"]
}
```

---

### PASO 9 — Interfaz clínica: `app/streamlit_app.py`

La Streamlit es el frontend para el médico. Dos modos de entrada:

**Modo audio:** el médico sube un `.wav`/`.mp3`/`.m4a`. La app llama a:

```python
from whisper_utils import transcribe_audio
texto_entrada = transcribe_audio(audio_file.read())
```

`app/whisper_utils.py` usa `faster-whisper` (versión optimizada de Whisper de OpenAI). El modelo descargado automáticamente (`"small"` por defecto) transcribe a texto en español. La transcripción se muestra al médico antes de enviarla a la API — puede corregirla si es necesario.

**Modo texto:** el médico pega o escribe la transcripción directamente en español.

**Tras el análisis (`POST /predecir/`):**

1. **Badge Manchester** — HTML renderizado vía `st.markdown(unsafe_allow_html=True)`:
   ```python
   MANCHESTER = {
       1: {"codigo": "C1", "nombre": "Inmediato", "color": "#d32f2f", ...},
       2: {"codigo": "C2", "nombre": "Muy Urgente", "color": "#f57c00", ...},
       ...
   }
   ```
   El badge muestra el código + nombre + color de fondo del nivel predicho.

2. **Métricas principales** en tres columnas: `score_urgencia / 100`, `confianza del RF`, `valoración / 10`.

3. **Badge de ansiedad** — función `ansiedad_badge(score)`:
   - `< 0.4` → verde "Paciente tranquilo"
   - `0.4-0.7` → amarillo "Ansiedad moderada"
   - `0.7-0.86` → naranja "⚠️ Ansiedad alta"
   - `>= 0.86` → rojo "⚠️ Pánico extremo"

4. **Alerta de under-triage** — si `nivel_predicho > nivel_llm`:
   ```python
   if nivel > nivel_llm:
       st.warning("⚠️ Posible under-triage: el modelo predice C3 pero el LLM asignó C2.")
   ```
   Esto ocurre cuando el RF bajó el nivel de urgencia respecto al criterio del LLM. El médico debe revisar clínicamente el caso.

5. **Tabla de auditoría ética** — expander al pie de la página que llama a `GET /metricas/auditoria`:
   ```python
   df_audit = fetch_auditoria()  # → pd.DataFrame
   st.dataframe(df_audit)
   ```

---

### PASO 10 — Auditoría ética: `services/metricas/router.py`

**Concepto clave antes del código:** un paciente muy ansioso describe sus síntomas de forma más dramática. El LLM puede captar esa ansiedad y asignar C2; el RF puede ver que clínicamente los síntomas objetivos no justifican C2 y predecir C3. ¿Quién tiene razón? No lo sabemos — pero sí sabemos que ese caso merece una segunda mirada. La auditoría no acusa al modelo de estar equivocado; le dice al médico "aquí hay una discrepancia, revísalo tú".

**Endpoint `GET /metricas/auditoria`:**

```python
# Criterio de under-triage:
WHERE prediccion_modelo > nivel_triaje   -- RF predice nivel MENOS urgente
  AND score_ansiedad >= 0.7             -- paciente con ansiedad alta
```

Un caso está marcado como posible under-triage cuando el RF "bajó" el nivel de urgencia respecto al LLM (ej. LLM dice C2 pero el RF dice C3) y además el paciente mostraba ansiedad alta. La hipótesis es que el RF puede haber sobre-ponderado la ansiedad como señal de urgencia durante el entrenamiento, pero al ver muchos casos ansiosos de baja urgencia, aprende a ignorarlos — y en ocasiones puede ir demasiado lejos.

La auditoría no implica que el RF se equivocó — implica que ese caso merece revisión clínica. El LLM y el RF son dos fuentes de criterio distintas; cuando discrepan en presencia de ansiedad, la prudencia clínica manda revisar.

**Endpoint `GET /metricas/`:**  
Agrega estadísticas del pipeline completo: distribución de estados, latencia media por fase, throughput (casos/hora), distribución de niveles predichos, errores. Útil para monitorización y para la demo.

---

## Features del modelo ML

| Feature | Tipo | Valores | Fuente | Por qué |
|---------|------|---------|--------|---------|
| `edad` | int | entero o -1 | LLM | Factor de riesgo cardiovascular |
| `sexo` | int | 1=M, 0=F, -1 | LLM | Diferencias en presentación de IAM |
| `dolor_intensidad` | int | 0-10 o -1 | LLM | Escala EVA; clave en C2/C3 |
| `disnea` | int | 0/1 | LLM | Síntoma cardinal de urgencia |
| `fiebre` | int | 0/1 | LLM | Sepsis / infección grave |
| `perdida_consciencia` | int | 0/1 | LLM | Siempre C1 o C2 |
| `irradiacion` | int | 0/1 | LLM | Patrón del dolor cardíaco |
| `antecedentes_cardiacos` | int | 0/1 | LLM | Aumenta riesgo C2 |
| `fumador` | int | 0/1 | LLM | Factor de riesgo |
| `score_urgencia` | float | 0-100 | LLM | Criterio holístico del LLM |
| `score_ansiedad` | float | 0.0-1.0 | LLM | Señal emocional — auditoria + feature |

**Target:** `nivel_triaje` (int 1-5, equivalente Manchester C1-C5).

---

## Desbalanceo de clases

| Nivel | Casos aprox. | % |
|-------|-------|---|
| C1 (Rojo) | 2-3 | <1 % |
| C2 (Naranja) | 9 | 3.3 % |
| C3 (Amarillo) | ~200 | 73.5 % |
| C4 (Verde) | ~44 | 16.2 % |
| C5 (Azul) | ~15 | 5.5 % |

Sin `class_weight`, el RF aprende a predecir casi siempre C3. Con `'balanced'`, el peso por clase es inversamente proporcional a su frecuencia — el RF penaliza mucho más los fallos en C2 que en C3. Resultado: recall C2 = 1.0 (ningún caso de emergencia perdido).

---

## Modelo de datos (Postgres)

Fuente de verdad: `sql/schema.sql`.

| Tabla | Rol |
|-------|-----|
| **Entrevista** | GUID, URLs (texto, dataset, modelo), timestamps por fase, `Estado`, `nombre_fichero`, `especialidad`, `origen` (`dataset`\|`simulacion`) |
| **Entidad** | Pares entidad cruda / normalizada por entrevista |
| **ResultadoML** | Features del LLM, `score_urgencia`, `score_ansiedad`, `nivel_triaje` (ground truth LLM), `prediccion_modelo`, `confianza`, `valoracion` |

**Campo `origen`:** distingue los 272 casos de entrenamiento (`'dataset'`) de las predicciones a demanda Fase 2 (`'simulacion'`). Evita contaminar futuros re-entrenamientos con predicciones del propio modelo.

**Índice clave:** `UNIQUE INDEX idx_resultado_guid_unique ON ResultadoML(GUID_Entrevista)` — permite UPSERT al re-enriquecer sin duplicar filas. Es la razón de que `ON CONFLICT DO UPDATE` funcione en `enrich()`.

---

## Justificación de decisiones clave

### ¿Por qué LLM + RF y no LLM solo?
El LLM actúa como **anotador clínico**: normaliza el lenguaje coloquial ("me ahogo" → disnea, "me duele el pecho" → dolor torácico) y extrae estructura de texto libre. El RF actúa como **decisor estadístico**: aprende de los 272 casos etiquetados y produce una predicción auditable con importancia de features.  
Un LLM como clasificador directo no es reproducible (temperature > 0) ni auditable en contexto clínico. El RF sí: se puede mostrar qué features pesaron más en cada predicción.

### ¿Por qué Ollama local y no siempre OpenRouter?
Para el batch de 272 casos: sin rate limits (429), sin envío de datos clínicos a terceros, `temperature=0` garantiza reproducibilidad. Para la demo en portátil sin GPU: OpenRouter con modelo gratuito es perfectamente válido para 2-3 predicciones. El sistema soporta ambos con una variable de entorno (`LLM_PROVIDER`).

### ¿Por qué Airflow como orquestador?
Los DAGs de Airflow modelan el pipeline como un grafo dirigido acíclico con dependencias, reintentos, logs por tarea y UI de monitorización. Alternativa obvia: scripts Python encadenados. El problema es que un script que falla a mitad no sabe por dónde retomar. Airflow mantiene el estado por tarea — si `dag_llm_enrichment` falla en el caso 143, se reintenta desde el 143, no desde el 1.

### ¿Por qué `score_ansiedad` como feature Y señal de auditoría?
El prompt del LLM enseña explícitamente la diferencia entre ansiedad y urgencia clínica. Al incluirlo como feature, el RF aprende que ansiedad alta en un caso C4 no justifica subir el nivel. Al monitorizarlo en `/metricas/auditoria`, el médico puede revisar los casos donde la discrepancia RF/LLM coincide con ansiedad alta — posible sesgo emocional del modelo.

---

## Gestión de errores

| Escenario | Comportamiento |
|---|---|
| LLM no responde (Ollama caído) | Timeout 120s + estado `ERROR_ENRICHMENT`. Re-trigger del DAG reintenta. |
| OpenRouter 429 (rate limit) | Backoff exponencial hasta 4 reintentos. Añadir `LLM_DELAY_SEC=2` en `.env` para prevenir. |
| OpenRouter 401 (auth) | El cliente lanza excepción inmediata. Verificar `OPENROUTER_API_KEY` en `.env`. |
| Modelo no existe en MinIO | `load_latest_model()` lanza `FileNotFoundError("MODEL_NOT_FOUND")`. FastAPI responde HTTP 503. |
| Buckets MinIO inexistentes | `docker compose run --rm minio-init` antes del primer DAG. |
| Un .txt corrupto en ingesta | Se marca individualmente como `ERROR_INGESTION`. No bloquea los demás 271 ficheros. |
| API contenedor no ve .env actualizado | `docker compose up -d --force-recreate api` — las variables se inyectan en la creación del contenedor, no en el restart. |
| MinIO accessible en localhost:9000 pero no en localhost:9001 | 9000 es la API S3. 9001 es la consola web. El cliente MinIO siempre usa 9000. |

---

## Preparación para la defensa

La defensa dura 15-20 minutos divididos en tres bloques: Fase 1 (datos y LLM), Fase 2 (modelado y desbalanceo) y Fase 3 (demo en vivo + auditoría). A continuación, las preguntas más probables con la respuesta correcta para cada una.

---

### Antes del día: checklist obligatorio

- [ ] **Tres audios de prueba preparados** — el documento de orientación los pide explícitamente:
  - *Urgente (C2):* "Llevo dos horas con un dolor muy fuerte en el pecho, me cuesta respirar, ya tuve un infarto hace dos años..."
  - *Leve (C4):* "Me torcí el tobillo jugando al fútbol, me duele al caminar pero puedo apoyar el pie..."
  - *Medio (C3):* "Llevo tres días con fiebre de 38 y medio, me duele la garganta y estoy muy cansado..."
- [ ] Docker corriendo + Streamlit accesible en `localhost:8501`
- [ ] Hacer una predicción de prueba con cada audio antes de entrar
- [ ] Coordinarse con el compañero: ambos deben conocer la totalidad del proyecto

---

### FASE 1 — Datos, transcripción y LLM

**"¿Cómo justificáis la elección del LLM?"**

> Para el batch de 272 casos usamos Ollama con `llama3.1:8b`: coste cero, sin rate limits, sin envío de datos clínicos a terceros, latencia baja en local. Para la demo usamos OpenRouter (Gemini Flash) porque el portátil no tiene GPU — el modelo gratuito es suficiente para 2-3 predicciones. El sistema soporta ambos con una sola variable de entorno (`LLM_PROVIDER`) sin cambiar código.

**"¿Qué técnicas de prompting utilizasteis?"**

> Cuatro técnicas combinadas: (1) *role prompting* ("eres un sistema experto en triaje médico"), (2) *few-shot* con dos ejemplos calibrados, (3) *Structured Outputs* (`format=json` fuerza JSON válido en cada respuesta), (4) `temperature=0` para reproducibilidad total. Además, la "regla de oro" en el prompt instrucción: ante duda, asignar el nivel más urgente.

**"¿Es válido usar el LLM como ground truth?"** *(pregunta trampa — la más importante de la Fase 1)*

> Es una limitación conocida del sistema: las etiquetas las genera el LLM, no un médico real. La mitigamos de tres formas: `temperature=0` garantiza que la misma transcripción produce siempre la misma etiqueta; los ejemplos few-shot anclan el criterio clínico al estándar Manchester; y la regla de oro reduce el riesgo de under-triage sistemático. El RF aprende a replicar ese criterio de forma reproducible y auditable — que es exactamente el objetivo del sistema.

**"Explicad la arquitectura de almacenamiento (Data-Lake)"**

> Dos capas complementarias. MinIO actúa como Data-Lake con tres buckets: `textos-originales/` (los `.txt` crudos), `datasets/` (CSVs de entrenamiento versionados con timestamp) y `modelos/` (`.pkl` serializados versionados). Postgres actúa como registro de estado: cada transcripción tiene un GUID único, un estado (`INGESTED → ENRICHED → COMPLETADA`) y timestamps de inicio y fin por fase — trazabilidad completa del pipeline.

**"¿Qué pasa si el LLM falla durante el enriquecimiento?"**

> La transcripción queda en estado `ERROR_ENRICHMENT` en Postgres. Airflow reintenta automáticamente hasta 3 veces con backoff exponencial. Si agota los reintentos, la tarea queda en `failed` en la UI de Airflow y el caso puede re-procesarse relanzando el DAG — que solo procesa los casos en `INGESTED` o `ERROR_ENRICHMENT`, no los ya completados.

---

### FASE 2 — Modelado, normalización y desbalanceo

**"¿Cómo transformasteis texto libre en variables numéricas sin generar redundancias?"**

> En `services/ml_features.py` cada tipo de dato tiene su función de codificación: los booleanos clínicos (`disnea`, `fiebre`…) con `as_bool()` → 0/1; `sexo` con `encode_sexo()` → M=1, F=0; `edad` y `dolor_intensidad` con `encode_optional_int()` → -1 si no se menciona. Las features son clínicamente independientes entre sí — cada una mide un síntoma distinto. La única correlación potencial es entre `score_urgencia` y las features individuales, ya que `score_urgencia` es un resumen holístico del LLM; la incluimos deliberadamente como señal global adicional.

**"¿Por qué -1 para valores desconocidos y no 0 o la media?"**

> 0 tiene significado clínico: `dolor_intensidad=0` significa "el paciente no tiene dolor". `dolor_intensidad=-1` significa "la transcripción no lo menciona". Son situaciones distintas y el modelo debe aprenderlas por separado. Imputar la media sería deshonesto — introduciría un valor artificial que no existe en los datos. Con -1 el RF trata "dato no disponible" como una categoría propia, que es la realidad de las urgencias.

**"¿Por qué class_weight y no SMOTE?"**

> SMOTE genera muestras sintéticas interpolando entre casos existentes. Con solo 9 casos C2 y features mixtas (booleanos + enteros + valores -1), SMOTE generaría casos C2 clínicamente irreales — habría que usar SMOTE-NC, más complejo, y aun así el resultado sería datos inventados. Con `class_weight='balanced'` no tocamos los datos: solo le decimos al modelo que cada error en C2 pesa ~15 veces más que uno en C3. Es más conservador y apropiado con un dataset pequeño. El resultado: recall C2 pasó de 0.0 a 1.0. En el modelo final (tras re-enriquecimiento con prompt Manchester) se mantiene en 0.970.

**"¿Por qué Random Forest y no XGBoost o una red neuronal?"**

> Con 272 muestras y 11 features, los modelos profundos sobreajustan. Además, entrenamos una Regresión Logística como baseline para comparar empíricamente — el RF la supera. RF tiene tres ventajas clave aquí: interpretabilidad (importancia de features defendible ante el tribunal), no necesita GPU para inferencia en Fase 2, y es robusto con datos tabulares mixtos incluyendo el -1. XGBoost habría sido la siguiente opción si necesitáramos más rendimiento.

**"¿Por qué F1 macro y no accuracy para evaluar?"**

> Con un dataset donde el 73% de los casos son C3, un modelo que predijera siempre C3 tendría un accuracy del 73% sin aprender nada. F1 macro calcula el F1 por clase y hace la media sin ponderar por frecuencia — penaliza igual un fallo en C2 (9 casos) que en C3 (200 casos). Es la métrica correcta cuando las clases minoritarias son las más importantes clínicamente.

**"¿Qué significa recall C2 = 0.970?"**

> Que el modelo detecta el 97% de los casos de emergencia. De todos los pacientes que realmente eran C2, el modelo identificó correctamente 32 de 33 en validación cruzada. En triaje clínico ese es el resultado más importante: un falso negativo en C2 (clasificarlo como C3) puede costar una vida. El 0.970 es prácticamente perfecto dado el dataset de solo 9 casos C2 en entrenamiento.

**"¿Por qué el F1 macro es 0.850 si los F1 por clase son todos ≥ 0.933?"**

> El F1 macro hace la media aritmética de todas las clases sin ponderar. C1 (reanimación inmediata) tiene soporte 0 en el dataset — su F1 es 0.0 — y arrastra la media. C1 no tiene casos porque esos pacientes no generan transcripciones: llegan inconscientes o en parada, el triaje es por observación directa, no por entrevista. Excluyendo C1, el F1 macro sobre las clases operativas es 0.969. La ausencia de C1 no es un gap de datos — es una característica correcta del dominio.

**"¿Por qué la especialidad no es una feature del modelo si está codificada en ml_features.py?"**

> `ESPECIALIDAD_MAP` existe y `encode_especialidad()` se llama en `row_from_llm_result()`, pero `especialidad` no está en la lista `FEATURES`. La razón: el nivel Manchester es una medida de urgencia clínica objetiva, independiente de la especialidad por la que entró el paciente. Un C2 puede aparecer en cardiología, respiratorio o musculoesquelético. Incluir la especialidad podría introducir un sesgo de departamento que no tiene base clínica.

---

### FASE 3 — Demo y auditoría

**"Explica la cadena completa de inferencia en tiempo real"**

> Audio → `faster-whisper` transcribe a texto en español → el médico ve y puede corregir la transcripción → `POST /predecir/` → preprocesado (extrae texto del paciente) → LLM extrae 14 campos clínicos en JSON → `ml_features.py` codifica el vector → RF predice nivel 1-5 + confianza → se calcula valoración (0-10) → Streamlit muestra badge de color Manchester + score de ansiedad + alerta de under-triage si RF < LLM.

**"¿Cómo se calcula la valoración (0-10)?"**

> `valoracion = max(0, confianza - |pred_RF - nivel_LLM| × 0.25) × 10`. Combina dos señales: la certeza interna del RF (probabilidad de la clase predicha) y su concordancia con el criterio del LLM. Si ambos dicen C2 con confianza 0.96 → valoración 9.6. Si el RF dice C3 pero el LLM dice C2 con confianza 0.85 → valoración 6.0. Una valoración baja es la señal para que el médico revise el caso.

**"¿Cómo funciona la auditoría ética de under-triage?"**

> El endpoint `GET /metricas/auditoria` ejecuta: `WHERE prediccion_modelo > nivel_triaje AND score_ansiedad >= 0.7`. Marca los casos donde el RF predijo un nivel menos urgente que el LLM y el paciente tenía ansiedad alta. La hipótesis: el RF puede haber aprendido a ignorar la ansiedad (correcto) pero en ocasiones infravalora casos donde la ansiedad enmascara síntomas reales. La tabla no acusa al modelo — le dice al médico "aquí hay discrepancia, revísalo tú".

**"¿Qué pasa si Whisper transcribe mal?"**

> La transcripción se muestra al médico antes de enviarse a la API. Puede corregirla en el campo de texto antes de pulsar "Analizar". El sistema no es un autómata — el médico siempre tiene la última palabra.

**"Si RF y LLM discrepan, ¿a cuál hacéis caso?"**

> El sistema muestra ambos niveles y calcula la valoración para capturar esa discrepancia. Ninguno tiene autoridad automática — la decisión final es siempre del médico. La auditoría registra esos casos para revisión posterior. Eso es exactamente lo que debe hacer un sistema de *soporte* a decisiones clínicas: informar, no decidir.

---

### Preguntas de comprensión individual

**"¿Qué limitaciones tiene el sistema?"**

> Cuatro principales: (1) el ground truth es LLM-generado, no validado por médicos reales; (2) 272 muestras es un dataset pequeño para producción clínica real; (3) el sistema fue entrenado con transcripciones en inglés — aunque funciona en español, no ha sido evaluado específicamente en ese idioma; (4) pacientes con trastorno de ansiedad conocido pueden ser sobre-triados — la regla de oro asigna C2 ante disnea + malestar torácico aunque el cuadro sea una crisis de pánico con diagnóstico previo confirmado.

**"¿Qué mejorarías si tuvieras más tiempo?"**

> Cuatro mejoras concretas:
>
> (1) **`antecedente_ansiedad` como feature.** El LLM ya extrae `antecedentes_cardiacos`; añadir un booleano equivalente para trastorno de ansiedad/pánico permitiría al RF aprender que `antecedente_ansiedad=true + disnea=true + sin dolor torácico real → C3`, evitando el sobre-triaje de crisis de pánico conocidas. Requeriría re-enriquecer las 272 transcripciones y reentrenar.
>
> (2) **Tercer ejemplo few-shot calibrado.** El prompt tiene dos ejemplos: SCA claro (C2) y ansiedad sin disnea (C3). Añadir un tercero con disnea funcional real + diagnóstico de pánico confirmado + C3 enseñaría al LLM la distinción más difícil sin tocar el código ni los datos.
>
> (3) **Validación clínica de etiquetas.** Una muestra de 30-50 casos revisados por médico de urgencias confirmaría si el LLM etiqueta correctamente los casos límite C2/C3.
>
> (4) **Explicabilidad por caso.** Ahora el sistema muestra importancia global de features (score_urgencia > score_ansiedad > edad…). Con SHAP o LIME se podría mostrar qué features concretas llevaron al RF a esa predicción para cada paciente individual — trazabilidad clínica real.

**"¿Podría el modelo estar aprendiendo del ruido del LLM?"**

> Sí, es un riesgo conocido. Si el LLM comete errores sistemáticos en el etiquetado, el RF los aprenderá. Lo mitigamos con `temperature=0` (errores deterministas y detectables), few-shot calibrado y la regla de oro. En producción real, la validación clínica de una muestra de etiquetas sería el siguiente paso.

---

## Variables de entorno relevantes

| Variable | Valor típico | Descripción |
|----------|-------------|-------------|
| `LLM_PROVIDER` | `ollama` / `openrouter` | Selecciona el backend LLM |
| `OLLAMA_MODEL` | `llama3.1:8b` | Modelo Ollama (debe estar descargado en el host) |
| `OPENROUTER_MODEL` | `google/gemini-2.0-flash-001` | Modelo OpenRouter gratuito |
| `OPENROUTER_API_KEY` | `sk-or-v1-...` | Clave OpenRouter (sin 's' extra al inicio) |
| `LLM_MAX_RETRIES` | `4` | Reintentos ante 429 |
| `LLM_RETRY_BASE_SEC` | `15` | Espera base del backoff exponencial |
| `LLM_DELAY_SEC` | `0` (Ollama) / `2` (OpenRouter demo) | Pausa entre llamadas al LLM |
| `LLM_BATCH_LIMIT` | `0` (sin límite) | Nº máximo de casos a enriquecer por ejecución |
| `MINIO_ENDPOINT` | `http://minio:9000` | Interno Docker — `setup.py` lo fuerza a localhost |
| `API_BASE_URL` | `http://api:8000` | Los DAGs llaman al servicio api por nombre de servicio Docker |
