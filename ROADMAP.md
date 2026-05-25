# ROADMAP — Sprint de Cierre (3 días)

Defensa: **2026-05-28**. Este documento recoge las tareas pendientes con ficheros exactos,
las decisiones de diseño vigentes y el prompt LLM actualizado.

Para la historia del proyecto y decisiones anteriores: [`docs/diario-desarrollo.md`](docs/diario-desarrollo.md)  
Para la arquitectura técnica completa: [`docs/arquitectura.md`](docs/arquitectura.md)

---

## Estado actual (2026-05-25) — PIPELINE COMPLETO ✅

| Fase | Estado | Detalle |
|------|--------|---------|
| F1: 272 transcripciones ingestadas y enriquecidas | ✅ | Re-enriquecidas con prompt Manchester + score_ansiedad |
| F1: Dataset CSV + RF entrenado | ✅ | **CV F1 macro = 0.850 ± 0.069** (272 casos, 5-fold) |
| F2: `/predecir/` con valoración + COMPLETADA | ✅ | Devuelve nivel_manchester + score_ansiedad |
| F2: `/metricas/` + `/metricas/auditoria` | ✅ | Auditoría under-triage operativa |
| F3: `score_ansiedad` en LLM + BD + modelo | ✅ | 2ª feature más importante (13.9%) |
| F3: `class_weight='balanced'` en RF | ✅ | Protege C1/C2 (minoría) |
| F3: Streamlit + Whisper | ✅ | `app/streamlit_app.py` funcional |
| F3: Auditoría ética (tabla under-triage) | ✅ | Endpoint + UI implementados |
| Modelo exportado para portátil | ✅ | `models/modelo_latest.pkl` + `setup_laptop.py` |

### Resultados demo (2026-05-25)
| Caso | Esperado | Obtenido | score_ansiedad | Nota |
|------|----------|----------|----------------|------|
| caso_urgente_C2.txt | C2 | **C2** ✅ | 0.85 | — |
| caso_leve_C4.txt | C4 | **C4** ✅ | 0.20 | — |
| caso_ansiedad_C3.txt | C3 | **C2** ⚠️ | 0.95 | LLM aplica Manchester estricto: presión+disnea=C2 |

---

## Sprint día 1 — score_ansiedad + re-enriquecimiento

### Tarea 1.1 — Actualizar prompt LLM
**Fichero:** `services/llm_enrichment/prompt.py`

Añadir `"score_ansiedad"` al JSON de salida del SYSTEM_PROMPT y al few-shot example.
Cambiar referencias de "SET" a "Manchester (MTS)" en los criterios.

```
"score_ansiedad": <float 0.0-1.0>,
```

Descripción para el LLM: nivel de ansiedad o pánico percibido en el paciente a partir del tono,
las expresiones emocionales y la intensidad subjetiva del relato, independiente de los síntomas clínicos.
- 0.0-0.3: paciente tranquilo, relato objetivo
- 0.4-0.6: cierta preocupación o angustia
- 0.7-0.85: ansiedad notable, puede influir en descripción de síntomas
- 0.85-1.0: pánico o angustia extrema, riesgo de sobrevaloración emocional

### Tarea 1.2 — Actualizar schema SQL
**Fichero:** `sql/schema.sql`

Añadir columna en `ResultadoML`:
```sql
score_ansiedad FLOAT,
```

Ejecutar en BD (migración):
```sql
ALTER TABLE ResultadoML ADD COLUMN IF NOT EXISTS score_ansiedad FLOAT;
```

### Tarea 1.3 — Actualizar ml_features.py
**Fichero:** `services/ml_features.py`

- Añadir `"score_ansiedad"` a la lista `FEATURES`.
- Añadir en `row_from_llm_result()`: `"score_ansiedad": float(resultado.get("score_ansiedad") or 0.0)`.
- Añadir en `prepare_dataset_export_df()` / `prepare_training_df()`: tratar `score_ansiedad` como float, fillna(0.0).

### Tarea 1.4 — Actualizar dataset_builder
**Fichero:** `services/dataset_builder/service.py`

