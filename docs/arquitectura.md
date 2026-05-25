# Documentación Técnica — Triaje IA

**Estado del documento:** actualizado 2026-05-25  
**Propósito:** referencia técnica completa + guía de comprensión del código para la defensa.

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
| Entrenamiento RF con `class_weight='balanced'` | Hecho (accuracy 96.4%, F1 0.904) |
| Evaluación CV 5-fold | Hecho |
| Endpoint `/predecir/` Fase 2 | Hecho (valoración + COMPLETADA) |
| Endpoint `/metricas/` y `/metricas/auditoria` | Hecho |
| `dag_prediction_phase_2` | Hecho |
| Streamlit front-end (Fase 3) | Hecho |
| Whisper (transcripción audio) | Hecho |
| Auditoría ética (under-triage) | Hecho |

---

## Guía de comprensión del código — flujo completo

Esta sección traza el recorrido completo de los datos desde un fichero `.txt` hasta el badge de color en Streamlit. Para cada paso se indica el fichero exacto, las funciones involucradas, por qué se diseñó así y qué alternativas se consideraron.

---

### PASO 1 — El dato de origen: `text/RES0001.txt`

Los 272 ficheros de `text/` son transcripciones de entrevistas médico-paciente en inglés con prefijo de especialidad: `CAR` (cardiología), `RES` (respiratorio), `MSK` (musculoesquelético), etc. Son el único dato de entrada de la Fase 1.

**¿Por qué en inglés si el sistema habla español?**  
El LLM entiende ambos idiomas de forma nativa. El prompt está en español y el LLM responde en español independientemente del idioma de la transcripción. La Fase 3 (Streamlit) acepta entrevistas en español directamente desde el campo de texto o desde audio en español vía Whisper — el pipeline no cambia nada por eso.

---

### PASO 2 — Ingesta: `dags/dag_text_ingestion.py`

**Qué hace:**  
- Itera sobre todos los `.txt` de `text/`.
- Genera un `GUID_Entrevista` (UUID4) por fichero — identificador que seguirá a ese caso durante toda su vida en el sistema.
- Sube el fichero a MinIO en `textos-originales/<especialidad>/<nombre>.txt`.
- Inserta una fila en la tabla `Entrevista` con estado `INGESTED`, `origen='dataset'` y la especialidad extraída del prefijo del nombre (`CAR`, `RES`…).

**Datos que entra en Postgres tras este paso:**
```
GUID_Entrevista: "3f7b-..."
Estado: "INGESTED"
origen: "dataset"
especialidad: "CAR"
nombre_fichero: "CAR0001.txt"
URL_Texto_Original: "s3://textos-originales/CAR/CAR0001.txt"
```

**¿Por qué MinIO y no guardar en disco?**  
Todos los contenedores Docker comparten el mismo MinIO pero no el mismo sistema de ficheros. Si el texto sólo existiera en el disco del contenedor Airflow, el contenedor API no podría leerlo. MinIO actúa como disco compartido compatible con S3.

**Campo `origen`:**  
Distingue los 272 casos de entrenamiento (`'dataset'`) de las predicciones futuras Fase 2 (`'simulacion'`). Es crítico para no contaminar futuros re-entrenamientos con datos generados por el propio modelo.

---

### PASO 3 — Enriquecimiento LLM: `dags/dag_llm_enrichment.py`

El DAG consulta todos los registros en estado `INGESTED` (o `ERROR_ENRICHMENT`) y para cada uno llama al microservicio FastAPI en `POST /enriquecer/`.

#### 3a. Preprocesado: `services/preprocessor/service.py`

**Función:** `preprocess(guid, texto) -> dict`  
Limpia el texto y extrae únicamente la parte del paciente (`texto_paciente`) de la transcripción, eliminando las preguntas del médico (`D:`). Si no hay separación clara, usa el texto completo. El resultado se pasa directamente al LLM — no hay más transformaciones.

```python
# En service.py de llm_enrichment:
prep = preprocess(guid, texto)
texto_llm = prep["texto_paciente"] or prep["texto_completo"]
```

**¿Por qué sólo el texto del paciente?**  
El paciente describe sus síntomas. El médico hace preguntas neutras ("¿Cuánto tiempo lleva así?"). Pasar sólo la parte del paciente reduce ruido y dirige la atención del LLM a lo clínicamente relevante. Es heurístico — se podría pasar todo, pero el rendimiento es ligeramente mejor así.

