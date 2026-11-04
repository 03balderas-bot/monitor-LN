"""Motor del diagnóstico de proyecciones externas de casillas.

Compara un archivo de proyección (una fila por casilla) contra la referencia
calculada con las actas de Senadores 2024, los catálogos y el reseccionamiento.
"""

import re
import sqlite3
import unicodedata
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

DB_PATH = "diagnostico.db"

COLUMNAS = ["Distrito", "Municipio", "Sección", "Localidad", "Cantidad Casilla",
            "Tipo de Casilla", "Lista Nominal", "Padron Electoral"]

_ALIAS = {
    "seccion": {"seccion", "secc", "sec", "numeroseccion"},
    "tipo": {"tipodecasilla", "tipocasilla", "tipo", "tipocas", "clasecasilla"},
    "distrito": {"distrito", "distritofederal", "dtto"},
    "municipio": {"municipio"},
    "localidad": {"localidad"},
    "cantidad": {"cantidadcasilla", "cantidad", "casilla", "numero", "numcasilla"},
    "ln": {"listanominal", "ln"},
    "padron": {"padronelectoral", "padron", "pe"},
}


def _db():
    return DB_PATH


def _sin_acentos(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto))
                   if not unicodedata.combining(c))


def _clave_columna(nombre):
    limpio = re.sub(r"[^a-z0-9]", "", _sin_acentos(nombre).lower())
    for canon, alias in _ALIAS.items():
        if limpio in alias:
            return canon
    return None


@st.cache_data(show_spinner=False)
def listar_cortes():
    con = sqlite3.connect(_db())
    df = pd.read_sql_query("SELECT DISTINCT CORTE FROM ref_padron ORDER BY CORTE DESC", con)
    con.close()
    return df["CORTE"].tolist()


@st.cache_data(show_spinner=False)
def catalogo_entidades():
    con = sqlite3.connect(_db())
    df = pd.read_sql_query(
        "SELECT CLAVE_ENTIDAD, NOMBRE_ENTIDAD FROM cat_entidades ORDER BY CLAVE_ENTIDAD", con
    )
    con.close()
    return {int(r.CLAVE_ENTIDAD): f"{int(r.CLAVE_ENTIDAD):02d} - {r.NOMBRE_ENTIDAD}"
            for r in df.itertuples()}


@st.cache_data(show_spinner=False)
def proyectar_referencia(entidad, distrito, corte):
    """Proyección de referencia: padrón del corte, B/C/E por regla de 750 y S fija."""
    con = sqlite3.connect(_db())
    cond_s, cond_p = [f"CLAVE_ENTIDAD = {int(entidad)}"], [f"CLAVE_ENTIDAD = {int(entidad)}"]
    if distrito is not None:
        cond_s.append(f"CLAVE_DISTRITO = {int(distrito)}")
        cond_p.append(f"CLAVE_DISTRITO = {int(distrito)}")
    secciones = pd.read_sql_query(
        f"SELECT * FROM ref_secciones WHERE {' AND '.join(cond_s)}", con
    )
    padron = pd.read_sql_query(
        f"""SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, PADRON_ELECTORAL, LISTA_NOMINAL
            FROM ref_padron WHERE CORTE = '{corte}' AND {' AND '.join(cond_p)}
              AND SECCION > 0""", con
    )
    eq = pd.read_sql_query(
        f"SELECT * FROM ref_equivalencias WHERE {' AND '.join(cond_s)}", con
    )
    con.close()

    matrices = set(pd.to_numeric(eq["SECCION_MATRIZ"], errors="coerce").dropna().astype(int))
    nuevas = set(pd.to_numeric(eq["SECCION_NUEVA"], errors="coerce").dropna().astype(int))

    pad_secc = padron.groupby("SECCION", as_index=False).agg(
        PADRON_ELECTORAL=("PADRON_ELECTORAL", "sum"),
        LISTA_NOMINAL=("LISTA_NOMINAL", "sum"),
        CLAVE_DISTRITO_P=("CLAVE_DISTRITO", "first"),
    )
    df = pad_secc.merge(secciones, on="SECCION", how="outer", suffixes=("", "_S"))
    numericas = ["PADRON_ELECTORAL", "LISTA_NOMINAL", "TOT_HIST", "B_HIST", "C_HIST",
                 "E_HIST", "S_HIST", "LN_ORD_24", "LN_E_24", "LN_2024", "TV_2024",
                 "NU_2024", "N_LOCALIDADES"]
    for c in numericas:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(float)
    df["SECCION"] = df["SECCION"].astype(int)
    if "CLAVE_DISTRITO" in df.columns:
        d24 = pd.to_numeric(df["CLAVE_DISTRITO"], errors="coerce").fillna(0)
    else:
        d24 = pd.Series(0.0, index=df.index)
    df["CLAVE_DISTRITO"] = d24.where(d24 > 0, df["CLAVE_DISTRITO_P"]).fillna(0).astype(int)
    df["TOT_HIST"] = df["B_HIST"] + df["C_HIST"] + df["E_HIST"] + df["S_HIST"]

    df["es_matriz"] = df["SECCION"].isin(matrices)
    df["tiene_padron"] = df["PADRON_ELECTORAL"] > 0
    df["sin_padron_proyectable"] = (~df["tiene_padron"]) & (~df["es_matriz"]) & (df["LN_2024"] > 0)

    pad26 = df["PADRON_ELECTORAL"].to_numpy(dtype=float)
    ln24 = df["LN_2024"].to_numpy(dtype=float)
    ln_e24 = df["LN_E_24"].to_numpy(dtype=float)
    proporcion_e = np.divide(ln_e24, ln24, out=np.zeros_like(ln24), where=ln24 > 0)
    pad_e26 = pad26 * proporcion_e
    pad_ord26 = np.clip(pad26 - pad_e26, 0, None)
    con_padron = pad26 >= 1

    df["B_2026"] = con_padron.astype(int)
    df["C_2026"] = np.maximum(
        np.where(con_padron, np.maximum(np.ceil(pad_ord26 / 750.0), 1), 0) - 1, 0
    ).astype(int)
    piso_e = np.ceil(np.divide(pad_e26, 750.0, out=np.zeros_like(pad_e26), where=pad_e26 > 0))
    df["E_2026"] = np.maximum(df["E_HIST"].to_numpy(dtype=int), piso_e).astype(int)
    df["S_2026"] = df["S_HIST"].to_numpy(dtype=int)
    df["PAD_E_2026"] = pad_e26
    df["PAD_ORD_2026"] = pad_ord26

    arrastre = df["sin_padron_proyectable"].to_numpy()
    for col_h, col_26 in [("B_HIST", "B_2026"), ("C_HIST", "C_2026"),
                          ("E_HIST", "E_2026"), ("S_HIST", "S_2026")]:
        df.loc[arrastre, col_26] = df.loc[arrastre, col_h]
    df.loc[df["es_matriz"], ["B_2026", "C_2026", "E_2026"]] = 0

    df["TOT_2026"] = df[["B_2026", "C_2026", "E_2026", "S_2026"]].sum(axis=1).astype(int)
    df["nuevas"] = df["SECCION"].isin(nuevas)
    return df


def leer_archivo(archivo):
    nombre = getattr(archivo, "name", str(archivo)).lower()
    if nombre.endswith((".xlsx", ".xls")):
        return pd.read_excel(archivo, sheet_name=0)
    if nombre.endswith(".csv"):
        for codificacion in ("utf-8-sig", "latin-1"):
            try:
                archivo.seek(0)
                return pd.read_csv(archivo, encoding=codificacion, sep=None, engine="python")
            except Exception:
                continue
    raise ValueError("Formato no soportado. Usa .xlsx, .xls o .csv.")


