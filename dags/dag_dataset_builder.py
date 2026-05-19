"""
dags/dag_dataset_builder.py
Consolida los registros ENRICHED en un CSV y lo sube a MinIO.
"""
import os
from datetime import datetime, timedelta

import httpx
from airflow import DAG
from airflow.operators.python import PythonOperator

API_BASE = os.environ.get("API_BASE_URL", "http://api:8000")

DEFAULT_ARGS = {
    "owner": "triaje",
    "retries": 2,
    "retry_delay": timedelta(seconds=30),
}


def _build():
    resp = httpx.post(f"{API_BASE}/dataset/", timeout=120)
    resp.raise_for_status()
    print(f"Dataset generado: {resp.json()['url']}")


with DAG(
    dag_id="dag_dataset_builder",
    description="Construye el CSV de entrenamiento desde Postgres",
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["triaje", "fase1"],
) as dag:

    build = PythonOperator(task_id="build_dataset", python_callable=_build)
