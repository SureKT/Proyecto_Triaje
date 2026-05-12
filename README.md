# Clasificación de Triaje de Urgencias con IA

Sistema de clasificación automática del nivel de triaje en urgencias hospitalarias a partir de transcripciones de entrevistas médico-paciente, usando procesamiento de lenguaje natural (NLP) y aprendizaje automático.

---

## Descripción del proyecto

El triaje determina la prioridad de atención de un paciente en urgencias. Este proyecto entrena un modelo de IA capaz de leer la transcripción de una entrevista clínica y predecir el nivel de urgencia según el **Sistema Español de Triaje (SET)**, equivalente al Manchester Triage System (MTS):

| Nivel | Color | Denominación | Tiempo máx. atención |
|-------|-------|--------------|----------------------|
| 1 | Rojo | Resucitación / Inmediato | Inmediato |
| 2 | Naranja | Emergencia | 10 min |
| 3 | Amarillo | Urgencia | 60 min |
| 4 | Verde | Menos urgente | 120 min |
| 5 | Azul | No urgente | 240 min |

---

## Estructura del repositorio

```
Proyecto_Triaje_IA/
├── text/                   # Transcripciones brutas de entrevistas médico-paciente
│   ├── CAR*.txt            # Cardiología        (  5 casos)
│   ├── DER*.txt            # Dermatología       (  1 caso )
│   ├── GAS*.txt            # Gastroenterología  (  6 casos)
│   ├── GEN*.txt            # General            (  1 caso )
│   ├── MSK*.txt            # Musculoesquelético ( 46 casos)
│   └── RES*.txt            # Respiratorio       (213 casos)
│
├── data/                   # (pendiente) Dataset estructurado y etiquetado
│   ├── raw/                # Copias originales sin tocar
│   ├── processed/          # Features extraídas por caso
│   └── labeled/            # Dataset final con etiqueta de triaje
│
├── notebooks/              # (pendiente) Análisis exploratorio y experimentos
├── src/                    # (pendiente) Código fuente modular
│   ├── parse.py            # Parser de transcripciones → features estructuradas
│   ├── label.py            # Etiquetado automático asistido por LLM
│   ├── train.py            # Entrenamiento de modelos
│   └── evaluate.py         # Métricas y evaluación
│
├── models/                 # (pendiente) Modelos entrenados serializados
└── README.md
```

---

## Datos disponibles

### Formato de las transcripciones

Cada fichero `.txt` contiene un diálogo estructurado entre médico (`D:`) y paciente (`P:`). Las entrevistas recogen:

- **Motivo de consulta** — síntoma principal y duración
- **Características del síntoma** — localización, intensidad (escala 1-10), irradiación, factores agravantes/atenuantes
- **Síntomas asociados** — disnea, fiebre, náuseas, pérdida de consciencia, etc.
- **Antecedentes personales** — patologías previas, cirugías, hospitalizaciones
- **Medicación actual** y alergias
- **Historia social** — tabaco, alcohol, drogas, ocupación, convivencia
- **Antecedentes familiares** — enfermedades relevantes en familiares de primer grado

### Distribución por especialidad

| Especialidad | Prefijo | Casos |
|-------------|---------|-------|
| Respiratorio | `RES` | 213 |
| Musculoesquelético | `MSK` | 46 |
| Cardiología | `CAR` | 5 |
| Gastroenterología | `GAS` | 6 |
| Dermatología | `DER` | 1 |
| General | `GEN` | 1 |
| **Total** | | **272** |

> **Nota:** El dataset actual está sesgado hacia casos respiratorios y musculoesqueléticos. Ver sección de construcción del dataset para estrategias de balanceo.

---

## Plan de desarrollo

### Fase 1 — Construcción del dataset
> Objetivo: obtener un CSV estructurado y etiquetado, listo para entrenar.

- [ ] **1.1** Parser de transcripciones: extraer features clínicas en formato estructurado
- [ ] **1.2** Etiquetado de triaje: asignación de nivel 1-5 a cada caso (proceso semi-automático con LLM + revisión manual)
- [ ] **1.3** Validación y limpieza: detectar duplicados, casos incompletos, errores de etiquetado
- [ ] **1.4** Balanceo de clases: aumentación de datos y/o submuestreo para distribuir niveles de triaje

### Fase 2 — Análisis exploratorio (EDA)
> Objetivo: entender la distribución de datos antes de modelar.

- [ ] **2.1** Distribución de niveles de triaje por especialidad
- [ ] **2.2** Frecuencia de síntomas por nivel de triaje
- [ ] **2.3** Análisis de longitud y estructura de las transcripciones
- [ ] **2.4** Detección de features más discriminativas

### Fase 3 — Preprocesamiento NLP
> Objetivo: transformar texto libre en representaciones utilizables por los modelos.

- [ ] **3.1** Limpieza textual: normalización, eliminación de disfluencias (`uh`, `um`, repeticiones)
- [ ] **3.2** Extracción de entidades clínicas (NER): síntomas, medicamentos, patologías
- [ ] **3.3** Representaciones de texto: TF-IDF, embeddings (BioBERT / ClinicalBERT)
- [ ] **3.4** Features estructuradas: edad, sexo, escala de dolor, duración, síntomas binarios

### Fase 4 — Modelado
> Objetivo: entrenar y comparar modelos de clasificación multiclase (5 niveles de triaje).

