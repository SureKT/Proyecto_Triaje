# Documentación Técnica — Triaje IA

**Estado del documento:** actualizado 2026-05-25  
**Referencia normativa:** Roadmap técnico del profesor + correo de orientaciones para la defensa.

---

## Sistema de Triaje Manchester (MTS)

El proyecto clasifica urgencias según el **Sistema de Triaje Manchester (MTS)**, estándar internacional de 5 niveles codificados por color:

| Código | Color | Tiempo máx. atención | Descripción |
|--------|-------|----------------------|-------------|
| C1 | 🔴 Rojo | Inmediato | Compromiso vital inmediato |
| C2 | 🟠 Naranja | 10 min | Emergencia — riesgo vital próximo |
| C3 | 🟡 Amarillo | 60 min | Urgente — deterioro posible |
| C4 | 🟢 Verde | 120 min | Menos urgente — estable |
| C5 | 🔵 Azul | 240 min | No urgente — consulta diferible |

Internamente el sistema almacena el nivel como entero 1-5 (`nivel_triaje`). La aplicación Streamlit lo muestra como C1-C5 con su color Manchester.

---

## Diagrama de arquitectura completo

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
│         + score_ansiedad (pendiente — ver §Pendiente)               │
│                        │                                            │
│                        ▼                                            │
│              [dag_dataset_builder] ──► CSV en MinIO (datasets/)     │
│                        │                                            │
│                        ▼                                            │
│              [dag_model_training] ──► modelo.pkl en MinIO (modelos/)│
│              (class_weight='balanced' — pendiente)                  │
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
│                   ├──► Postgres (crea registro GUID, origen=simulacion) │
│                   ├──► llm_enrichment (preprocess + LLM)            │
│                   ├──► carga modelo .pkl desde MinIO                │
│                   ├──► predicción (nivel 1-5 + confianza)           │
│                   ├──► valoración automática (0-10)                 │
│                   └──► Postgres (estado COMPLETADA)                 │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│           FASE 3 — aplicación clínica (Streamlit) [PENDIENTE]       │
│                                                                     │
│  Médico ──► Streamlit UI                                            │
│                   │                                                 │
│                   ├── Sube audio .wav/.mp3                          │
│                   │       │                                         │
│                   │       ▼                                         │
│                   │   [Whisper] ──► texto transcrito                │
│                   │                                                 │
│                   ├── O pega texto directamente                     │
│                   │                                                 │
│                   ▼                                                 │
│               POST /predecir/ ──► nivel Manchester (C1-C5)          │
│                   │                                                 │
│                   ├──► Color Manchester + score_urgencia            │
│                   ├──► score_ansiedad (señal de auditoría)          │
│                   ├──► entidades normalizadas                       │
│                   └──► tabla de auditoría ética (under-triage)      │
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

Cada entrevista arrastra un `GUID_Entrevista` único a través de todos los estados:

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

## Descripción del pipeline — Fase 1

### Paso 1: Ingesta (`dag_text_ingestion`)

- Lee todos los ficheros `.txt` de `text/` (272 transcripciones).
- Genera un `GUID_Entrevista` único por fichero (UUID4).
- Sube cada fichero a MinIO en `textos-originales/<especialidad>/<nombre>.txt`.
- Inserta fila en `Entrevista` con estado `INGESTED`, `origen='dataset'`, especialidad extraída del prefijo del nombre de fichero (`CAR`, `RES`, `MSK`, etc.).

### Paso 2: Enriquecimiento LLM (`dag_llm_enrichment`)

- Para cada entrevista en estado `INGESTED` (o `ERROR_ENRICHMENT`), recupera el texto desde MinIO.
- Llama al microservicio `llm_enrichment`, que:
  1. Preprocesa el texto (limpieza básica).
  2. Envía a Ollama con prompt clínico estructurado (few-shot, `temperature=0`).
  3. Parsea el JSON de respuesta.
