"""
dags/dag_prediction.py
DAG de predicción (Fase 2). Disparado por FastAPI via Airflow REST API.
Recibe el GUID por conf y ejecuta el pipeline completo de predicción.
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
    """
    Recibe el GUID y el texto desde conf (params pasados por FastAPI).
    Llama al servicio de predicción.
    """
    import httpx
    params = context["dag_run"].conf or {}
    guid   = params.get("guid")
    texto  = params.get("texto")

    if not guid or not texto:
        raise ValueError("Se requieren 'guid' y 'texto' en dag_run.conf")

    resp = httpx.post(
        f"{API_BASE}/predecir/",
        data={"texto": texto},
        timeout=180,
    )
    resp.raise_for_status()
    result = resp.json()

    logger.info(f"[{guid}] Predicción: nivel={result['nivel_triaje_predicho']}  "
                f"confianza={result['confianza']}")
    print(f"Resultado: {result}")
    return result


with DAG(
    dag_id="dag_prediction",
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
