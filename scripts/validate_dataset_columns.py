#!/usr/bin/env python3
"""Valida columnas y calidad de datos ENRICHED vs dataset_builder / ml_trainer."""
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services"))
from ml_features import UNKNOWN, prepare_dataset_export_df, prepare_training_df


def pg_execute(query, params=None, fetch=False):
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5433")),
        user=os.environ.get("POSTGRES_USER", "triaje"),
        password=os.environ.get("POSTGRES_PASSWORD", "triaje_pass"),
        dbname=os.environ.get("POSTGRES_DB", "triaje_db"),
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            if fetch:
                return cur.fetchall()
            conn.commit()
    finally:
        conn.close()

EXPECTED_CSV_COLS = [
    "guid", "especialidad", "edad", "sexo", "dolor_intensidad",
    "disnea", "fiebre", "perdida_consciencia", "irradiacion",
    "antecedentes_cardiacos", "fumador", "score_urgencia", "nivel_triaje",
]
FEATURES = [
    "edad", "sexo", "dolor_intensidad", "disnea", "fiebre",
    "perdida_consciencia", "irradiacion", "antecedentes_cardiacos",
    "fumador", "score_urgencia",
]
BOOL_COLS = [
    "disnea", "fiebre", "perdida_consciencia",
    "irradiacion", "antecedentes_cardiacos", "fumador",
]


def main():
    rows = pg_execute(
        """
        SELECT e.GUID_Entrevista AS guid, e.especialidad, e.nombre_fichero,
               r.edad, r.sexo, r.dolor_intensidad, r.disnea, r.fiebre,
               r.perdida_consciencia, r.irradiacion, r.antecedentes_cardiacos,
               r.fumador, r.score_urgencia, r.nivel_triaje, r.motivo_consulta
        FROM Entrevista e
        JOIN ResultadoML r ON e.GUID_Entrevista = r.GUID_Entrevista
        WHERE e.Estado = 'ENRICHED'
        """,
        fetch=True,
    )
    if not rows:
        print("NO HAY FILAS ENRICHED — no se puede validar el dataset aún.")
        return

    df = pd.DataFrame([dict(r) for r in rows])
    print(f"=== FILAS ENRICHED: {len(df)} ===\n")
    issues = []

    df_csv = prepare_dataset_export_df(df.copy())

    missing = [c for c in EXPECTED_CSV_COLS if c not in df_csv.columns]
    print("Columnas esperadas en CSV:", ", ".join(EXPECTED_CSV_COLS))
    print("Faltan en datos:", missing or "ninguna")
    print("OK estructura CSV:", "SÍ" if not missing else "NO")
    print()

    print("=== NULOS (valores crudos del LLM) ===")
    check_cols = FEATURES + ["nivel_triaje", "motivo_consulta", "especialidad"]
    for c in check_cols:
        n = int(df[c].isna().sum())
        pct = 100 * n / len(df)
        flag = ""
        if c in ("edad", "sexo", "dolor_intensidad") and n > 0:
            flag = " (→ -1 en CSV, esperado si no se menciona)"
        elif c == "nivel_triaje" and n > 0:
            flag = " ⚠"
        print(f"  {c:25} {n:3}/{len(df)} ({pct:.0f}%){flag}")
        if c == "nivel_triaje" and n > 0:
            issues.append(f"null en {c}: {n}")

    print("\n=== nivel_triaje (target ML) ===")
    print(df["nivel_triaje"].value_counts().sort_index().to_string())
    bad = df[~df["nivel_triaje"].between(1, 5) & df["nivel_triaje"].notna()]
    print(f"Fuera de rango 1-5: {len(bad)}")
    if len(bad):
        issues.append("nivel_triaje fuera de 1-5")

    print("\n=== score_urgencia ===")
    s = df["score_urgencia"]
    print(f"  min={s.min()}, max={s.max()}, nulls={s.isna().sum()}")

    print("\n=== sexo (crudo M/F/null) ===")
    print(df["sexo"].value_counts(dropna=False).to_string())

    print("\n=== especialidad ===")
    print(df["especialidad"].value_counts().to_string())

    train_df = prepare_training_df(df_csv)
    print(f"\n=== Filas usables por ml_trainer (target + score; edad/sexo -1 si faltan) ===")
    print(f"  {len(train_df)}/{len(df)}")
    print(f"  edad={UNKNOWN} (desconocida): {(train_df['edad'] == UNKNOWN).sum()}")
    print(f"  sexo={UNKNOWN} (desconocido): {(train_df['sexo'] == UNKNOWN).sum()}")
    if len(train_df) < len(df):
        issues.append(f"{len(df) - len(train_df)} filas sin nivel_triaje o score_urgencia")

    ent = pg_execute(
        """
        SELECT COUNT(*) AS n FROM Entidad e
        JOIN Entrevista i ON e.GUID_Entrevista = i.GUID_Entrevista
        WHERE i.Estado = 'ENRICHED'
        """,
        fetch=True,
    )
    avg_ent = pg_execute(
        """
        SELECT AVG(cnt)::float AS avg FROM (
            SELECT COUNT(*) AS cnt FROM Entidad e
            JOIN Entrevista i ON e.GUID_Entrevista = i.GUID_Entrevista
            WHERE i.Estado = 'ENRICHED'
            GROUP BY e.GUID_Entrevista
        ) t
        """,
        fetch=True,
    )
    print(f"\n=== Entidades (tabla Entidad) ===")
    print(f"  Total filas: {ent[0]['n']}, media por entrevista: {avg_ent[0]['avg']:.1f}")

    print("\n=== Muestra (como iría al CSV) ===")
    print(df_csv[EXPECTED_CSV_COLS].head(5).to_string())

    print("\n=== VEREDICTO ===")
    if not missing and len(bad) == 0 and len(train_df) == len(df):
        print("Columnas y tipos: CORRECTOS. Listo para dataset_builder y Random Forest.")
    elif not missing and len(train_df) >= len(df) * 0.95:
        print("Columnas: CORRECTAS. Nulls en edad/sexo/dolor son esperables (codificados como -1).")
    else:
        print("Columnas: estructura OK, pero HAY problemas de calidad:")
        for i in issues:
            print(f"  - {i}")

    # ENRICHED sin ResultadoML
    orphan = pg_execute(
        """
        SELECT COUNT(*) AS n FROM Entrevista e
        LEFT JOIN ResultadoML r ON e.GUID_Entrevista = r.GUID_Entrevista
        WHERE e.Estado = 'ENRICHED' AND r.GUID_Entrevista IS NULL
        """,
        fetch=True,
    )
    if orphan[0]["n"]:
        print(f"  - {orphan[0]['n']} ENRICHED sin fila en ResultadoML")


if __name__ == "__main__":
    main()
