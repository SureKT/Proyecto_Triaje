"""
Codificación común de features para dataset CSV, entrenamiento y predicción.
-1 = desconocido / no mencionado en la transcripción (edad, sexo, dolor_intensidad).
"""
import pandas as pd

UNKNOWN = -1

ESPECIALIDAD_MAP = {"CAR": 0, "DER": 1, "GAS": 2, "GEN": 3, "MSK": 4, "RES": 5, "UNK": 6}

FEATURES = [
    "edad", "sexo", "dolor_intensidad", "disnea", "fiebre",
    "perdida_consciencia", "irradiacion", "antecedentes_cardiacos",
    "fumador", "score_urgencia", "score_ansiedad",
]
TARGET = "nivel_triaje"

BOOL_COLS = [
    "disnea", "fiebre", "perdida_consciencia",
    "irradiacion", "antecedentes_cardiacos", "fumador",
]


def encode_especialidad(value) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ESPECIALIDAD_MAP["UNK"]
    return ESPECIALIDAD_MAP.get(str(value).upper().strip(), ESPECIALIDAD_MAP["UNK"])


def as_bool(value) -> bool:
    """Booleanos clínicos: null del LLM → False (no mencionado)."""
    if value is None:
        return False
    return bool(value)


def encode_sexo(value) -> int:
    if value in (1, 0, UNKNOWN):
        return int(value)
    if value == "M":
        return 1
    if value == "F":
        return 0
    return UNKNOWN


def encode_optional_int(value) -> int:
    """Edad o dolor_intensidad: null → desconocido (-1)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return UNKNOWN
    return int(value)


def prepare_dataset_export_df(df: pd.DataFrame) -> pd.DataFrame:
    """Mismas transformaciones que dataset_builder al generar el CSV."""
    out = df.copy()
    for col in BOOL_COLS:
        out[col] = out[col].map(as_bool).astype(int)
    out["edad"] = out["edad"].map(encode_optional_int)
    out["sexo"] = out["sexo"].map(encode_sexo)
    out["dolor_intensidad"] = out["dolor_intensidad"].map(encode_optional_int)
    if "score_ansiedad" in out.columns:
        out["score_ansiedad"] = out["score_ansiedad"].fillna(0.0).astype(float)
    else:
        out["score_ansiedad"] = 0.0
    if "especialidad" in out.columns:
        out["especialidad"] = out["especialidad"].map(encode_especialidad)
    return out


def prepare_training_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filas para entrenamiento/evaluación: solo exige target (y score).
    Features opcionales faltantes → -1 (no se descartan filas por edad/sexo).
    """
    out = df.copy()
    # CSV ya codificado o crudo re-exportado
    if out["sexo"].dtype == object:
        out = prepare_dataset_export_df(out)
    else:
        for col in BOOL_COLS:
            if col in out.columns:
                out[col] = out[col].fillna(0).astype(int)
        for col in ("edad", "dolor_intensidad"):
            if col in out.columns:
                out[col] = out[col].apply(
                    lambda v: UNKNOWN if pd.isna(v) else int(v)
                )
        if "sexo" in out.columns:
            out["sexo"] = out["sexo"].apply(
                lambda v: UNKNOWN if pd.isna(v) else int(v)
            )
        if "score_ansiedad" in out.columns:
            out["score_ansiedad"] = out["score_ansiedad"].fillna(0.0).astype(float)
        else:
            out["score_ansiedad"] = 0.0

    if "especialidad" in out.columns:
        if out["especialidad"].dtype == object:
            out["especialidad"] = out["especialidad"].map(encode_especialidad)
        else:
            out["especialidad"] = out["especialidad"].fillna(ESPECIALIDAD_MAP["UNK"]).astype(int)
    else:
        out["especialidad"] = ESPECIALIDAD_MAP["UNK"]

    out = out.dropna(subset=[TARGET, "score_urgencia"])
    out[FEATURES] = out[FEATURES].fillna(UNKNOWN)
    return out


def row_from_llm_result(resultado: dict, especialidad: str = "UNK") -> dict:
    """Vector de features alineado con el modelo (Fase 2)."""
    return {
        "especialidad": encode_especialidad(especialidad),
        "edad": encode_optional_int(resultado.get("edad")),
        "sexo": encode_sexo(resultado.get("sexo")),
        "dolor_intensidad": encode_optional_int(resultado.get("dolor_intensidad")),
        "disnea": int(as_bool(resultado.get("disnea"))),
        "fiebre": int(as_bool(resultado.get("fiebre"))),
        "perdida_consciencia": int(as_bool(resultado.get("perdida_consciencia"))),
        "irradiacion": int(as_bool(resultado.get("irradiacion"))),
        "antecedentes_cardiacos": int(as_bool(resultado.get("antecedentes_cardiacos"))),
        "fumador": int(as_bool(resultado.get("fumador"))),
        "score_urgencia": resultado.get("score_urgencia", 50),
        "score_ansiedad": float(resultado.get("score_ansiedad") or 0.0),
    }
