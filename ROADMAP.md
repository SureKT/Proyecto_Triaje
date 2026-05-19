# ROADMAP interno — Triaje IA

Documento de trabajo interno. No es un entregable. Recoge decisiones de diseño, división de tareas y borradores técnicos.

**Diario de desarrollo (defensa, fallos, cronología):** [`docs/diario-desarrollo.md`](docs/diario-desarrollo.md)

---

## Decisiones tomadas

| Decisión | Elección | Razón |
|---|---|---|
| Orquestador | **Solo Airflow** | Un orquestador único simplifica la arquitectura sin perder funcionalidad. Fase 2 se dispara via API REST de Airflow desde FastAPI. |
| LLM | **Ollama en host** (p. ej. `llama3.1:8b`) **u OpenRouter** | Batch sin 429 con Ollama; el profesor permite cualquier API para columnas del dataset. `LLM_PROVIDER` en `.env`. |
| Modelo ML | Random Forest + features del LLM | Simple, interpretable, adecuado para ~272 casos con desbalance de clases. |
| Score del dominio | `score_urgencia` (0–100) | Equivalente al `score_ansiedad` genérico de la spec, adaptado al dominio clínico. |
| Entrada Fase 2 | FastAPI `/predecir` → Airflow REST API | Sin n8n. FastAPI hace de API Gateway y delega la ejecución a Airflow. |

---

## División de tareas

El trabajo se divide en dos bloques con dependencia mínima entre sí para poder desarrollar en paralelo.

### Persona A

Responsable del núcleo de IA/ML y la lógica de los DAGs centrales.

| Tarea | Fichero(s) |
|---|---|
| Diseño y ajuste del prompt LLM | `services/llm_enrichment/prompt.py` |
| Servicio de enriquecimiento LLM | `services/llm_enrichment/` |
| DAG de enriquecimiento | `dags/dag_llm_enrichment.py` |
| Servicio de entrenamiento ML | `services/ml_trainer/` |
| DAG de entrenamiento | `dags/dag_model_training.py` |
| DAG de evaluación | `dags/dag_evaluation.py` |
| Documentación funcional | `docs/arquitectura.md` |

### Persona B

Responsable de la infraestructura, la ingesta de datos y la Fase 2.

| Tarea | Fichero(s) |
|---|---|
| Docker Compose y variables de entorno | `docker-compose.yml`, `.env.example` |
| Esquema SQL | `sql/schema.sql` |
| Servicio de preprocesado de texto | `services/preprocessor/` |
| DAG de ingesta | `dags/dag_text_ingestion.py` |
| DAG de construcción de dataset | `dags/dag_dataset_builder.py` |
| Servicio de predicción + endpoint FastAPI | `services/ml_predictor/` |
| DAG de predicción (Fase 2) | `dags/dag_prediction.py` |

### Punto de integración crítico

Antes de que Persona A pueda desarrollar `dag_llm_enrichment.py`, Persona B debe tener funcional:
- Postgres levantado con el esquema creado
- MinIO operativo con los buckets creados
- `dag_text_ingestion.py` ejecutado al menos una vez (registros en estado `INGESTED`)

---

## Orden de desarrollo recomendado

```
Semana 1
├── [B] docker-compose.yml + .env.example
├── [B] sql/schema.sql
├── [B] dag_text_ingestion.py
└── [A] services/llm_enrichment/ + prompt (desarrollo y pruebas locales)

Semana 2
├── [A] dag_llm_enrichment.py  (necesita semana 1 de B completada)
├── [B] dag_dataset_builder.py (necesita dag_llm_enrichment ejecutado)
└── [A] services/ml_trainer/ + dag_model_training.py

Semana 3
├── [A] dag_evaluation.py
├── [B] services/ml_predictor/ + dag_prediction.py
└── [A+B] Integración y pruebas end-to-end

Semana 4
└── [A+B] Pulir docs, presentación, README final
```

---

## Prompt LLM — borrador v1

```
Eres un médico de urgencias experto en triaje hospitalario usando el Sistema Español de Triaje (SET).
Analiza la siguiente transcripción de entrevista médico-paciente y devuelve EXCLUSIVAMENTE un JSON válido con esta estructura exacta:

{
  "nivel_triaje": <entero 1-5>,
  "score_urgencia": <float 0-100>,
  "motivo_consulta": "<resumen en 1 frase>",
  "entidades": ["<síntoma1>", "<síntoma2>"],
  "entidades_normalizadas": ["<término_médico1>", "<término_médico2>"],
  "edad": <entero o null>,
  "sexo": "<M|F|null>",
  "dolor_intensidad": <entero 0-10 o null>,
  "disnea": <true|false>,
  "fiebre": <true|false>,
  "perdida_consciencia": <true|false>,
  "irradiacion": <true|false>,
  "antecedentes_cardiacos": <true|false>,
  "fumador": <true|false>,
  "justificacion": "<razonamiento clínico breve>"
}

Criterios SET:
- Nivel 1 (Rojo/Inmediato): parada cardiorrespiratoria, pérdida de consciencia, compromiso vital inmediato
- Nivel 2 (Naranja/10 min): dolor torácico + disnea + edad >40, sospecha SCA/TEP, deterioro neurológico agudo
- Nivel 3 (Amarillo/60 min): dolor moderado-severo ≥7/10, fiebre alta, primer episodio agudo sin compromiso vital
- Nivel 4 (Verde/120 min): dolor leve-moderado <7/10, crónico reagudizado, sin signos de alarma
- Nivel 5 (Azul/240 min): consulta no urgente, síntomas leves, sin factores de riesgo

No incluyas nada antes ni después del JSON.

TRANSCRIPCIÓN:
{transcripcion}
```

---

## Notas técnicas

- **LLM:** en `.env`, `LLM_PROVIDER=openrouter` o `ollama`. Si no se define y existe `OPENROUTER_API_KEY`, se usa OpenRouter; si no, Ollama. Ollama debe correr en el **host**; los contenedores usan `host.docker.internal:11434`.
- **OpenRouter:** definir `OPENROUTER_API_KEY` y `OPENROUTER_MODEL`. Los modelos gratuitos pueden devolver HTTP 429 (rate limit).
- **Fase 2:** el endpoint `POST /predecir/` ejecuta hoy el pipeline **síncrono** (enrich + modelo) en `ml_predictor`. Para disparar solo `dag_prediction` vía Airflow: `POST http://airflow-webserver:8080/api/v1/dags/dag_prediction/dagRuns` con autenticación básica (integración con el mismo GUID puede requerir ajuste).
- El modelo `.pkl` se versiona con timestamp en el nombre (`modelo_20260514_143022.pkl`) para no sobreescribir versiones anteriores. `dag_prediction` carga siempre el más reciente.
- Airflow necesita `AIRFLOW_UID` configurado correctamente en Linux para evitar problemas de permisos en volúmenes montados.
- MinIO en modo standalone es suficiente para desarrollo; no hace falta cluster distribuido.
