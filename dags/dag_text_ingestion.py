"""
dags/dag_text_ingestion.py
Lee los .txt de /opt/airflow/text/, sube a MinIO y crea registros en Postgres.
"""
import os
import uuid
import logging
from pathlib import Path
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

TEXT_DIR = Path("/opt/airflow/text")

DEFAULT_ARGS = {
    "owner": "triaje",
    "retries": 3,
    "retry_delay": timedelta(seconds=30),
    "retry_exponential_backoff": True,
}


def _ingest_texts():
    import sys
    sys.path.insert(0, "/opt/airflow/dags")
    from common import get_pg_conn, get_minio_client, now

    bucket  = os.environ["MINIO_BUCKET_TEXTOS"]
    client  = get_minio_client()
    conn    = get_pg_conn()

    txt_files = sorted(TEXT_DIR.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No hay .txt en {TEXT_DIR}")

    ingested = skipped = errors = 0

    with conn:
        with conn.cursor() as cur:
            for txt in txt_files:
                try:
                    # Comprobar si ya existe
                    cur.execute(
                        "SELECT 1 FROM Entrevista WHERE nombre_fichero = %s",
                        (txt.name,),
                    )
                    if cur.fetchone():
                        skipped += 1
                        continue

                    # Leer con detección de codificación
                    texto = None
                    for enc in ["utf-8", "utf-16", "latin-1"]:
                        try:
                            texto = txt.read_text(encoding=enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    if texto is None:
                        raise ValueError(f"No se pudo decodificar {txt.name}")

                    # Especialidad desde nombre de fichero (RES, MSK, CAR, GAS…)
                    especialidad = "".join(c for c in txt.stem if c.isalpha()).upper()[:3]

                    guid        = str(uuid.uuid4())
                    object_name = f"{especialidad}/{txt.name}"

                    # Subir a MinIO
                    import io
                    data = texto.encode("utf-8")
                    client.put_object(bucket, object_name, io.BytesIO(data), len(data),
                                      content_type="text/plain")
                    url = f"{os.environ['MINIO_ENDPOINT']}/{bucket}/{object_name}"

                    # Insertar en Postgres
                    cur.execute(
                        """INSERT INTO Entrevista
                           (GUID_Entrevista, URL_Texto_Original, Estado, Motor_Workflow,
                            Inicio_Solicitud, nombre_fichero, especialidad)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (guid, url, "INGESTED", "airflow", now(), txt.name, especialidad),
                    )
                    ingested += 1
                    logger.info(f"INGESTED {txt.name} → {guid}")

                except Exception as e:
                    logger.error(f"ERROR en {txt.name}: {e}")
                    errors += 1

    logger.info(f"Ingesta completa — ingested={ingested}  skipped={skipped}  errors={errors}")
    if errors:
        raise RuntimeError(f"{errors} ficheros fallaron en la ingesta.")


with DAG(
    dag_id="dag_text_ingestion",
    description="Ingesta de transcripciones .txt a MinIO y Postgres",
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,  # manual
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["triaje", "fase1"],
) as dag:

    ingest = PythonOperator(
        task_id="ingest_texts",
        python_callable=_ingest_texts,
    )