- [ ] **4.1** Baselines: Regresión Logística, Random Forest, SVM con TF-IDF
- [ ] **4.2** Modelos de secuencia: LSTM / GRU sobre embeddings
- [ ] **4.3** Fine-tuning de modelos transformer: BioBERT, ClinicalBERT, o multilingual BERT
- [ ] **4.4** Enfoque híbrido: features estructuradas + representación textual

### Fase 5 — Evaluación
> Objetivo: medir el rendimiento con métricas clínicamente relevantes.

- [ ] **5.1** Métricas: accuracy, macro-F1, matriz de confusión por nivel
- [ ] **5.2** Análisis de errores: confusión entre niveles adyacentes (clínicamente aceptable) vs. saltos graves
- [ ] **5.3** Validación cruzada estratificada por especialidad
- [ ] **5.4** Interpretabilidad: SHAP / LIME para explicar predicciones

### Fase 6 — Despliegue (opcional)
- [ ] **6.1** API REST con FastAPI
- [ ] **6.2** Interfaz web mínima para demo

---

## Construcción del dataset

### Estrategia de etiquetado

Las transcripciones **no tienen etiqueta de triaje** asignada. El etiquetado se hará en dos pasos:

#### Paso A — Etiquetado automático asistido por LLM

Se usará la API de Claude para leer cada transcripción y asignar un nivel de triaje provisional basándose en criterios clínicos del SET/MTS:

```python
# Pseudocódigo del proceso de etiquetado
for cada transcripcion en text/:
    features = extraer_features(transcripcion)   # síntomas, edad, dolor, etc.
    nivel_propuesto = llm_clasificar(transcripcion, criterios_SET)
    guardar(features, nivel_propuesto, confianza)
```

**Criterios de asignación de nivel** que el LLM debe seguir:

| Señal clínica | Nivel sugerido |
|--------------|----------------|
| Pérdida de consciencia, parada cardiorrespiratoria | 1 |
| Dolor torácico + disnea + edad >40, sospecha SCA o TEP | 2 |
| Dolor moderado-severo (≥7/10), fiebre alta, primer episodio agudo | 3 |
| Dolor leve-moderado (<7/10), crónico reagudizado, sin signos de alarma | 4 |
| Consulta no urgente, síntomas leves, sin factores de riesgo | 5 |

#### Paso B — Revisión y validación manual

- Al menos el 20% de los casos etiquetados deben ser revisados por un experto clínico o comparados con literatura.
- Se documentará el acuerdo inter-anotador (Cohen's Kappa) si hay más de un revisor.
- Los casos con baja confianza del LLM se marcan para revisión prioritaria.

### Extracción de features estructuradas

Cada transcripción se convierte en un registro con las siguientes columnas:

| Feature | Tipo | Descripción |
|---------|------|-------------|
| `id` | str | Identificador del fichero (`CAR0001`) |
| `especialidad` | cat | Prefijo de especialidad |
| `edad` | int | Edad del paciente |
| `sexo` | cat | M / F |
| `motivo_consulta` | text | Síntoma principal (texto libre resumido) |
| `dolor_intensidad` | int | Escala 1-10 (0 si no aplica) |
| `dolor_duracion_horas` | float | Duración del síntoma principal en horas |
| `disnea` | bool | Presencia de dificultad respiratoria |
| `fiebre` | bool | Fiebre referida o medida |
| `perdida_consciencia` | bool | Síncope o pérdida de consciencia |
| `irradiacion` | bool | Dolor irradiado |
| `sintomas_neurologicos` | bool | Deficit motor, sensitivo, confusión |
| `antecedentes_cardiacos` | bool | Cardiopatía previa |
| `fumador` | bool | Consumo activo de tabaco |
| `transcripcion_completa` | text | Texto limpio del diálogo completo |
| `nivel_triaje` | int | **Etiqueta objetivo** (1-5) |

### Balanceo del dataset

Con 272 casos actuales y mayoría en RES/MSK, se esperan pocos casos de nivel 1-2. Estrategias:

1. **Aumentación textual**: parafrasear casos de niveles minoritarios con LLM
2. **Síntesis de casos**: generar casos sintéticos realistas para niveles 1 y 2 guiados por criterios clínicos
3. **Submuestreo** de nivel 4-5 si hay superrepresentación
4. **Weighted loss** en el entrenamiento para compensar el desbalance

---

## Tecnologías previstas

| Área | Herramienta |
|------|-------------|
| Lenguaje | Python 3.11+ |
| NLP / Embeddings | `transformers` (HuggingFace), `spaCy`, `scikit-learn` |
| Modelos | BioBERT, ClinicalBERT, `sklearn` classifiers |
| Etiquetado LLM | Anthropic API (Claude) |
| Análisis de datos | `pandas`, `matplotlib`, `seaborn` |
| Tracking experimentos | MLflow o Weights & Biases |
| API (opcional) | FastAPI |

---

## Referencias

- **Sistema Español de Triaje (SET):** Sociedad Española de Medicina de Urgencias y Emergencias (SEMES)
- **Manchester Triage System:** Mackway-Jones et al.
- **BioBERT:** Lee et al., 2019 — *BioBERT: a pre-trained biomedical language representation model*
- **ClinicalBERT:** Alsentzer et al., 2019 — *Publicly Available Clinical BERT Embeddings*