def normalizar_archivo(crudo):
    """Devuelve (casillas, secciones, avisos) a partir del archivo del usuario."""
    avisos = []
    mapa = {}
    for col in crudo.columns:
        canon = _clave_columna(col)
        if canon and canon not in mapa:
            mapa[canon] = col
    faltan = [c for c in ("seccion", "tipo") if c not in mapa]
    if faltan:
        raise ValueError(
            "Faltan columnas obligatorias: " +
            ", ".join("Sección" if c == "seccion" else "Tipo de Casilla" for c in faltan) + "."
        )

    df = pd.DataFrame()
    df["SECCION"] = pd.to_numeric(crudo[mapa["seccion"]], errors="coerce")
    tipo_txt = crudo[mapa["tipo"]].astype(str).str.strip().str.upper()
    df["TIPO_TEXTO"] = tipo_txt
    df["TIPO"] = tipo_txt.str[0]
    df["DISTRITO"] = (pd.to_numeric(crudo[mapa["distrito"]], errors="coerce")
                      if "distrito" in mapa else np.nan)
    df["MUNICIPIO"] = crudo[mapa["municipio"]] if "municipio" in mapa else np.nan
    df["LOCALIDAD"] = crudo[mapa["localidad"]] if "localidad" in mapa else np.nan
    df["CANTIDAD"] = (pd.to_numeric(crudo[mapa["cantidad"]], errors="coerce")
                      if "cantidad" in mapa else np.nan)
    df["LN"] = pd.to_numeric(crudo[mapa["ln"]], errors="coerce") if "ln" in mapa else np.nan
    df["PADRON"] = (pd.to_numeric(crudo[mapa["padron"]], errors="coerce")
                    if "padron" in mapa else np.nan)

    sin_seccion = int(df["SECCION"].isna().sum())
    if sin_seccion:
        avisos.append(f"{sin_seccion} renglón(es) sin sección (totales o notas al pie) se ignoraron.")
    df = df[df["SECCION"].notna()].copy()
    df["SECCION"] = df["SECCION"].astype(int)

    validos = (df["TIPO"].isin(list("BCES"))
               & df["TIPO_TEXTO"].str.match(r"^[BCES]\d*(C\d+)?$").fillna(False))
    invalidos = sorted(df.loc[~validos, "TIPO_TEXTO"].replace("", "(vacío)").unique().tolist())
    if invalidos:
        avisos.append(
            f"Se ignoraron {int((~validos).sum())} renglón(es) con tipo no reconocido: "
            + ", ".join(invalidos[:8]) + ("…" if len(invalidos) > 8 else "")
        )
    df = df[validos].copy()

    no_ambito = df["DISTRITO"].notna() & (df["DISTRITO"] > 0)
    if no_ambito.any():
        distritos = sorted(df.loc[no_ambito, "DISTRITO"].astype(int).unique().tolist())
        if len(distritos) > 1:
            avisos.append(f"El archivo mezcla distritos: {distritos}. Verifica el ámbito.")

    repetidos = df.groupby(["SECCION", "TIPO_TEXTO"]).size()
    repetidos = repetidos[repetidos > 1]
    if len(repetidos):
        avisos.append(
            f"{len(repetidos)} combinación(es) sección-tipo aparecen más de una vez "
            "(posibles casillas duplicadas)."
        )

    for col, etiqueta in [("LN", "Lista Nominal"), ("PADRON", "Padrón Electoral")]:
        excedidos = int((df[col] > 750).sum())
        if excedidos:
            avisos.append(f"{excedidos} renglón(es) con {etiqueta} mayor a 750 electores.")

    secciones = df.groupby("SECCION", as_index=False).agg(
        B_USU=("TIPO", lambda s: int((s == "B").sum())),
        C_USU=("TIPO", lambda s: int((s == "C").sum())),
        E_USU=("TIPO", lambda s: int((s == "E").sum())),
        S_USU=("TIPO", lambda s: int((s == "S").sum())),
        RENGLONES=("TIPO", "size"),
        PADRON_SUMA=("PADRON", lambda s: s.sum(min_count=1)),
        PADRON_MAX=("PADRON", "max"),
        LN_SUMA=("LN", lambda s: s.sum(min_count=1)),
        DISTRITO=("DISTRITO", "first"),
    )
    secciones["TOT_USU"] = secciones[["B_USU", "C_USU", "E_USU", "S_USU"]].sum(axis=1)
    return df, secciones, avisos


def detectar_corte(secciones, entidad, distrito, corte_sel):
    """Sugiere el corte de padrón más cercano al total del archivo."""
    if "PADRON_SUMA" not in secciones or secciones["PADRON_SUMA"].isna().all():
        return None
    lista = sorted(secciones["SECCION"].astype(int).tolist())
    con = sqlite3.connect(_db())
    cond = [f"CLAVE_ENTIDAD = {int(entidad)}", f"SECCION IN ({','.join(map(str, lista))})"]
    if distrito is not None:
        cond.append(f"CLAVE_DISTRITO = {int(distrito)}")
    totales = pd.read_sql_query(
        f"""SELECT CORTE, SUM(PADRON_ELECTORAL) AS TOTAL FROM ref_padron
            WHERE {' AND '.join(cond)} GROUP BY CORTE""", con
    )
    con.close()
    if totales.empty:
        return None
    totales["TOTAL"] = pd.to_numeric(totales["TOTAL"], errors="coerce").fillna(0)

    candidatos = []
    for forma, columna in (("suma", "PADRON_SUMA"), ("máximo", "PADRON_MAX")):
        total = float(secciones[columna].fillna(0).sum())
        dif = (totales["TOTAL"] - total).abs()
        idx = dif.idxmin()
        candidatos.append({
            "forma": forma,
            "total_archivo": total,
            "corte": totales.loc[idx, "CORTE"],
            "total_corte": float(totales.loc[idx, "TOTAL"]),
            "diferencia": float(totales.loc[idx, "TOTAL"] - total),
            "error_abs": float(dif.loc[idx]),
        })
    mejor = min(candidatos, key=lambda c: c["error_abs"])
    vigente = totales[totales["CORTE"] == corte_sel]
    mejor["total_vigente"] = float(vigente["TOTAL"].iloc[0]) if not vigente.empty else None
    mejor["diferencia_vigente"] = (
        mejor["total_vigente"] - mejor["total_archivo"] if mejor["total_vigente"] is not None else None
    )
    return mejor


def _casillas(n, ordinarias=False):
    n = int(n)
    if ordinarias:
        return "1 casilla ordinaria" if n == 1 else f"{n} casillas ordinarias"
    return "1 casilla" if n == 1 else f"{n} casillas"


def _texto_contiguas(ord_usu, ord_ref, ord_casillas_ref, ord_casillas_usu):
    if ord_usu is not None and not pd.isna(ord_usu):
        requeridas = max(int(np.ceil(ord_usu / 750.0)), 1) if ord_usu > 0 else 0
        verbo = "se justifica" if requeridas == 1 else "se justifican"
        texto = (f"Tu padrón ordinario es {ord_usu:,.0f}: {verbo} {_casillas(requeridas, True)} "
                 f"(B+C) e instalas {ord_casillas_usu}.")
        if ord_casillas_usu < requeridas:
            faltan_c = requeridas - ord_casillas_usu
            texto += (" Falta 1 casilla." if faltan_c == 1 else f" Faltan {faltan_c} casillas.")
        elif ord_casillas_usu > requeridas:
            faltan = (ord_casillas_usu - 1) * 750 + 1 - ord_usu
            texto += (f" Para sostener esa cantidad necesitas {(ord_casillas_usu - 1) * 750 + 1:,} "
                      f"electores; faltan {faltan:,.0f}.")
        texto += (f" La referencia usa {ord_ref:,.0f} electores "
                  f"({_casillas(ord_casillas_ref, True)}).")
        return texto
    if ord_ref > 0:
        return (f"La referencia usa {ord_ref:,.0f} electores ordinarios "
                f"({_casillas(ord_casillas_ref, True)} B+C).")
    return ""


