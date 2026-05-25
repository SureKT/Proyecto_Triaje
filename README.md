# Triaje IA — Sistema de clasificación automática de urgencias

Pipeline completo de clasificación de urgencias hospitalarias según el **Sistema de Triaje Manchester (C1-C5)** a partir de transcripciones o audios de entrevista médico-paciente.

**Fase 1 (batch):** 272 transcripciones → LLM extrae features clínicas → Random Forest aprende a clasificar → modelo evaluado con CV 5-fold.  
**Fase 2 (a demanda):** `POST /predecir/` → enriquecimiento LLM + RF → nivel Manchester + valoración automática (0-10).  
**Fase 3 (MVP clínico):** Audio → Whisper → `/predecir/` → Streamlit con colores Manchester + auditoría ética de under-triage.

Orquestado con **Apache Airflow**. LLM: **Ollama en host** (recomendado) u **OpenRouter**. Persistencia: **Postgres** + **MinIO**.

Documentación interna de avance y decisiones: [`docs/diario-desarrollo.md`](docs/diario-desarrollo.md).

---

## Requisitos previos

- Docker y Docker Compose instalados
- **Ollama** en el host (recomendado para desarrollo) con un modelo instruct descargado, por ejemplo:
  ```bash
  ollama pull llama3.1:8b
  ```
  Opcional (más calidad, más VRAM / tiempo): `ollama pull llama3.1:70b-instruct-q4_K_M` o `ollama pull qwen2.5:14b-instruct`
- GPU con CUDA recomendable para modelos grandes; `llama3.1:8b` puede ejecutarse también en CPU (más lento)

---

## Cómo ejecutar el sistema

```bash
# 1. Clonar el repositorio
git clone <url-repositorio>
cd Proyecto_Triaje

# 2. Copiar y rellenar variables de entorno
cp .env.example .env

# 3. Crear buckets en MinIO (necesario antes de la ingesta)
docker compose run --rm minio-init

# 4. Levantar todos los servicios
docker compose up -d

# 5. Acceder a las interfaces (puertos del compose actual)
#    Airflow:  http://localhost:8088   (admin / admin por defecto)
#    API:      http://localhost:8002
#    MinIO:    http://localhost:9001
#    Postgres: localhost:5433  (mapeado desde 5432 en el contenedor)
```

### Ejecutar el pipeline completo — Fase 1

Activar los DAGs en orden desde la UI de Airflow o via CLI:

```bash
docker compose exec airflow-webserver airflow dags trigger dag_text_ingestion
# Esperar a que termine, luego continuar en orden:
# (dag_llm_enrichment puede procesar en lotes: ver LLM_BATCH_LIMIT en .env)
docker compose exec airflow-webserver airflow dags trigger dag_llm_enrichment
docker compose exec airflow-webserver airflow dags trigger dag_dataset_builder
docker compose exec airflow-webserver airflow dags trigger dag_model_training
docker compose exec airflow-webserver airflow dags trigger dag_evaluation
```

### Probar una predicción nueva — Fase 2

Requiere un modelo `.pkl` ya generado en MinIO (`dag_model_training` ejecutado).

```bash
curl -X POST http://localhost:8002/predecir/ \
  -F "file=@ruta/a/nueva_entrevista.txt"
```

Respuesta esperada (campos principales):

```json
{
  "GUID": "abc-123",
  "nivel_triaje_predicho": 3,
  "nivel_triaje_llm": 3,
  "score_urgencia": 62.5,
  "score_ansiedad": 0.45,
  "confianza": 0.85,
  "valoracion": 8.5,
  "motivo_consulta": "...",
  "justificacion": "...",
  "entidades_normalizadas": ["dolor torácico", "disnea"]
}
```

El campo `nivel_triaje_predicho` es un entero 1-5 que equivale a los niveles Manchester C1-C5. La app Streamlit lo muestra con el color correspondiente.

---

## Estructura del proyecto

