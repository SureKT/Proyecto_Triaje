"""
dags/dag_evaluation.py
Evaluación final: validación cruzada, matriz de confusión, auditoría de under-triage.
"""
import os
import io
import json
import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "triaje",
    "retries": 1,
    "retry_delay": timedelta(seconds=30),
}


def _evaluate():
    import sys
    sys.path.insert(0, "/opt/airflow/dags")
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from common import (pg_execute, minio_download_bytes, minio_upload_bytes,
                        minio_list_objects)

    BUCKET_MODELOS  = os.environ["MINIO_BUCKET_MODELOS"]
    BUCKET_DATASETS = os.environ["MINIO_BUCKET_DATASETS"]

    # ── Cargar modelo ──────────────────────────────────────────────────────────
    models = sorted(minio_list_objects(BUCKET_MODELOS, prefix="modelo_"))
    if not models:
        raise FileNotFoundError("No hay modelos entrenados.")
    model_bytes = minio_download_bytes(BUCKET_MODELOS, models[-1])
    model = joblib.load(io.BytesIO(model_bytes))

    # ── Cargar dataset ─────────────────────────────────────────────────────────
    datasets = sorted(minio_list_objects(BUCKET_DATASETS, prefix="dataset_entrenamiento_"))
    csv_bytes = minio_download_bytes(BUCKET_DATASETS, datasets[-1])
    FEATURES = [
        "edad", "sexo", "dolor_intensidad", "disnea", "fiebre",
        "perdida_consciencia", "irradiacion", "antecedentes_cardiacos",
        "fumador", "score_urgencia", "score_ansiedad",
    ]
    UNKNOWN = -1
    df = pd.read_csv(io.BytesIO(csv_bytes))
    bool_cols = ["disnea", "fiebre", "perdida_consciencia",
                 "irradiacion", "antecedentes_cardiacos", "fumador"]
    for col in bool_cols:
        df[col] = df[col].fillna(0).astype(int)
    for col in ("edad", "dolor_intensidad", "sexo"):
        df[col] = df[col].fillna(UNKNOWN)
    df["score_ansiedad"] = df["score_ansiedad"].fillna(0.0)
    df = df.dropna(subset=["nivel_triaje", "score_urgencia"])
    X = df[FEATURES]
    y = df["nivel_triaje"].astype(int)

    # ── Validación cruzada 5-fold ──────────────────────────────────────────────
    cv    = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    f1_cv = cross_val_score(model, X, y, cv=cv, scoring="f1_macro")
    logger.info(f"CV F1 macro: {f1_cv.mean():.3f} ± {f1_cv.std():.3f}")

    # ── Predicciones y matriz de confusión ─────────────────────────────────────
    y_pred = model.predict(X)
    cm     = confusion_matrix(y, y_pred, labels=[1, 2, 3, 4, 5])
    report = classification_report(y, y_pred, labels=[1, 2, 3, 4, 5],
                                   target_names=["C1","C2","C3","C4","C5"],
                                   output_dict=True)

    # ── Auditoría de under-triage ──────────────────────────────────────────────
    df["pred"] = y_pred
    undertriage = df[
        (df["nivel_triaje"] <= 2) & (df["pred"] > df["nivel_triaje"])
    ]
    logger.warning(f"Under-triage detectados: {len(undertriage)} casos")
    for _, row in undertriage.iterrows():
        logger.warning(f"  GT={row['nivel_triaje']}  PRED={row['pred']}  score={row['score_urgencia']}")

    # ── Feature importance ─────────────────────────────────────────────────────
    importances = dict(zip(FEATURES, model.feature_importances_.tolist()))

    # ── Guardar artefactos en MinIO ────────────────────────────────────────────
    artefacto = {
        "modelo": models[-1],
        "dataset": datasets[-1],
        "cv_f1_macro": round(float(f1_cv.mean()), 4),
        "cv_f1_std":   round(float(f1_cv.std()),  4),
        "classification_report": report,
        "confusion_matrix": cm.tolist(),
        "under_triage_count": len(undertriage),
        "feature_importances": importances,
    }
    ts          = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_name = f"evaluacion/evaluacion_{ts}.json"
    minio_upload_bytes(
        BUCKET_MODELOS, report_name,
        json.dumps(artefacto, indent=2, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
    )

    # ── Actualizar estado en Postgres ──────────────────────────────────────────
    pg_execute(
        "UPDATE Entrevista SET Estado = 'EVALUATED' WHERE Estado = 'MODEL_TRAINED'",
    )

    logger.info(f"Evaluación guardada: {report_name}")
    print(f"\nCV F1 macro: {f1_cv.mean():.3f} ± {f1_cv.std():.3f}")
    print(f"Under-triage (C1/C2 bajados a C3+): {len(undertriage)}")
    print(f"Feature importances: {importances}")


with DAG(
    dag_id="dag_evaluation",
    description="Evaluación del modelo: CV, matriz de confusión, auditoría under-triage",
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["triaje", "fase1"],
) as dag:

    evaluate = PythonOperator(task_id="evaluate_model", python_callable=_evaluate)