def diagnosticar(crudo, entidad, distrito, corte):
    casillas, usu, avisos = normalizar_archivo(crudo)
    ref = proyectar_referencia(entidad, distrito, corte)
    matrices = set(ref.loc[ref["es_matriz"], "SECCION"].astype(int))
    nuevas = set(ref.loc[ref["nuevas"], "SECCION"].astype(int))

    m = ref.merge(usu, on="SECCION", how="outer", indicator=True)
    m["EN_REF"] = m["_merge"] != "right_only"
    m["EN_USU"] = m["_merge"] != "left_only"
    for c in ["B_USU", "C_USU", "E_USU", "S_USU", "TOT_USU", "RENGLONES"]:
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0).astype(int)
    for c in ["B_2026", "C_2026", "E_2026", "S_2026", "TOT_2026", "TOT_HIST"]:
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0).astype(int)
    for c in ["PADRON_ELECTORAL", "PAD_ORD_2026", "PAD_E_2026"]:
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0).astype(float)

    m["B_DIF"] = m["B_2026"] - m["B_USU"]
    m["C_DIF"] = m["C_2026"] - m["C_USU"]
    m["E_DIF"] = m["E_2026"] - m["E_USU"]
    m["S_DIF"] = m["S_2026"] - m["S_USU"]
    m["TOT_DIF"] = m["TOT_2026"] - m["TOT_USU"]

    filas = []
    for r in m.itertuples():
        seccion = int(r.SECCION)
        presente = bool(r.EN_USU)
        causa, detalle = None, ""

        if not bool(r.EN_REF):
            causa = "Sección ajena al ámbito"
            detalle = ("La sección no existe en la referencia del ámbito seleccionado "
                       "(otro distrito, otro estado o número inexistente).")
        elif seccion in matrices and r.TOT_USU > 0:
            causa = "Matriz extinta con casillas"
            detalle = (f"El reseccionamiento extinguió la sección matriz; sus casillas se "
                       f"trasladan a las secciones nuevas. Tu archivo instala {int(r.TOT_USU)}.")
        elif r.TOT_2026 > 0 and (not presente or r.TOT_USU == 0):
            if r.TOT_HIST == 0:
                causa = "Sección nueva faltante"
                detalle = (f"Sección del reseccionamiento con padrón {r.PADRON_ELECTORAL:,.0f} "
                           "y sin acta 2024; debe instalar 1 Básica.")
            else:
                causa = "Sección omitida"
                detalle = (f"La sección tenía {_casillas(r.TOT_HIST)} en 2024 y la referencia "
                           f"proyecta {int(r.TOT_2026)}; el archivo no la incluye.")
                if 0 < r.PADRON_ELECTORAL < 100:
                    detalle += (f" Su padrón es de solo {r.PADRON_ELECTORAL:,.0f} electores; "
                                "revisa si aplicaste un piso de 100.")
        elif r.S_DIF != 0:
            causa = "Especiales"
            etiqueta = "Especial" if int(r.S_HIST) == 1 else "Especiales"
            detalle = (f"2024 instaló {int(r.S_HIST)} {etiqueta}. No se calculan: deben "
                       f"copiarse tal cual. Tu archivo trae {int(r.S_USU)}.")
        elif r.E_DIF != 0:
            causa = "Extraordinarias"
            detalle = (f"2024 instaló {int(r.E_HIST)}; la parte rural del padrón requiere "
                       f"{int(np.ceil(r.PAD_E_2026 / 750.0))} por piso de 750. "
                       f"La referencia deja {int(r.E_2026)} y tu archivo {int(r.E_USU)}.")
            if r.E_USU > r.E_2026:
                detalle += " Revisa si separaste una E en dos por localidad."
        elif r.C_DIF != 0:
            causa = "Contiguas por umbral"
            ord_usu = None
            if r.PADRON_ELECTORAL and r.PADRON_SUMA and r.PADRON_SUMA > 0:
                proporcion = (r.PAD_E_2026 / r.PADRON_ELECTORAL) if r.PADRON_ELECTORAL > 0 else 0
                ord_usu = max(r.PADRON_SUMA * (1 - proporcion), 0)
            detalle = _texto_contiguas(ord_usu, r.PAD_ORD_2026,
                                       int(r.B_2026 + r.C_2026), int(r.B_USU + r.C_USU))
        elif r.B_DIF != 0:
            causa = "Básicas"
            detalle = (f"La referencia instala {int(r.B_2026)} Básicas (una por sección con "
                       f"padrón) y tu archivo {int(r.B_USU)}.")
        elif r.TOT_DIF != 0:
            causa = "Otras diferencias"
            detalle = "El total no coincide y no se identificó una causa específica."

        if causa:
            filas.append({
                "Sección": seccion,
                "Distrito": int(r.CLAVE_DISTRITO) if not pd.isna(r.CLAVE_DISTRITO) else None,
                "Causa": causa,
                "B ref": int(r.B_2026), "B archivo": int(r.B_USU),
                "C ref": int(r.C_2026), "C archivo": int(r.C_USU),
                "E ref": int(r.E_2026), "E archivo": int(r.E_USU),
                "S ref": int(r.S_2026), "S archivo": int(r.S_USU),
                "Total ref": int(r.TOT_2026), "Total archivo": int(r.TOT_USU),
                "Diferencia": int(r.TOT_DIF),
                "Padrón ref": round(r.PADRON_ELECTORAL),
                "Padrón archivo": round(r.PADRON_SUMA) if r.PADRON_SUMA == r.PADRON_SUMA else None,
                "Detalle": detalle,
            })

    detalle = pd.DataFrame(filas)
    if not detalle.empty:
        prioridad = ["Sección ajena al ámbito", "Matriz extinta con casillas",
                     "Sección nueva faltante", "Sección omitida", "Especiales",
                     "Extraordinarias", "Contiguas por umbral", "Básicas",
                     "Otras diferencias"]
        detalle["_p"] = detalle["Causa"].map({c: i for i, c in enumerate(prioridad)})
        detalle = detalle.sort_values(["_p", "Sección"]).drop(columns="_p").reset_index(drop=True)

    totales = pd.DataFrame([
        {"Tipo": "Básicas B", "Archivo": int(usu["B_USU"].sum()),
         "Referencia": int(m["B_2026"].sum())},
        {"Tipo": "Contiguas C", "Archivo": int(usu["C_USU"].sum()),
         "Referencia": int(m["C_2026"].sum())},
        {"Tipo": "Extraordinarias E", "Archivo": int(usu["E_USU"].sum()),
         "Referencia": int(m["E_2026"].sum())},
        {"Tipo": "Especiales S", "Archivo": int(usu["S_USU"].sum()),
         "Referencia": int(m["S_2026"].sum())},
    ])
    totales["Diferencia"] = totales["Referencia"] - totales["Archivo"]
    totales.loc[len(totales)] = {
        "Tipo": "Total", "Archivo": int(usu["TOT_USU"].sum()),
        "Referencia": int(m["TOT_2026"].sum()),
        "Diferencia": int(m["TOT_2026"].sum() - usu["TOT_USU"].sum()),
    }

    resumen = (detalle.groupby("Causa", as_index=False)
               .agg(Secciones=("Sección", "count"), Impacto=("Diferencia", "sum"))
               .rename(columns={"Impacto": "Impacto neto en casillas"})) if not detalle.empty else pd.DataFrame()

    corte_info = detectar_corte(usu, entidad, distrito, corte)
    return {
        "casillas": casillas,
        "secciones": usu,
        "detalle": detalle,
        "resumen": resumen,
        "totales": totales,
        "avisos": avisos,
        "corte": corte_info,
        "n_ref": int(len(ref)),
        "n_usu": int(len(usu)),
    }


CORTE_OFICIAL = "2026-09-30"


