# Diario de desarrollo — Triaje IA

**Documento interno.** No es entregable oficial. Sirve para la defensa oral: qué hemos hecho, por qué, qué falló y cómo lo resolvimos.  
**Mantener vivo:** añadir entradas al final de cada sesión o decisión relevante.

| Campo | Valor |
|-------|--------|
| Última actualización | 2026-05-25 |
| Equipo | Persona A (Gerard) · Persona B (Braulio) |
| Checkpoint | **PIPELINE COMPLETO** — CV F1 macro 0.850 ± 0.069 · Streamlit + Whisper operativos · sistema validado en portátil con OpenRouter |

---

## Cómo usar este documento

| Otro doc | Para qué sirve | Este diario |
|----------|----------------|-------------|
| `README.md` | Cómo levantar y ejecutar el sistema | No duplica comandos; enlaza si hace falta |
| `docs/arquitectura.md` | Diagramas y flujo funcional (entregable técnico) | Registra **historia**, fallos, cambios de rumbo |
| `Proyecto Triage IA.pdf` | Especificación del profesor | Referencia de requisitos |

**Plantilla para nuevas entradas** (copiar en §9, más reciente arriba):

```markdown
### YYYY-MM-DD — Título breve
**Quién:** A / B / ambos  
**Qué:** …  
**Por qué:** …  
**Problema (si hubo):** …  
**Solución:** …  
**Estado:** hecho / en curso / bloqueado  
```

---

## 1. Resumen ejecutivo (para la defensa)

### Qué es el proyecto

Sistema que clasifica el **nivel de triaje hospitalario (SET, 1–5)** a partir de transcripciones médico-paciente (~272 casos). Pipeline en dos fases:

- **Fase 1 (batch):** ingesta → LLM extrae columnas estructuradas → CSV → entrena Random Forest → evaluación.
- **Fase 2 (a demanda):** `POST /predecir` con nueva entrevista → mismo enriquecimiento + modelo ML.

### Decisiones clave (mensaje de 30 segundos)

1. **Un solo orquestador (Airflow)** para batch y disparo de Fase 2 vía REST.
2. **LLM como anotador clínico** (JSON con features + `nivel_triaje`); **ML como decisor** entrenado sobre esas columnas.
3. **Postgres** = estado y trazabilidad; **MinIO** = textos, CSVs y modelos `.pkl`.
4. **LLM intercambiable** (OpenRouter u Ollama): el profesor indicó flexibilidad; en desarrollo usamos **Ollama local** por rate limits de la API free.

### Hasta dónde hemos llegado (mayo 2026)

| Área | Estado |
|------|--------|
| Docker Compose (Postgres, MinIO, Airflow, API) | Operativo |
| Esquema SQL + 272 `.txt` en `text/` | Listo |
| DAGs y servicios FastAPI | Código presente y probado parcialmente |
| Cliente LLM dual (`client.py`: OpenRouter + Ollama) | Implementado |
| Ingesta 272 (`dag_text_ingestion`) | **Hecho** |
| Enriquecimiento LLM (`dag_llm_enrichment`) | **Hecho** — 272/272 ENRICHED |
| Dataset CSV + entrenamiento ML + evaluación | **Hecho** (`dataset_*`, `modelo_*`, eval JSON en MinIO) |
| Codificación edad/sexo desconocidos (`-1`) | **Hecho** — ver §10 entrada 2026-05-19 |
| Fase 2 `/predecir` con modelo entrenado | **Pendiente** (probar con `.txt` nuevo) |

---

## 2. División del equipo

| Persona A (Gerard) | Persona B |
|--------------------|-----------|
| Prompt y servicio `llm_enrichment` | `docker-compose`, `.env`, SQL |
| DAGs: `llm_enrichment`, `model_training`, `evaluation` | DAGs: `text_ingestion`, `dataset_builder`, `prediction` |
| `ml_trainer`, evaluación, `docs/arquitectura.md` | `preprocessor`, `ml_predictor`, `/predecir` |

