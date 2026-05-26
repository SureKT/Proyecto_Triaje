"""
setup.py — Configuración inicial para equipos sin GPU (portátil / demo).

Sube el modelo pre-entrenado (models/modelo_latest.pkl) al bucket MinIO del
sistema, habilitando el endpoint /predecir/ sin necesidad de re-entrenar.

Ejecutar UNA SOLA VEZ tras `docker compose up -d`:

    python setup.py

Requisitos:
  - Docker corriendo con los servicios del compose levantados
  - LLM_PROVIDER=openrouter y OPENROUTER_API_KEY configurados en .env
  - El fichero models/modelo_latest.pkl debe existir (viene en el repositorio)

Ver README.md sección "Configuracion en portatil / sin GPU" para instrucciones completas.
"""
import os, sys, time

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
# setup.py corre fuera de Docker → siempre usar localhost:9000 (puerto API S3)
if "minio:" in MINIO_ENDPOINT:
    MINIO_ENDPOINT = "http://localhost:9000"
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
print(f"Subiendo {MODEL_FILE} -> {BUCKET}/{MODEL_OBJECT} ...")
client.fput_object(BUCKET, MODEL_OBJECT, MODEL_FILE)
print("OK Modelo cargado en MinIO.")
print("\nAhora puedes lanzar Streamlit:")
print("  streamlit run app/streamlit_app.py")
