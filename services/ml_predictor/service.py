"""
services/ml_predictor/service.py
Carga el modelo más reciente de MinIO y genera predicciones (Fase 2).
"""
import os
import io
import logging
import joblib
import httpx
import pandas as pd
from datetime import datetime

from common import (pg_execute, update_estado, minio_download_bytes,
                    minio_list_objects, minio_upload_text, new_guid, now)
from llm_enrichment.service import enrich
from ml_features import FEATURES, row_from_llm_result

logger = logging.getLogger(__name__)

BUCKET_MODELOS  = os.environ.get("MINIO_BUCKET_MODELOS",  "modelos")
BUCKET_TEXTOS   = os.environ.get("MINIO_BUCKET_TEXTOS",   "textos-originales")
AIRFLOW_BASE    = os.environ.get("AIRFLOW_BASE_URL",       "http://airflow-webserver:8080")
AIRFLOW_USER    = os.environ.get("AIRFLOW_USER",           "admin")
AIRFLOW_PASS    = os.environ.get("AIRFLOW_PASSWORD",       "admin")

def load_latest_model():
    objects = sorted(minio_list_objects(BUCKET_MODELOS, prefix="modelo_"))
    if not objects:
        raise FileNotFoundError("MODEL_NOT_FOUND: No hay modelos entrenados en MinIO.")
    latest = objects[-1]
    buf    = io.BytesIO(minio_download_bytes(BUCKET_MODELOS, latest))
    logger.info(f"Modelo cargado: {latest}")
    return joblib.load(buf), latest


def _especialidad_from_filename(filename: str) -> str:
    """Extrae código de especialidad del nombre de fichero (ej. CAR0001.txt → CAR)."""
    prefix = "".join(c for c in filename[:3] if c.isalpha()).upper()
    from ml_features import ESPECIALIDAD_MAP
    return prefix if prefix in ESPECIALIDAD_MAP else "UNK"


def predict(texto: str, filename: str = "") -> dict:
    """
    Pipeline completo Fase 2:
    1. Crea registro en Postgres
    2. Sube texto a MinIO
    3. Preprocesa + enriquece con LLM
    4. Carga modelo y predice
    5. Guarda predicción
    """
    guid = new_guid()
    t0   = now()

    # ── 1. Registro inicial ────────────────────────────────────────────────────
    pg_execute(
        """INSERT INTO Entrevista
           (GUID_Entrevista, Estado, Motor_Workflow, Inicio_Solicitud, origen)
           VALUES (%s, %s, %s, %s, %s)""",
        (guid, "INGESTED", "airflow", t0, "simulacion"),
    )

    # ── 2. Subir texto a MinIO ─────────────────────────────────────────────────
    url_texto = minio_upload_text(BUCKET_TEXTOS, f"fase2/{guid}.txt", texto)
    pg_execute(
        "UPDATE Entrevista SET URL_Texto_Original = %s WHERE GUID_Entrevista = %s",
        (url_texto, guid),
    )

    # ── 3. Preprocesar + enriquecer con LLM ────────────────────────────────────
    resultado_llm = enrich(guid, texto)
    especialidad  = _especialidad_from_filename(filename)

    # ── 5. Cargar modelo y predecir ────────────────────────────────────────────
    model, model_name = load_latest_model()

    X = pd.DataFrame([row_from_llm_result(resultado_llm, especialidad)])[FEATURES]
    pred      = int(model.predict(X)[0])
    proba     = model.predict_proba(X)[0]
    confianza = float(max(proba))

    # ── 6. Valoración automática ───────────────────────────────────────────────
    # Confianza del RF penalizada por discrepancia con nivel LLM (escala 0-10).
    nivel_llm   = resultado_llm.get("nivel_triaje") or pred
    discrepancia = abs(pred - nivel_llm)
    valoracion   = round(max(0.0, confianza - discrepancia * 0.25) * 10, 1)

    # ── 7. Guardar predicción y valoración → COMPLETADA ───────────────────────
    pg_execute(
        """UPDATE ResultadoML
           SET prediccion_modelo = %s, confianza = %s, valoracion = %s
           WHERE GUID_Entrevista = %s""",
        (pred, confianza, valoracion, guid),
    )
    pg_execute(
        """UPDATE Entrevista
           SET Estado = 'COMPLETADA', URL_Modelo_Entrenado = %s, Fin_Solicitud = %s
           WHERE GUID_Entrevista = %s""",
        (model_name, now(), guid),
    )

    nivel_manchester = f"C{pred}"

    return {
        "GUID":                   guid,
        "nivel_triaje_predicho":  pred,
        "nivel_manchester":       nivel_manchester,
        "nivel_triaje_llm":       nivel_llm,
        "score_urgencia":         resultado_llm.get("score_urgencia"),
        "score_ansiedad":         resultado_llm.get("score_ansiedad"),
        "confianza":              round(confianza, 3),
        "valoracion":             valoracion,
        "motivo_consulta":        resultado_llm.get("motivo_consulta"),
        "justificacion":          resultado_llm.get("justificacion"),
        "entidades_normalizadas": resultado_llm.get("entidades_normalizadas", []),
    }