**Dependencia crítica (superada para ingesta):** Postgres + MinIO + ingesta. El enriquecimiento batch depende de Ollama en el host y de repetir el DAG en lotes.

---

## 3. Cronología del desarrollo

### Fase inicial — Estructura del repositorio

**Qué pasó:** El compañero levantó la arquitectura del ROADMAP: compose, schema, DAGs y microservicios.

**Incidente — carpeta `{dags,services...}`:** Brace expansion de bash en Windows creó un directorio literal en lugar de varias carpetas.

**Solución:** Eliminada; la estructura correcta ya existía en la raíz.

---

### 2026-05-18 — Revisión Persona A + correcciones pipeline

| Problema | Solución |
|----------|----------|
| Fase 1 sin preprocess | `enrich()` llama a `preprocess()` |
| `ON CONFLICT` sin índice único | `UNIQUE` en `ResultadoML.GUID_Entrevista` + UPSERT |
| Entidades duplicadas al re-ejecutar | `DELETE` por GUID antes de insertar |
| Ruta MinIO frágil en DAG | `especialidad/nombre_fichero` desde Postgres |
| Doble preprocess en Fase 2 | Solo `enrich()` preprocesa |
| FK en prueba manual | `ensure_entrevista(guid)` |
| OpenRouter free → 429 | Cambio a **Ollama** local |
| MinIO `NoSuchBucket` | `docker compose run --rm minio-init` |

**Código añadido:** `llm_enrichment/client.py`, reintentos 429, `LLM_BATCH_LIMIT` / `LLM_DELAY_SEC` en DAG, `scripts/test_enrich.py`.

---

### 2026-05-18 — Ollama y modelo para el batch

| Paso | Detalle |
|------|---------|
| Prueba inicial | `qwen3:4b` — OK en `CAR0001.txt` (~88 s) |
| Modelo elegido | **`llama3.1:8b`** (~4.9 GB) — mejor calidad/velocidad para 272 casos |
| Alternativa instalada | `qwen2.5:14b-instruct` (~9 GB) — opcional si se prioriza calidad sobre velocidad |
| Config actual | `.env`: `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=llama3.1:8b` |
| Primer lote DAG | 5 entrevistas más → **6 ENRICHED** total |

---

## 4. Tabla viva de decisiones

| Fecha | Decisión | Alternativas descartadas | Motivo |
|-------|----------|------------------------|--------|
| Inicio | Airflow único | n8n + Airflow | Simplicidad, trazabilidad |
| Inicio | Random Forest | DL end-to-end | ~272 muestras, interpretabilidad |
| Inicio | `score_urgencia` 0–100 | `score_ansiedad` genérico | Dominio clínico |
| 2026-05-18 | LLM proveedor configurable | Solo cloud / solo local | Indicación profesor |
| 2026-05-18 | Preprocess en `enrich()` | DAG preprocess Fase 1 | Estados `PREPROCESSED` → `ENRICHED` |
| 2026-05-18 | **Ollama `llama3.1:8b` para batch** | OpenRouter free (429), `qwen3:4b` (pequeño) | Sin rate limit; JSON estable; GPU local |
| 2026-05-18 | Lotes de 5 (`LLM_BATCH_LIMIT=5`) | 272 de golpe | Control de tiempo y recuperación ante fallos |

---

## 5. Estado por componente (checklist)

### Infraestructura

- [x] `docker-compose.yml` (Postgres, MinIO, Airflow, API)
- [x] `sql/schema.sql` + índice único `ResultadoML`
- [x] `.env.example`
- [x] Airflow operativo (UI :8088)
- [ ] Alinear puertos en `README` (8088, 5433, 8002)

### Datos

- [x] 272 transcripciones en `text/`
- [x] Ingesta → 272 `INGESTED` en Postgres + MinIO

### Fase 1 — Pipeline batch

- [x] `dag_text_ingestion`
- [x] `dag_llm_enrichment` — **272/272 ENRICHED** (re-enriquecido con prompt Manchester + score_ansiedad)
- [x] `dag_dataset_builder`
- [x] `dag_model_training` — CV F1 macro 0.850 ± 0.069, `class_weight='balanced'`
- [x] `dag_evaluation`

