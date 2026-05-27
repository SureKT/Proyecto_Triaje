"""
app/streamlit_app.py
Interfaz clínica Triaje IA — Fase 3.
Flujo: Audio → Whisper → POST /predecir/ → visualización Manchester + auditoría.

Lanzar:
    streamlit run app/streamlit_app.py
"""
import os
import requests
import streamlit as st
import pandas as pd

API_URL = os.environ.get("API_URL", "http://localhost:8002")

# ── Colores Manchester ─────────────────────────────────────────────────────────
MANCHESTER = {
    1: {"codigo": "C1", "nombre": "Inmediato",    "color": "#d32f2f", "texto": "white"},
    2: {"codigo": "C2", "nombre": "Muy Urgente",  "color": "#f57c00", "texto": "white"},
    3: {"codigo": "C3", "nombre": "Urgente",      "color": "#fbc02d", "texto": "black"},
    4: {"codigo": "C4", "nombre": "Menos Urgente","color": "#388e3c", "texto": "white"},
    5: {"codigo": "C5", "nombre": "No Urgente",   "color": "#1565c0", "texto": "white"},
}


def badge_manchester(nivel: int) -> str:
    m = MANCHESTER.get(nivel, MANCHESTER[3])
    return (
        f"<div style='background:{m['color']};color:{m['texto']};"
        f"padding:24px 40px;border-radius:12px;text-align:center;"
        f"font-size:2.5rem;font-weight:bold;margin:16px 0;'>"
        f"{m['codigo']} — {m['nombre']}"
        f"</div>"
    )


def ansiedad_badge(score: float) -> str:
    if score is None:
        return ""
    if score >= 0.86:
        color, label = "#b71c1c", f"⚠️ Pánico extremo ({score:.2f})"
    elif score >= 0.7:
        color, label = "#e65100", f"⚠️ Ansiedad alta ({score:.2f})"
    elif score >= 0.4:
        color, label = "#f9a825", f"Ansiedad moderada ({score:.2f})"
    else:
        color, label = "#2e7d32", f"Paciente tranquilo ({score:.2f})"
    return (
        f"<span style='background:{color};color:white;padding:4px 12px;"
        f"border-radius:8px;font-size:0.9rem;'>{label}</span>"
    )


def call_predecir(texto: str) -> dict:
    resp = requests.post(
        f"{API_URL}/predecir/",
        data={"texto": texto},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_auditoria() -> pd.DataFrame:
    """
    Recupera casos con posible under-triage desde /metricas/ o
    construye la tabla directamente desde los datos del histórico de predicciones.
    """
    try:
        resp = requests.get(f"{API_URL}/metricas/auditoria", timeout=10)
        if resp.status_code == 200:
            return pd.DataFrame(resp.json())
    except Exception:
        pass
    return pd.DataFrame(columns=[
        "ID_Caso", "Entidades", "Score Ansiedad", "Pred. IA", "Ground Truth", "Validación"
    ])


# ── Layout ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Triaje IA",
    page_icon="🏥",
    layout="centered",
)

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.title("🏥 Triaje IA — Sistema Manchester")
st.caption("Pipeline LLM + Random Forest · Clasificación automática de urgencias hospitalarias")

# ── Entrada ────────────────────────────────────────────────────────────────────
modo = st.radio("Modo de entrada", ["🎤 Audio", "📝 Texto"], horizontal=True)

texto_entrada = ""

if modo == "🎤 Audio":
    audio_file = st.file_uploader(
        "Sube el audio de la entrevista (.wav, .mp3, .m4a)",
        type=["wav", "mp3", "m4a", "ogg"],
    )
    if audio_file:
        st.audio(audio_file)
        with st.spinner("Transcribiendo audio con Whisper..."):
            try:
                from whisper_utils import transcribe_audio
                texto_entrada = transcribe_audio(audio_file.read())
                st.success("Transcripción completada")
                st.text_area("Texto transcrito", texto_entrada, height=150, disabled=True)
            except Exception as e:
                st.error(f"Error en Whisper: {e}")
else:
    texto_entrada = st.text_area(
        "Pega o escribe la transcripción de la entrevista",
        height=200,
        placeholder="D: ¿Cuál es el motivo de su consulta?\nP: Llevo dos días con dolor en el pecho...",
    )