@st.cache_data(show_spinner=False)
def _localidades_oficial(entidad, distrito):
    cond = f"CLAVE_ENTIDAD = {int(entidad)}"
    if distrito is not None:
        cond += f" AND CLAVE_DISTRITO = {int(distrito)}"
    con = sqlite3.connect(_db())
    df = pd.read_sql_query(
        f"SELECT * FROM ref_localidades WHERE CORTE = '{CORTE_OFICIAL}' AND {cond}", con)
    con.close()
    for c in ("PADRON", "LISTA", "E_PADRON", "E_LISTA"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df


@st.cache_data(show_spinner=False)
def _datos_entidad(entidad):
    con = sqlite3.connect(_db())
    eq = pd.read_sql_query(
        "SELECT SECCION_MATRIZ, SECCION_NUEVA FROM ref_equivalencias "
        "WHERE CLAVE_ENTIDAD = ?", con, params=(int(entidad),))
    hist = pd.read_sql_query(
        "SELECT SECCION, S_HIST FROM ref_secciones "
        "WHERE CLAVE_ENTIDAD = ?", con, params=(int(entidad),))
    con.close()
    matrices = set(pd.to_numeric(eq["SECCION_MATRIZ"], errors="coerce").dropna().astype(int))
    nuevas = set(pd.to_numeric(eq["SECCION_NUEVA"], errors="coerce").dropna().astype(int))
    s_hist = {int(r.SECCION): int(r.S_HIST) for r in hist.itertuples()}
    mats_de = {}
    for r in eq.itertuples():
        mats_de.setdefault(int(r.SECCION_NUEVA), set()).add(int(r.SECCION_MATRIZ))
    return matrices, nuevas, s_hist, mats_de


@st.cache_data(show_spinner=False)
def _manzanas_oficial(entidad, distrito):
    """Padrón/LN 2026 por manzana con la marca de casilla 2024, del corte oficial."""
    cond = f"CLAVE_ENTIDAD = {int(entidad)}"
    if distrito is not None:
        cond += f" AND CLAVE_DISTRITO = {int(distrito)}"
    con = sqlite3.connect(_db())
    df = pd.read_sql_query(
        f"SELECT * FROM ref_manzanas WHERE CORTE = '{CORTE_OFICIAL}' AND {cond}", con)
    con.close()
    if df.empty:
        return df
    for c in ("MUNICIPIO", "LOCALIDAD", "MANZANA", "PADRON", "LISTA"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["MARCA"] = df["CASILLA"].fillna("").astype(str).str.strip()
    return df


@st.cache_data(show_spinner=False)
def _conformacion_oficial(entidad):
    """Reporte SUCyMEC PEF 2024 (base de la conformación): familia -> localidades
    y manzanas atendidas, y localidad/manzana de instalación."""
    con = sqlite3.connect(_db())
    try:
        df = pd.read_sql_query(
            "SELECT SECCION, FAMILIA, N_CAS, LOCALIDAD, MANZANAS, INSTALA_LOC, "
            "INSTALA_MZ, ORDEN FROM ref_conformacion WHERE CLAVE_ENTIDAD = ?",
            con, params=(int(entidad),))
    except sqlite3.OperationalError:
        df = pd.DataFrame(columns=["SECCION", "FAMILIA", "N_CAS", "LOCALIDAD",
                                   "MANZANAS", "INSTALA_LOC", "INSTALA_MZ", "ORDEN"])
    con.close()
    return df


def _row_instala(locs, inst_loc):
    if inst_loc is None:
        return None
    sel = locs[locs["LOCALIDAD"] == int(inst_loc)]
    return sel.iloc[0] if len(sel) else None


def _row_mayor_p(locs, mz_sec, asig_mz, fa):
    sub = mz_sec[[a == fa for a in asig_mz]]
    if sub.empty:
        return None
    loc = int(sub.groupby("LOCALIDAD")["PADRON"].sum().idxmax())
    sel = locs[locs["LOCALIDAD"] == loc]
    return sel.iloc[0] if len(sel) else None


def _asignar_familias(mz_df, filas_c):
    """Asigna cada manzana a una familia (B/E#): listas explícitas del reporte,
    marcas del estadístico, reclamos de localidad entera y, por omisión, B.
    Claves (MUNICIPIO, LOCALIDAD, MANZANA): la clave de localidad no es única
    entre municipios. Devuelve (asig, fam_p, fam_l, asig_mz, conflictos)."""
    muns_de = mz_df.groupby(["LOCALIDAD", "MANZANA"])["MUNICIPIO"] \
        .apply(lambda s: sorted(set(int(v) for v in s))).to_dict()

    def claves(loc, mz):
        return [(m, loc, mz) for m in muns_de.get((int(loc), int(mz)), ())]

    asig = {}
    for r2 in filas_c.itertuples(index=False):
        fa = str(r2.FAMILIA)
        if str(r2.MANZANAS or ""):
            for x in str(r2.MANZANAS).split(","):
                for k in claves(r2.LOCALIDAD, x):
                    asig[k] = fa
    for r2 in mz_df.itertuples(index=False):
        if not getattr(r2, "MARCA", ""):
            continue
        mfa = re.match(r"E\d+", r2.MARCA)
        fa = mfa.group(0) if mfa else "B"
        asig.setdefault((int(r2.MUNICIPIO), int(r2.LOCALIDAD), int(r2.MANZANA)), fa)
    mz_por_loc = mz_df.groupby("LOCALIDAD")["MANZANA"].apply(set).to_dict()
    claims = sorted(filas_c.itertuples(index=False),
                    key=lambda r2: (str(r2.FAMILIA) == "B", int(r2.ORDEN)))
    for r2 in claims:
        if str(r2.MANZANAS or ""):
            continue
        fa = str(r2.FAMILIA)
        for x in mz_por_loc.get(int(r2.LOCALIDAD), ()):
            for k in claves(r2.LOCALIDAD, x):
                asig.setdefault(k, fa)
    fam_p, fam_l, asig_mz, conflictos = {}, {}, [], 0
    for r2 in mz_df.itertuples(index=False):
        fa = asig.get((int(r2.MUNICIPIO), int(r2.LOCALIDAD), int(r2.MANZANA)), "B")
        asig_mz.append(fa)
        fam_p[fa] = fam_p.get(fa, 0) + int(r2.PADRON)
        fam_l[fa] = fam_l.get(fa, 0) + int(r2.LISTA)
    for r2 in filas_c.itertuples(index=False):
        if str(r2.MANZANAS or ""):
            fa = str(r2.FAMILIA)
            for x in str(r2.MANZANAS).split(","):
                for k in claves(r2.LOCALIDAD, x):
                    if k in asig and asig[k] != fa:
                        conflictos += 1
    return asig, fam_p, fam_l, asig_mz, conflictos


@st.cache_data(show_spinner=False)
def _universo_familias(entidad):
    """Padrón 2026 de cada familia E en todo el corte oficial: sirve para saber
    si una sección heredó la familia completa (aplica su N_CAS 2024) o solo
    una parte (solo el piso de 750)."""
    conf = _conformacion_oficial(entidad)
    if conf.empty:
        return {}
    mz = _manzanas_oficial(entidad, None)
    if mz.empty:
        return {}
    _, fam_p, _, _, _ = _asignar_familias(mz, conf)
    return {fa: p for fa, p in fam_p.items() if fa != "B"}


def _reparto(total, n):
    total = int(round(total))
    base = total // n
    rem = total - base * n
    return [base + rem] + [base] * (n - 1)


def _locs_txt(locs):
    vals = sorted({int(v) for v in locs})
    if not vals:
        return "—"
    txt = ", ".join(map(str, vals[:15]))
    return txt + ("…" if len(vals) > 15 else "")


@st.cache_data(show_spinner=False)
def _secciones_pef2024(entidad):
    con = sqlite3.connect(_db())
    df = pd.read_sql_query(
        "SELECT DISTINCT SECCION FROM ref_padron WHERE CORTE = '2024-06-02' "
        "AND CLAVE_ENTIDAD = ?", con, params=(int(entidad),))
    con.close()
    return set(int(s) for s in df["SECCION"])


def proyectar_conformacion(crudo, entidad, distrito=None):
    """Conformación 2026 a partir de una conformación PEF 2024 subida y el corte
    oficial. La asignación casilla-localidad-manzana sale del reporte SUCyMEC
    2024 (base, autoritativa) y el padrón/LN se suma manzana a manzana del
    corte oficial; en secciones sin reporte se usa el marcador del estadístico
    y, en su defecto, la proporción de LN del archivo. Reparto equitativo con
    el remanente en la primera casilla del grupo."""
    casillas, usu, avisos = normalizar_archivo(crudo)
    loc_of = _localidades_oficial(entidad, distrito)
    if loc_of.empty:
        raise ValueError(
            f"El corte oficial {CORTE_OFICIAL} aún no está integrado para esta entidad.")
    matrices, nuevas, s_hist, mats_de = _datos_entidad(entidad)
    conf = _conformacion_oficial(entidad)
    conf_secs = set(conf["SECCION"].astype(int)) if not conf.empty else set()
    mz_of = _manzanas_oficial(entidad, distrito)

    sec_of = (loc_of.groupby(["CLAVE_DISTRITO", "SECCION"], as_index=False)
              .agg(PADRON=("PADRON", "sum"), LISTA=("LISTA", "sum")))
    usu_idx = usu.set_index("SECCION")
    ln_e = casillas.loc[casillas["TIPO"] == "E"].groupby("SECCION")["LN"].sum()
    ln_t = casillas.groupby("SECCION")["LN"].sum()

    filas, cambios = [], []
    obs_padron, obs_umbral = [], []
    n_e_estimado = 0
    n_e_reporte = 0
    n_e_marcador = 0
    conflictos = 0
    set_usr = set(usu["SECCION"].astype(int))

    for r in sec_of.itertuples(index=False):
        sec = int(r.SECCION)
        dist = int(r.CLAVE_DISTRITO)
        total_p, total_l = float(r.PADRON), float(r.LISTA)
        if total_p <= 0:
            continue
        up = usu_idx.loc[sec] if sec in usu_idx.index else None
        up_e = int(up["E_USU"]) if up is not None else 0
        up_s = int(up["S_USU"]) if up is not None else 0
        up_tot = int(up["TOT_USU"]) if up is not None else 0

        locs = loc_of[loc_of["SECCION"] == sec].copy()
        claves_loc = [(int(m), int(l)) for m, l in zip(locs["MUNICIPIO"], locs["LOCALIDAD"])]
        mz_sec = mz_of[mz_of["SECCION"] == sec] if not mz_of.empty else None

        # grupos: [fila de instalación, padrón E, LN E, piso de casillas, localidades]
        grupos, cab, e_p, e_l = [], None, 0.0, 0.0
        loc_de_fa, ord_locs = {}, []
        if mz_sec is not None and not mz_sec.empty and conf_secs:
            if sec in conf_secs:
                cands = [sec]
            else:
                cands = [m for m in mats_de.get(sec, ()) if m in conf_secs]
        else:
            cands = []

        if cands:
            # --- Rama manzana a manzana: reporte SUCyMEC + corte oficial
            n_e_reporte += 1
            filas_c = conf[conf["SECCION"].isin(cands)]
            n24, inst, orden_fa = {}, {}, {}
            for r2 in filas_c.itertuples(index=False):
                fa = str(r2.FAMILIA)
                n24[fa] = max(n24.get(fa, 1), int(r2.N_CAS))
                orden_fa[fa] = min(orden_fa.get(fa, 10**6), int(r2.ORDEN))
                if r2.INSTALA_LOC is not None and fa not in inst:
                    inst[fa] = int(r2.INSTALA_LOC)
            asig, fam_p, fam_l, asig_mz, conf_c = _asignar_familias(mz_sec, filas_c)
            conflictos += conf_c
            for r2, fa in zip(mz_sec.itertuples(index=False), asig_mz):
                loc_de_fa.setdefault(fa, set()).add(int(r2.LOCALIDAD))
            e_fams = sorted((f for f in fam_p if f != "B"),
                            key=lambda f: orden_fa.get(f, 10**6))
            universo = _universo_familias(entidad)
            for fa in e_fams:
                completo = fam_p[fa] >= universo.get(fa, 0)
                row_g = _row_instala(locs, inst.get(fa))
                if row_g is None:
                    row_g = _row_mayor_p(locs, mz_sec, asig_mz, fa)
                grupos.append([row_g, float(fam_p[fa]), float(fam_l[fa]),
                               n24.get(fa, 0) if completo else 0,
                               _locs_txt(loc_de_fa.get(fa, ()))])
            e_p = sum(g[1] for g in grupos)
            e_l = sum(g[2] for g in grupos)
            ord_p, ord_l = float(fam_p.get("B", 0)), float(fam_l.get("B", 0))
            ord_locs = sorted(loc_de_fa.get("B", ()))
            cab = _row_instala(locs, inst.get("B"))
            if cab is None:
                cab = _row_mayor_p(locs, mz_sec, asig_mz, "B")
        else:
            # --- Rama localidad: marcador del estadístico / archivo
            e_partes, el_partes = {}, {}
            for _, lr in locs.iterrows():
                c = (int(lr["MUNICIPIO"]), int(lr["LOCALIDAD"]))
                if lr["E_GRUPO"] is None or pd.isna(lr["E_GRUPO"]):
                    e_partes[c], el_partes[c] = 0.0, 0.0
                elif lr["E_PADRON"] > 0:
                    e_partes[c] = float(lr["E_PADRON"])
                    el_partes[c] = float(lr["E_LISTA"])
                else:
                    e_partes[c] = float(lr["PADRON"])
                    el_partes[c] = float(lr["LISTA"])
            e_locs = locs[locs["E_GRUPO"].notna()]
            for _, g in e_locs.groupby("E_GRUPO"):
                g = g.sort_values(["PADRON", "LOCALIDAD"], ascending=[False, True])
                g_claves = [(int(m), int(l)) for m, l in zip(g["MUNICIPIO"], g["LOCALIDAD"])]
                grupos.append([g.iloc[0],
                               sum(e_partes[c] for c in g_claves),
                               sum(el_partes[c] for c in g_claves), 0,
                               _locs_txt(l for _, l in g_claves)])
            grupos.sort(key=lambda t: int(t[0]["LOCALIDAD"]))
            ord_locs = sorted(set(int(l) for l in locs.loc[locs["E_GRUPO"].isna(), "LOCALIDAD"]))
            if len(e_locs):
                n_e_marcador += 1
            locs["_ORD_P"] = [float(p) - e_partes[c] for p, c
                              in zip(locs["PADRON"], claves_loc)]
            e_p = sum(g[1] for g in grupos)
            e_l = sum(g[2] for g in grupos)
            ord_p = max(total_p - e_p, 0)
            ord_l = max(total_l - e_l, 0)
            cab = locs.sort_values(["_ORD_P", "PADRON", "LOCALIDAD"],
                                   ascending=[False, False, True]).iloc[0]

        if not grupos and up_e > 0:
            base = float(ln_t.get(sec, 0))
            prop = float(ln_e.get(sec, 0)) / base if base > 0 else 0.5
            e_p, e_l = round(total_p * prop), round(total_l * prop)
            ord_p, ord_l = max(total_p - e_p, 0), max(total_l - e_l, 0)
            n_e_estimado += 1

        for t in grupos:
            t[3] = max(t[3], int(np.ceil(t[1] / 750.0)))
            if t[1] > 0:
                t[3] = max(t[3], 1)
        n_e_base = sum(t[3] for t in grupos)
        n_e_piso = int(np.ceil(e_p / 750.0)) if e_p > 0 else 0
        n_e = max(n_e_base, n_e_piso, up_e)

        n_ord = max(int(np.ceil(ord_p / 750.0)), 1)
        s_n = max(up_s, s_hist.get(sec, 0))
        if cab is None:
            cab = locs.sort_values(["PADRON", "LOCALIDAD"],
                                   ascending=[False, True]).iloc[0]

        def fila(loc_row, cantidad, tipo, ln, padron):
            filas.append({
                "Distrito": dist,
                "Municipio": int(loc_row["MUNICIPIO"]),
                "Sección": sec,
                "Localidad": int(loc_row["LOCALIDAD"]),
                "Cantidad Casilla": int(cantidad),
                "Tipo de Casilla": tipo,
                "Lista Nominal": int(round(ln)),
                "Padron Electoral": int(round(padron)),
            })

        part_p, part_l = _reparto(ord_p, n_ord), _reparto(ord_l, n_ord)
        fila(cab, 1, "B", part_l[0], part_p[0])
        for i in range(1, n_ord):
            fila(cab, i + 1, f"C{i}", part_l[i], part_p[i])

        if ord_p > 0:
            falta = 750 * n_ord + 1 - int(round(ord_p))
            if 1 <= falta <= 10:
                obs_umbral.append({
                    "Sección": sec, "Distrito": dist, "Grupo": "Ordinaria B + C",
                    "Localidades": _locs_txt(ord_locs),
                    "Padrón": int(round(ord_p)), "Casillas": n_ord,
                    "Electores faltantes": falta, "Casillas al cruzar": n_ord + 1})

        if n_e > 0:
            if grupos:
                extras = n_e - n_e_base
                mayor = max(range(len(grupos)), key=lambda i: grupos[i][1])
                for k, (row_g, g_ep, g_el, floor_g, g_locs) in enumerate(grupos, start=1):
                    n_g = floor_g + (extras if k - 1 == mayor else 0)
                    gp, gl = _reparto(g_ep, n_g), _reparto(g_el, n_g)
                    fila(row_g, 1, f"E{k}", gl[0], gp[0])
                    for j in range(1, n_g):
                        fila(row_g, j + 1, f"E{k}C{j}", gl[j], gp[j])
                    if g_ep > 0 and n_g > 0:
                        falta = 750 * n_g + 1 - int(round(g_ep))
                        if 1 <= falta <= 10:
                            obs_umbral.append({
                                "Sección": sec, "Distrito": dist,
                                "Grupo": f"Extraordinaria E{k}",
                                "Localidades": g_locs,
                                "Padrón": int(round(g_ep)), "Casillas": n_g,
                                "Electores faltantes": falta,
                                "Casillas al cruzar": n_g + 1})
            else:
                gp, gl = _reparto(e_p, n_e), _reparto(e_l, n_e)
                fila(cab, 1, "E1", gl[0], gp[0])
                for j in range(1, n_e):
                    fila(cab, j + 1, f"E1C{j}", gl[j], gp[j])
                if e_p > 0:
                    falta = 750 * n_e + 1 - int(round(e_p))
                    if 1 <= falta <= 10:
                        obs_umbral.append({
                            "Sección": sec, "Distrito": dist,
                            "Grupo": "Extraordinaria E1 (estimada)",
                            "Localidades": "Reparto estimado por LN 2024",
                            "Padrón": int(round(e_p)), "Casillas": n_e,
                            "Electores faltantes": falta,
                            "Casillas al cruzar": n_e + 1})

        for k in range(1, s_n + 1):
            fila(cab, k, "S", 0, 0)

        tot_26 = n_ord + n_e + s_n
        if total_p < 110:
            obs_padron.append({
                "Sección": sec, "Distrito": dist,
                "Rango": "Menos de 100" if total_p < 100 else "100 a 110",
                "Padrón": int(round(total_p)), "LN": int(round(total_l)),
                "B+C": n_ord, "E": n_e, "Total": tot_26})
        if sec in nuevas or up is None:
            clase = "Nueva (reseccionamiento)" if sec in nuevas else "No incluida en tu archivo"
        elif tot_26 > up_tot:
            clase = "Creció"
        elif tot_26 < up_tot:
            clase = "Disminuyó"
        else:
            clase = "Sin cambio de total"
        cambios.append({
            "Sección": sec, "Distrito": dist, "Clasificación": clase,
            "B_2024": int(up["B_USU"]) if up is not None else 0,
            "C_2024": int(up["C_USU"]) if up is not None else 0,
            "E_2024": up_e, "S_2024": up_s, "Total_2024": up_tot,
            "B_2026": 1, "C_2026": n_ord - 1, "E_2026": n_e, "S_2026": s_n,
            "Total_2026": tot_26, "Diferencia": tot_26 - up_tot,
            "Padrón oficial": int(round(total_p)), "LN oficial": int(round(total_l)),
        })
        if up is not None and up_e != n_e:
            avisos.append(
                f"Sección {sec}: tu archivo trae {up_e} E y el corte oficial justifica "
                f"{n_e}; se deja en {n_e}.")

    en_oficial = set(sec_of["SECCION"].astype(int))
    for sec in sorted(set_usr - en_oficial):
        if distrito is not None:
            avisos.append(f"Sección {sec}: fuera del distrito seleccionado; se omite.")
        elif sec in matrices:
            avisos.append(f"Sección {sec}: matriz extinta por reseccionamiento; se excluye.")
        else:
            avisos.append(f"Sección {sec}: no existe en el corte oficial; se omite.")
    en_pef = _secciones_pef2024(entidad)
    novedad = sorted(s for s in en_oficial & set_usr
                     if s not in en_pef and s not in nuevas)
    if novedad:
        avisos.append(
            f"{len(novedad)} sección(es) de tu archivo no aparecen en el corte PEF 2024 "
            "(corroboración geográfica): " + ", ".join(map(str, novedad[:12]))
            + ("…" if len(novedad) > 12 else ""))
    if n_e_estimado:
        avisos.append(
            f"{n_e_estimado} sección(es) traen E en tu archivo pero sin reporte oficial "
            "ni marcas de manzana: su reparto E se estimó con la proporción de LN de 2024.")
    if conflictos:
        avisos.append(
            f"{conflictos} manzana(s) aparecen asignadas a más de una familia en el "
            "reporte oficial 2024; se usó la primera asignación encontrada.")
    if n_e_reporte or n_e_marcador:
        avisos.append(
            f"Grupos E: {n_e_reporte} sección(es) con el reporte oficial SUCyMEC 2024 "
            f"(manzana a manzana), {n_e_marcador} con el marcador del estadístico.")

    salida = pd.DataFrame(filas, columns=COLUMNAS)
    orden_tipo = {"B": 0, "C": 1, "E": 2, "S": 3}
    salida["_o"] = salida["Tipo de Casilla"].str[0].map(orden_tipo)
    salida = salida.sort_values(["Sección", "_o", "Cantidad Casilla"]).drop(columns="_o")
    salida = salida.reset_index(drop=True)

    t24 = {"B": int(usu["B_USU"].sum()), "C": int(usu["C_USU"].sum()),
           "E": int(usu["E_USU"].sum()), "S": int(usu["S_USU"].sum())}
    t26 = {"B": int((salida["Tipo de Casilla"] == "B").sum()),
           "C": int(salida["Tipo de Casilla"].str[0].eq("C").sum()),
           "E": int(salida["Tipo de Casilla"].str[0].eq("E").sum()),
           "S": int(salida["Tipo de Casilla"].str[0].eq("S").sum())}
    totales = pd.DataFrame([
        {"Tipo": f"Básicas B", "Tu archivo (2024)": t24["B"], "Conformación 2026": t26["B"]},
        {"Tipo": "Contiguas C", "Tu archivo (2024)": t24["C"], "Conformación 2026": t26["C"]},
        {"Tipo": "Extraordinarias E", "Tu archivo (2024)": t24["E"], "Conformación 2026": t26["E"]},
        {"Tipo": "Especiales S", "Tu archivo (2024)": t24["S"], "Conformación 2026": t26["S"]},
    ])
    totales["Diferencia"] = totales["Conformación 2026"] - totales["Tu archivo (2024)"]
    totales.loc[len(totales)] = {
        "Tipo": "Total", "Tu archivo (2024)": sum(t24.values()),
        "Conformación 2026": sum(t26.values()),
        "Diferencia": sum(t26.values()) - sum(t24.values())}

    cambios = pd.DataFrame(cambios)
    resumen = (cambios.groupby("Clasificación", as_index=False)
               .agg(Secciones=("Sección", "count"), Impacto=("Diferencia", "sum"))) \
        if not cambios.empty else pd.DataFrame()

    secciones_df = cambios[[
        "Sección", "Distrito", "Clasificación", "B_2024", "C_2024", "E_2024", "S_2024",
        "Total_2024", "B_2026", "C_2026", "E_2026", "S_2026", "Total_2026",
        "Diferencia", "Padrón oficial", "LN oficial"]].copy()

    obs_pad = pd.DataFrame(obs_padron, columns=[
        "Sección", "Distrito", "Rango", "Padrón", "LN", "B+C", "E", "Total"])
    obs_umb = pd.DataFrame(obs_umbral, columns=[
        "Sección", "Distrito", "Grupo", "Localidades", "Padrón", "Casillas",
        "Electores faltantes", "Casillas al cruzar"])
    if not obs_umb.empty:
        obs_umb = obs_umb.sort_values(["Sección", "Grupo"]).reset_index(drop=True)

    return {
        "salida": salida,
        "totales": totales,
        "resumen": resumen,
        "secciones": secciones_df,
        "avisos": avisos,
        "observaciones": {
            "bajo_100": obs_pad[obs_pad["Rango"] == "Menos de 100"].reset_index(drop=True),
            "critico": obs_pad[obs_pad["Rango"] == "100 a 110"].reset_index(drop=True),
            "umbrales": obs_umb,
        },
        "n_secciones": int(sec_of["SECCION"].nunique()),
    }


def conformacion_a_excel(res):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as w:
        res["salida"].to_excel(w, sheet_name="Conformación 2026", index=False)
        res["secciones"].to_excel(w, sheet_name="Resumen por sección", index=False)
    return buffer.getvalue()


_AZUL = colors.HexColor("#1f3864")
_GRIS = colors.HexColor("#64748B")
_BORDE = colors.HexColor("#CBD5E1")
_ZEBRA = colors.HexColor("#F1F5F9")
_ROJO = colors.HexColor("#B91C1C")


def _entero(v):
    try:
        if v is None or pd.isna(v):
            return "—"
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "—"


def _par(ref, usu):
    return f"{_entero(ref)}/{_entero(usu)}"


def generar_pdf(resultado, ambito, corte, nombre_archivo=None):
    """PDF detallado del diagnóstico: totales, causas y sección por sección."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(letter),
        leftMargin=26, rightMargin=26, topMargin=26, bottomMargin=30,
        title="Diagnóstico de proyección de casillas 2026",
        author="Monitor LN - DERFE",
    )
    base = getSampleStyleSheet()
    titulo = ParagraphStyle("Titulo", parent=base["Title"], fontName="Helvetica-Bold",
                            fontSize=15, leading=18, textColor=_AZUL, alignment=0,
                            spaceAfter=2)
    sub = ParagraphStyle("Sub", parent=base["Normal"], fontName="Helvetica", fontSize=8,
                         leading=10, textColor=_GRIS, spaceAfter=8)
    seccion = ParagraphStyle("Seccion", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=10.5, leading=13, textColor=_AZUL, spaceBefore=10,
                             spaceAfter=4)
    cuerpo = ParagraphStyle("Cuerpo", parent=base["Normal"], fontName="Helvetica", fontSize=7.8,
                            leading=10.2, textColor=colors.HexColor("#334155"), spaceAfter=4)
    aviso = ParagraphStyle("Aviso", parent=cuerpo, fontName="Helvetica-Oblique",
                           textColor=_ROJO)
    celda = ParagraphStyle("Celda", parent=base["Normal"], fontName="Helvetica", fontSize=6.7,
                           leading=8.4, textColor=colors.HexColor("#1E293B"))
    celda_c = ParagraphStyle("CeldaC", parent=celda, alignment=1)
    celda_b = ParagraphStyle("CeldaB", parent=celda, fontName="Helvetica-Bold")
    encabezado = ParagraphStyle("Enc", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=6.9, leading=8.4, textColor=colors.white,
                                alignment=1)

    story = [Paragraph("Diagnóstico de proyección de casillas 2026", titulo)]
    pie_sub = f"{ambito} &nbsp;|&nbsp; Corte de referencia: {corte}"
    if nombre_archivo:
        pie_sub += f" &nbsp;|&nbsp; Archivo: {escape(str(nombre_archivo))}"
    pie_sub += f" &nbsp;|&nbsp; Generado: {datetime.now():%d/%m/%Y %H:%M}"
    story.append(Paragraph(pie_sub, sub))

    totales = resultado["totales"]
    t_arch = int(totales.loc[totales["Tipo"] == "Total", "Archivo"].iloc[0])
    t_ref = int(totales.loc[totales["Tipo"] == "Total", "Referencia"].iloc[0])
    dif = t_ref - t_arch

    def _kpi(valor, etiqueta):
        return [Paragraph(f"<b>{valor}</b>", ParagraphStyle(
                    "k", parent=celda, fontSize=14, leading=16, alignment=1)),
                Paragraph(etiqueta, ParagraphStyle("kl", parent=celda_c,
                                                   textColor=_GRIS))]

    kpi = Table([[_kpi(f"{t_arch:,}", "Casillas en tu archivo"),
                  _kpi(f"{t_ref:,}", "Casillas de referencia"),
                  _kpi(f"{dif:+,}", "Diferencia (referencia − archivo)"),
                  _kpi(f"{resultado['n_ref']:,}", "Secciones comparadas")]],
                colWidths=[185, 185, 185, 185])
    kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEF2F7")),
        ("BOX", (0, 0), (-1, -1), 0.6, _BORDE),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi)

    info = resultado["corte"]
    if info and info.get("corte"):
        if info["corte"] != corte:
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                f"El padrón del archivo se parece más al corte <b>{info['corte']}</b> "
                f"({info['total_archivo']:,.0f} vs {info['total_corte']:,.0f} electores; "
                f"diferencia {info['diferencia']:+,.0f}). El corte seleccionado ({corte}) "
                f"difiere en {info['diferencia_vigente']:+,.0f} electores, lo que puede cambiar "
                "casillas en secciones cercanas a un umbral de 750.", cuerpo))
    for a in resultado["avisos"]:
        story.append(Paragraph(escape(a), aviso))

    story.append(Paragraph("1. Totales por tipo de casilla", seccion))
    filas = [[Paragraph(h, encabezado) for h in
              ["Tipo", "Archivo", "Referencia", "Diferencia"]]]
    for r in totales.itertuples(index=False):
        filas.append([Paragraph(r.Tipo, celda), Paragraph(_entero(r.Archivo), celda_c),
                      Paragraph(_entero(r.Referencia), celda_c),
                      Paragraph(f"{int(r.Diferencia):+,}", celda_c)])
    t1 = Table(filas, colWidths=[220, 90, 90, 90], repeatRows=1)
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _AZUL),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
        ("GRID", (0, 0), (-1, -1), 0.4, _BORDE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t1)

    resumen = resultado["resumen"]
    story.append(Paragraph("2. Resumen por causa", seccion))
    if resumen is None or resumen.empty:
        story.append(Paragraph("No se encontraron diferencias: la proyección coincide con "
                               "la referencia.", cuerpo))
    else:
        filas = [[Paragraph(h, encabezado) for h in
                  ["Causa", "Secciones", "Impacto neto en casillas"]]]
        for r in resumen.itertuples(index=False):
            filas.append([Paragraph(escape(str(r[0])), celda),
                          Paragraph(_entero(r[1]), celda_c),
                          Paragraph(f"{int(r[2]):+,}", celda_c)])
        t2 = Table(filas, colWidths=[260, 90, 140], repeatRows=1)
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _AZUL),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
            ("GRID", (0, 0), (-1, -1), 0.4, _BORDE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t2)

        detalle = resultado["detalle"]
        story.append(Paragraph("3. Detalle por sección", seccion))
        encabezados = ["Sección", "Dist.", "Causa", "B\nref/arch", "C\nref/arch",
                       "E\nref/arch", "S\nref/arch", "Total\nref/arch", "Dif.",
                       "Padrón\nref", "Padrón\narch", "Explicación"]
        filas = [[Paragraph(h.replace("\n", "<br/>"), encabezado) for h in encabezados]]
        for _, r in detalle.iterrows():
            difs = int(r["Diferencia"])
            filas.append([
                Paragraph(_entero(r["Sección"]), celda_b),
                Paragraph(_entero(r["Distrito"]), celda_c),
                Paragraph(escape(str(r["Causa"])), celda),
                Paragraph(_par(r["B ref"], r["B archivo"]), celda_c),
                Paragraph(_par(r["C ref"], r["C archivo"]), celda_c),
                Paragraph(_par(r["E ref"], r["E archivo"]), celda_c),
                Paragraph(_par(r["S ref"], r["S archivo"]), celda_c),
                Paragraph(_par(r["Total ref"], r["Total archivo"]), celda_c),
                Paragraph(f"{difs:+d}", ParagraphStyle("dif", parent=celda_c,
                                                       textColor=_ROJO if difs else celda.textColor,
                                                       fontName="Helvetica-Bold")),
                Paragraph(_entero(r["Padrón ref"]), celda_c),
                Paragraph(_entero(r["Padrón archivo"]), celda_c),
                Paragraph(escape(str(r["Detalle"])), celda),
            ])
        anchos = [40, 30, 88, 40, 40, 40, 40, 46, 30, 42, 44, 250]
        t3 = Table(filas, colWidths=anchos, repeatRows=1)
        t3.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _AZUL),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
            ("GRID", (0, 0), (-1, -1), 0.4, _BORDE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t3)

    story.append(Paragraph("Notas de cálculo de la referencia", seccion))
    story.append(Paragraph(
        "• <b>B:</b> una por sección con padrón (ID 01).<br/>"
        "• <b>C:</b> techo(padrón ordinario / 750) − 1. El padrón ordinario excluye la parte que "
        "en 2024 correspondió a casillas extraordinarias.<br/>"
        "• <b>E:</b> se conservan las de 2024; si la parte rural creció, se aplica el piso de 750 "
        "electores por casilla extraordinaria.<br/>"
        "• <b>S:</b> no se calculan; se copian de 2024 (1,000 boletas fijas y LN = 0).<br/>"
        "• <b>Matrices extintas:</b> cero casillas; sus electores pasan a las secciones nuevas.<br/>"
        "• <b>Casillas tipo A:</b> se excluyen de todos los cálculos.<br/>"
        "• La Lista Nominal no interviene en la proyección; solo se usa para el porcentaje de "
        "votación en la app principal.", cuerpo))

    def _pie(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(_GRIS)
        canvas.drawString(26, 16, "Diagnóstico de proyección de casillas 2026 — Monitor LN / DERFE")
        canvas.drawRightString(documento.pagesize[0] - 26, 16, f"Página {documento.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_pie, onLaterPages=_pie)
    return buffer.getvalue()


_NOTAS_CONFORMACION = (
    "• <b>Fuentes:</b> tu conformación PEF 2024 (archivo subido), reporte oficial SUCyMEC "
    "de casillas extraordinarias 2023-2024, marcas de casilla por manzana del estadístico "
    f"oficial al {CORTE_OFICIAL} y resultados de Senadores 2024.<br/>"
    "• <b>B y C:</b> el padrón ordinario (total menos la parte E) se divide entre "
    "techo(padrón ordinario / 750) casillas: una Básica y el resto Contiguas, con reparto "
    "equitativo y el remanente en la Básica.<br/>"
    "• <b>E:</b> se respetan las localidades atendidas por cada familia E del reporte "
    "oficial 2024; el número de casillas no baja de las instaladas en 2024 y crece con el "
    "piso de 750 electores. Si la E era a nivel sub-localidad y no hay marcas de manzana, "
    "la parte E se estima con la proporción de LN de Senadores 2024.<br/>"
    "• <b>S:</b> se copian de Senadores 2024 (no se calculan).<br/>"
    "• <b>Reseccionamiento:</b> las matrices extintas quedan excluidas; sus localidades "
    "aparecen en las secciones nuevas con la misma asignación E de su matriz.<br/>"
    "• <b>Lista Nominal:</b> se reparte en las mismas proporciones que el padrón; no "
    "interviene en el cálculo de casillas."
)


def generar_pdf_conformacion(res, ambito, nombre_archivo=None):
    """PDF de la conformación 2026: totales, cambios, detalle y lista de casillas."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(letter),
        leftMargin=26, rightMargin=26, topMargin=26, bottomMargin=30,
        title="Conformación de casillas 2026",
        author="Monitor LN - DERFE",
    )
    base = getSampleStyleSheet()
    titulo = ParagraphStyle("Titulo", parent=base["Title"], fontName="Helvetica-Bold",
                            fontSize=15, leading=18, textColor=_AZUL, alignment=0,
                            spaceAfter=2)
    sub = ParagraphStyle("Sub", parent=base["Normal"], fontName="Helvetica", fontSize=8,
                         leading=10, textColor=_GRIS, spaceAfter=8)
    seccion = ParagraphStyle("Seccion", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=10.5, leading=13, textColor=_AZUL, spaceBefore=10,
                             spaceAfter=4)
    cuerpo = ParagraphStyle("Cuerpo", parent=base["Normal"], fontName="Helvetica", fontSize=7.8,
                            leading=10.2, textColor=colors.HexColor("#334155"), spaceAfter=4)
    aviso = ParagraphStyle("Aviso", parent=cuerpo, fontName="Helvetica-Oblique",
                           textColor=_ROJO)
    celda = ParagraphStyle("Celda", parent=base["Normal"], fontName="Helvetica", fontSize=6.7,
                           leading=8.4, textColor=colors.HexColor("#1E293B"))
    celda_c = ParagraphStyle("CeldaC", parent=celda, alignment=1)
    celda_b = ParagraphStyle("CeldaB", parent=celda, fontName="Helvetica-Bold")
    encabezado = ParagraphStyle("Enc", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=6.9, leading=8.4, textColor=colors.white,
                                alignment=1)

    story = [Paragraph("Conformación de casillas 2026", titulo)]
    pie_sub = f"{ambito} &nbsp;|&nbsp; Corte oficial: {CORTE_OFICIAL}"
    if nombre_archivo:
        pie_sub += f" &nbsp;|&nbsp; Archivo: {escape(str(nombre_archivo))}"
    pie_sub += f" &nbsp;|&nbsp; Generado: {datetime.now():%d/%m/%Y %H:%M}"
    story.append(Paragraph(pie_sub, sub))

    totales = res["totales"]
    t24 = int(totales.loc[totales["Tipo"] == "Total", "Tu archivo (2024)"].iloc[0])
    t26 = int(totales.loc[totales["Tipo"] == "Total", "Conformación 2026"].iloc[0])

    def _kpi(valor, etiqueta):
        return [Paragraph(f"<b>{valor}</b>", ParagraphStyle(
                    "k", parent=celda, fontSize=14, leading=16, alignment=1)),
                Paragraph(etiqueta, ParagraphStyle("kl", parent=celda_c,
                                                   textColor=_GRIS))]

    kpi = Table([[_kpi(f"{t24:,}", "Casillas PEF 2024 (tu archivo)"),
                  _kpi(f"{t26:,}", "Casillas 2026 (proyección)"),
                  _kpi(f"{t26 - t24:+,}", "Diferencia"),
                  _kpi(f"{res['n_secciones']:,}", "Secciones")]],
                colWidths=[185, 185, 185, 185])
    kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEF2F7")),
        ("BOX", (0, 0), (-1, -1), 0.6, _BORDE),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi)
    for a in res["avisos"]:
        story.append(Paragraph(escape(a), aviso))

    def _tabla(filas, anchos):
        t = Table(filas, colWidths=anchos, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _AZUL),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
            ("GRID", (0, 0), (-1, -1), 0.4, _BORDE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    story.append(Paragraph("1. Totales por tipo de casilla", seccion))
    filas = [[Paragraph(h, encabezado) for h in
              ["Tipo", "PEF 2024 (tu archivo)", "Conformación 2026", "Diferencia"]]]
    for _, r in totales.iterrows():
        filas.append([Paragraph(r["Tipo"], celda),
                      Paragraph(_entero(r["Tu archivo (2024)"]), celda_c),
                      Paragraph(_entero(r["Conformación 2026"]), celda_c),
                      Paragraph(f"{int(r['Diferencia']):+,}", celda_c)])
    story.append(_tabla(filas, [220, 130, 130, 90]))

    resumen = res["resumen"]
    story.append(Paragraph("2. Resumen de cambios por sección", seccion))
    if resumen is None or resumen.empty:
        story.append(Paragraph("Sin cambios entre tu archivo y la proyección.", cuerpo))
    else:
        filas = [[Paragraph(h, encabezado) for h in
                  ["Clasificación", "Secciones", "Impacto neto en casillas"]]]
        for r in resumen.itertuples(index=False):
            filas.append([Paragraph(escape(str(r[0])), celda),
                          Paragraph(_entero(r[1]), celda_c),
                          Paragraph(f"{int(r[2]):+,}", celda_c)])
        story.append(_tabla(filas, [260, 90, 140]))

    obs = res.get("observaciones") or {}
    bajo = obs.get("bajo_100")
    critico = obs.get("critico")
    umbrales = obs.get("umbrales")
    subseccion = ParagraphStyle("SubSeccion", parent=celda, fontName="Helvetica-Bold",
                                fontSize=8.4, leading=10.2, textColor=_AZUL,
                                spaceBefore=7, spaceAfter=3)

    story.append(Paragraph("3. Secciones y casillas en observación", seccion))
    story.append(Paragraph(
        "Puntos a vigilar en los siguientes cortes. <b>Padrón bajo:</b> una sección con "
        "menos de 100 electores puede perder su casilla o cambiar de tipo con cualquier "
        "alta; el rango de 100 a 110 electores es crítico porque unos cuantos registros "
        "más la llevan al siguiente escalón de casillas. <b>Umbral de 750:</b> cada "
        "casilla atiende hasta 750 electores, de modo que un grupo a 10 electores o menos "
        "de ese límite requeriría una casilla adicional en el siguiente corte "
        "(741 electores = 1 casilla; 751 = 2 casillas).", cuerpo))

    story.append(Paragraph("3.1 Secciones con menos de 100 electores en padrón", subseccion))
    if bajo is None or bajo.empty:
        story.append(Paragraph("Ninguna sección del ámbito tiene menos de 100 electores.", cuerpo))
    else:
        filas = [[Paragraph(h, encabezado) for h in
                  ["Sección", "Distrito", "Padrón", "LN", "B+C", "E", "Total"]]]
        for _, r in bajo.iterrows():
            filas.append([
                Paragraph(_entero(r["Sección"]), celda_b),
                Paragraph(_entero(r["Distrito"]), celda_c),
                Paragraph(_entero(r["Padrón"]), celda_c),
                Paragraph(_entero(r["LN"]), celda_c),
                Paragraph(_entero(r["B+C"]), celda_c),
                Paragraph(_entero(r["E"]), celda_c),
                Paragraph(_entero(r["Total"]), celda_c),
            ])
        story.append(_tabla(filas, [70, 60, 80, 80, 60, 60, 60]))

    story.append(Paragraph("3.2 Secciones en rango crítico (100 a 110 electores)", subseccion))
    if critico is None or critico.empty:
        story.append(Paragraph("Ninguna sección del ámbito tiene entre 100 y 110 electores.",
                               cuerpo))
    else:
        filas = [[Paragraph(h, encabezado) for h in
                  ["Sección", "Distrito", "Padrón", "LN", "B+C", "E", "Total"]]]
        for _, r in critico.iterrows():
            filas.append([
                Paragraph(_entero(r["Sección"]), celda_b),
                Paragraph(_entero(r["Distrito"]), celda_c),
                Paragraph(_entero(r["Padrón"]), celda_c),
                Paragraph(_entero(r["LN"]), celda_c),
                Paragraph(_entero(r["B+C"]), celda_c),
                Paragraph(_entero(r["E"]), celda_c),
                Paragraph(_entero(r["Total"]), celda_c),
            ])
        story.append(_tabla(filas, [70, 60, 80, 80, 60, 60, 60]))

    story.append(Paragraph("3.3 Grupos de casillas a 10 electores o menos del siguiente umbral",
                           subseccion))
    if umbrales is None or umbrales.empty:
        story.append(Paragraph(
            "Ningún grupo de casillas del ámbito está a 10 electores o menos de requerir "
            "una casilla adicional.", cuerpo))
    else:
        filas = [[Paragraph(h.replace("\n", "<br/>"), encabezado) for h in
                  ["Sección", "Distrito", "Grupo", "Localidades", "Padrón",
                   "Casillas\n2026", "Electores\nfaltantes", "Casillas al\ncruzar"]]]
        for _, r in umbrales.iterrows():
            filas.append([
                Paragraph(_entero(r["Sección"]), celda_b),
                Paragraph(_entero(r["Distrito"]), celda_c),
                Paragraph(escape(str(r["Grupo"])), celda),
                Paragraph(escape(str(r["Localidades"])), celda),
                Paragraph(_entero(r["Padrón"]), celda_c),
                Paragraph(_entero(r["Casillas"]), celda_c),
                Paragraph(f"+{int(r['Electores faltantes'])}", ParagraphStyle(
                    "falta", parent=celda_c, textColor=_ROJO, fontName="Helvetica-Bold")),
                Paragraph(_entero(r["Casillas al cruzar"]), celda_c),
            ])
        story.append(_tabla(filas, [50, 38, 118, 250, 56, 52, 58, 56]))
        story.append(Paragraph(
            "Localidades: claves de localidad que integran cada grupo; en la casilla "
            "ordinaria son las localidades con padrón B/C y en la extraordinaria las que "
            "atiende esa familia E.", cuerpo))

    detalle = res["secciones"]
    story.append(Paragraph("4. Detalle por sección (solo las que cambian o son nuevas)",
                           seccion))
    encabezados = ["Sección", "Dist.", "Clasificación",
                   "B\n24", "C\n24", "E\n24", "S\n24", "Tot\n24",
                   "B\n26", "C\n26", "E\n26", "S\n26", "Tot\n26", "Dif.",
                   "Padrón\noficial", "LN\noficial"]
    cambian = detalle[detalle["Diferencia"] != 0]
    filas = [[Paragraph(h.replace("\n", "<br/>"), encabezado) for h in encabezados]]
    for _, r in cambian.iterrows():
        difs = int(r["Diferencia"])
        filas.append([
            Paragraph(_entero(r["Sección"]), celda_b),
            Paragraph(_entero(r["Distrito"]), celda_c),
            Paragraph(escape(str(r["Clasificación"])), celda),
            Paragraph(_entero(r["B_2024"]), celda_c),
            Paragraph(_entero(r["C_2024"]), celda_c),
            Paragraph(_entero(r["E_2024"]), celda_c),
            Paragraph(_entero(r["S_2024"]), celda_c),
            Paragraph(_entero(r["Total_2024"]), celda_c),
            Paragraph(_entero(r["B_2026"]), celda_c),
            Paragraph(_entero(r["C_2026"]), celda_c),
            Paragraph(_entero(r["E_2026"]), celda_c),
            Paragraph(_entero(r["S_2026"]), celda_c),
            Paragraph(_entero(r["Total_2026"]), celda_c),
            Paragraph(f"{difs:+d}", ParagraphStyle("dif", parent=celda_c,
                                                   textColor=_ROJO if difs else celda.textColor,
                                                   fontName="Helvetica-Bold")),
            Paragraph(_entero(r["Padrón oficial"]), celda_c),
            Paragraph(_entero(r["LN oficial"]), celda_c),
        ])
    anchos = [42, 28, 118, 26, 26, 26, 26, 32, 26, 26, 26, 26, 32, 30, 44, 40]
    if len(filas) > 1:
        story.append(_tabla(filas, anchos))
    else:
        story.append(Paragraph("Ninguna sección cambia de total.", cuerpo))

    story.append(Paragraph("5. Conformación 2026 (lista de casillas)", seccion))
    salida = res["salida"]
    encabezados = ["Distrito", "Municipio", "Sección", "Localidad",
                   "Cantidad\nCasilla", "Tipo de\nCasilla", "Lista\nNominal",
                   "Padrón\nElectoral"]
    filas = [[Paragraph(h.replace("\n", "<br/>"), encabezado) for h in encabezados]]
    for _, r in salida.iterrows():
        filas.append([
            Paragraph(_entero(r["Distrito"]), celda_c),
            Paragraph(_entero(r["Municipio"]), celda_c),
            Paragraph(_entero(r["Sección"]), celda_b),
            Paragraph(_entero(r["Localidad"]), celda_c),
            Paragraph(_entero(r["Cantidad Casilla"]), celda_c),
            Paragraph(escape(str(r["Tipo de Casilla"])), celda_c),
            Paragraph(_entero(r["Lista Nominal"]), celda_c),
            Paragraph(_entero(r["Padron Electoral"]), celda_c),
        ])
    story.append(_tabla(filas, [40, 52, 46, 52, 48, 46, 60, 64]))

    story.append(Paragraph("Notas de cálculo", seccion))
    story.append(Paragraph(_NOTAS_CONFORMACION, cuerpo))

    def _pie(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(_GRIS)
        canvas.drawString(26, 16, "Conformación de casillas 2026 — Monitor LN / DERFE")
        canvas.drawRightString(documento.pagesize[0] - 26, 16, f"Página {documento.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_pie, onLaterPages=_pie)
    return buffer.getvalue()