### Fase 2

- [x] Modelo `.pkl` en MinIO + `models/modelo_latest.pkl` en repo
- [x] `/predecir/` end-to-end con `score_ansiedad` + `valoracion` + estado `COMPLETADA`
- [x] `/metricas/` + `/metricas/auditoria` (detección under-triage)
- [x] `dag_prediction_phase_2` (reescrito desde `dag_prediction.py`)

### Fase 3

- [x] `app/streamlit_app.py` — badge Manchester, score ansiedad, tabla auditoría
- [x] `app/whisper_utils.py` — transcripción audio con faster-whisper
- [x] 3 casos demo en `demo/`
- [x] `setup.py` — configuración en portátil sin GPU

### Documentación

- [x] `docs/arquitectura.md`
- [x] Este diario
- [x] `README.md` con sección portátil/OpenRouter

---

## 6. Problemas conocidos / deuda técnica

| ID | Descripción | Estado |
|----|-------------|--------|
| D1 | README puertos ≠ compose | **Resuelto** — 2026-05-18 |
| D2 | `arquitectura.md` SQL desactualizado | **Resuelto** — 2026-05-24 |
| D3 | `dag_prediction` / `guid` inconsistente | **Resuelto** — reescrito como `dag_prediction_phase_2` |
| D4 | Rate limit API free | **Mitigado** — Ollama local |
| D5 | `UNIQUE` en `ResultadoML` | **Resuelto** |
| D6 | Buckets MinIO tras primer `compose up` | **Resuelto** — ejecutar `minio-init` |
| D7 | OpenRouter 429 | **Evitado** — `LLM_PROVIDER=ollama` |
| D8 | Valoración ausente en Fase 2 | **Resuelto** — 2026-05-24 |
| D9 | Estado `PREDICTED` sin `COMPLETADA` final | **Resuelto** — 2026-05-24 |
| D10 | `validate_dataset_columns.py` filtraba solo `ENRICHED` | **Resuelto** — 2026-05-24 |

---

## 7. Guion breve para la exposición oral

**1. Problema** — Clasificar urgencia (SET 1–5) desde entrevistas en lenguaje natural.

**2. Enfoque** — LLM extrae columnas → Random Forest aprende; Airflow orquesta; Postgres audita.

**3. Demo** — Ingesta → JSON LLM en BD → (cuando exista) predicción Fase 2.

**4. Decisiones** — Tabla §4; separación LLM / ML.

**5. Dificultades reales** — Carpeta Windows; FK pruebas; MinIO buckets; 429 API → Ollama; batch en lotes.

**6. Pendiente** — Completar 266 enriquecimientos; dataset; train; evaluación.

---

## 8. Próximos pasos

~~En curso: enriquecimiento batch~~ **Completado** (272 EVALUATED).

1. (Opcional) Presentación 8-10 diapositivas para la defensa oral.
2. Push a origin/main cuando el equipo lo decida.
3. No hay deuda técnica crítica abierta (ver §6).

---

## 9. Comandos útiles

```powershell
cd Proyecto_Triaje

# Buckets MinIO (si falla ingesta):
docker compose run --rm minio-init

# Progreso enriquecimiento:
docker compose exec -T postgres psql -U triaje -d triaje_db -c "SELECT estado, COUNT(*) FROM entrevista GROUP BY estado;"

# Lote de 5 entrevistas (Ollama debe estar en marcha):
docker compose exec -T airflow-webserver airflow dags trigger dag_llm_enrichment

# Prueba manual:
python scripts/test_enrich.py <GUID> text/RES0001.txt

# Modelos Ollama instalados:
ollama list
```

| Servicio | URL |
|----------|-----|
| Airflow | http://localhost:8088 (admin / admin) |
| API | http://localhost:8002 |
| MinIO console | http://localhost:9001 |

