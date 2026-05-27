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

MANCHESTER = {
    1: {"codigo": "C1", "nombre": "Inmediato",     "color": "#c62828", "bg": "#1a0a0a"},
    2: {"codigo": "C2", "nombre": "Muy Urgente",   "color": "#e65100", "bg": "#1a0e00"},
    3: {"codigo": "C3", "nombre": "Urgente",       "color": "#f9a825", "bg": "#1a1600"},
    4: {"codigo": "C4", "nombre": "Menos Urgente", "color": "#2e7d32", "bg": "#0a1a0a"},
    5: {"codigo": "C5", "nombre": "No Urgente",    "color": "#1565c0", "bg": "#0a0f1a"},
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500&family=DM+Mono:wght@400&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* Fondo principal */
.stApp {
    background-color: #0e0e0f;
}

/* Ocultar chrome de Streamlit */
#MainMenu, header, footer { visibility: hidden; }

/* Título principal */
h1 { font-weight: 300 !important; letter-spacing: -0.5px; color: #f0f0ee !important; }
h2 { font-weight: 500 !important; color: #f0f0ee !important; }
h3 { font-weight: 500 !important; color: #c8c8c4 !important; }

/* Caption y texto secundario */
.stCaption { color: #5a5a56 !important; font-size: 0.8rem; }

/* Inputs y textareas */
.stTextArea textarea, .stTextInput input {
    background-color: #1e1e21 !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 10px !important;
    color: #f0f0ee !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.82rem !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
    border-color: rgba(255,255,255,0.18) !important;
    box-shadow: none !important;
}

/* Botón primario */
.stButton > button[kind="primary"] {
    background-color: #c8f0dc !important;
    color: #0e0e0f !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-family: 'DM Sans', sans-serif !important;
    transition: opacity 150ms ease !important;
}
.stButton > button[kind="primary"]:hover { opacity: 0.85 !important; }

/* Botón secundario */
.stButton > button {
    background-color: transparent !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #c8c8c4 !important;
    border-radius: 8px !important;
    font-family: 'DM Sans', sans-serif !important;
    transition: border-color 150ms ease, color 150ms ease !important;
}
.stButton > button:hover {
    border-color: rgba(255,255,255,0.2) !important;
    color: #f0f0ee !important;
}

/* Radio */
.stRadio label { color: #9b9b97 !important; font-size: 0.875rem; }
.stRadio label:hover { color: #f0f0ee !important; }

/* Métricas */
[data-testid="stMetric"] {
    background-color: #161618 !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 10px !important;
    padding: 16px 20px !important;
}
[data-testid="stMetricLabel"] { color: #5a5a56 !important; font-size: 0.75rem !important; text-transform: uppercase; letter-spacing: 0.05em; }
[data-testid="stMetricValue"] { color: #f0f0ee !important; font-weight: 300 !important; font-size: 1.6rem !important; }

/* Expanders */
.streamlit-expanderHeader {
    background-color: #161618 !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 10px !important;
    color: #9b9b97 !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
}
.streamlit-expanderHeader:hover { border-color: rgba(255,255,255,0.13) !important; color: #f0f0ee !important; }
.streamlit-expanderContent {
    background-color: #161618 !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-top: none !important;
    border-radius: 0 0 10px 10px !important;
}

/* Dataframe */
[data-testid="stDataFrame"] { border: 1px solid rgba(255,255,255,0.07) !important; border-radius: 10px !important; overflow: hidden; }

/* Info / warning / error */
.stInfo { background-color: #161618 !important; border-left: 3px solid #1565c0 !important; border-radius: 8px !important; }
.stWarning { background-color: #1a1200 !important; border-left: 3px solid #f9a825 !important; border-radius: 8px !important; }
.stError { background-color: #1a0a0a !important; border-left: 3px solid #c62828 !important; border-radius: 8px !important; }
.stSuccess { background-color: #0a1a0e !important; border-left: 3px solid #2e7d32 !important; border-radius: 8px !important; }

/* Spinner */
.stSpinner > div { border-top-color: #c8f0dc !important; }

/* Divider */
hr { border-color: rgba(255,255,255,0.07) !important; margin: 24px 0 !important; }

/* File uploader */
[data-testid="stFileUploader"] {
    background-color: #161618 !important;
    border: 1px dashed rgba(255,255,255,0.12) !important;
    border-radius: 10px !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0e0e0f; }
::-webkit-scrollbar-thumb { background: #26262a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #3a3a3e; }
</style>
"""


def badge_manchester(nivel: int) -> str:
    m = MANCHESTER.get(nivel, MANCHESTER[3])
    return f"""
    <div style='
        background: {m["bg"]};
        border: 1px solid {m["color"]}40;
        border-left: 4px solid {m["color"]};
        border-radius: 10px;
        padding: 20px 28px;
        margin: 12px 0;
        display: flex;
        align-items: center;
        gap: 16px;
    '>
        <div style='
            background: {m["color"]};
            color: white;
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 1rem;
            font-weight: 500;
            font-family: DM Mono, monospace;
            letter-spacing: 0.05em;
            white-space: nowrap;
        '>{m["codigo"]}</div>
        <div>
            <div style='color: #f0f0ee; font-size: 1.4rem; font-weight: 300; line-height: 1.2;'>{m["nombre"]}</div>
            <div style='color: #5a5a56; font-size: 0.75rem; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.06em;'>Nivel de triaje Manchester</div>
        </div>
    </div>"""


def ansiedad_badge(score: float) -> str:
    if score is None:
        return ""
    if score >= 0.86:
        color, bg, label = "#f87171", "#1a0a0a", f"Pánico extremo"
    elif score >= 0.7:
        color, bg, label = "#fbbf24", "#1a1200", f"Ansiedad alta"
    elif score >= 0.4:
        color, bg, label = "#f9a825", "#161000", f"Ansiedad moderada"
    else:
        color, bg, label = "#4ade80", "#0a1a0e", f"Paciente tranquilo"
    return f"""
    <div style='
        background: {bg};
        border: 1px solid {color}30;
        border-radius: 8px;
        padding: 10px 16px;
        display: inline-flex;
        align-items: center;
        gap: 10px;
        margin: 4px 0;
    '>
        <span style='color: {color}; font-size: 0.8rem; font-weight: 500;'>{label}</span>
        <span style='
            background: {color}20;
            color: {color};
            font-family: DM Mono, monospace;
            font-size: 0.75rem;
            padding: 2px 8px;
            border-radius: 4px;
        '>{score:.2f}</span>
    </div>"""


def stat_card(label: str, value: str, sub: str = "") -> str:
    return f"""
    <div style='
        background: #161618;
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 10px;
        padding: 16px 20px;
    '>
        <div style='color: #5a5a56; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;'>{label}</div>
        <div style='color: #f0f0ee; font-size: 1.5rem; font-weight: 300; line-height: 1;'>{value}</div>
        {f'<div style="color: #5a5a56; font-size: 0.72rem; margin-top: 4px;">{sub}</div>' if sub else ''}
    </div>"""


def call_predecir(texto: str) -> dict:
    resp = requests.post(f"{API_URL}/predecir/", data={"texto": texto}, timeout=180)
    resp.raise_for_status()
    return resp.json()


def fetch_auditoria() -> pd.DataFrame:
    try:
        resp = requests.get(f"{API_URL}/metricas/auditoria", timeout=10)
        if resp.status_code == 200:
            return pd.DataFrame(resp.json())
    except Exception:
        pass
    return pd.DataFrame()


def fetch_metricas() -> dict:
    try:
        resp = requests.get(f"{API_URL}/metricas/", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


# ── Config ─────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Triaje IA", page_icon="🏥", layout="centered")
st.markdown(CSS, unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style='padding: 8px 0 24px 0;'>
    <div style='color: #f0f0ee; font-size: 1.6rem; font-weight: 300; letter-spacing: -0.3px;'>Triaje IA</div>
    <div style='color: #5a5a56; font-size: 0.8rem; margin-top: 4px;'>Sistema de Triaje Manchester · LLM + Random Forest</div>
</div>
""", unsafe_allow_html=True)

# ── Entrada ────────────────────────────────────────────────────────────────────
modo = st.radio("Modo de entrada", ["🎤 Audio", "📝 Texto"], horizontal=True, label_visibility="collapsed")

texto_entrada = ""

if modo == "🎤 Audio":
    audio_file = st.file_uploader(
        "Sube el audio de la entrevista",
        type=["wav", "mp3", "m4a", "ogg"],
        label_visibility="collapsed",
    )
    if audio_file:
        st.audio(audio_file)
        with st.spinner("Transcribiendo con Whisper..."):
            try:
                from whisper_utils import transcribe_audio
                texto_entrada = transcribe_audio(audio_file.read())
                st.success("Transcripción completada")
                st.text_area("Texto transcrito", texto_entrada, height=120, disabled=True, label_visibility="collapsed")
            except Exception as e:
                st.error(f"Error Whisper: {e}")
else:
    texto_entrada = st.text_area(
        "Transcripción",
        height=180,
        placeholder="D: ¿Cuál es el motivo de su consulta?\nP: Llevo dos días con dolor en el pecho...",
        label_visibility="collapsed",
    )

analizar = st.button("Analizar", disabled=not texto_entrada.strip(), type="primary", use_container_width=True)

# ── Resultado ──────────────────────────────────────────────────────────────────
if analizar and texto_entrada.strip():
    with st.spinner("Procesando · LLM + modelo ML · ~15 s"):
        try:
            resultado = call_predecir(texto_entrada)
        except requests.HTTPError as e:
            st.error(f"Error API ({e.response.status_code}): {e.response.text}")
            st.stop()
        except Exception as e:
            st.error(f"Error de conexión: {e}")
            st.stop()

    nivel      = resultado.get("nivel_triaje_predicho", 3)
    nivel_llm  = resultado.get("nivel_triaje_llm", nivel)
    ansiedad   = resultado.get("score_ansiedad")
    under      = nivel > nivel_llm

    st.markdown("---")
    st.markdown(badge_manchester(nivel), unsafe_allow_html=True)

    # Métricas de la predicción
    col1, col2, col3 = st.columns(3)
    col1.metric("Urgencia LLM", f"{resultado.get('score_urgencia', 0):.0f} / 100")
    col2.metric("Confianza RF",  f"{resultado.get('confianza', 0):.1%}")
    col3.metric("Valoración",    f"{resultado.get('valoracion', 0):.1f} / 10")

    if ansiedad is not None:
        st.markdown(ansiedad_badge(ansiedad), unsafe_allow_html=True)

    if under:
        st.warning(
            f"⚠ **Posible under-triage** — RF predice {MANCHESTER[nivel]['codigo']} "
            f"pero LLM asignó {MANCHESTER[nivel_llm]['codigo']}. Revise clínicamente."
        )

    with st.expander("Detalle clínico"):
        st.markdown(f"**Motivo de consulta** — {resultado.get('motivo_consulta', '—')}")
        st.markdown(f"**Justificación** — {resultado.get('justificacion', '—')}")
        entidades = resultado.get("entidades_normalizadas", [])
        if entidades:
            tags = " &nbsp;".join(
                f"<code style='background:#1e1e21;padding:2px 8px;border-radius:4px;font-size:0.78rem;color:#9b9b97;'>{e}</code>"
                for e in entidades
            )
            st.markdown(f"**Entidades** &nbsp; {tags}", unsafe_allow_html=True)
        if nivel_llm != nivel:
            st.markdown(
                f"**Discrepancia** — LLM: `{MANCHESTER[nivel_llm]['codigo']}` · RF: `{MANCHESTER[nivel]['codigo']}`"
            )
        st.markdown(f"<div style='color:#5a5a56;font-size:0.72rem;margin-top:8px;font-family:DM Mono,monospace;'>GUID: {resultado.get('GUID','—')}</div>", unsafe_allow_html=True)

# ── Métricas del modelo ────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("Métricas del modelo"):
    metricas = fetch_metricas()
    m = metricas.get("metricas_modelo", {})
    lat = metricas.get("latencia_fase2", {})
    thr = metricas.get("throughput_batch", {})
    ent = metricas.get("entrenamiento", {})

    if m:
        # F1 y recall
        report = m.get("classification_report", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("CV F1 macro", f"{m.get('cv_f1_macro', 0):.3f}", f"± {m.get('cv_f1_std', 0):.3f}")
        c2.metric("Recall C2",   f"{report.get('C2', {}).get('recall', 0):.3f}")
        c3.metric("F1 C3",       f"{report.get('C3', {}).get('f1-score', 0):.3f}")

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # Latencia y throughput
        c4, c5, c6 = st.columns(3)
        c4.metric("Latencia E2E media",  f"{lat.get('avg_latencia_e2e_s', 0):.1f} s",  f"mín {lat.get('min_latencia_e2e_s', 0):.1f} s")
        c5.metric("Tiempo LLM medio",    f"{lat.get('avg_tiempo_llm_s', 0):.1f} s")
        c6.metric("Throughput batch",    f"{thr.get('throughput_por_minuto', 0):.2f} txt/min")

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # Importancia de features
        fi = m.get("feature_importances", {})
        if fi:
            st.markdown("<div style='color:#5a5a56;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px;'>Importancia de features</div>", unsafe_allow_html=True)
            fi_sorted = sorted(fi.items(), key=lambda x: x[1], reverse=True)
            for feat, imp in fi_sorted:
                pct = imp * 100
                bar_color = "#c8f0dc" if pct > 10 else "#26262a"
                st.markdown(f"""
                <div style='display:flex;align-items:center;gap:12px;margin-bottom:6px;'>
                    <div style='width:130px;color:#9b9b97;font-size:0.78rem;font-family:DM Mono,monospace;'>{feat}</div>
                    <div style='flex:1;background:#1e1e21;border-radius:3px;height:4px;'>
                        <div style='width:{min(pct*1.5,100):.0f}%;background:{bar_color};height:4px;border-radius:3px;'></div>
                    </div>
                    <div style='width:42px;text-align:right;color:#5a5a56;font-size:0.75rem;font-family:DM Mono,monospace;'>{pct:.1f}%</div>
                </div>""", unsafe_allow_html=True)

        # Modelo
        modelo_id = m.get("modelo", "—")
        ultimo_ent = ent.get("ultimo_entrenamiento", "—")
        st.markdown(f"<div style='color:#5a5a56;font-size:0.72rem;margin-top:12px;font-family:DM Mono,monospace;'>modelo: {modelo_id} &nbsp;·&nbsp; entrenado: {ultimo_ent}</div>", unsafe_allow_html=True)
    else:
        st.info("Métricas no disponibles.")

# ── Auditoría ──────────────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("Registro de auditoría ética"):
    st.markdown("<div style='color:#5a5a56;font-size:0.8rem;margin-bottom:12px;'>Casos donde RF predijo nivel menos urgente que LLM con ansiedad ≥ 0.7 — requieren revisión clínica.</div>", unsafe_allow_html=True)
    df = fetch_auditoria()
    if df.empty:
        st.markdown("""
        <div style='text-align:center;padding:32px 0;'>
            <div style='color:#5a5a56;font-size:0.85rem;'>Sin casos de under-triage registrados</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