# ── Análisis ───────────────────────────────────────────────────────────────────
analizar = st.button("🔍 Analizar", disabled=not texto_entrada.strip(), type="primary")

if analizar and texto_entrada.strip():
    with st.spinner("Procesando con LLM + modelo ML... (~15 s)"):
        try:
            resultado = call_predecir(texto_entrada)
        except requests.HTTPError as e:
            st.error(f"Error API ({e.response.status_code}): {e.response.text}")
            st.stop()
        except Exception as e:
            st.error(f"Error de conexión: {e}")
            st.stop()

    nivel = resultado.get("nivel_triaje_predicho", 3)
    nivel_llm = resultado.get("nivel_triaje_llm", nivel)
    score_ansiedad = resultado.get("score_ansiedad")
    under_triage = nivel > nivel_llm

    # ── Resultado principal ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Resultado del triaje")
    st.markdown(badge_manchester(nivel), unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Score Urgencia", f"{resultado.get('score_urgencia', 0):.1f} / 100")
    col2.metric("Confianza RF", f"{resultado.get('confianza', 0):.1%}")
    col3.metric("Valoración", f"{resultado.get('valoracion', 0):.1f} / 10")

    # ── Score ansiedad ─────────────────────────────────────────────────────────
    if score_ansiedad is not None:
        st.markdown("**Nivel de ansiedad detectado:**")
        st.markdown(ansiedad_badge(score_ansiedad), unsafe_allow_html=True)

    # ── Alerta under-triage ────────────────────────────────────────────────────
    if under_triage:
        st.warning(
            f"⚠️ **Posible under-triage:** el modelo predice {MANCHESTER[nivel]['codigo']} "
            f"pero el LLM asignó {MANCHESTER[nivel_llm]['codigo']}. "
            f"Revise clínicamente este caso."
        )

    # ── Detalle clínico ────────────────────────────────────────────────────────
    with st.expander("Detalle clínico"):
        st.write("**Motivo de consulta:**", resultado.get("motivo_consulta", "—"))
        st.write("**Justificación:**", resultado.get("justificacion", "—"))
        entidades = resultado.get("entidades_normalizadas", [])
        if entidades:
            st.write("**Entidades normalizadas:**")
            st.write(" · ".join(f"`{e}`" for e in entidades))
        st.write("**GUID:**", resultado.get("GUID", "—"))
        if nivel_llm != nivel:
            st.write(
                f"**Nivel LLM:** {MANCHESTER[nivel_llm]['codigo']} vs "
                f"**Nivel RF:** {MANCHESTER[nivel]['codigo']}"
            )

# ── Métricas del modelo ────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("📊 Métricas del modelo ML"):
    try:
        resp = requests.get(f"{API_URL}/metricas/", timeout=10)
        if resp.status_code == 200:
            m = resp.json().get("metricas_modelo", {})
            if m:
                col1, col2, col3 = st.columns(3)
                col1.metric("CV F1 macro", f"{m.get('cv_f1_macro', 0):.3f} ± {m.get('cv_f1_std', 0):.3f}")
                report = m.get("classification_report", {})
                col2.metric("Recall C2", f"{report.get('C2', {}).get('recall', 0):.3f}")
                col3.metric("F1 C3", f"{report.get('C3', {}).get('f1-score', 0):.3f}")

                fi = m.get("feature_importances", {})
                if fi:
                    st.caption("Importancia de features (modelo actual)")
                    fi_sorted = sorted(fi.items(), key=lambda x: x[1], reverse=True)
                    df_fi = pd.DataFrame(fi_sorted, columns=["Feature", "Importancia"])
                    df_fi["Importancia"] = df_fi["Importancia"].map("{:.1%}".format)
                    st.dataframe(df_fi, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"No se pudieron cargar las métricas: {e}")

# ── Tabla de auditoría ─────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("📋 Registro de auditoría ética (under-triage detectado)"):
    st.caption(
        "Casos donde el modelo RF predijo un nivel menos urgente que el criterio LLM "
        "y el paciente mostraba ansiedad alta (≥0.7). Requieren revisión clínica."
    )
    df_audit = fetch_auditoria()
    if df_audit.empty:
        st.info("No hay casos de under-triage registrados.")
    else:
        st.dataframe(df_audit, use_container_width=True)