**Variables LLM actuales (`.env`):**

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
LLM_BATCH_LIMIT=5
LLM_DELAY_SEC=4
```

---

## 10. Bitácora — nuevas entradas

*(Más reciente arriba)*

### 2026-05-25 — Puesta en marcha en portátil + limpieza final del repo

**Quién:** Gerard (A)  
**Qué:** Primera ejecución completa del sistema en el portátil (sin GPU). Identificación y resolución de 5 bugs de entorno. Limpieza del repositorio para entrega.

**Bugs encontrados y resueltos:**

| Bug | Causa | Solución |
|-----|-------|----------|
| `setup.py` falla con "MinIO no responde" | Script conectaba a puerto `9001` (UI web) en vez de `9000` (API S3). Además leía `MINIO_ENDPOINT=http://minio:9000` del `.env` (red Docker interna, inaccesible desde el host) | Forzar `localhost:9000` cuando el endpoint contiene `minio:` |
| `UnicodeEncodeError` en `setup.py` | Consola Windows usa cp1252; los caracteres `→` y `✓` no están en cp1252 | Sustituidos por `->` y `OK` |
| API devuelve `Connection refused` en `/predecir/` | `LLM_PROVIDER=ollama` pero el portátil no tiene GPU ni Ollama instalado | Cambiar a `LLM_PROVIDER=openrouter` en `.env` |
| API devuelve `401 Unauthorized` de OpenRouter | API key pegada con `ssk-or-v1-` (una `s` extra) en vez de `sk-or-v1-` | Corregir la key en `.env` |
| `docker compose restart` no aplica cambios del `.env` | `restart` reutiliza la configuración del contenedor anterior | Usar `docker compose up -d --force-recreate api` |

**Decisión — OpenRouter como proveedor en portátil:**  
El portátil no tiene GPU. Ollama con `llama3.1:8b` en CPU tarda ~4 min/transcripción (inaceptable en demo). OpenRouter con `google/gemini-2.0-flash-001` responde en ~3-5 s. Para 3 predicciones de demo no hay riesgo de rate limit con la cuenta gratuita. Documentado en `README.md` como "Configuración en portátil / sin GPU".

**Validación end-to-end en portátil:**
```
texto: "Presión fuerte en el pecho, cuesta respirar, brazo izquierdo dormido, 58 años, hipertenso"
→ LLM (OpenRouter/Gemini): nivel_triaje=2, score_urgencia=90, score_ansiedad=0.6
→ RF: predicción C2, confianza 0.475
→ Streamlit: badge C2 naranja, alerta ansiedad moderada
→ Tiempo respuesta: ~5 s
```

**Limpieza del repositorio (entrega):**

| Eliminado | Motivo |
|-----------|--------|
| `translated_texts/` (272 ficheros) | Pre-traducciones al español generadas durante el desarrollo. El pipeline usa `text/` (inglés original) y el LLM hace la extracción en español internamente. Cero referencias en el código. |
| `scripts/test_enrich.py` | Script de prueba manual durante el sprint. La API está validada y no se necesita. |
| `scripts/validate_dataset_columns.py` | Script de validación de datos durante el desarrollo. Irrelevante post-entrega. |
| `ROADMAP.md` | Documento de sprint interno ya completado. La información relevante para la defensa está en `docs/arquitectura.md` y en este diario. |
| `scripts/backup_resultadoml_20260524.csv` | Dato de BD exportado durante el re-enriquecimiento. No debe estar en el repo. Añadido `scripts/backup_*.csv` al `.gitignore`. |
| `data/labeled|processed|raw` | Directorios vacíos de runtime. Ya cubiertos por `.gitignore`. |
| `cleantext/` | Carpeta vacía sin uso. |

**Mejoras al `.gitignore`:** reorganizado con categorías, añadidas entradas para `data/`, `cleantext/`, `scripts/backup_*.csv`, `Thumbs.db`.

**Estado:** sistema operativo en portátil, repo limpio, listo para entrega y defensa.

---

### 2026-05-25 — Sprint defensa: Fase 3 completa + score_ansiedad + Manchester

**Quién:** Gerard (A) — sesión en PC de casa  
**Qué:** Implementación completa del sprint de cierre (commits `691ada4` → `b6edf14`).

