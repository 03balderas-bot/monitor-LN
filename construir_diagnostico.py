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
INSUMOS = RAIZ / "insumos_originales"


def integrar_corte_oficial(con_d):
    """Corte oficial 30-sep-2026 por entidad: totales por seccion y desglose
    por localidad con el grupo de casilla E 2024 (columna CASILLA)."""
    archivos = sorted(INSUMOS.glob("*_estadistico_pdln_*_30092026.xlsx"))
    if not archivos:
        print("  (sin archivos de corte oficial 30-sep-2026)")
        return []
    cortes = []
    for ruta in archivos:
        df = pd.read_excel(ruta, sheet_name=0)
        df.columns = [str(c).strip().upper() for c in df.columns]
        entidad = int(df["ENTIDAD"].iloc[0])
        corte = "2026-09-30"
        claves = ["ENTIDAD", "DISTRITO", "MUNICIPIO", "SECCION", "LOCALIDAD"]
        loc = df.groupby(claves, as_index=False).agg(
            PADRON=("PADRON", "sum"), LISTA=("LISTA", "sum"))
        marca_e = df[df["CASILLA"].astype(str).str.startswith("E")]
        if not marca_e.empty:
            e_grupo = marca_e.groupby(claves)["CASILLA"].first().rename("E_GRUPO")
            loc = loc.merge(e_grupo, on=claves, how="left")
            e_pad = marca_e.groupby(claves).agg(
                E_PADRON=("PADRON", "sum"), E_LISTA=("LISTA", "sum"))
            loc = loc.merge(e_pad, on=claves, how="left")
        else:
            loc["E_GRUPO"] = None
            loc["E_PADRON"] = 0
            loc["E_LISTA"] = 0
        loc = loc.rename(columns={
            "ENTIDAD": "CLAVE_ENTIDAD", "DISTRITO": "CLAVE_DISTRITO",
            "LOCALIDAD": "LOCALIDAD"})
        loc.insert(0, "CORTE", corte)
        loc.to_sql("ref_localidades", con_d, if_exists="append", index=False)

        secc = df.groupby(["ENTIDAD", "DISTRITO", "SECCION"], as_index=False).agg(
            PADRON_ELECTORAL=("PADRON", "sum"), LISTA_NOMINAL=("LISTA", "sum"))
        secc = secc.rename(columns={"ENTIDAD": "CLAVE_ENTIDAD",
                                    "DISTRITO": "CLAVE_DISTRITO"})
        secc.insert(0, "CORTE", corte)
        secc.to_sql("ref_padron", con_d, if_exists="append", index=False)
        cortes.append(corte)
        print(f"  oficial {ruta.name}: {len(secc):,} secciones, "
              f"{len(loc):,} localidades (entidad {entidad})")
    return cortes


def integrar_pef2024(con_d):
    """Corte oficial PEF 2024 (02-jun-2024) por seccion: totales de padrón y LN."""
    archivos = sorted(INSUMOS.glob("derfe-pdln_edms_sexo_PEF_*.xlsx"))
    if not archivos:
        print("  (sin corte oficial PEF 2024)")
        return []
    cortes = []
    for ruta in archivos:
        df = pd.read_excel(ruta, header=None, skiprows=[0, 1])
        df = df[[0, 1, 3, 7, 11]]
        df.columns = ["ENTIDAD", "DISTRITO", "SECCION", "PADRON", "LN"]
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[df["SECCION"] > 0]
        secc = df.groupby(["ENTIDAD", "DISTRITO", "SECCION"], as_index=False).agg(
            PADRON=("PADRON", "sum"), LN=("LN", "sum"))
        secc = secc.rename(columns={"ENTIDAD": "CLAVE_ENTIDAD",
                                    "DISTRITO": "CLAVE_DISTRITO",
                                    "PADRON": "PADRON_ELECTORAL",
                                    "LN": "LISTA_NOMINAL"})
        secc.insert(0, "CORTE", "2024-06-02")
        secc.to_sql("ref_padron", con_d, if_exists="append", index=False)
        cortes.append("2024-06-02")
        print(f"  PEF2024 {ruta.name}: {len(secc):,} secciones, "
              f"padrón {secc['PADRON_ELECTORAL'].sum():,.0f}")
    return cortes