- El LLM devuelve (estructura actual):
  - Entidades crudas y normalizadas
  - `nivel_triaje` (1-5, Manchester C1-C5)
  - `score_urgencia` (0-100)
  - Features estructuradas: `edad`, `sexo`, `dolor_intensidad`, booleanos clínicos
  - `motivo_consulta`, `justificacion`
  - **`score_ansiedad` (0.0-1.0) — PENDIENTE DE AÑADIR AL PROMPT**
- Guarda entidades en `Entidad`, resto en `ResultadoML`.
- Actualiza estado a `ENRICHED`.

### Paso 3: Construcción del dataset (`dag_dataset_builder`)

- Consolida todos los registros `EVALUATED` de Postgres en un CSV versionado.
- Columnas: `guid`, `especialidad`, `origen`, `edad`, `sexo`, `dolor_intensidad`, `disnea`, `fiebre`, `perdida_consciencia`, `irradiacion`, `antecedentes_cardiacos`, `fumador`, `score_urgencia`, `score_ansiedad` (pendiente), `nivel_triaje`.
- Codificación (`ml_features.py`): booleanos → 0/1; sexo M/F → 1/0; **-1 = desconocido** si valor no aparece en transcripción.
- Guarda CSV en MinIO: `datasets/dataset_entrenamiento_<timestamp>.csv`.
- Actualiza estado a `DATASET_READY`.

### Paso 4: Entrenamiento (`dag_model_training`)

- Carga el CSV desde MinIO.
- Separa train/test (80/20, estratificado por `nivel_triaje`).
- Entrena **Random Forest** con `class_weight='balanced'` (**PENDIENTE**) — protege categorías críticas C1/C2 frente al desbalanceo (C3=200, C2=9 casos).
- Features de entrenamiento (10 actuales + `score_ansiedad` pendiente): `edad`, `sexo`, `dolor_intensidad`, `disnea`, `fiebre`, `perdida_consciencia`, `irradiacion`, `antecedentes_cardiacos`, `fumador`, `score_urgencia`.
- Registra métricas en Postgres. Serializa `modelo_<timestamp>.pkl` → MinIO `modelos/`.
- Actualiza estado a `MODEL_TRAINED`.

### Paso 5: Evaluación (`dag_evaluation`)

- Carga el modelo desde MinIO.
- Validación cruzada estratificada (5 folds).
- Genera matriz de confusión y classification report.
- Guarda artefactos JSON en MinIO `modelos/evaluacion/`.
- Actualiza estado a `EVALUATED`.

**Métricas tras re-entrenamiento con prompt mejorado (2026-05-24):**

| Métrica | Valor |
|---------|-------|
| RF Accuracy | 96.4 % |
| CV F1 macro | 0.904 |
| C2 (Naranja) recall | 1.0 |
| C3 (Amarillo) F1 | 0.987 |
| C4 (Verde) F1 | 0.952 |

---

## Descripción del pipeline — Fase 2

**Endpoint `POST /predecir/`** — `services/ml_predictor/service.py`

1. **Cliente** envía fichero `.txt` (multipart) o texto en formulario.
2. Genera `GUID_Entrevista`, sube texto a MinIO (`fase2/<guid>.txt`), registra en Postgres con `origen='simulacion'`.
3. Llama a `enrich()` → preprocesado + LLM + persistencia en `Entidad` / `ResultadoML`.
4. Carga el **modelo más reciente** desde MinIO (`modelo_*.pkl`).
5. Calcula predicción: `nivel_triaje_predicho` (1-5), `confianza` (prob. clase predicha).
6. Calcula **valoración automática** (0-10): `max(0, confianza - |pred_RF - nivel_LLM| × 0.25) × 10`.
   - Concordancia perfecta, confianza 0.96 → valoración 9.6
   - Discrepancia 1 nivel, confianza 0.85 → valoración 5.8
7. Actualiza `ResultadoML` (predicción, confianza, valoración) y `Entrevista` (estado `COMPLETADA`).

