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


def predict(texto: str) -> dict:
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
           (GUID_Entrevista, Estado, Motor_Workflow, Inicio_Solicitud)
           VALUES (%s, %s, %s, %s)""",
        (guid, "INGESTED", "airflow", t0),
    )

    # ── 2. Subir texto a MinIO ─────────────────────────────────────────────────
    url_texto = minio_upload_text(BUCKET_TEXTOS, f"fase2/{guid}.txt", texto)
    pg_execute(
        "UPDATE Entrevista SET URL_Texto_Original = %s WHERE GUID_Entrevista = %s",
        (url_texto, guid),
    )

    # ── 3. Preprocesar + enriquecer con LLM ────────────────────────────────────
    resultado_llm = enrich(guid, texto)

    # ── 5. Cargar modelo y predecir ────────────────────────────────────────────
    model, model_name = load_latest_model()

    X = pd.DataFrame([row_from_llm_result(resultado_llm)])[FEATURES]
    pred     = int(model.predict(X)[0])
    proba    = model.predict_proba(X)[0]
    confianza = float(max(proba))

    # ── 6. Guardar predicción ──────────────────────────────────────────────────
    pg_execute(
        """UPDATE ResultadoML
           SET prediccion_modelo = %s, confianza = %s
           WHERE GUID_Entrevista = %s""",
        (pred, confianza, guid),
    )
    pg_execute(
        """UPDATE Entrevista
           SET Estado = 'PREDICTED', URL_Modelo_Entrenado = %s, Fin_Solicitud = %s
           WHERE GUID_Entrevista = %s""",
        (model_name, now(), guid),
    )

    return {
        "GUID":                   guid,
        "nivel_triaje_predicho":  pred,
        "nivel_triaje_llm":       resultado_llm.get("nivel_triaje"),
        "score_urgencia":         resultado_llm.get("score_urgencia"),
        "confianza":              round(confianza, 3),
        "motivo_consulta":        resultado_llm.get("motivo_consulta"),
        "justificacion":          resultado_llm.get("justificacion"),
        "entidades_normalizadas": resultado_llm.get("entidades_normalizadas", []),
    }