def integrar_manzanas(con_d):
    """Nivel manzana del corte oficial: padrón/LN 2026 por manzana y marca de
    casilla 2024 (columna CASILLA del estadístico). Solo del corte oficial."""
    archivos = sorted(INSUMOS.glob("*_estadistico_pdln_*_30092026.xlsx"))
    if not archivos:
        print("  (sin archivos de corte oficial para manzanas)")
        return 0
    total = 0
    for ruta in archivos:
        df = pd.read_excel(ruta, sheet_name=0)
        df.columns = [str(c).strip().upper() for c in df.columns]
        df = df[df["SECCION"] > 0]
        mz = df[["ENTIDAD", "DISTRITO", "MUNICIPIO", "SECCION", "LOCALIDAD",
                 "MANZANA", "PADRON", "LISTA", "CASILLA"]].copy()
        mz = mz.rename(columns={"ENTIDAD": "CLAVE_ENTIDAD",
                                "DISTRITO": "CLAVE_DISTRITO"})
        for c in ("MANZANA", "PADRON", "LISTA"):
            mz[c] = pd.to_numeric(mz[c], errors="coerce").fillna(0).astype(int)
        mz["CASILLA"] = mz["CASILLA"].astype(str).str.strip()
        mz.loc[mz["CASILLA"].isin(("nan", "", "None")), "CASILLA"] = ""
        mz.insert(0, "CORTE", "2026-09-30")
        mz.to_sql("ref_manzanas", con_d, if_exists="append", index=False)
        total += len(mz)
        print(f"  manzanas {ruta.name}: {len(mz):,} filas")
    return total


