"""
dags/common.py
Utilidades compartidas directamente en los DAGs (sin depender de services/).
"""
import os
import io
import uuid
import logging
from datetime import datetime

import psycopg2
import psycopg2.extras
from minio import Minio

logger = logging.getLogger(__name__)


def get_pg_conn():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def pg_execute(sql, params=None, fetch=False):
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                if fetch:
                    return cur.fetchall()
    finally:
        conn.close()


def update_estado(guid, estado, **timestamps):
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


def get_minio_client():
    endpoint = os.environ["MINIO_ENDPOINT"].replace("http://", "").replace("https://", "")
    secure = os.environ["MINIO_ENDPOINT"].startswith("https")
    return Minio(
        endpoint,
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=secure,
    )


def minio_upload_text(bucket, object_name, text):
    client = get_minio_client()
    data = text.encode("utf-8")
    client.put_object(bucket, object_name, io.BytesIO(data), len(data),
                      content_type="text/plain")
    return f"{os.environ['MINIO_ENDPOINT']}/{bucket}/{object_name}"


def minio_download_text(bucket, object_name):
    client = get_minio_client()
    response = client.get_object(bucket, object_name)
    return response.read().decode("utf-8")


def minio_upload_bytes(bucket, object_name, data, content_type="application/octet-stream"):
    client = get_minio_client()
    client.put_object(bucket, object_name, io.BytesIO(data), len(data),
                      content_type=content_type)
    return f"{os.environ['MINIO_ENDPOINT']}/{bucket}/{object_name}"


def minio_download_bytes(bucket, object_name):
    client = get_minio_client()
    return client.get_object(bucket, object_name).read()


def minio_list_objects(bucket, prefix=""):
    client = get_minio_client()
    return [obj.object_name for obj in client.list_objects(bucket, prefix=prefix)]


def new_guid():
    return str(uuid.uuid4())


def now():
    return datetime.utcnow()