-- ── Schema Triaje IA ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS Entrevista (
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
    Motor_Workflow              VARCHAR(50),
    Workflow_Id                 VARCHAR(255),
    Estado                      VARCHAR(50),
    nombre_fichero              VARCHAR(255),
    especialidad                VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS Entidad (
    id                  SERIAL PRIMARY KEY,
    GUID_Entrevista     VARCHAR(255) REFERENCES Entrevista(GUID_Entrevista),
    entidad_raw         TEXT,
    entidad_normalizada TEXT,
    tipo                VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS ResultadoML (
    id                  SERIAL PRIMARY KEY,
    GUID_Entrevista     VARCHAR(255) REFERENCES Entrevista(GUID_Entrevista),
    -- Features extraídas por el LLM
    edad                INT,
    sexo                VARCHAR(1),
    dolor_intensidad    INT,
    disnea              BOOLEAN,
    fiebre              BOOLEAN,
    perdida_consciencia BOOLEAN,
    irradiacion         BOOLEAN,
    antecedentes_cardiacos BOOLEAN,
    fumador             BOOLEAN,
    motivo_consulta     TEXT,
    justificacion       TEXT,
    -- Etiquetas y scores
    score_urgencia      FLOAT,
    nivel_triaje        INT,          -- Ground Truth asignado por LLM (F1)
    -- Predicción del modelo ML (F2)
    prediccion_modelo   INT,
    confianza           FLOAT,
    valoracion          FLOAT,
    timestamp_pred      TIMESTAMP
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_entrevista_estado    ON Entrevista(Estado);
CREATE INDEX IF NOT EXISTS idx_entrevista_especialidad ON Entrevista(especialidad);
CREATE INDEX IF NOT EXISTS idx_entidad_guid         ON Entidad(GUID_Entrevista);
CREATE UNIQUE INDEX IF NOT EXISTS idx_resultado_guid_unique ON ResultadoML(GUID_Entrevista);
CREATE INDEX IF NOT EXISTS idx_resultado_triaje     ON ResultadoML(nivel_triaje);