**Respuesta JSON actual:**
```json
{
  "GUID": "f3a2-91bc-...",
  "nivel_triaje_predicho": 2,
  "nivel_triaje_llm": 2,
  "score_urgencia": 91.0,
  "confianza": 0.93,
  "valoracion": 9.3,
  "motivo_consulta": "Dolor torácico intenso con disnea en paciente con antecedente de infarto",
  "justificacion": "Alta sospecha de SCA. Nivel 2 según MTS.",
  "entidades_normalizadas": ["dolor torácico", "disnea", "taquicardia"]
}
```

**Campos pendientes de añadir:** `score_ansiedad`, `nivel_manchester` (ej. `"C2"`).

**DAG `dag_prediction_phase_2`** — alternativa orquestada vía Airflow.  
Acepta en `dag_run.conf`:
- `{"filename": "CAR0001.txt", "especialidad": "CAR"}` → descarga de MinIO y POST como multipart.
- `{"texto": "..."}` → POST texto directo.

---

## Descripción del pipeline — Fase 3 (PENDIENTE)

### Cadena completa requerida

```
Audio (.wav/.mp3) → Whisper → texto → POST /predecir/ → Streamlit UI
```

### Componentes a implementar

**Servicio Whisper** (`app/whisper_service.py` o integrado en Streamlit):
- Librería: `faster-whisper` (más rápido que `openai-whisper`, misma API).
- Entrada: fichero de audio subido por el médico.
- Salida: texto transcrito en español.
- Modelo recomendado: `faster-whisper` modelo `medium` o `small` para balance velocidad/precisión.

**Aplicación Streamlit** (`app/streamlit_app.py`):
- Interfaz con dos modos de entrada: upload de audio o caja de texto.
- Si audio → transcripción vía Whisper → muestra texto transcrito → llama a `/predecir/`.
- Visualización del resultado:
  - Color Manchester (C1-C5) en grande con badge de color.
  - `score_urgencia` en barra de progreso.
  - `score_ansiedad` con indicador de alerta si > 0.7.
  - Entidades normalizadas como chips.
  - Justificación del LLM.
- Tabla de auditoría ética (ver §Auditoría).

**`score_ansiedad`** (añadir al prompt LLM):
- El LLM extrae el nivel de ansiedad/pánico percibido en el paciente (0.0-1.0).
- Uso dual:
  1. Feature del RF: el modelo aprende que la clínica debe pesar más que la ansiedad.
  2. Señal de auditoría: si `prediccion_modelo < nivel_llm` y `score_ansiedad > 0.7` → posible under-triage por sesgo emocional.

### Auditoría ética (tabla de desviaciones)

La Streamlit muestra una tabla de auditoría con todos los casos `COMPLETADA` donde el modelo puede haber cometido under-triage:

| ID_Caso | Entidades | Score Ansiedad | Predicción IA | Ground Truth (LLM) | Validación |
|---------|-----------|---------------|--------------|-------------------|------------|
| SIM_xxx | disnea, fatiga | 0.98 (Extrema) | C3 | C2 | ❌ Under-triage |
| CAR0001 | dolor torácico, disnea | 0.85 (Alta) | C2 | C2 | ✅ Acierto |

**Criterio de alerta:** `prediccion_modelo < nivel_llm` (el RF predice menor urgencia que el LLM).  
**Causa técnica documentada:** sesgo emocional — el RF sobrepondera el estado de ansiedad del paciente frente a los síntomas clínicos objetivos.  
**Acción correctiva:** `class_weight='balanced'` en el RF + `score_ansiedad` como feature explícita.

---

## Features del modelo ML

