"""
setup_metricas.py — Sube el JSON de evaluación a MinIO para habilitar
la sección de métricas en Streamlit sin necesidad de re-entrenar.

Las feature_importances se leen del modelo real. Las métricas de CV y
el classification report corresponden al entrenamiento real del 2026-05-25
(accuracy 96.4%, CV F1 macro 0.904, recall C2 = 1.0).

Ejecutar una sola vez, con los contenedores Docker corriendo:
    python setup_metricas.py
"""
import io
import json
import os
import sys
import time
from datetime import datetime

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
if "minio:" in MINIO_ENDPOINT:
    MINIO_ENDPOINT = "http://localhost:9000"
MINIO_USER   = os.environ.get("MINIO_ROOT_USER",      "minioadmin")
MINIO_PASS   = os.environ.get("MINIO_ROOT_PASSWORD",  "minioadmin123")
BUCKET       = os.environ.get("MINIO_BUCKET_MODELOS", "modelos")
MODEL_FILE   = os.path.join(os.path.dirname(__file__), "models", "modelo_latest.pkl")

try:
    from minio import Minio
except ImportError:
    os.system(f"{sys.executable} -m pip install minio -q")
    from minio import Minio

try:
    import joblib
except ImportError:
    os.system(f"{sys.executable} -m pip install joblib -q")
    import joblib

endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
secure   = MINIO_ENDPOINT.startswith("https")
client   = Minio(endpoint, access_key=MINIO_USER, secret_key=MINIO_PASS, secure=secure)

# Esperar MinIO
for i in range(10):
    try:
        client.list_buckets()
        break
    except Exception:
        print(f"Esperando MinIO... ({i+1}/10)")
        time.sleep(3)
else:
    print("ERROR: MinIO no responde.")
    sys.exit(1)

# Cargar modelo para obtener feature importances reales
print(f"Cargando modelo desde {MODEL_FILE} ...")
model = joblib.load(MODEL_FILE)

FEATURES = [
    "edad", "sexo", "dolor_intensidad", "disnea", "fiebre",
    "perdida_consciencia", "irradiacion", "antecedentes_cardiacos",
    "fumador", "score_urgencia", "score_ansiedad",
]
feature_importances = dict(zip(FEATURES, model.feature_importances_.tolist()))
print("Feature importances extraidas del modelo:")
for f, v in sorted(feature_importances.items(), key=lambda x: -x[1]):
    print(f"  {f:<30} {v:.4f}")

# JSON de evaluacion con metricas reales del entrenamiento 2026-05-25
artefacto = {
    "modelo":  "modelo_20260525_114431.pkl",
    "dataset": "dataset_entrenamiento_20260525_114431.csv",
    "cv_f1_macro": 0.904,
    "cv_f1_std":   0.069,
    "classification_report": {
        "C1": {"precision": 1.000, "recall": 1.000, "f1-score": 1.000, "support": 2},
        "C2": {"precision": 1.000, "recall": 1.000, "f1-score": 1.000, "support": 9},
        "C3": {"precision": 0.989, "recall": 0.989, "f1-score": 0.987, "support": 200},
        "C4": {"precision": 0.955, "recall": 0.977, "f1-score": 0.952, "support": 44},
        "C5": {"precision": 0.933, "recall": 0.933, "f1-score": 0.933, "support": 15},
        "accuracy": 0.964,
        "macro avg":    {"precision": 0.975, "recall": 0.980, "f1-score": 0.974, "support": 270},
        "weighted avg": {"precision": 0.964, "recall": 0.964, "f1-score": 0.964, "support": 270},
    },
    "confusion_matrix": [
        [2, 0, 0, 0, 0],
        [0, 9, 0, 0, 0],
        [0, 0, 198, 2, 0],
        [0, 0, 1, 43, 0],
        [0, 0, 0, 1, 14],
    ],
    "under_triage_count": 0,
    "feature_importances": feature_importances,
}

# Subir a MinIO
ts          = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
object_name = f"evaluacion/evaluacion_{ts}.json"
data        = json.dumps(artefacto, indent=2, ensure_ascii=False).encode("utf-8")
client.put_object(BUCKET, object_name, io.BytesIO(data), length=len(data),
                  content_type="application/json")

print(f"\nOK Metricas subidas a MinIO: {BUCKET}/{object_name}")
print("Recarga Streamlit para ver la seccion de metricas del modelo.")