#### 3b. Llamada al LLM: `services/llm_enrichment/client.py`

**Función:** `call_llm(texto) -> dict`

Según `LLM_PROVIDER` en `.env`, llama a:
- **Ollama** (`http://host.docker.internal:11434`) — modelo local en el host, sin rate limits, datos sin salir del equipo. Ideal para batch de 272 casos.
- **OpenRouter** (`https://openrouter.ai/api/v1`) — API externa. Útil en portátil sin GPU para la demo (2-3 predicciones). Con modelo `google/gemini-2.0-flash-001` gratuito.

En ambos casos la llamada es `temperature=0` y `format=json`. La reproducibilidad total es deliberada: la misma transcripción siempre produce el mismo JSON.

**Reintentos (OpenRouter):** ante HTTP 429 (rate limit), el cliente reintenta con backoff exponencial hasta `LLM_MAX_RETRIES=4` veces. Base configurable: `LLM_RETRY_BASE_SEC=15`. En Ollama local no hay 429.

#### 3c. El prompt clínico: `services/llm_enrichment/prompt.py`

**Función:** `build_messages(texto) -> list[dict]`

Esta es la pieza central del sistema. El prompt tiene cuatro secciones:

**1. SYSTEM_PROMPT — definición del rol y del MTS:**
```
Eres un sistema experto en triaje médico. Clasifica según el Sistema de
Triaje Manchester (MTS) en niveles 1-5...
```
Define los 5 niveles con sus criterios clínicos. Establece la "regla de oro": *cuando hay duda entre dos niveles, asignar el más urgente*. Esta regla es clave para evitar under-triage — es preferible sobreestimar la urgencia de un C3 que subestimar un C2.

**2. Definición de `score_ansiedad`:**
El prompt explica explícitamente que `score_ansiedad` mide el pánico/ansiedad *percibido* en el paciente (0.0-1.0), **separado de la urgencia clínica**. Esto es deliberado: un paciente puede estar muy ansioso (0.9) por un esguince de tobillo (C4). El LLM debe distinguir la ansiedad emocional del deterioro clínico.

**3. Dos ejemplos few-shot:**
- **Caso C2 (cardíaco):** dolor torácico + disnea + antecedentes, `score_urgencia=91`, `score_ansiedad=0.3` (paciente asustado pero no en pánico). Ancla el formato JSON y calibra el criterio de nivel 2.
- **Caso C3 (ansiedad):** dolor inespecífico + respiración agitada, pero clínica leve. `score_urgencia=41`, `score_ansiedad=0.92`. Demuestra que ansiedad alta ≠ urgencia alta: el LLM debe primar los síntomas objetivos.

**4. JSON de salida (14 campos):**
```json
{
  "nivel_triaje": 2,
  "score_urgencia": 91.0,
  "score_ansiedad": 0.3,
  "motivo_consulta": "...",
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
  "justificacion": "..."
}
```

**¿Por qué few-shot y no zero-shot?**  
Sin ejemplos, el LLM tiende a clasificar casos ambiguos como C3 (la clase mayoritaria). Los ejemplos concretos de C2 y del error de sobreponderar ansiedad recalibran su criterio sin necesidad de fine-tuning.

**¿Por qué `temperature=0`?**  
En producción clínica, la misma transcripción debe producir siempre el mismo resultado. Temperature > 0 introduce variabilidad no deseable en un sistema de soporte a decisiones médicas.

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
# → 0.850 ± 0.069 (o 0.904 con prompt v2)
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

**Métricas actuales (modelo con prompt v2 + class_weight):**

| Métrica | Valor |
|---------|-------|
| Accuracy (test 20%) | 96.4 % |
| F1 macro (CV 5-fold) | 0.904 |
| Recall C2 (Naranja) | 1.0 |
| F1 C3 (Amarillo) | 0.987 |
| F1 C4 (Verde) | 0.952 |

El recall C2 = 1.0 es el resultado más importante: el modelo no pierde ningún caso de emergencia. En triaje clínico, un falso negativo en C2 (decir que es C3 cuando en realidad es C2) puede costar una vida.

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
