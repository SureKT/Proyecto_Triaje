"""
dags/dag_prediction.py
DAG de predicción Fase 2. Acepta 'filename' (objeto en MinIO) o 'texto' en conf.
El GUID lo genera internamente la API — no se pasa en conf.

Uso:
    airflow dags trigger dag_prediction_phase_2 \
        --conf '{"filename": "CAR0001.txt", "especialidad": "CAR"}'
    airflow dags trigger dag_prediction_phase_2 \
        --conf '{"texto": "Paciente con dolor torácico..."}'
"""
import os
import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

API_BASE = os.environ.get("API_BASE_URL", "http://api:8000")

DEFAULT_ARGS = {
    "owner": "triaje",
    "retries": 3,
    "retry_delay": timedelta(seconds=30),
    "retry_exponential_backoff": True,
}


def _predict(**context):
    import httpx
    import sys
    sys.path.insert(0, "/opt/airflow/dags")
    from common import minio_download_bytes

    params   = context["dag_run"].conf or {}
    filename = params.get("filename", "").strip()
    texto    = params.get("texto", "").strip()

    if not filename and not texto:
        raise ValueError("dag_run.conf debe incluir 'filename' o 'texto'.")

    if filename:
        bucket = os.environ.get("MINIO_BUCKET_TEXTOS", "textos-originales")
        especialidad = params.get("especialidad", filename[:3].upper())
        object_key   = f"{especialidad}/{filename}"
        try:
            raw   = minio_download_bytes(bucket, object_key)
            texto = raw.decode("utf-8", errors="replace")
        except Exception as e:
            raise RuntimeError(f"No se pudo descargar {object_key} de MinIO: {e}")

        resp = httpx.post(
            f"{API_BASE}/predecir/",
            files={"file": (filename, texto.encode("utf-8"), "text/plain")},
            timeout=300,
        )
    else:
        resp = httpx.post(
            f"{API_BASE}/predecir/",
            data={"texto": texto},
            timeout=300,
        )

    resp.raise_for_status()
    result = resp.json()

    logger.info(
        f"GUID={result['GUID']}  "
        f"nivel_predicho={result['nivel_triaje_predicho']}  "
        f"nivel_llm={result['nivel_triaje_llm']}  "
        f"confianza={result['confianza']}  "
        f"valoracion={result.get('valoracion', 'N/A')}"
    )
    return result


with DAG(
    dag_id="dag_prediction_phase_2",
    description="Predicción de triaje para nuevas entrevistas (Fase 2)",
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["triaje", "fase2"],
) as dag:

    predict = PythonOperator(
        task_id="predict",
        python_callable=_predict,
    )
