"""
services/metricas/router.py
GET /metricas/ — agrega métricas de rendimiento del pipeline desde Postgres y MinIO.
"""
import io
import json
import logging
import os

from fastapi import APIRouter
from common import pg_execute, minio_download_bytes, minio_list_objects

router = APIRouter()
logger = logging.getLogger(__name__)

MANCHESTER = {1: "C1", 2: "C2", 3: "C3", 4: "C4", 5: "C5"}

BUCKET_MODELOS = os.environ.get("MINIO_BUCKET_MODELOS", "modelos")


def _latest_evaluation() -> dict:
    try:
        objects = sorted(minio_list_objects(BUCKET_MODELOS, prefix="evaluacion/evaluacion_"))
        if not objects:
            return {}
        raw = minio_download_bytes(BUCKET_MODELOS, objects[-1])
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"No se pudo leer evaluación desde MinIO: {e}")
        return {}


@router.get("/auditoria")
def auditoria():
    """
    Casos de posible under-triage: prediccion_modelo > nivel_triaje (RF menos urgente que LLM)
    con score_ansiedad >= 0.7. Señal de sesgo emocional en la predicción.
    """
    rows = pg_execute(
        """
        SELECT
            e.GUID_Entrevista                        AS id_caso,
            e.nombre_fichero,
            r.score_ansiedad,
            r.prediccion_modelo,
            r.nivel_triaje                           AS ground_truth_llm,
            r.motivo_consulta,
            r.justificacion,
            e.Fin_Solicitud                          AS timestamp_pred
        FROM Entrevista e
        JOIN ResultadoML r ON e.GUID_Entrevista = r.GUID_Entrevista
        WHERE r.prediccion_modelo IS NOT NULL
          AND r.nivel_triaje      IS NOT NULL
          AND r.prediccion_modelo > r.nivel_triaje
          AND r.score_ansiedad   >= 0.7
        ORDER BY r.score_ansiedad DESC
        """,
        fetch=True,
    )

    result = []
    for r in rows:
        pred = r["prediccion_modelo"]
        gt   = r["ground_truth_llm"]
        result.append({
            "ID_Caso":        r["nombre_fichero"] or r["id_caso"][:8],
            "Motivo":         r["motivo_consulta"] or "—",
            "Score Ansiedad": round(float(r["score_ansiedad"]), 2) if r["score_ansiedad"] else None,
            "Pred. IA":       MANCHESTER.get(pred, str(pred)),
            "Ground Truth":   MANCHESTER.get(gt, str(gt)),
            "Validación":     "❌ Under-triage",
            "Causa":          "El modelo RF priorizó ansiedad sobre clínica",
        })
    return result


@router.get("/latencias")
def latencias_por_caso():
    """
    Latencias individuales por caso procesado. Últimas 50 entrevistas completadas.
    Devuelve tiempos E2E, LLM, preprocesamiento y normalización en segundos.
    """
    rows = pg_execute(
        """
        SELECT
            nombre_fichero,
            estado,
            ROUND(EXTRACT(EPOCH FROM (fin_solicitud       - inicio_solicitud))::numeric, 1)             AS e2e_s,
            ROUND(EXTRACT(EPOCH FROM (fin_extraccion_entidades - inicio_extraccion_entidades))::numeric, 1) AS llm_s,
            ROUND(EXTRACT(EPOCH FROM (fin_preprocesamiento - inicio_preprocesamiento))::numeric, 2)      AS prep_s,
            ROUND(EXTRACT(EPOCH FROM (fin_normalizacion    - inicio_normalizacion))::numeric, 2)         AS norm_s,
            inicio_solicitud
        FROM entrevista
        WHERE fin_solicitud IS NOT NULL
          AND inicio_solicitud IS NOT NULL
          AND EXTRACT(EPOCH FROM (fin_solicitud - inicio_solicitud)) < 120
        ORDER BY inicio_solicitud DESC
        LIMIT 50
        """,
        fetch=True,
    )
    return [dict(r) for r in rows]