```
Proyecto_Triaje/
├── text/                          # Transcripciones originales (272 ficheros .txt)
├── dags/                          # DAGs de Airflow
│   ├── dag_text_ingestion.py      # Ingesta .txt → Postgres + MinIO
│   ├── dag_llm_enrichment.py      # Extracción de entidades + etiquetado LLM
│   ├── dag_dataset_builder.py     # Construcción del CSV de entrenamiento
│   ├── dag_model_training.py      # Entrenamiento y guardado del modelo ML
│   ├── dag_evaluation.py          # Evaluación con CV 5-fold y matriz de confusión
│   └── dag_prediction_phase_2.py  # Predicción orquestada Fase 2 (dag_id: dag_prediction_phase_2)
├── services/                      # Microservicios Python (FastAPI, puerto 8002)
│   ├── preprocessor/              # Limpieza y normalización del texto
│   ├── llm_enrichment/            # Llamadas al LLM: entidades, triaje, scores
│   ├── dataset_builder/           # Generación del CSV estructurado
│   ├── ml_trainer/                # Entrenamiento y serialización del modelo
│   ├── ml_predictor/              # POST /predecir/ — pipeline completo Fase 2
│   ├── metricas/                  # GET /metricas/ — métricas agregadas en tiempo real
│   ├── ml_features.py             # Codificación de features compartida (train + predict)
│   └── main.py                    # FastAPI app — monta todos los routers
├── app/                           # [PENDIENTE] Streamlit + Whisper (Fase 3)
│   ├── streamlit_app.py           # Interfaz clínica: audio/texto → triaje Manchester
│   └── whisper_utils.py           # Transcripción de audio con faster-whisper
├── sql/
│   └── schema.sql                 # Esquema de tablas Postgres
├── docs/
│   ├── arquitectura.md            # Documentación técnica completa (referencia para defensa)
│   └── diario-desarrollo.md       # Cronología, fallos y decisiones (interno)
├── scripts/
│   ├── test_enrich.py             # Prueba manual POST /enriquecer/
│   └── validate_dataset_columns.py # Validación calidad dataset post-enriquecimiento
├── docker-compose.yml
├── .env.example
├── ROADMAP.md                     # Sprint de cierre 3 días + preguntas de defensa
└── README.md
```

### Lanzar la aplicación Streamlit — Fase 3

```bash
# Instalar dependencias de la app
pip install streamlit faster-whisper requests

# Lanzar (con los servicios Docker ya activos)
streamlit run app/streamlit_app.py
# Acceder en: http://localhost:8501
```

---

## Configuración en portátil / sin GPU (OpenRouter)

Si el equipo **no tiene GPU** o no se puede ejecutar Ollama localmente, usar **OpenRouter** como proveedor LLM:

