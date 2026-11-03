"""Genera diagnostico.db y diagnostico.7z: base de referencia para el
diagnóstico de proyecciones externas, sin tablas del PREP.

Uso: python construir_diagnostico.py
"""

import sqlite3
from pathlib import Path

import pandas as pd
import py7zr

RAIZ = Path(__file__).parent
ORIGEN = RAIZ / "derfe_web.db"
DESTINO_DB = RAIZ / "diagnostico.db"
DESTINO_7Z = RAIZ / "diagnostico.7z"


def main():
    if not ORIGEN.exists():
        raise SystemExit("No existe derfe_web.db")

    if DESTINO_DB.exists():
        DESTINO_DB.unlink()

    con_o = sqlite3.connect(ORIGEN)
    con_d = sqlite3.connect(DESTINO_DB)
    cur = con_d.cursor()

    cur.executescript("""
        CREATE TABLE ref_secciones (
            CLAVE_ENTIDAD INTEGER, CLAVE_DISTRITO INTEGER, SECCION INTEGER,
            TIPO_3 TEXT, N_LOCALIDADES INTEGER,
            B_HIST INTEGER, C_HIST INTEGER, E_HIST INTEGER, S_HIST INTEGER,
            LN_ORD_24 REAL, LN_E_24 REAL, LN_2024 REAL, TV_2024 REAL, NU_2024 REAL
        );
        CREATE TABLE ref_padron (
            CORTE TEXT, CLAVE_ENTIDAD INTEGER, CLAVE_DISTRITO INTEGER,
            SECCION INTEGER, PADRON_ELECTORAL REAL, LISTA_NOMINAL REAL
        );
        CREATE TABLE ref_equivalencias (
            CLAVE_ENTIDAD INTEGER, CLAVE_DISTRITO INTEGER,
            SECCION_MATRIZ INTEGER, SECCION_NUEVA INTEGER
        );
        CREATE TABLE cat_entidades (
            CLAVE_ENTIDAD INTEGER PRIMARY KEY, NOMBRE_ENTIDAD TEXT
        );
        CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);
    """)

    secciones = pd.read_sql_query("""
        SELECT
            CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION,
            SUM(CASE WHEN TIPO_CASILLA = 'B' THEN 1 ELSE 0 END) AS B_HIST,
            SUM(CASE WHEN TIPO_CASILLA = 'C' THEN 1 ELSE 0 END) AS C_HIST,
            SUM(CASE WHEN TIPO_CASILLA = 'E' THEN 1 ELSE 0 END) AS E_HIST,
            SUM(CASE WHEN TIPO_CASILLA = 'S' THEN 1 ELSE 0 END) AS S_HIST,
            SUM(CASE WHEN TIPO_CASILLA IN ('B','C') THEN LISTA_NOMINAL ELSE 0 END) AS LN_ORD_24,
            SUM(CASE WHEN TIPO_CASILLA = 'E' THEN LISTA_NOMINAL ELSE 0 END) AS LN_E_24,
            SUM(LISTA_NOMINAL) AS LN_2024,
            SUM(TOTAL_VOTOS) AS TV_2024,
            SUM(VOTOS_NULOS) AS NU_2024
        FROM resultados_sen_2024
        WHERE TIPO_CASILLA IN ('B','C','E','S')
        GROUP BY 1, 2, 3
    """, con_o)
    tipo = pd.read_sql_query(
        "SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, TIPO_3 FROM cat_secciones", con_o
    )
    locales = pd.read_sql_query("""
        SELECT CLAVE_ENTIDAD, SECCION, COUNT(DISTINCT LOCALIDAD) AS N_LOCALIDADES
        FROM cat_localidades_seccion GROUP BY 1, 2
    """, con_o)
    secciones = secciones.merge(tipo, on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO", "SECCION"], how="left")
    secciones = secciones.merge(locales, on=["CLAVE_ENTIDAD", "SECCION"], how="left")
    secciones["N_LOCALIDADES"] = secciones["N_LOCALIDADES"].fillna(0).astype(int)
    secciones.to_sql("ref_secciones", con_d, if_exists="append", index=False)

    tablas = [r[0] for r in con_o.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'padron_2026_%' ORDER BY name"
    )]
    total_padron = 0
    for t in tablas:
        corte = "-".join(t.split("_")[1:4])
        df = pd.read_sql_query(f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, PADRON_ELECTORAL, LISTA_NOMINAL
            FROM {t}
        """, con_o)
        df.insert(0, "CORTE", corte)
        df.to_sql("ref_padron", con_d, if_exists="append", index=False)
        total_padron += len(df)
        print(f"  {t}: {len(df):,} filas")

    equivalencias = pd.read_sql_query("""
        SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION_MATRIZ, SECCION_NUEVA
        FROM cat_equivalencias_reseccionamiento
    """, con_o)
    equivalencias.to_sql("ref_equivalencias", con_d, if_exists="append", index=False)

    entidades = pd.read_sql_query("""
        SELECT DISTINCT CLAVE_ENTIDAD, NOMBRE_ENTIDAD FROM cat_secciones ORDER BY 1
    """, con_o)
    entidades.to_sql("cat_entidades", con_d, if_exists="append", index=False)

    con_d.executescript("""
        CREATE INDEX ix_secciones ON ref_secciones (CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION);
        CREATE INDEX ix_padron ON ref_padron (CORTE, CLAVE_ENTIDAD, CLAVE_DISTRITO);
        CREATE INDEX ix_equiv ON ref_equivalencias (CLAVE_ENTIDAD, CLAVE_DISTRITO);
    """)
    meta = {
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "cortes": ",".join(sorted({"-".join(t.split("_")[1:4]) for t in tablas})),
        "secciones": str(len(secciones)),
        "padron_filas": str(total_padron),
    }
    pd.DataFrame(list(meta.items()), columns=["clave", "valor"]).to_sql(
        "meta", con_d, if_exists="append", index=False
    )
    con_d.commit()
    con_d.execute("VACUUM")
    con_d.close()
    con_o.close()

    if DESTINO_7Z.exists():
        DESTINO_7Z.unlink()
    with py7zr.SevenZipFile(DESTINO_7Z, mode="w") as z:
        z.write(DESTINO_DB, arcname="diagnostico.db")

    print(f"OK {DESTINO_DB.name}: {DESTINO_DB.stat().st_size/1e6:.1f} MB")
    print(f"OK {DESTINO_7Z.name}: {DESTINO_7Z.stat().st_size/1e6:.1f} MB")
    print("Cortes:", meta["cortes"])


if __name__ == "__main__":
    main()