@router.get("/")
def metricas():
    """
    Métricas de rendimiento del pipeline (§2 enunciado):
    - Textos procesados por estado
    - Latencia end-to-end y tiempo LLM (Fase 2)
    - Tiempo de entrenamiento
    - Throughput batch
    - Errores y reintentos
    - Métricas del modelo ML
    """
    # ── Conteo por estado ──────────────────────────────────────────────────────
    estado_rows = pg_execute(
        "SELECT estado, COUNT(*) AS n FROM entrevista GROUP BY estado ORDER BY estado",
        fetch=True,
    )
    por_estado = {r["estado"]: int(r["n"]) for r in estado_rows}
    total = sum(por_estado.values())

    # ── Latencias Fase 2 (registros COMPLETADA) ────────────────────────────────
    lat_rows = pg_execute(
        """
        SELECT
            ROUND(AVG(EXTRACT(EPOCH FROM (fin_solicitud - inicio_solicitud)))::numeric, 2)
                AS avg_latencia_e2e_s,
            ROUND(MIN(EXTRACT(EPOCH FROM (fin_solicitud - inicio_solicitud)))::numeric, 2)
                AS min_latencia_e2e_s,
            ROUND(MAX(EXTRACT(EPOCH FROM (fin_solicitud - inicio_solicitud)))::numeric, 2)
                AS max_latencia_e2e_s,
            ROUND(AVG(EXTRACT(EPOCH FROM (fin_extraccion_entidades - inicio_extraccion_entidades)))::numeric, 2)
                AS avg_tiempo_llm_s,
            COUNT(*) AS n_completadas
        FROM entrevista
        WHERE estado = 'COMPLETADA'
          AND fin_solicitud IS NOT NULL
          AND inicio_solicitud IS NOT NULL
        """,
        fetch=True,
    )
    latencias = dict(lat_rows[0]) if lat_rows else {}

    # ── Entrenamiento ──────────────────────────────────────────────────────────
    train_rows = pg_execute(
        """
        SELECT
            ROUND(AVG(EXTRACT(EPOCH FROM (fin_entrenamiento - inicio_entrenamiento)))::numeric, 2)
                AS avg_tiempo_entrenamiento_s,
            MAX(fin_entrenamiento) AS ultimo_entrenamiento
        FROM entrevista
        WHERE fin_entrenamiento IS NOT NULL
        """,
        fetch=True,
    )
    entrenamiento = {}
    if train_rows and train_rows[0]["avg_tiempo_entrenamiento_s"] is not None:
        r = train_rows[0]
        entrenamiento = {
            "avg_tiempo_entrenamiento_s": float(r["avg_tiempo_entrenamiento_s"]),
            "ultimo_entrenamiento":       str(r["ultimo_entrenamiento"]),
        }

    # ── Throughput batch (último batch: ventana de 3h desde el máx reciente) ──
    tp_rows = pg_execute(
        """
        WITH ultimo_batch AS (
            SELECT MAX(fin_extraccion_entidades) AS fin_max
            FROM entrevista
            WHERE fin_extraccion_entidades IS NOT NULL
        )
        SELECT
            COUNT(*) AS n_enriquecidas,
            ROUND(EXTRACT(EPOCH FROM
                (MAX(fin_extraccion_entidades) - MIN(inicio_extraccion_entidades))
            )::numeric, 0) AS duracion_s
        FROM entrevista, ultimo_batch
        WHERE fin_extraccion_entidades IS NOT NULL
          AND inicio_extraccion_entidades IS NOT NULL
          AND fin_extraccion_entidades >= (fin_max - INTERVAL '3 hours')
        """,
        fetch=True,
    )
    throughput = {}
    if tp_rows and tp_rows[0]["duracion_s"]:
        n   = int(tp_rows[0]["n_enriquecidas"])
        dur = float(tp_rows[0]["duracion_s"])
        throughput = {
            "textos_ultimo_batch":   n,
            "duracion_s":            dur,
            "throughput_por_minuto": round(n / (dur / 60), 2) if dur > 0 else None,
        }

    # ── Errores ────────────────────────────────────────────────────────────────
    errores = {k: v for k, v in por_estado.items() if "ERROR" in k}

    # ── Métricas ML (último JSON de evaluación en MinIO) ──────────────────────
    metricas_ml = _latest_evaluation()

    return {
        "textos": {
            "total":      total,
            "por_estado": por_estado,
        },
        "latencia_fase2":   {k: (float(v) if v is not None else None) for k, v in latencias.items()},
        "entrenamiento":    entrenamiento,
        "throughput_batch": throughput,
        "errores":          errores,
        "metricas_modelo":  metricas_ml,
    }
