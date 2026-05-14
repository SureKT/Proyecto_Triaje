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
│               Ollama local ◄── GPU (4060 Ti 16 GB)                  │
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
│  Cliente ──► POST /predecir (FastAPI)                               │
│                   │                                                 │
│                   ├──► MinIO (guarda .txt)                          │
│                   ├──► Postgres (crea registro GUID)                │
│                   └──► Airflow REST API                             │
│                              │                                      │
│                              ▼                                      │
│                    [dag_prediction]                                  │
│                    │              │                                  │
│              [llm_enrichment]  [ml_predictor]                       │
│              (features)        (modelo.pkl)                         │
│                    │                                                │
│                    ▼                                                │
│             Postgres (guarda predicción)                            │
│                    │                                                │
│                    ▼                                                │
│         FastAPI devuelve resultado al cliente                       │
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
INGESTED → PREPROCESSED → ENRICHED → DATASET_READY → MODEL_TRAINED → EVALUATED
                                                                          │
                                                           (Fase 2)       ▼
                                                                    PREDICTED → COMPLETED
```

Cada transición registra `timestamp_inicio` y `timestamp_fin` en la tabla `Entrevista`.

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
- Guarda el CSV en MinIO (`datasets/dataset_entrenamiento.csv`).
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

1. **Cliente** envía `POST /predecir` al servicio FastAPI con el fichero `.txt`.
2. **FastAPI** sube el fichero a MinIO, crea un registro con nuevo GUID en Postgres (estado `INGESTED`) y llama a la API REST de Airflow para disparar `dag_prediction`.
3. **`dag_prediction`** llama al servicio `llm_enrichment` para extraer features, carga el modelo desde MinIO y genera la predicción de nivel de triaje.
4. El resultado se guarda en `ResultadoML` (estado `PREDICTED`).
5. **FastAPI** consulta el resultado en Postgres y lo devuelve al cliente (estado final `COMPLETED`).

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

```sql
CREATE TABLE Entrevista (
    GUID_Entrevista             VARCHAR(255) PRIMARY KEY,
    URL_Texto_Original          VARCHAR(255),
    URL_Dataset_Generado        VARCHAR(255),
    URL_Modelo_Entrenado        VARCHAR(255),
    Inicio_Solicitud            TIMESTAMP,
    Fin_Solicitud               TIMESTAMP,
    Inicio_Preprocesamiento     TIMESTAMP,
    Fin_Preprocesamiento        TIMESTAMP,
    Inicio_Extraccion_Entidades TIMESTAMP,
    Fin_Extraccion_Entidades    TIMESTAMP,
    Inicio_Normalizacion        TIMESTAMP,
    Fin_Normalizacion           TIMESTAMP,
    Inicio_Etiquetado           TIMESTAMP,
    Fin_Etiquetado              TIMESTAMP,
    Inicio_Score                TIMESTAMP,
    Fin_Score                   TIMESTAMP,
    Inicio_Entrenamiento        TIMESTAMP,
    Fin_Entrenamiento           TIMESTAMP,
    Motor_Workflow              VARCHAR(50),   -- 'airflow'
    Workflow_Id                 VARCHAR(255),
    Estado                      VARCHAR(50)
);

CREATE TABLE Entidad (
    id                  SERIAL PRIMARY KEY,
    GUID_Entrevista     VARCHAR(255) REFERENCES Entrevista(GUID_Entrevista),
    entidad_raw         TEXT,
    entidad_normalizada TEXT,
    tipo                VARCHAR(100)
);

CREATE TABLE ResultadoML (
    id                  SERIAL PRIMARY KEY,
    GUID_Entrevista     VARCHAR(255) REFERENCES Entrevista(GUID_Entrevista),
    nivel_triaje        INT,
    score_urgencia      FLOAT,
    etiqueta_llm        INT,
    prediccion_modelo   INT,
    confianza           FLOAT,
    valoracion          FLOAT,
    timestamp_pred      TIMESTAMP
);
```

---

## Justificación del uso del LLM

Las transcripciones son texto clínico no estructurado con variabilidad léxica alta: el paciente describe "me ahogo" y el término médico es "disnea". Un parser de reglas no puede cubrir esa variabilidad de forma fiable.

El LLM (Llama 3.1 70B ejecutado localmente con Ollama) actúa como extractor y anotador clínico: normaliza entidades, aplica criterios del Sistema Español de Triaje y devuelve un JSON estructurado que alimenta directamente al modelo ML. Esto separa la comprensión del lenguaje natural (LLM) de la decisión estadística (ML), haciendo el pipeline más interpretable y auditable.

Ollama se usa en lugar de una API externa para eliminar costes y dependencias de red.

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