Añadir `r.score_ansiedad` al SELECT de la query que construye el CSV.

### Tarea 1.5 — Actualizar ml_trainer (class_weight)
**Fichero:** `services/ml_trainer/service.py`

Cambiar instanciación del RandomForestClassifier:
```python
# Antes:
clf = RandomForestClassifier(n_estimators=200, random_state=42)
# Después:
clf = RandomForestClassifier(n_estimators=200, random_state=42, class_weight='balanced')
```

### Tarea 1.6 — Lanzar re-enriquecimiento + reentrenamiento
1. Migrar BD: `ALTER TABLE ResultadoML ADD COLUMN IF NOT EXISTS score_ansiedad FLOAT;`
2. Reset estados a INGESTED para re-enriquecer:
   ```sql
   UPDATE Entrevista SET estado='INGESTED' WHERE origen='dataset';
   ```
3. Trigger `dag_llm_enrichment` (tarda ~1-2h, lanzar en background y trabajar en Streamlit)
4. Cuando termine: trigger `dag_dataset_builder` → `dag_model_training` → `dag_evaluation`

---

## Sprint día 2 — Streamlit + Whisper

### Tarea 2.1 — Instalar dependencias
```bash
pip install streamlit faster-whisper requests
```
O añadir a `requirements.txt` de la app si se dockeriza.

### Tarea 2.2 — Crear aplicación Streamlit
**Fichero nuevo:** `app/streamlit_app.py`

Estructura de la app:
```
app/
├── streamlit_app.py     # Aplicación principal
├── whisper_utils.py     # Función transcribe_audio(file) -> str
└── requirements.txt
```

**Flujo de la app:**
1. Sidebar con modo de entrada: "Audio" o "Texto directo"
2. Si Audio: `st.file_uploader` → `transcribe_audio()` → muestra texto transcrito
3. Si Texto: `st.text_area`
4. Botón "Analizar" → `POST http://localhost:8002/predecir/` con el texto
5. Mostrar resultado:
   - Badge grande con color Manchester (C1=rojo, C2=naranja, C3=amarillo, C4=verde, C5=azul)
   - `score_urgencia` como barra de progreso
   - `score_ansiedad` con alerta si > 0.7
   - Entidades normalizadas como lista
   - Justificación del LLM
6. Tabla de auditoría al final (ver Tarea 2.3)

### Tarea 2.3 — Tabla de auditoría ética
En la Streamlit, consultar al endpoint `/metricas/` o directamente a Postgres los casos donde:
- `prediccion_modelo < nivel_triaje` (RF predice menor urgencia que LLM = under-triage)
- `score_ansiedad > 0.7`

Mostrar tabla:

| ID_Caso | Entidades | Score Ansiedad | Pred. IA | Ground Truth | Estado |
|---------|-----------|---------------|---------|--------------|--------|
| SIM_xxx | disnea | 0.98 | C3 | C2 | ❌ Under-triage |

Añadir endpoint a la API para servir esto, o calcularlo en la propia Streamlit desde `/metricas/`.

### Tarea 2.4 — Preparar 3 audios de prueba para la demo
Grabar o conseguir 3 audios en español:
- **Caso urgente (C2):** paciente con dolor torácico + disnea + historial cardíaco
- **Caso leve (C4/C5):** dolor de rodilla leve, sin signos de alarma
- **Caso con ansiedad alta:** paciente muy ansioso con síntomas que podrían ser C3 real (demo del audit)

---

## Sprint día 3 — Pulido + estudio

### Mañana — verificación técnica
1. `docker compose up -d` → verificar que todos los servicios arrancan limpios
2. `streamlit run app/streamlit_app.py` → verificar flujo completo con los 3 audios
3. Verificar que el modelo cargado es el re-entrenado con `score_ansiedad`
4. Probar el caso de under-triage en la tabla de auditoría

### Tarde — estudio del código
Orden recomendado siguiendo el flujo de datos:

1. **Prompt y LLM** — `services/llm_enrichment/prompt.py` + `client.py`
   - ¿Qué hace el few-shot? ¿Por qué temperature=0? ¿Qué pasa si el JSON viene mal formado?