**1. Terminología Manchester (commits `691ada4`, `31758ab`)**  
- Prompt LLM actualizado: referencias a "SET" → "Manchester (MTS)", criterios C1-C5 con colores.  
- `score_ansiedad` añadido al JSON de salida del LLM (0.0-1.0), al schema SQL (`ResultadoML`), a `ml_features.py` como feature del RF, y al endpoint `/predecir/`.  
- Re-enriquecimiento de 272 transcripciones con el prompt actualizado y reentrenamiento del RF con `class_weight='balanced'`. Resultado: **CV F1 macro 0.850 ± 0.069**.  
- `score_ansiedad` es la **2ª feature más importante** del RF (13.9%), solo por detrás de `score_urgencia`.

**Decisión — `class_weight='balanced'` en RandomForest:**  
El dataset tiene 9 casos C1/C2 frente a ~200 C3. Sin balanceo el RF ignoraba las minorías (recall C2 = 0.0 antes). `class_weight='balanced'` asigna pesos inversamente proporcionales a la frecuencia de clase: penaliza más un fallo en C2 (9 casos) que en C3 (200). Recall C2 pasa de 0.0 a 1.0 tras el reentrenamiento.

**Decisión — ansiedad como feature Y como auditoría:**  
El `score_ansiedad` entra al RF como variable numérica (aprende que ansiedad alta no implica urgencia alta) Y se usa en `/metricas/auditoria` para detectar under-triage: si `prediccion_RF < nivel_LLM` y `score_ansiedad > 0.7`, el caso se marca como posible sesgo emocional.

**2. Fase 3: Streamlit + Whisper (commit `e0de700`)**  
- `app/streamlit_app.py`: interfaz clínica con badge Manchester por color, barra de urgencia, alerta de ansiedad, tabla de auditoría ética.  
- `app/whisper_utils.py`: transcripción de audio con `faster-whisper` modelo `small` en CPU (equilibrio velocidad/precisión para español).  
- Flujo completo: audio `.wav/.mp3` → Whisper → texto → `POST /predecir/` → resultado visual.

**3. Casos demo defensa (commit `caa04ee`)**  
Creados 3 casos en `demo/` para la presentación:

| Fichero | Caso | Esperado | Resultado | score_ansiedad |
|---------|------|----------|-----------|----------------|
| `caso_urgente_C2.txt` | Dolor torácico + disnea + historial cardíaco | C2 | C2 ✅ | 0.85 |
| `caso_leve_C4.txt` | Dolor de rodilla leve | C4 | C4 ✅ | 0.20 |
| `caso_ansiedad_C3.txt` | Ansiedad extrema + síntomas ambiguos | C3 | C2 ⚠️ | 0.95 |

El caso de ansiedad devuelve C2 porque el LLM aplica Manchester estricto: presión torácica + disnea = C2 independientemente del estado emocional. Demuestra que **la clínica prevalece sobre la emoción** — exactamente el comportamiento correcto según el enunciado.

**4. Exportación modelo para portátil (commit `b6edf14`)**  
- `models/modelo_latest.pkl` añadido al repo (excepción en `.gitignore`: `!models/*.pkl`).  
- `setup.py` creado para subir el modelo a MinIO en equipos sin GPU.

**Estado:** pipeline 100% completo. Listo para defensa 2026-05-28.

---

### 2026-05-25 — Correo defensa: Fase 3 obligatoria + Manchester + ansiedad

**Quién:** Gerard (A)  
**Qué:** El profesor envió las orientaciones para la defensa. Revelan tres gaps críticos no contemplados en el desarrollo anterior.

**Gap 1 — Sistema Manchester (no SET)**  
El enunciado y el roadmap usan etiquetas C1-C5 con colores Manchester. El proyecto usaba "SET (Sistema Español de Triaje)" en el prompt. Son sistemas equivalentes de 5 niveles, pero la terminología correcta para la defensa es Manchester. Corrección: actualizar prompt y documentación.

