"""
services/common.py
Utilidades compartidas: conexión Postgres, cliente MinIO, helpers.
"""
import os
import json
import uuid
import logging
from datetime import datetime

import psycopg2
import psycopg2.extras
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


# ── Postgres ───────────────────────────────────────────────────────────────────

def get_pg_conn():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def pg_execute(sql: str, params=None, fetch: bool = False):
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                if fetch:
                    return cur.fetchall()
    finally:
        conn.close()


def ensure_entrevista(guid: str, estado: str = "INGESTED") -> None:
    """Crea la fila en Entrevista si no existe (pruebas manuales o Fase 2)."""
    pg_execute(
        """INSERT INTO Entrevista (GUID_Entrevista, Estado, Motor_Workflow, Inicio_Solicitud)
           VALUES (%s, %s, 'api', %s)
           ON CONFLICT (GUID_Entrevista) DO NOTHING""",
        (guid, estado, now()),
    )


def update_estado(guid: str, estado: str, **timestamps):
    """
    Actualiza el estado de una entrevista y opcionalmente sus timestamps.
    timestamps: dict de columna → valor (ej. Fin_Preprocesamiento=datetime.utcnow())
    """
    sets = ["Estado = %s"]
    vals = [estado]
    for col, val in timestamps.items():
        sets.append(f"{col} = %s")
        vals.append(val)
    vals.append(guid)
    pg_execute(
        f"UPDATE Entrevista SET {', '.join(sets)} WHERE GUID_Entrevista = %s",
        vals,
    )


# ── MinIO ──────────────────────────────────────────────────────────────────────

def get_minio_client() -> Minio:
    endpoint = os.environ["MINIO_ENDPOINT"].replace("http://", "").replace("https://", "")
    secure = os.environ["MINIO_ENDPOINT"].startswith("https")
    return Minio(
        endpoint,
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=secure,
    )


def minio_upload_text(bucket: str, object_name: str, text: str) -> str:
    """Sube texto como objeto y devuelve la URL."""
    import io
    client = get_minio_client()
    data = text.encode("utf-8")
    client.put_object(bucket, object_name, io.BytesIO(data), len(data),
                      content_type="text/plain")
    return f"{os.environ['MINIO_ENDPOINT']}/{bucket}/{object_name}"


def minio_download_text(bucket: str, object_name: str) -> str:
    client = get_minio_client()
    response = client.get_object(bucket, object_name)
    return response.read().decode("utf-8")


def minio_upload_bytes(bucket: str, object_name: str, data: bytes,
                       content_type: str = "application/octet-stream") -> str:
    import io
    client = get_minio_client()
    client.put_object(bucket, object_name, io.BytesIO(data), len(data),
                      content_type=content_type)
    return f"{os.environ['MINIO_ENDPOINT']}/{bucket}/{object_name}"


def minio_download_bytes(bucket: str, object_name: str) -> bytes:
    client = get_minio_client()
    response = client.get_object(bucket, object_name)
    return response.read()


def minio_list_objects(bucket: str, prefix: str = "") -> list[str]:
    client = get_minio_client()
    return [obj.object_name for obj in client.list_objects(bucket, prefix=prefix)]


# ── Helpers ────────────────────────────────────────────────────────────────────

def new_guid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.utcnow()
