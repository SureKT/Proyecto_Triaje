"""
dags/dag_model_training.py
Entrena el modelo ML y lo sube a MinIO.
"""
import os
import json
from datetime import datetime, timedelta

import httpx
from airflow import DAG
from airflow.operators.python import PythonOperator

API_BASE = os.environ.get("API_BASE_URL", "http://api:8000")

DEFAULT_ARGS = {
    "owner": "triaje",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


def _train():
    resp = httpx.post(f"{API_BASE}/entrenar/", timeout=300)
    resp.raise_for_status()
    result = resp.json()
    print(f"Modelo: {result['modelo']}")
    print(f"RF accuracy : {result['rf_accuracy']:.3f}")
    print(f"LR accuracy : {result['lr_accuracy']:.3f}")
    print(f"CV F1 macro : {result['cv_f1_macro']:.3f}")
    print(f"Class weights: {result['class_weights']}")


with DAG(
    dag_id="dag_model_training",
    description="Entrena Random Forest y sube modelo a MinIO",
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["triaje", "fase1"],
) as dag:

    train = PythonOperator(task_id="train_model", python_callable=_train)
