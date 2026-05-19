# Diario de desarrollo — Triaje IA

**Documento interno.** No es entregable oficial. Sirve para la defensa oral: qué hemos hecho, por qué, qué falló y cómo lo resolvimos.  
**Mantener vivo:** añadir entradas al final de cada sesión o decisión relevante.

| Campo | Valor |
|-------|--------|
| Última actualización | 2026-05-18 (sesión 3) |
| Equipo | Persona A (Gerard) · Persona B (compañero/a) |
| Checkpoint | **6 ENRICHED · 266 INGESTED** (~2 % del batch LLM); **Ollama `llama3.1:8b`** en producción local |

---

## Cómo usar este documento

| Otro doc | Para qué sirve | Este diario |
|----------|----------------|-------------|
| `README.md` | Cómo levantar y ejecutar el sistema | No duplica comandos; enlaza si hace falta |
| `ROADMAP.md` | División de tareas, orden semanal, borrador de prompt | Registra **decisiones ya tomadas** y **por qué** |
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
| Enriquecimiento LLM (`dag_llm_enrichment`) | **En curso** — 6/272 ENRICHED |
| Dataset CSV + entrenamiento ML + evaluación | **Pendiente** (tras completar enriquecimiento) |
| Fase 2 `/predecir` con modelo entrenado | **Pendiente** |

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
- [ ] `dag_llm_enrichment` — **6/272** `ENRICHED` (en curso)
- [ ] `dag_dataset_builder`
- [ ] `dag_model_training`
- [ ] `dag_evaluation`

### Fase 2

- [ ] Modelo `.pkl` en MinIO
- [ ] Prueba `/predecir` end-to-end
- [ ] Revisar `guid` en `dag_prediction` vs `/predecir` (deuda D3)

### Documentación

- [x] `docs/arquitectura.md` (borrador)
- [x] Este diario
- [ ] Sincronizar SQL en `arquitectura.md` con `schema.sql`

---

## 6. Problemas conocidos / deuda técnica

| ID | Descripción | Estado |
|----|-------------|--------|
| D1 | README puertos ≠ compose | Abierto |
| D2 | `arquitectura.md` SQL desactualizado | Abierto |
| D3 | `dag_prediction` / `guid` inconsistente | Abierto |
| D4 | Rate limit API free | **Mitigado** — Ollama local |
| D5 | `UNIQUE` en `ResultadoML` | **Resuelto** |
| D6 | Buckets MinIO tras primer `compose up` | **Resuelto** — ejecutar `minio-init` |
| D7 | OpenRouter 429 | **Evitado** — `LLM_PROVIDER=ollama` |

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

1. **En curso:** Repetir `dag_llm_enrichment` hasta `INGESTED = 0` (~54 triggers × 5 entrevistas).
2. `dag_dataset_builder` → CSV en MinIO.
3. `dag_model_training` + `dag_evaluation`.
4. Prueba Fase 2 con `/predecir`.
5. Pulir README y `arquitectura.md`.

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
