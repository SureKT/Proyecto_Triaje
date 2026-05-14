# Triaje IA — Sistema de clasificación automática de urgencias

Pipeline de procesamiento de texto con LLM y Machine Learning para clasificar el nivel de triaje (1–5) de pacientes en urgencias a partir de transcripciones de entrevista médico-paciente.

Orquestado con **Apache Airflow**. LLM local con **Ollama**. Persistencia en **Postgres** y **MinIO**.

---

## Requisitos previos

- Docker y Docker Compose instalados
- Ollama instalado en el host con el modelo descargado:
  ```bash
  ollama pull llama3.1:70b-instruct-q4_K_M
  ```
- GPU con soporte CUDA (recomendado: 16 GB VRAM)

---

## Cómo ejecutar el sistema

```bash
# 1. Clonar el repositorio
git clone <url-repositorio>
cd Proyecto_Triaje

# 2. Copiar y rellenar variables de entorno
cp .env.example .env

# 3. Levantar todos los servicios
docker compose up -d

# 4. Acceder a las interfaces
#    Airflow:  http://localhost:8080   (admin / admin por defecto)
#    MinIO:    http://localhost:9001
```

### Ejecutar el pipeline completo — Fase 1

Activar los DAGs en orden desde la UI de Airflow o via CLI:

```bash
docker compose exec airflow-webserver airflow dags trigger dag_text_ingestion
# Esperar a que termine, luego continuar en orden:
docker compose exec airflow-webserver airflow dags trigger dag_llm_enrichment
docker compose exec airflow-webserver airflow dags trigger dag_dataset_builder
docker compose exec airflow-webserver airflow dags trigger dag_model_training
docker compose exec airflow-webserver airflow dags trigger dag_evaluation
```

### Probar una predicción nueva — Fase 2

```bash
curl -X POST http://localhost:8000/predecir \
  -F "file=@ruta/a/nueva_entrevista.txt"
```

Respuesta esperada:

```json
{
  "GUID": "abc-123",
  "nivel_triaje": 3,
  "score_urgencia": 62.5,
  "justificacion": "Dolor moderado-severo (7/10), fiebre alta, primer episodio agudo"
}
```

---

## Estructura del proyecto

```
Proyecto_Triaje/
├── text/                        # Transcripciones originales (272 ficheros .txt)
├── dags/                        # DAGs de Airflow
│   ├── dag_text_ingestion.py    # Ingesta de .txt → Postgres + MinIO
│   ├── dag_llm_enrichment.py    # Extracción de entidades y etiquetado con LLM
│   ├── dag_dataset_builder.py   # Construcción del CSV de entrenamiento
│   ├── dag_model_training.py    # Entrenamiento y guardado del modelo ML
│   ├── dag_evaluation.py        # Evaluación con métricas y matriz de confusión
│   └── dag_prediction.py        # Predicción sobre nuevas entrevistas (Fase 2)
├── services/                    # Microservicios Python (FastAPI)
│   ├── preprocessor/            # Limpieza y normalización del texto
│   ├── llm_enrichment/          # Llamadas a Ollama: entidades, etiqueta, score
│   ├── dataset_builder/         # Generación del CSV estructurado
│   ├── ml_trainer/              # Entrenamiento y serialización del modelo
│   └── ml_predictor/            # Endpoint de predicción (Fase 2)
├── sql/
│   └── schema.sql               # Esquema de tablas Postgres
├── docs/
│   └── arquitectura.md          # Documentación funcional completa
├── docker-compose.yml
├── .env.example
├── ROADMAP.md                   # Guía interna de desarrollo y división de tareas
└── README.md
```

---

## Descripción de los servicios

### Airflow (puerto 8080)
Orquestador único del sistema. Ejecuta todos los DAGs (Fase 1 y Fase 2), gestiona dependencias entre tareas, registra logs por tarea y ejecuta reintentos automáticos. Cada tarea actualiza el estado de la entrevista en Postgres con timestamps de inicio y fin.

### API Python / FastAPI (puerto 8000)
Conjunto de microservicios invocados por los DAGs de Airflow. Cada servicio cubre una única etapa del pipeline: preprocesado de texto, llamada al LLM, construcción del dataset, entrenamiento del modelo y predicción. El endpoint `/predecir` actúa como punto de entrada para la Fase 2: recibe el fichero, crea el registro en Postgres, lanza `dag_prediction` via la API REST de Airflow y devuelve el resultado.

### Postgres (puerto 5432)
Fuente de verdad del estado del sistema. Almacena el estado de cada entrevista a lo largo de todo el pipeline, las entidades extraídas, las etiquetas asignadas por el LLM, los scores de urgencia, las predicciones del modelo y las valoraciones finales.

### MinIO (puertos 9000 / 9001)
Almacenamiento de objetos compatible con S3. Tres buckets:
- `textos-originales/` — ficheros `.txt` tal como se ingieren
- `datasets/` — CSVs generados para entrenamiento
- `modelos/` — modelos ML serializados y artefactos de evaluación

### Ollama (puerto 11434, en el host)
LLM local que procesa las transcripciones y devuelve JSON estructurado con entidades clínicas, nivel de triaje, score de urgencia y justificación. Corre en el host (no en Docker) para acceder directamente a la GPU. Los contenedores lo alcanzan via `host.docker.internal:11434`.

---

## Descripción de los DAGs de Airflow

| DAG | Función | Estado resultante |
|---|---|---|
| `dag_text_ingestion` | Lee los `.txt` de `text/`, sube a MinIO, crea registros en Postgres con GUID único | `INGESTED` |
| `dag_llm_enrichment` | Envía cada texto al LLM, extrae entidades, asigna nivel de triaje y score_urgencia | `ENRICHED` |
| `dag_dataset_builder` | Consolida los datos de Postgres en CSV y lo guarda en MinIO | `DATASET_READY` |
| `dag_model_training` | Carga el CSV, entrena Random Forest, serializa el modelo en MinIO, registra métricas | `MODEL_TRAINED` |
| `dag_evaluation` | Valida el modelo con validación cruzada, genera matriz de confusión | `EVALUATED` |
| `dag_prediction` | Carga el modelo entrenado, predice el nivel de triaje de una nueva entrevista | `PREDICTED` |

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

# Ollama (corre en el host, no en Docker)
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1:70b-instruct-q4_K_M

# Airflow
AIRFLOW_UID=50000
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://triaje:triaje_pass@postgres/triaje_db
AIRFLOW__CORE__FERNET_KEY=

# API interna
API_BASE_URL=http://api:8000
```

---

## Gestión de errores

| Escenario | Comportamiento |
|---|---|
| El LLM no responde | La tarea de Airflow reintenta hasta 3 veces con backoff exponencial. Si agota reintentos, el estado queda en `ERROR_ENRICHMENT` y se registra en Postgres. |
| Un microservicio Python no está disponible | Airflow marca la tarea como `failed`, registra el error en sus logs y en Postgres. |
| El modelo no está entrenado al llegar Fase 2 | `dag_prediction` comprueba la existencia del modelo en MinIO antes de ejecutar. Si no existe, responde con error controlado `MODEL_NOT_FOUND`. |
| Fallo en la ingesta de un fichero concreto | El fichero se marca individualmente como `ERROR_INGESTION` sin detener el resto del batch. |

Todos los errores quedan registrados en el campo `Estado` de la tabla `Entrevista` y en los logs nativos de Airflow.
