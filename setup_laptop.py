"""
setup_laptop.py — Sube el modelo pre-entrenado a MinIO en el portátil.
Ejecutar UNA VEZ tras `docker compose up -d` en el portátil.

    python setup_laptop.py
"""
import os, sys, time

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9001")
MINIO_USER     = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_PASS     = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin123")
BUCKET         = os.environ.get("MINIO_BUCKET_MODELOS", "modelos")
MODEL_FILE     = os.path.join(os.path.dirname(__file__), "models", "modelo_latest.pkl")
MODEL_OBJECT   = "modelo_20260525_114431.pkl"

try:
    from minio import Minio
except ImportError:
    print("Instalando minio...")
    os.system(f"{sys.executable} -m pip install minio -q")
    from minio import Minio

endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
secure   = MINIO_ENDPOINT.startswith("https")
client   = Minio(endpoint, access_key=MINIO_USER, secret_key=MINIO_PASS, secure=secure)

# Esperar a que MinIO esté listo
for i in range(10):
    try:
        client.list_buckets()
        break
    except Exception:
        print(f"Esperando MinIO... ({i+1}/10)")
        time.sleep(3)
else:
    print("ERROR: MinIO no responde. ¿Está Docker corriendo?")
    sys.exit(1)

# Crear bucket si no existe
if not client.bucket_exists(BUCKET):
    client.make_bucket(BUCKET)
    print(f"Bucket '{BUCKET}' creado.")

# Subir modelo
print(f"Subiendo {MODEL_FILE} → {BUCKET}/{MODEL_OBJECT} ...")
client.fput_object(BUCKET, MODEL_OBJECT, MODEL_FILE)
print("✓ Modelo cargado en MinIO.")
print("\nAhora puedes lanzar Streamlit:")
print("  streamlit run app/streamlit_app.py")