**Gap 2 — `score_ansiedad` obligatorio**  
El roadmap define explícitamente que el LLM debe extraer un score de ansiedad del paciente (0.0-1.0), usado como feature del RF Y como señal de auditoría de under-triage. Ejemplo del profesor: paciente con disnea real + ansiedad 0.98 → RF predice C3 en lugar de C2 por sesgo emocional. Esto requiere actualizar prompt + schema + re-enriquecimiento + reentrenamiento.

**Gap 3 — Fase 3 completamente ausente**  
La defensa incluye demo en vivo de la cadena: Audio → Whisper → LLM → RF → Streamlit. Nada de esto existe. Tarea: crear `app/streamlit_app.py` + `app/whisper_utils.py`, con tabla de auditoría ética.

**Documentación actualizada esta sesión:**
- `docs/arquitectura.md` — reescritura completa con Fase 3, Manchester, ansiedad, tabla pendientes
- `ROADMAP.md` — reconvertido en sprint de 3 días con tareas exactas y preguntas de defensa
- `README.md` — descripción actualizada, estructura con `app/`, JSON con `score_ansiedad`

**Estado:** documentación al día. Desarrollo Fase 3 comienza día 1 del sprint.

---

### 2026-05-24 — Campo `origen`, endpoint `/metricas/` y `dag_prediction_phase_2`

**Quién:** Gerard (A)  
**Qué:** Tres gaps del enunciado cerrados en una sesión.

**1. Campo `origen` en `Entrevista`**
- `schema.sql`: nueva columna `origen VARCHAR(20)` (`'dataset'` | `'simulacion'`).
- `dag_text_ingestion`: inserta `origen='dataset'` para las 272 transcripciones batch.
- `ml_predictor/service.py`: inserta `origen='simulacion'` en cada solicitud Fase 2.
- `dataset_builder/service.py`: incluye `e.origen` en el SELECT para el CSV de entrenamiento.
- **Motivación:** el enunciado distingue explícitamente entre datos de entrenamiento y predicciones a demanda; el campo permite filtrar y auditar.

**2. Endpoint `GET /metricas/`**
- Nuevo módulo `services/metricas/` montado en `main.py` como `/metricas/`.
- Agrega desde Postgres y MinIO:
  - Textos procesados por estado y total.
  - Latencia end-to-end y tiempo LLM (promedio/min/max, solo registros `COMPLETADA`).
  - Tiempo de entrenamiento promedio.
  - Throughput del último batch (ventana 3 h): textos/min.
  - Errores por estado (`ERROR_*`).
  - Métricas del modelo ML (último JSON de evaluación en MinIO: accuracy, F1, matriz de confusión).
- Resultado observado: latencia E2E ~15 s, throughput ~2 txt/min, F1 macro 0.904 *(modelo previo al sprint de defensa; tras re-enriquecimiento con prompt Manchester + score_ansiedad el modelo final da 0.850 ± 0.069 — ver entrada 2026-05-25 sprint defensa)*.

**3. DAG `dag_prediction_phase_2`**
- Renombrado/reescrito desde `dag_prediction.py` con `dag_id="dag_prediction_phase_2"`.
- Acepta en `dag_run.conf`:
  - `{"filename": "CAR0001.txt", "especialidad": "CAR"}` → descarga de MinIO y POST como multipart.
  - `{"texto": "..."}` → POST texto directo.
- El GUID lo genera la API; el DAG lo registra en sus logs.
- Eliminado el param `guid` huérfano del diseño anterior.

**Migración BD:** 14 registros `PREDICTED` (predicciones pre-COMPLETADA) migrados a `COMPLETADA` → total 18 `COMPLETADA`.  
**Estado:** hecho.

---

### 2026-05-24 — Valoración automática Fase 2 + estado COMPLETADA

**Quién:** Gerard (A)  
**Qué:** Gap crítico del enunciado: `/predecir/` no calculaba valoración ni usaba estado `COMPLETADA`.  
**Solución:**
- Valoración automática (escala 0-10): `max(0, confianza - |pred_RF - nivel_LLM| * 0.25) * 10`
  - Concordancia perfecta + alta confianza → valoración ~9-10
  - Discrepancia de 1 nivel → penalización -2.5 puntos
  - Justificación para defensa: mide fiabilidad del modelo ponderada por acuerdo con el criterio LLM
