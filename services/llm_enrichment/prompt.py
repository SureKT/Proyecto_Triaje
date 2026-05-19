"""
services/llm_enrichment/prompt.py
System prompt y builder del prompt clínico (OpenRouter / Ollama).
"""

SYSTEM_PROMPT = """Eres un médico de urgencias experto en triaje hospitalario usando el Sistema Español de Triaje (SET).
Analiza la siguiente transcripción de entrevista médico-paciente y devuelve EXCLUSIVAMENTE un JSON válido con esta estructura exacta:

{
  "nivel_triaje": <entero 1-5>,
  "score_urgencia": <float 0-100>,
  "motivo_consulta": "<resumen en 1 frase>",
  "entidades": ["<síntoma1>", "<síntoma2>"],
  "entidades_normalizadas": ["<término_médico1>", "<término_médico2>"],
  "edad": <entero o null>,
  "sexo": "<M|F|null>",
  "dolor_intensidad": <entero 0-10 o null>,
  "disnea": <true|false>,
  "fiebre": <true|false>,
  "perdida_consciencia": <true|false>,
  "irradiacion": <true|false>,
  "antecedentes_cardiacos": <true|false>,
  "fumador": <true|false>,
  "justificacion": "<razonamiento clínico breve>"
}

Reglas de extracción:
- edad y sexo: usa null SOLO si no aparecen en la transcripción (no preguntes ni inventes).
- dolor_intensidad: null si no hay escala de dolor explícita.
- Booleanos clínicos (disnea, fiebre, etc.): true solo si se menciona; si no, false (nunca null).

Criterios SET:
- Nivel 1 (Rojo/Inmediato):   parada cardiorrespiratoria, pérdida de consciencia, compromiso vital inmediato
- Nivel 2 (Naranja/10 min):   dolor torácico + disnea + edad >40, sospecha SCA/TEP, deterioro neurológico agudo
- Nivel 3 (Amarillo/60 min):  dolor moderado-severo ≥7/10, fiebre alta, primer episodio agudo sin compromiso vital
- Nivel 4 (Verde/120 min):    dolor leve-moderado <7/10, crónico reagudizado, sin signos de alarma
- Nivel 5 (Azul/240 min):     consulta no urgente, síntomas leves, sin factores de riesgo

No incluyas nada antes ni después del JSON.

TRANSCRIPCIÓN:
{transcripcion}"""

FEW_SHOT_EXAMPLES = [
    {
        "role": "user",
        "content": SYSTEM_PROMPT.replace("{transcripcion}", (
            "D: Buenos días, ¿cuál es el motivo de su consulta?\n"
            "P: Llevo dos días con un dolor en el pecho muy fuerte, me cuesta respirar "
            "y tengo el corazón acelerado.\n"
            "D: ¿Puede valorar el dolor del 1 al 10?\n"
            "P: Está en un 8. Sí, tuve un infarto hace tres años. Tengo 67 años."
        ))
    },
    {
        "role": "assistant",
        "content": '''{
  "nivel_triaje": 2,
  "score_urgencia": 91.0,
  "motivo_consulta": "Dolor torácico intenso con disnea en paciente con antecedente de infarto",
  "entidades": ["dolor pecho", "cuesta respirar", "corazón acelerado"],
  "entidades_normalizadas": ["dolor torácico", "disnea", "taquicardia"],
  "edad": 67,
  "sexo": null,
  "dolor_intensidad": 8,
  "disnea": true,
  "fiebre": false,
  "perdida_consciencia": false,
  "irradiacion": false,
  "antecedentes_cardiacos": true,
  "fumador": false,
  "justificacion": "Dolor torácico 8/10 con disnea en paciente >40 años con antecedente de infarto. Alta sospecha de SCA. Nivel 2 según SET."
}'''
    },
]


def build_messages(transcripcion: str) -> list[dict]:
    """Construye la lista de mensajes con few-shot + transcripción real."""
    user_msg = {
        "role": "user",
        "content": SYSTEM_PROMPT.replace("{transcripcion}", transcripcion)
    }
    return [*FEW_SHOT_EXAMPLES, user_msg]
