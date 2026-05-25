# Casos de demo — Defensa Triaje IA

Tres transcripciones preparadas para la demo en vivo. Usar en Streamlit (texto directo)
o grabar como audio y subir como .wav/.mp3.

| Fichero | Caso | Nivel esperado | score_ansiedad esperado | Punto de interés |
|---------|------|---------------|------------------------|-----------------|
| `caso_urgente_C2.txt` | Dolor torácico 8/10 + disnea + antecedente infarto, 71 años | **C2** | ~0.3 (paciente tranquilo) | Demuestra detección correcta de urgencia crítica |
| `caso_leve_C4.txt` | Dolor rodilla 3/10, crónico, sin alarma, 34 años | **C4** | ~0.1 (relato objetivo) | Demuestra que el sistema no sobre-triaja |
| `caso_ansiedad_C3.txt` | Crisis de ansiedad, disnea funcional, 27 años, sin cardiopatía | **C3** (no C2) | ~0.9 (pánico extremo) | **Demo clave:** ansiedad alta pero clínica manda — aparece en tabla de auditoría si RF < LLM |

## Guion para la defensa

**Caso 1 (C2):** "Aquí vemos un caso de sospecha de SCA. El modelo asigna C2 Muy Urgente
con alta confianza. La ansiedad es moderada — no interfiere en la decisión."

**Caso 2 (C4):** "Contraste: dolor musculoesquelético crónico sin signos de alarma.
El sistema clasifica correctamente C4, sin sobre-triaje."

**Caso 3 (C3 + ansiedad):** "Este es el caso más interesante para la defensa.
La paciente está en pánico, score_ansiedad 0.9+. Pero los síntomas clínicos no justifican C2:
sin dolor torácico real, sin antecedentes cardíacos, 27 años, crisis de ansiedad conocida.
El sistema asigna C3 — la clínica prevalece sobre la emoción. Si el RF hubiera predicho C4,
aparecería automáticamente en la tabla de auditoría ética como under-triage."