| Feature | Tipo | Valores | Fuente |
|---------|------|---------|--------|
| `edad` | int | entero o **-1** (desconocida) | LLM |
| `sexo` | int | 1=M, 0=F, **-1** (desconocido) | LLM |
| `dolor_intensidad` | int | 0-10 o **-1** (no mencionado) | LLM |
| `disnea` | int | 0/1 | LLM |
| `fiebre` | int | 0/1 | LLM |
| `perdida_consciencia` | int | 0/1 | LLM |
| `irradiacion` | int | 0/1 | LLM |
| `antecedentes_cardiacos` | int | 0/1 | LLM |
| `fumador` | int | 0/1 | LLM |
| `score_urgencia` | float | 0-100 | LLM |
| `score_ansiedad` | float | 0.0-1.0 | LLM — **PENDIENTE** |

**Target:** `nivel_triaje` (int 1-5, equivalente Manchester C1-C5).

**Decisión de diseño — valores -1:**  
La mayoría de transcripciones no recogen la edad ni el sexo del paciente (no siempre se pregunta). Asignar -1 en lugar de descartar la fila permite entrenar con las 272 muestras. El RF lo trata como una categoría válida ("dato no disponible"), que es la realidad clínica.

**Desbalanceo de clases:**

| Nivel | Casos | % |
|-------|-------|---|
| C2 (Naranja) | 9 | 3.3 % |
| C3 (Amarillo) | ~200 | 73.5 % |
| C4 (Verde) | ~44 | 16.2 % |
| C5 (Azul) | ~27 | 9.9 % |

Mitigación: `class_weight='balanced'` en RandomForestClassifier (pendiente).  
Efecto: el RF penaliza más los fallos en clases minoritarias (C1/C2), reduciendo el riesgo de under-triage en casos críticos.

---

## Prompt LLM (versión actual)

Sistema: few-shot con 1 ejemplo de caso C2 confirmado. `temperature=0` para reproducibilidad.

**JSON de salida actual (10 campos + `score_ansiedad` pendiente):**
```json
{
  "nivel_triaje": 2,
  "score_urgencia": 91.0,
  "motivo_consulta": "Dolor torácico intenso con disnea...",
  "entidades": ["dolor pecho", "cuesta respirar"],
  "entidades_normalizadas": ["dolor torácico", "disnea"],
  "edad": 67,
  "sexo": null,
  "dolor_intensidad": 8,
  "disnea": true,
  "fiebre": false,
  "perdida_consciencia": false,
  "irradiacion": false,
  "antecedentes_cardiacos": true,
  "fumador": false,
  "justificacion": "Alta sospecha SCA. Nivel 2 MTS."
}
```

**Campo pendiente:** añadir `"score_ansiedad": 0.0-1.0` — nivel de ansiedad/pánico percibido en el paciente, independiente de los síntomas clínicos.

**Técnica de prompting:** Structured Outputs (formato JSON forzado con `"format": "json"` en Ollama). El few-shot ancla el formato y calibra el criterio C2. La "regla de oro" (ante duda, nivel más urgente) reduce under-triage.

---

## Modelo de datos (Postgres)

Fuente de verdad: `sql/schema.sql`.

| Tabla | Rol |
|-------|-----|
| **Entrevista** | GUID, URLs (texto, dataset, modelo), timestamps por fase, `Estado`, `nombre_fichero`, `especialidad`, `origen` (`dataset`\|`simulacion`) |
| **Entidad** | Pares entidad cruda / normalizada por entrevista |
| **ResultadoML** | Features del LLM, `score_urgencia`, `score_ansiedad` (pendiente), `nivel_triaje` (ground truth LLM), `prediccion_modelo`, `confianza`, `valoracion` |

**Campo `origen`:** distingue los 272 casos de entrenamiento (`'dataset'`) de las predicciones a demanda Fase 2 (`'simulacion'`). Evita contaminar futuros re-entrenamientos con predicciones del propio modelo.

**Índice clave:** `UNIQUE INDEX idx_resultado_guid_unique ON ResultadoML(GUID_Entrevista)` — permite UPSERT al re-enriquecer sin duplicar filas.

---

## Justificación de decisiones de diseño

