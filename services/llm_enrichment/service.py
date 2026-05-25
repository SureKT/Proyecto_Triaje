"""
services/llm_enrichment/service.py
Extrae columnas del dataset via LLM (OpenRouter u Ollama) y persiste en Postgres.
"""
import logging

from common import pg_execute, update_estado, ensure_entrevista, now
from llm_enrichment.client import call_llm
from ml_features import as_bool
from preprocessor.service import preprocess

logger = logging.getLogger(__name__)


def _llm_bool(resultado: dict, key: str) -> bool:
    return as_bool(resultado.get(key))


def enrich(guid: str, texto: str) -> dict:
    """
    Enriquece una entrevista:
    1. Llama al LLM.
    2. Persiste entidades en tabla Entidad.
    3. Persiste features y nivel_triaje en ResultadoML.
    4. Actualiza estado → ENRICHED.
    """
    ensure_entrevista(guid)
    prep = preprocess(guid, texto)
    texto_llm = prep["texto_paciente"] or prep["texto_completo"]

    t_inicio = now()
    update_estado(guid, "ENRICHING", Inicio_Extraccion_Entidades=t_inicio)

    resultado = call_llm(texto_llm)

    pg_execute("DELETE FROM Entidad WHERE GUID_Entrevista = %s", (guid,))

    # ── Entidades ──────────────────────────────────────────────────────────────
    entidades_raw  = resultado.get("entidades", [])
    entidades_norm = resultado.get("entidades_normalizadas", [])

    for raw, norm in zip(entidades_raw, entidades_norm):
        pg_execute(
            """INSERT INTO Entidad (GUID_Entrevista, entidad_raw, entidad_normalizada, tipo)
               VALUES (%s, %s, %s, %s)""",
            (guid, raw, norm, "sintoma"),
        )

    # ── ResultadoML ────────────────────────────────────────────────────────────
    pg_execute(
        """INSERT INTO ResultadoML
           (GUID_Entrevista, edad, sexo, dolor_intensidad, disnea, fiebre,
            perdida_consciencia, irradiacion, antecedentes_cardiacos, fumador,
            motivo_consulta, justificacion, score_urgencia, score_ansiedad,
            nivel_triaje, timestamp_pred)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (GUID_Entrevista) DO UPDATE SET
            edad = EXCLUDED.edad, sexo = EXCLUDED.sexo,
            dolor_intensidad = EXCLUDED.dolor_intensidad, disnea = EXCLUDED.disnea,
            fiebre = EXCLUDED.fiebre, perdida_consciencia = EXCLUDED.perdida_consciencia,
            irradiacion = EXCLUDED.irradiacion, antecedentes_cardiacos = EXCLUDED.antecedentes_cardiacos,
            fumador = EXCLUDED.fumador, motivo_consulta = EXCLUDED.motivo_consulta,
            justificacion = EXCLUDED.justificacion, score_urgencia = EXCLUDED.score_urgencia,
            score_ansiedad = EXCLUDED.score_ansiedad,
            nivel_triaje = EXCLUDED.nivel_triaje, timestamp_pred = EXCLUDED.timestamp_pred""",
        (
            guid,
            resultado.get("edad"),
            resultado.get("sexo"),
            resultado.get("dolor_intensidad"),
            _llm_bool(resultado, "disnea"),
            _llm_bool(resultado, "fiebre"),
            _llm_bool(resultado, "perdida_consciencia"),
            _llm_bool(resultado, "irradiacion"),
            _llm_bool(resultado, "antecedentes_cardiacos"),
            _llm_bool(resultado, "fumador"),
            resultado.get("motivo_consulta"),
            resultado.get("justificacion"),
            resultado.get("score_urgencia"),
            resultado.get("score_ansiedad"),
            resultado.get("nivel_triaje"),
            now(),
        ),
    )

    t_fin = now()
    update_estado(
        guid, "ENRICHED",
        Fin_Extraccion_Entidades=t_fin,
        Inicio_Normalizacion=t_inicio,
        Fin_Normalizacion=t_fin,
        Inicio_Etiquetado=t_inicio,
        Fin_Etiquetado=t_fin,
        Inicio_Score=t_inicio,
        Fin_Score=t_fin,
    )

    logger.info(f"[{guid}] ENRICHED — nivel_triaje={resultado.get('nivel_triaje')}")
    return resultado