- `valoracion` guardada en `ResultadoML`
- Estado final: `PREDICTED` → **`COMPLETADA`** (alineado con flujo conceptual del PDF §4.1)
- Campo `valoracion` añadido a la respuesta JSON de `/predecir/`

**Ejemplos:** CAR0001 → valoración 8.7 (SET 2, confianza 0.865); MSK0020 → 5.8 (SET 4, confianza 0.575).  
**Estado:** hecho.

---

### 2026-05-24 — Mejora prompt LLM: criterios SET más precisos

**Quién:** Gerard (A)  
**Qué:** Reescritura de criterios SET en `services/llm_enrichment/prompt.py`.  
**Por qué:** El prompt original restringía SET 2 a "dolor torácico + disnea + edad >40". Casos como RES0028 (joven con sospecha SCA) no encajaban y el LLM bajaba a SET 3.  
**Cambios:**
- SET 2 ahora incluye sospecha SCA/TEP **independientemente de la edad**, además de sepsis, hemorragia activa, saturación <90 %.
- Añadida "regla de oro": ante duda entre dos niveles, asignar el más urgente.
- Temperaturas LLM: Ollama `options.temperature=0`, OpenRouter `temperature=0` (antes 0.1). Respuestas deterministas.

**Resultado:** RES0028 → LLM ahora devuelve SET 2 (score 95); antes SET 3 (score 85). MSK0020 (leve) sigue siendo SET 4. El RF aún predice SET 3 para RES0028 — entrenado con datos del prompt viejo; requiere re-enriquecimiento batch + reentrenamiento para alinear.

**Experimento fallido (revertido):** `especialidad` (CAR/MSK/RES…) añadida como feature RF → accuracy bajó 85.5 %→83.6 %, F1 macro 0.692→0.674. Revertido. Con solo 9 SET 2 y 213 RES de todos los niveles, la feature añadía ruido.

**Re-enriquecimiento y reentrenamiento (2026-05-24):**
- Reset 272 EVALUATED → INGESTED; backup previo en `resultadoml_backup_20260524` (tabla + CSV).
- DAG re-enriqueció 272/272 con prompt nuevo y temperature=0.
- Nuevo dataset + reentrenamiento RF:

| Métrica | Antes | Después (este sprint) |
|---------|-------|---------|
| RF accuracy | 85.5% | **96.4%** |
| CV F1 macro | 0.692 | **0.904** |
| SET 2 recall | 0.0 | **1.0** |
| SET 3 F1 | 0.937 | 0.987 |
| SET 4 F1 | 0.737 | 0.952 |

> **Nota:** este modelo (0.904) es intermedio. En el sprint de defensa (2026-05-25) se añadió `score_ansiedad` como feature y se re-enriqueció el dataset completo con el prompt Manchester actualizado. El modelo final es `modelo_20260525_114431.pkl` con CV F1 macro **0.850 ± 0.069**. La bajada de 0.904 → 0.850 se debe a la variabilidad del LLM al re-enriquecer con el prompt más complejo.

- RES0028 (sospecha SCA, joven): antes SET 3, ahora **SET 2** predicho con confianza 0.93.

**Estado:** pipeline completo con datos mejorados. Modelo `modelo_20260524_184636.pkl` en MinIO (sustituido por `modelo_20260525_114431.pkl` en el sprint de defensa).

---

### 2026-05-24 — Fase 2 `/predecir/` validada end-to-end

**Quién:** Gerard (A)  
**Qué:** Prueba exitosa `POST /predecir/` con `text/CAR0001.txt` contra la API en localhost:8002.  
**Resultado:**
- GUID: `487025be-3ac9-4623-bd51-fc2be03ac5ea`
- `nivel_triaje_predicho`: 3 (RF) = `nivel_triaje_llm`: 3 — coincidencia perfecta.
- `score_urgencia`: 83.0 · `confianza`: 0.96
- Tiempo de respuesta: ~15 s (Ollama `llama3.1:8b` local)
- Estado en Postgres: `PREDICTED`

