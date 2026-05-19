# Documentación Funcional — Triaje IA

## Diagrama de arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FASE 1 — batch                               │
│                                                                     │
│  text/*.txt ──► [dag_text_ingestion]                                │
│                        │                                            │
│               Postgres + MinIO                                      │
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
│                        │                                            │
│                        ▼                                            │
│              [dag_dataset_builder] ──► CSV en MinIO                 │
│                        │                                            │
│                        ▼                                            │
│              [dag_model_training] ──► modelo.pkl en MinIO           │
│                        │                                            │
│                        ▼                                            │
│               [dag_evaluation] ──► métricas + artefactos           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                       FASE 2 — a demanda                            │
│                                                                     │
│  Cliente ──► POST /predecir/ (FastAPI, ml_predictor)                  │
│                   │                                                 │
│                   ├──► MinIO (guarda .txt)                          │
│                   ├──► Postgres (crea registro GUID)                │
│                   ├──► llm_enrichment (preprocess + LLM)            │
│                   ├──► carga modelo .pkl desde MinIO                │
│                   └──► Postgres (predicción, estado PREDICTED)      │
│                                                                     │
│  (Opcional) dag_prediction + Airflow REST para orquestación async   │
└─────────────────────────────────────────────────────────────────────┘

Capa de persistencia transversal:
┌──────────────────┐    ┌────────────────────────────────────┐
│     Postgres     │    │               MinIO                │
│                  │    │  textos-originales/                │
│  Entrevista      │    │  datasets/                         │
│  Entidad         │    │  modelos/                          │
│  ResultadoML     │    └────────────────────────────────────┘
└──────────────────┘
```

---

## Flujo de tareas completo

Cada texto arrastra un `GUID_Entrevista` desde la ingesta hasta la valoración final. Los estados posibles son:

```
INGESTED → (PREPROCESSING / PREPROCESSED dentro de enrich) → ENRICHED → DATASET_READY → MODEL_TRAINED → EVALUATED
                                                                          │
                                                           (Fase 2)       ▼
                                                                    PREDICTED → (COMPLETED, si se implementa)
```

En la implementación actual, el microservicio `llm_enrichment` ejecuta el preprocesado antes del LLM; los estados intermedios `PREPROCESSING` / `PREPROCESSED` se registran en columnas de timestamp de `Entrevista`. Cada transición relevante actualiza `Estado` y los timestamps en Postgres.

---

## Explicación del pipeline — Fase 1

### Paso 1: Ingesta (`dag_text_ingestion`)

- Lee todos los ficheros `.txt` de `text/` (272 transcripciones).
- Genera un `GUID_Entrevista` único por fichero (UUID4).
- Sube cada fichero a MinIO en el bucket `textos-originales/`.
- Inserta una fila en la tabla `Entrevista` con la URL del fichero y estado `INGESTED`.

### Paso 2: Enriquecimiento LLM (`dag_llm_enrichment`)

- Para cada entrevista en estado `INGESTED`, recupera el texto desde MinIO.
- Llama al microservicio `llm_enrichment`, que envía el texto a Ollama con un prompt clínico estructurado.
- El LLM devuelve un JSON con:
  - Entidades crudas y normalizadas (síntomas, medicamentos, patologías)
  - Nivel de triaje SET (1–5)
  - `score_urgencia` (0–100)
  - Features estructuradas: edad, sexo, dolor_intensidad, disnea, fiebre, etc.
- Guarda entidades en la tabla `Entidad` y el resto en `ResultadoML`.
- Actualiza estado a `ENRICHED`.

### Paso 3: Construcción del dataset (`dag_dataset_builder`)

- Consolida todos los registros `ENRICHED` de Postgres en un CSV.
- Columnas: `GUID`, `especialidad`, `edad`, `sexo`, `dolor_intensidad`, `disnea`, `fiebre`, `perdida_consciencia`, `irradiacion`, `antecedentes_cardiacos`, `fumador`, `score_urgencia`, `nivel_triaje`.
- Codificación para ML (`ml_features.py`): booleanos → 0/1; `sexo` M/F → 1/0; **-1 = desconocido** si edad, sexo o dolor no constan en la transcripción (el LLM devuelve `null`, no se inventan).
- Guarda el CSV en MinIO con nombre versionado (`datasets/dataset_entrenamiento_<timestamp>.csv`).
- Actualiza estado a `DATASET_READY`.

### Paso 4: Entrenamiento del modelo (`dag_model_training`)

- Carga el CSV desde MinIO.
- Separa train/test (80/20, estratificado por `nivel_triaje`).
- Entrena un **Random Forest** con las features estructuradas.
- Registra métricas (accuracy, F1-macro por clase) en Postgres.
- Serializa el modelo como `modelo_<timestamp>.pkl` y lo sube a MinIO (`modelos/`).
- Actualiza estado a `MODEL_TRAINED`.

### Paso 5: Evaluación (`dag_evaluation`)

- Carga el modelo desde MinIO.
- Ejecuta validación cruzada estratificada (5 folds).
- Genera matriz de confusión y classification report.
- Guarda artefactos en MinIO (`modelos/evaluacion/`).
- Registra métricas finales en Postgres.
- Actualiza estado a `EVALUATED`.

---

## Explicación del pipeline — Fase 2

**Implementación actual del endpoint `POST /predecir/`**

1. **Cliente** envía el fichero `.txt` (multipart) o texto en formulario.
2. **FastAPI** (`ml_predictor`) crea un nuevo `GUID_Entrevista`, sube el texto a MinIO (`fase2/<guid>.txt`) y llama a **`enrich()`** (preprocesado + LLM + persistencia en `Entidad` / `ResultadoML`).
3. Carga el **modelo más reciente** desde MinIO (`modelo_*.pkl`), calcula la predicción y actualiza `ResultadoML` y `Entrevista` (estado `PREDICTED`).
4. Devuelve al cliente un JSON con `nivel_triaje_predicho`, `nivel_triaje_llm`, `score_urgencia`, `confianza`, etc.

**DAG `dag_prediction`**

Existe para disparar el flujo vía Airflow (p. ej. con `dag_run.conf`); la integración completa con que el DAG use el mismo GUID que devuelve la API puede requerir ajuste (trazabilidad). El camino principal de prueba en desarrollo es la llamada directa a `/predecir/`.

---

## Ejemplos de entrada y salida

### Entrada — fragmento de transcripción

```
D: Buenos días, ¿cuál es el motivo de su consulta hoy?
P: Llevo dos días con un dolor en el pecho muy fuerte, me cuesta respirar
   y me noto el corazón acelerado.
D: ¿Puede valorar el dolor del 1 al 10?
P: Está en un 8, no me deja hacer nada.
D: ¿Tiene usted alguna enfermedad del corazón previa?
P: Sí, tuve un infarto hace tres años.
D: ¿Cuántos años tiene?
P: 67 años.
```

### Salida del LLM — JSON estructurado

```json
{
  "nivel_triaje": 2,
  "score_urgencia": 91.0,
  "motivo_consulta": "Dolor torácico intenso con disnea en paciente con antecedente de infarto",
  "entidades": ["dolor pecho", "cuesta respirar", "corazón acelerado"],
  "entidades_normalizadas": ["dolor torácico", "disnea", "taquicardia"],
  "edad": 67,
  "sexo": null,
  "dolor_intensidad": 8,
  "disnea": true,
  "fiebre": false,
  "perdida_consciencia": false,
  "irradiacion": false,
  "antecedentes_cardiacos": true,
  "fumador": false,
  "justificacion": "Dolor torácico 8/10 con disnea en paciente >40 años con antecedente de infarto. Alta sospecha de SCA. Nivel 2 según SET."
}
```

### Salida del modelo — predicción Fase 2

```json
{
  "GUID": "f3a2-91bc-...",
  "nivel_triaje_predicho": 2,
  "nivel_triaje_llm": 2,
  "score_urgencia": 91.0,
  "confianza": 0.87,
  "valoracion": null
}
```

---

## Modelo de datos

La **fuente de verdad** del esquema es el fichero `sql/schema.sql` del repositorio (init de Postgres). Resumen:

| Tabla | Rol |
|-------|-----|
| **Entrevista** | GUID, URLs (texto, dataset, modelo), timestamps de pipeline, `Estado`, `nombre_fichero`, `especialidad` |
| **Entidad** | Pares entidad cruda / normalizada por entrevista |
| **ResultadoML** | Features del LLM (`edad`, `sexo`, booleanos clínicos, `motivo_consulta`, `justificacion`), `score_urgencia`, `nivel_triaje` (etiqueta LLM en Fase 1), `prediccion_modelo` y `confianza` (Fase 2) |

Índice único: `ResultadoML(GUID_Entrevista)` (`idx_resultado_guid_unique`) para permitir UPSERT al re-enriquecer.

Para el DDL completo y los índices, ver `sql/schema.sql`.

---

## Justificación del uso del LLM

Las transcripciones son texto clínico no estructurado con variabilidad léxica alta: el paciente describe "me ahogo" y el término médico es "disnea". Un parser de reglas no puede cubrir esa variabilidad de forma fiable.

El LLM actúa como **extractor y anotador clínico** (modelo instruct configurable: p. ej. **Llama 3.1 8B** u otro vía **Ollama** en el host, o un modelo remoto vía **OpenRouter**): normaliza entidades, aplica criterios del Sistema Español de Triaje y devuelve un JSON estructurado que alimenta al modelo ML. Esto separa la comprensión del lenguaje natural (LLM) de la decisión estadística (ML), haciendo el pipeline más interpretable y auditable.

**Ollama** evita límites de cuota en el batch y no envía datos a terceros si todo corre en local. **OpenRouter** (u otra API compatible) es válida cuando el profesor o el equipo priorizan no depender de la GPU local.

---

## Justificación del modelo ML

Se elige **Random Forest** para clasificar el nivel de triaje (1–5) a partir de las features estructuradas extraídas por el LLM:

- **Interpretabilidad**: permite calcular importancia de features, relevante en contexto clínico.
- **Robustez con datasets pequeños y desbalanceados**: con ~272 casos, los árboles de decisión manejan mejor el sobreajuste que los transformers.
- **Sin requisitos de GPU** para inferencia, compatible con el pipeline de producción.
- **No requiere normalización de features numéricas**, lo que simplifica el preprocesado.

Se evalúa también Logistic Regression como baseline.

---

## Justificación del uso de Airflow

La ingesta y el enriquecimiento de 272 ficheros es un proceso batch con dependencias claras entre etapas: no se puede entrenar sin dataset, no hay dataset sin enriquecimiento. Airflow permite definir esas dependencias como DAG en Python, gestiona reintentos automáticos, registra logs por tarea y facilita la rejecución parcial si falla un paso intermedio.

Para la Fase 2, Airflow expone una API REST que permite disparar `dag_prediction` desde el endpoint FastAPI, manteniendo un único orquestador para todo el sistema. Esto simplifica la arquitectura y facilita la trazabilidad: todos los flujos, tanto batch como a demanda, quedan registrados en el mismo sistema de logs.
