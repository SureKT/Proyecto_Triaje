"""
services/dataset_builder/service.py
Consolida todos los registros ENRICHED de Postgres en un CSV
y lo sube a MinIO.
"""
import os
import io
import logging
import pandas as pd
from datetime import datetime

from common import pg_execute, update_estado, minio_upload_bytes, now
from ml_features import prepare_dataset_export_df

logger = logging.getLogger(__name__)

BUCKET_DATASETS = os.environ.get("MINIO_BUCKET_DATASETS", "datasets")


def build_dataset() -> str:
    """
    Construye el CSV de entrenamiento y lo sube a MinIO.
    Devuelve la URL del objeto.
    """
    rows = pg_execute(
        """
        SELECT
            e.GUID_Entrevista  AS guid,
            e.especialidad,
            e.origen,
            r.edad,
            r.sexo,
            r.dolor_intensidad,
            r.disnea,
            r.fiebre,
            r.perdida_consciencia,
            r.irradiacion,
            r.antecedentes_cardiacos,
            r.fumador,
            r.score_urgencia,
            r.score_ansiedad,
            r.nivel_triaje
        FROM Entrevista e
        JOIN ResultadoML r ON e.GUID_Entrevista = r.GUID_Entrevista
        WHERE e.Estado = 'ENRICHED'
        """,
        fetch=True,
    )

    if not rows:
        raise ValueError("No hay registros ENRICHED para construir el dataset.")

    df = prepare_dataset_export_df(pd.DataFrame([dict(r) for r in rows]))

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    ts         = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    object_name = f"dataset_entrenamiento_{ts}.csv"

    url = minio_upload_bytes(BUCKET_DATASETS, object_name, csv_bytes,
                             content_type="text/csv")

    # Actualizar referencias en Postgres
    pg_execute(
        "UPDATE Entrevista SET URL_Dataset_Generado = %s, Estado = %s WHERE Estado = 'ENRICHED'",
        (url, "DATASET_READY"),
    )

    logger.info(f"Dataset generado: {object_name} ({len(df)} filas)")
    return url