2. **Features y codificación** — `services/ml_features.py`
   - ¿Por qué -1 y no 0 para desconocidos? ¿Qué hace `class_weight='balanced'`?

3. **Entrenamiento** — `services/ml_trainer/service.py`
   - ¿Por qué RF y no un transformer? ¿Qué es el F1 macro? ¿Qué muestra la matriz de confusión?

4. **Predicción Fase 2** — `services/ml_predictor/service.py`
   - ¿Cómo se calcula la valoración? ¿Qué es el GUID? ¿Qué significa COMPLETADA?

5. **Arquitectura global** — `docs/arquitectura.md` sección "Justificación de decisiones"
   - Memoriza las justificaciones: LLM+RF, Ollama, -1, class_weight, ansiedad

---

## Decisiones de diseño vigentes

| Decisión | Elección | Razón para la defensa |
|----------|----------|----------------------|
| Sistema de triaje | **Manchester (MTS)** C1-C5 | Estándar internacional; el roadmap del profesor lo exige |
| Orquestador | **Airflow único** | Un sistema de logs y reintentos; Fase 2 usa `dag_prediction_phase_2` |
| LLM | **Ollama `llama3.1:8b`** local | Sin rate limits; sin datos clínicos a terceros; `temperature=0` reproducible |
| LLM como | **Anotador clínico** (extrae features) | No como clasificador: la decisión final la toma el RF (auditable) |
| Modelo ML | **Random Forest** | 272 muestras, interpretable, sin GPU en inferencia |
| Desbalanceo | **`class_weight='balanced'`** | Protege C1/C2 (9 casos) frente a C3 (200 casos) |
| Valores nulos | **-1 = desconocido** | 80% de transcripciones sin edad/sexo; no se descartan filas |
| Ansiedad | **Feature + señal de auditoría** | Clínica > emoción; detecta under-triage por sesgo emocional |
| Front-end | **Streamlit** | Prototipo rápido; el profesor lo menciona explícitamente |

---

## Preguntas previsibles en la defensa

**Fase 1:**
- *¿Por qué ese LLM y no otro?* → Ollama local: sin 429, sin datos a terceros, temperature=0 reproducible
- *¿Cómo evitáis JSON malformado del LLM?* → `"format": "json"` en Ollama (Structured Outputs), few-shot ancla el formato, try/except con estado ERROR_ENRICHMENT
- *¿El LLM puede equivocarse?* → Sí. El ground truth del LLM es una aproximación; el RF aprende sobre esas etiquetas. La auditoría detecta inconsistencias.
- *¿Qué es el GUID?* → UUID4 único por entrevista, persiste en Postgres y MinIO a través de todas las fases

**Fase 2:**
- *¿Qué hace `class_weight='balanced'`?* → Asigna pesos inversamente proporcionales a la frecuencia de cada clase. El RF penaliza más un fallo en C2 (9 casos) que en C3 (200 casos).
- *¿Por qué -1 y no 0?* → 0 significa "dolor intensidad = 0" (sin dolor), que es información real. -1 significa "no consta en la transcripción", que es diferente.
- *¿Qué es el F1 macro?* → Media de F1 por clase sin ponderar por frecuencia. Mide si el modelo es bueno en todas las clases, no solo en la mayoritaria.
- *¿Cómo detectáis el under-triage?* → `prediccion_modelo < nivel_llm` con `score_ansiedad > 0.7` → el RF predijo menor urgencia, y el paciente mostraba ansiedad alta que pudo contaminar el relato

**Fase 3:**
- *¿Por qué Streamlit?* → Prototipo clínico rápido sin frontend complejo; el profesor lo menciona explícitamente
- *¿Qué hace Whisper?* → Transcripción de audio a texto (modelo ASR de OpenAI, ejecutado local con `faster-whisper`)
- *¿Qué es el registro de auditoría?* → Tabla de casos donde el modelo pudo cometer under-triage por sesgo emocional; permite al médico revisar y corregir
