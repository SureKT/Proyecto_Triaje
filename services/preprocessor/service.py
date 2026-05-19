"""
services/preprocessor/service.py
Limpia y normaliza el texto clínico.
Extrae únicamente las intervenciones del paciente (P:) para el LLM.
"""
import re
import logging
from common import update_estado, now

logger = logging.getLogger(__name__)


def clean_text(texto: str) -> str:
    """
    Limpieza básica:
    - Elimina caracteres de control excepto saltos de línea
    - Colapsa espacios múltiples
    - Preserva estructura D: / P:
    """
    texto = re.sub(r"[^\S\n]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def extract_patient_turns(texto: str) -> str:
    """Extrae solo las líneas del paciente (P:) para el análisis clínico."""
    lines = []
    for line in texto.splitlines():
        stripped = line.strip()
        if stripped.startswith("P:"):
            lines.append(stripped[2:].strip())
    return " ".join(lines)


def preprocess(guid: str, texto: str) -> dict:
    t_inicio = now()
    update_estado(guid, "PREPROCESSING", Inicio_Preprocesamiento=t_inicio)

    texto_limpio   = clean_text(texto)
    texto_paciente = extract_patient_turns(texto_limpio)

    update_estado(guid, "PREPROCESSED", Fin_Preprocesamiento=now())
    logger.info(f"[{guid}] PREPROCESSED — {len(texto_paciente)} chars de paciente")

    return {
        "texto_completo": texto_limpio,
        "texto_paciente": texto_paciente,
    }