### ¿Por qué LLM + RF y no LLM solo?
El LLM actúa como **anotador clínico**: normaliza el lenguaje coloquial ("me ahogo" → disnea) y estructura la información. El RF actúa como **decisor estadístico**: aprende de los 272 casos etiquetados y produce una predicción auditable con importancia de features. Un LLM como clasificador directo no es reproducible ni auditable en contexto clínico.

### ¿Por qué Ollama local y no OpenRouter?
Sin rate limits (429) en el batch de 272 casos. Sin envío de datos clínicos a terceros. `temperature=0` garantiza reproducibilidad total: la misma transcripción siempre produce el mismo JSON.

### ¿Por qué Random Forest y no un modelo más complejo?
Con 272 muestras y fuerte desbalanceo (73 % C3), los modelos profundos sobreajustan. RF es interpretable (importancia de features defensible ante el tribunal), no requiere GPU para inferencia y es robusto con datos tabulares mixtos.

### ¿Por qué -1 para valores desconocidos y no descartar filas?
El 80 % de transcripciones no mencionan la edad ni el sexo del paciente. Descartar esas filas deja ~4 casos entrenables. -1 es una categoría válida ("dato no disponible en la transcripción"), que el RF aprende a manejar.

### ¿Por qué `score_ansiedad` como feature Y como señal de auditoría?
El profesor lo define en el roadmap: el modelo puede sesgar sus predicciones por el estado emocional del paciente (pánico → over-reporting de síntomas). Incluyéndolo como feature, el RF puede aprender que la clínica pesa más. Monitorizándolo en la auditoría, el médico puede revisar los casos donde la ansiedad es extrema y la predicción es más baja que el criterio LLM.

---

## Gestión de errores

### Si falla el LLM (Ollama / OpenRouter)
- Timeout configurable (`LLM_TIMEOUT`, por defecto 120 s).
- OpenRouter: reintentos con backoff exponencial ante 429, hasta `LLM_MAX_RETRIES` (por defecto 4).
- Fallo definitivo: estado `ERROR_ENRICHMENT`. Re-trigger del `dag_llm_enrichment` reintenta automáticamente esos registros.

### Si falla un servicio (API, Postgres, MinIO)
- Airflow reintenta la tarea (3 reintentos, backoff exponencial, configurado en `DEFAULT_ARGS`).
- Si persiste: tarea en `failed` en Airflow UI. El registro en Postgres mantiene el último estado válido.

### En Fase 2 (`/predecir/`)
- Modelo no existe en MinIO → HTTP 503 `MODEL_NOT_FOUND`.
- Texto vacío → HTTP 422.
- LLM falla durante enriquecimiento → HTTP 500; registro queda en `ENRICHING`.

---

## Estado actual del proyecto (2026-05-25)

| Componente | Estado |
|-----------|--------|
| Ingesta 272 transcripciones | ✅ Hecho |
| Enriquecimiento LLM (272/272) | ✅ Hecho |
| Dataset CSV en MinIO | ✅ Hecho |
| Entrenamiento RF | ✅ Hecho (accuracy 96.4 %, F1 0.904) |
| Evaluación CV 5-fold | ✅ Hecho |
| Endpoint `/predecir/` Fase 2 | ✅ Hecho (valoración + COMPLETADA) |
| Endpoint `/metricas/` | ✅ Hecho |
| `dag_prediction_phase_2` | ✅ Hecho |
| Campo `origen` en BD | ✅ Hecho |
| `score_ansiedad` en prompt + BD + modelo | ⏳ Pendiente |
| `class_weight='balanced'` en RF | ⏳ Pendiente |
| Streamlit front-end (Fase 3) | ⏳ Pendiente |
| Whisper (transcripción audio) | ⏳ Pendiente |
| Registro de auditoría ética | ⏳ Pendiente |
| Reentrenamiento con `score_ansiedad` | ⏳ Pendiente (requiere re-enriquecimiento) |