def integrar_conformacion(con_o, con_d):
    """Reporte SUCyMEC 'Secciones donde se instalaran Casillas Extraordinarias'
    PEF 2023-2024: BASE de la conformación. Por sección y familia (B o E#):
    localidades atendidas, manzanas explícitas cuando existen, y localidad/
    manzana de instalación."""
    import re
    archivos = sorted(INSUMOS.glob("seccionesConCasillasExtraordinarias*.xlsx"))
    if not archivos:
        print("  (sin reportes de casillas extraordinarias 2024)")
        return 0
    entidades = pd.read_sql_query(
        "SELECT CLAVE_ENTIDAD, NOMBRE_ENTIDAD FROM cat_entidades", con_d)
    nom_a_clave = {str(n).strip().upper(): int(c) for c, n in entidades.itertuples(index=False)}
    distritos = pd.read_sql_query("""
        SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION FROM cat_secciones
    """, con_o)
    distritos_hist = pd.read_sql_query("""
        SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION FROM ref_secciones
    """, con_d)
    total = 0
    for ruta in archivos:
        crudo = pd.read_excel(ruta, header=4)
        crudo.columns = [str(c).strip() for c in crudo.columns]
        encab = pd.read_excel(ruta, sheet_name=0, header=None, nrows=3)
        estado = next((str(v).split(":", 1)[1].strip()
                       for v in encab.stack().dropna() if str(v).startswith("Estado:")), None)
        entidad = nom_a_clave.get(str(estado).upper())
        if entidad is None:
            print(f"  {ruta.name}: entidad '{estado}' no reconocida; se omite")
            continue
        df = crudo[pd.to_numeric(crudo["Sección"], errors="coerce").notna()].copy()
        df["SECCION"] = df["Sección"].astype(int)
        filas = []
        for orden, (_, r) in enumerate(df.iterrows()):
            cas = str(r["Casilla"]).strip()
            if not cas or cas == "nan":
                continue
            if cas == "B":
                fams = [("B", 1)]
            else:
                codigos = [c.strip() for c in cas.split(",")]
                fams = [(fa, sum(1 for c in codigos if c.split("C")[0] == fa))
                        for fa in sorted({c.split("C")[0] for c in codigos})]
            locs = [int(m) for m in re.findall(
                r"^\s*(\d+)\)", str(r["Localidad(es) a atender"]), re.M)]
            bloques = {}
            for m in re.finditer(r"^\s*(\d+)\s*\[([^\]]*)\]",
                                 str(r["Manzana(s) a atender"]), re.M):
                bloques[int(m.group(1))] = ",".join(
                    str(int(x)) for x in re.findall(r"\d+", m.group(2)))
            inst = str(r["Localidad y manzana de instalación"])
            mi = re.search(r"^\s*(\d+)\)", inst)
            inst_loc = int(mi.group(1)) if mi else None
            resto = inst[mi.end():].strip() if mi else ""
            inst_mz = resto if re.fullmatch(r"\d+", resto) else ""
            for fa, n_cas in fams:
                for loc in locs:
                    filas.append((entidad, r["SECCION"], fa, n_cas, loc,
                                  bloques.get(loc, ""), inst_loc, inst_mz, orden))
        c = pd.DataFrame(filas, columns=[
            "CLAVE_ENTIDAD", "SECCION", "FAMILIA", "N_CAS", "LOCALIDAD",
            "MANZANAS", "INSTALA_LOC", "INSTALA_MZ", "ORDEN"]).drop_duplicates()
        c = c.merge(distritos, on=["CLAVE_ENTIDAD", "SECCION"], how="left")
        faltan = c[c["CLAVE_DISTRITO"].isna()][["CLAVE_ENTIDAD", "SECCION"]].drop_duplicates()
        if not faltan.empty:
            extra = faltan.merge(distritos_hist, on=["CLAVE_ENTIDAD", "SECCION"], how="left")
            c = c.drop(columns=["CLAVE_DISTRITO"]).merge(
                pd.concat([distritos, extra]).drop_duplicates(),
                on=["CLAVE_ENTIDAD", "SECCION"], how="left")
        sin_d = int(c["CLAVE_DISTRITO"].isna().sum())
        c = c[c["CLAVE_DISTRITO"].notna()]
        c = c[["CLAVE_ENTIDAD", "CLAVE_DISTRITO", "SECCION", "FAMILIA", "N_CAS",
               "LOCALIDAD", "MANZANAS", "INSTALA_LOC", "INSTALA_MZ", "ORDEN"]]
        c.to_sql("ref_conformacion", con_d, if_exists="append", index=False)
        total += len(c)
        print(f"  conformación {ruta.name}: entidad {entidad}, "
              f"{c['SECCION'].nunique()} secciones, {len(c)} filas localidad-familia"
              + (f", {sin_d} sin distrito" if sin_d else ""))
    return total


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
        CREATE TABLE ref_localidades (
            CORTE TEXT, CLAVE_ENTIDAD INTEGER, CLAVE_DISTRITO INTEGER,
            MUNICIPIO INTEGER, SECCION INTEGER, LOCALIDAD INTEGER,
            PADRON REAL, LISTA REAL, E_GRUPO TEXT,
            E_PADRON REAL, E_LISTA REAL
        );
        CREATE TABLE cat_entidades (
            CLAVE_ENTIDAD INTEGER PRIMARY KEY, NOMBRE_ENTIDAD TEXT
        );
        CREATE TABLE ref_manzanas (
            CORTE TEXT, CLAVE_ENTIDAD INTEGER, CLAVE_DISTRITO INTEGER,
            MUNICIPIO INTEGER, SECCION INTEGER, LOCALIDAD INTEGER, MANZANA INTEGER,
            PADRON INTEGER, LISTA INTEGER, CASILLA TEXT
        );
        CREATE TABLE ref_conformacion (
            CLAVE_ENTIDAD INTEGER, CLAVE_DISTRITO INTEGER, SECCION INTEGER,
            FAMILIA TEXT, N_CAS INTEGER, LOCALIDAD INTEGER, MANZANAS TEXT,
            INSTALA_LOC INTEGER, INSTALA_MZ TEXT, ORDEN INTEGER
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

    cortes_oficiales = integrar_corte_oficial(con_d)
    cortes_pef2024 = integrar_pef2024(con_d)

    entidades = pd.read_sql_query("""
        SELECT DISTINCT CLAVE_ENTIDAD, NOMBRE_ENTIDAD FROM cat_secciones ORDER BY 1
    """, con_o)
    entidades.to_sql("cat_entidades", con_d, if_exists="append", index=False)

    manzanas_filas = integrar_manzanas(con_d)
    conf_filas = integrar_conformacion(con_o, con_d)

    con_d.executescript("""
        CREATE INDEX ix_secciones ON ref_secciones (CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION);
        CREATE INDEX ix_padron ON ref_padron (CORTE, CLAVE_ENTIDAD, CLAVE_DISTRITO);
        CREATE INDEX ix_equiv ON ref_equivalencias (CLAVE_ENTIDAD, CLAVE_DISTRITO);
        CREATE INDEX ix_loc ON ref_localidades (CORTE, CLAVE_ENTIDAD, SECCION);
        CREATE INDEX ix_manzanas ON ref_manzanas (CORTE, CLAVE_ENTIDAD, SECCION);
        CREATE INDEX ix_conf ON ref_conformacion (CLAVE_ENTIDAD, SECCION);
    """)
    meta = {
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "cortes": ",".join(sorted({"-".join(t.split("_")[1:4]) for t in tablas})),
        "cortes_oficiales": ",".join(sorted(set(cortes_oficiales + cortes_pef2024))),
        "secciones": str(len(secciones)),
        "padron_filas": str(total_padron),
        "manzanas_filas": str(manzanas_filas),
        "conformacion_filas": str(conf_filas),
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
