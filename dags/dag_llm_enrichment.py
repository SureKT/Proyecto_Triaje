"""
dags/dag_llm_enrichment.py
Para cada entrevista INGESTED o ERROR_ENRICHMENT, llama al servicio de enriquecimiento LLM.
"""
import os
import time
import logging
from datetime import datetime, timedelta

import httpx
from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

API_BASE = os.environ.get("API_BASE_URL", "http://api:8000")
TIMEOUT  = int(os.environ.get("LLM_TIMEOUT", "300"))
BATCH_LIMIT = int(os.environ.get("LLM_BATCH_LIMIT", "0"))  # 0 = todas las INGESTED
LLM_DELAY_SEC = float(os.environ.get("LLM_DELAY_SEC", "0"))

DEFAULT_ARGS = {
    "owner": "triaje",
    "retries": 3,
    "retry_delay": timedelta(seconds=60),
    "retry_exponential_backoff": True,
}


def _enrich_all():
    import sys
    sys.path.insert(0, "/opt/airflow/dags")
    from common import pg_execute, minio_download_text, update_estado

    bucket = os.environ["MINIO_BUCKET_TEXTOS"]

    limit_sql = f" LIMIT {BATCH_LIMIT}" if BATCH_LIMIT > 0 else ""
    rows = pg_execute(
        f"""SELECT GUID_Entrevista, nombre_fichero, especialidad
            FROM Entrevista
            WHERE Estado IN ('INGESTED', 'ERROR_ENRICHMENT')
            ORDER BY nombre_fichero{limit_sql}""",
        fetch=True,
    )
    if not rows:
        logger.info("No hay entrevistas pendientes (INGESTED / ERROR_ENRICHMENT).")
        return

    logger.info(
        f"Procesando {len(rows)} entrevistas "
        f"(batch_limit={BATCH_LIMIT or 'sin límite'}, delay={LLM_DELAY_SEC}s, timeout={TIMEOUT}s)"
    )
    ok = err = 0
    for i, row in enumerate(rows):
        if i > 0 and LLM_DELAY_SEC > 0:
            time.sleep(LLM_DELAY_SEC)
        guid = row["guid_entrevista"]
        try:
            object_name = f"{row['especialidad']}/{row['nombre_fichero']}"
            texto = minio_download_text(bucket, object_name)

            resp = httpx.post(
                f"{API_BASE}/enriquecer/",
                json={"guid": guid, "texto": texto},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            ok += 1
            logger.info(f"ENRICHED {guid}")

        except Exception as e:
            logger.error(f"ERROR enriqueciendo {guid}: {e}")
            update_estado(guid, "ERROR_ENRICHMENT")
            err += 1

    logger.info(f"Enriquecimiento completo — ok={ok}  errores={err}")
    if err:
        raise RuntimeError(f"{err} entrevistas fallaron en el enriquecimiento.")


with DAG(
    dag_id="dag_llm_enrichment",
    description="Enriquecimiento LLM (INGESTED + reintentos ERROR_ENRICHMENT)",
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["triaje", "fase1"],
) as dag:

    enrich = PythonOperator(
        task_id="enrich_all",
        python_callable=_enrich_all,
        execution_timeout=timedelta(hours=12),
    )