1. Obtener API key gratuita en [openrouter.ai/keys](https://openrouter.ai/keys)
2. En el `.env`, configurar:
   ```env
   LLM_PROVIDER=openrouter
   OPENROUTER_API_KEY=sk-or-v1-...
   OPENROUTER_MODEL=google/gemini-2.0-flash-001
   ```
3. Levantar los servicios normalmente (`docker compose up -d`)
4. Subir el modelo pre-entrenado a MinIO ejecutando **una sola vez**:
   ```bash
   python setup.py
   ```
   Este script detecta automáticamente el endpoint correcto de MinIO y sube
   `models/modelo_latest.pkl` al bucket `modelos/`, habilitando `/predecir/` sin
   necesidad de re-entrenar.

5. Lanzar Streamlit:
   ```bash
   streamlit run app/streamlit_app.py
   ```

> **Nota:** Con OpenRouter gratuito y uso de demo (2-3 predicciones), no hay riesgo de rate limit.
> Para lotes grandes, añadir `LLM_DELAY_SEC=2` en el `.env`.

---

## Descripción de los servicios

### Airflow (puerto **8088** en el host)
Orquestador único del sistema. Ejecuta todos los DAGs (Fase 1 y Fase 2), gestiona dependencias entre tareas, registra logs por tarea y ejecuta reintentos automáticos. Cada tarea actualiza el estado de la entrevista en Postgres con timestamps de inicio y fin.

### API Python / FastAPI (puerto **8002** en el host)
Conjunto de microservicios invocados por los DAGs de Airflow. Cada servicio cubre una única etapa del pipeline: preprocesado de texto, llamada al LLM, construcción del dataset, entrenamiento del modelo y predicción. El endpoint **`POST /predecir/`** (Fase 2) recibe el fichero, crea el registro en Postgres, ejecuta **preprocesado + LLM + modelo ML** de forma síncrona y devuelve el JSON de resultado. Existe además el DAG `dag_prediction_phase_2` para orquestación vía Airflow si se integra con la API REST de Airflow.

### Postgres (puerto **5433** en el host → 5432 en el contenedor)
Fuente de verdad del estado del sistema. Almacena el estado de cada entrevista a lo largo de todo el pipeline, las entidades extraídas, las etiquetas asignadas por el LLM, los scores de urgencia, las predicciones del modelo y las valoraciones finales.

### MinIO (puertos 9000 / 9001)
Almacenamiento de objetos compatible con S3. Tres buckets:
- `textos-originales/` — ficheros `.txt` tal como se ingieren
- `datasets/` — CSVs generados para entrenamiento
- `modelos/` — modelos ML serializados y artefactos de evaluación

### Ollama (puerto 11434, en el host)
Procesa las transcripciones y devuelve JSON estructurado (entidades, `nivel_triaje`, `score_urgencia`, etc.). Corre en el host (no en Docker). Los contenedores lo alcanzan vía `host.docker.internal:11434`. Configuración: `LLM_PROVIDER=ollama` y `OLLAMA_MODEL` en `.env` (p. ej. `llama3.1:8b`).

### OpenRouter (opcional)
Si `LLM_PROVIDER=openrouter`, el servicio `llm_enrichment` llama a `https://openrouter.ai/api/v1` con `OPENROUTER_API_KEY` y `OPENROUTER_MODEL`. Útil si no hay GPU local; los modelos gratuitos pueden tener **rate limit** (HTTP 429).

---

## Descripción de los DAGs de Airflow

| DAG | Función | Estado resultante |
|---|---|---|
| `dag_text_ingestion` | Lee los `.txt` de `text/`, sube a MinIO, crea registros en Postgres con GUID único | `INGESTED` |
| `dag_llm_enrichment` | Por cada `INGESTED`, llama a `/enriquecer/` (preprocesado + LLM). Opcional: `LLM_BATCH_LIMIT` y `LLM_DELAY_SEC` en `.env` para lotes y pausa entre llamadas | `ENRICHED` |
| `dag_dataset_builder` | Consolida los datos de Postgres en CSV y lo guarda en MinIO | `DATASET_READY` |
| `dag_model_training` | Carga el CSV, entrena Random Forest, serializa el modelo en MinIO, registra métricas | `MODEL_TRAINED` |
| `dag_evaluation` | Valida el modelo con validación cruzada, genera matriz de confusión | `EVALUATED` |
| `dag_prediction_phase_2` | Descarga el texto de MinIO (o acepta texto directo), llama a `/predecir/` y registra el resultado | `COMPLETADA` |

---

## Variables de entorno

Copiar `.env.example` a `.env` y completar los valores:

```env
# Postgres
POSTGRES_USER=triaje
POSTGRES_PASSWORD=triaje_pass
POSTGRES_DB=triaje_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# MinIO
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin123
MINIO_ENDPOINT=http://minio:9000
MINIO_BUCKET_TEXTOS=textos-originales
MINIO_BUCKET_DATASETS=datasets
MINIO_BUCKET_MODELOS=modelos

# LLM: ollama | openrouter
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1:8b
# Si openrouter:
# OPENROUTER_API_KEY=sk-or-v1-...
# OPENROUTER_MODEL=google/gemini-2.0-flash-001
LLM_BATCH_LIMIT=0
LLM_DELAY_SEC=4

# Airflow (el compose ya inyecta FERNET_KEY y SQL desde .env)
AIRFLOW_UID=50000

# API interna (red Docker; los DAGs llaman al servicio api)
API_BASE_URL=http://api:8000
```

---

## Gestión de errores

| Escenario | Comportamiento |
|---|---|
| El LLM no responde | La tarea de Airflow reintenta hasta 3 veces con backoff exponencial. Si agota reintentos, el estado queda en `ERROR_ENRICHMENT` y se registra en Postgres. |
| Un microservicio Python no está disponible | Airflow marca la tarea como `failed`, registra el error en sus logs y en Postgres. |
| El modelo no está entrenado al llegar Fase 2 | `dag_prediction_phase_2` y el endpoint `/predecir/` comprueban la existencia del modelo en MinIO antes de ejecutar. Si no existe, responden con error controlado `MODEL_NOT_FOUND` (HTTP 503). |
| Fallo en la ingesta de un fichero concreto | El fichero se marca individualmente como `ERROR_INGESTION` sin detener el resto del batch. |
| Buckets MinIO inexistentes (`NoSuchBucket`) | Ejecutar `docker compose run --rm minio-init` antes de `dag_text_ingestion`. |
| API LLM remota en rate limit (429) | Reintentos en `client.py`; usar **Ollama** local o modelo/créditos distintos. |

Todos los errores quedan registrados en el campo `Estado` de la tabla `Entrevista` y en los logs nativos de Airflow.
