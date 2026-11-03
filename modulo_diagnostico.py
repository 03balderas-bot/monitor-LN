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