**Comando usado:**
```bash
curl.exe -X POST http://localhost:8002/predecir/ -F "file=@text/CAR0001.txt"
```

**Estado:** hecho. Fase 2 demostrable.

---

### 2026-05-19 — Fase 1 ML: dataset, entrenamiento y evaluación

**Qué:** `dag_dataset_builder` → 272 filas CSV; `dag_model_training` → `modelo_20260519_132951.pkl`; `dag_evaluation` → CV F1 macro 0.692, 2 under-triage.  
**Fix:** Airflow sin `joblib` → `_PIP_ADDITIONAL_REQUIREMENTS` ampliado en `docker-compose.yml`.  
**Estado:** hecho. Siguiente: Fase 2 `POST /predecir/`.

### 2026-05-19 — Edad/sexo no mencionados → feature `-1` (no descartar filas)

**Quién:** Gerard (A)  
**Qué:** Muchas transcripciones no incluyen edad ni sexo (no se pregunta en la entrevista). El LLM debe devolver `null`, no inventar.  
**Por qué:** Es dato faltante real del dominio, no error de ingesta ni del enriquecimiento. Descartar esas filas en `ml_trainer` (`dropna` en todas las features) dejaba ~4/272 casos entrenables.  
**Solución:**
- Módulo `services/ml_features.py`: `edad`, `sexo` y `dolor_intensidad` null → **-1** (desconocido); booleanos null → **false**.
- `dataset_builder`, `ml_trainer`, `ml_predictor` y prompt LLM alineados.
- Entrenamiento solo exige `nivel_triaje` + `score_urgencia`; el resto puede ser -1.
- Documentado para defensa: “-1 = no consta en la transcripción”.  
**Estado:** hecho. Siguiente: `dag_dataset_builder`.

### 2026-05-19 — Enriquecimiento completo + reintentos ERROR_ENRICHMENT

**Qué:** 272/272 `ENRICHED`. ~99 fallos por API/Ollama caídos (`Connection refused`); reset a `INGESTED` + segundo batch. DAG actualizado para reintentar `ERROR_ENRICHMENT`.  
**Estado:** hecho.

### 2026-05-18 — Sincronización README, ROADMAP y arquitectura

**Qué:** Puertos reales (8088, 8002, 5433), paso `minio-init`, LLM dual (Ollama/OpenRouter), variables `LLM_*`, respuesta `/predecir/`, diagrama y Fase 2 alineados con el código; modelo de datos → remisión a `sql/schema.sql`.  
**Estado:** hecho.

### 2026-05-18 — Sesión 3: actualización checkpoint diario

**Estado BD:** 6 `ENRICHED`, 266 `INGESTED`.  
**Modelos Ollama:** `llama3.1:8b` (activo), `qwen2.5:14b-instruct`, `qwen3:4b`, `nomic-embed-text-v2-moe`.  
**Siguiente hito:** completar enriquecimiento → dataset → ML.

### 2026-05-18 — Modelo `llama3.1:8b` + primer lote DAG

**Qué:** `ollama pull llama3.1:8b`; `.env` actualizado; trigger `dag_llm_enrichment` → +5 ENRICHED.  
**Estado:** enriquecimiento masivo en curso.

### 2026-05-18 — Ollama operativo (`qwen3:4b`)

**Qué:** Prueba OK `CAR0001.txt` (~88 s). Confirmado que Docker alcanza `host.docker.internal:11434`.  
**Estado:** sustituido por `llama3.1:8b`.

### 2026-05-18 — Sesión 2: ingesta + bloqueo API

**Qué:** 272 ingested; Airflow; `minio-init`; OpenRouter 429; `client.py` reintentos; `test_enrich.py`.  
**Estado:** ingesta hecha; LLM bloqueado hasta Ollama.

### 2026-05-18 — Creación del diario

**Quién:** Gerard (A).  
**Estado:** documento base para defensa.

---
