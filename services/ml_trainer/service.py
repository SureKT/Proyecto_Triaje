"""
services/ml_trainer/service.py
Entrena un Random Forest sobre el CSV de MinIO,
evalúa y sube el modelo serializado.
"""
import os
import io
import logging
import joblib
import pandas as pd
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report, accuracy_score
from sklearn.utils.class_weight import compute_class_weight
import numpy as np

from common import (pg_execute, minio_download_bytes, minio_upload_bytes,
                    minio_list_objects, now)
from ml_features import FEATURES, TARGET, prepare_training_df

logger = logging.getLogger(__name__)

BUCKET_DATASETS = os.environ.get("MINIO_BUCKET_DATASETS", "datasets")
BUCKET_MODELOS  = os.environ.get("MINIO_BUCKET_MODELOS",  "modelos")

def get_latest_dataset() -> pd.DataFrame:
    objects = sorted(minio_list_objects(BUCKET_DATASETS, prefix="dataset_entrenamiento_"))
    if not objects:
        raise FileNotFoundError("No hay datasets en MinIO.")
    latest = objects[-1]
    csv_bytes = minio_download_bytes(BUCKET_DATASETS, latest)
    return pd.read_csv(io.BytesIO(csv_bytes))


def train() -> dict:
    t_inicio = now()

    df = prepare_training_df(get_latest_dataset())

    X = df[FEATURES]
    y = df[TARGET].astype(int)

    # Class weights para proteger C1/C2
    classes      = np.unique(y)
    class_weights = compute_class_weight("balanced", classes=classes, y=y)
    cw_dict       = dict(zip(classes, class_weights))

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    # ── Random Forest ─────────────────────────────────────────────────────────
    rf = RandomForestClassifier(
        n_estimators=200,
        class_weight=cw_dict,
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)

    # ── Baseline Logistic Regression ──────────────────────────────────────────
    lr = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
    lr.fit(X_train, y_train)

    # ── Métricas ──────────────────────────────────────────────────────────────
    y_pred_rf = rf.predict(X_test)
    y_pred_lr = lr.predict(X_test)

    rf_acc = accuracy_score(y_test, y_pred_rf)
    lr_acc = accuracy_score(y_test, y_pred_lr)
    report = classification_report(y_test, y_pred_rf, output_dict=True)

    # Validación cruzada
    cv      = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_f1   = cross_val_score(rf, X, y, cv=cv, scoring="f1_macro").mean()

    logger.info(f"RF accuracy={rf_acc:.3f}  LR accuracy={lr_acc:.3f}  CV F1={cv_f1:.3f}")

    # ── Guardar modelo en MinIO ───────────────────────────────────────────────
    ts          = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    model_name  = f"modelo_{ts}.pkl"
    buf         = io.BytesIO()
    joblib.dump(rf, buf)
    url = minio_upload_bytes(BUCKET_MODELOS, model_name, buf.getvalue(),
                             content_type="application/octet-stream")

    # ── Actualizar Postgres ───────────────────────────────────────────────────
    pg_execute(
        """UPDATE Entrevista SET URL_Modelo_Entrenado = %s,
           Estado = 'MODEL_TRAINED', Inicio_Entrenamiento = %s, Fin_Entrenamiento = %s
           WHERE Estado = 'DATASET_READY'""",
        (url, t_inicio, now()),
    )

    return {
        "modelo": model_name,
        "url": url,
        "rf_accuracy": rf_acc,
        "lr_accuracy": lr_acc,
        "cv_f1_macro": cv_f1,
        "classification_report": report,
        "class_weights": {str(k): round(v, 3) for k, v in cw_dict.items()},
        "n_samples": len(df),
    }
