from datetime import datetime
from io import BytesIO
from pathlib import Path
import sqlite3
import unicodedata
import matplotlib.pyplot as plt
import pandas as pd
import py7zr
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
import streamlit as st
import streamlit.components.v1 as components

# ==============================================================================
# EXTRACCIÓN AUTOMÁTICA Y SEGURA DE LA BASE DE DATOS (.7Z)
# ==============================================================================
DIR_RAIZ = Path(__file__).resolve().parent
DB_PATH = DIR_RAIZ / "derfe_web.db"
ARCHIVE_7Z_PATH = DIR_RAIZ / "derfe_web.7z"
LOGO_PATH = DIR_RAIZ / "logo_ine.png"

if not DB_PATH.exists() and ARCHIVE_7Z_PATH.exists():
  try:
    with py7zr.SevenZipFile(ARCHIVE_7Z_PATH, mode="r") as z:
      z.extractall(path=DIR_RAIZ)
  except Exception as e:
    st.error(f"Error al descomprimir derfe_web.7z: {e}")

# ==============================================================================
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# ==============================================================================
st.set_page_config(
    page_title="Monitor DERFE | Histórico Municipal/Distrital",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="auto",
)

# BLINDAJE DE IDIOMA Y SUPRESIÓN DE TRADUCCIÓN AUTOMÁTICA
components.html(
    """
<script>
    const root = window.parent.document.documentElement;
    root.setAttribute('lang', 'es');
    root.setAttribute('xml:lang', 'es');
    root.setAttribute('translate', 'no');
    root.classList.add('notranslate');

    let metaGoogle = window.parent.document.querySelector('meta[name="google"]');
    if (!metaGoogle) {
        metaGoogle = window.parent.document.createElement('meta');
        metaGoogle.name = 'google';
        metaGoogle.content = 'notranslate';
        window.parent.document.getElementsByTagName('head')[0].appendChild(metaGoogle);
    }
</script>
""",
    height=0,
    width=0,
)


@st.cache_resource
def get_conn():
  if not DB_PATH.exists():
    st.error(
        f"⚠️ Base de datos no encontrada en: {DB_PATH}. Asegúrate de que"
        " 'derfe_web.7z' esté cargado en el repositorio."
    )
    st.stop()
  return sqlite3.connect(str(DB_PATH), check_same_thread=False)


conn = get_conn()

st.markdown(
    """
<style>
    html, body, [class*="css"] {
        translate: no !important;
    }
    .main-title { font-size: 1.55rem !important; font-weight: 800; margin-bottom: 0.1rem; line-height: 1.2; }
    .sub-title { color: #8A99AD; font-size: 0.88rem !important; margin-bottom: 0.5rem; }
    .footer-fuente { font-size: 0.78rem !important; color: #64748B; margin-top: 1.5rem; margin-bottom: 1rem; border-top: 1px solid #334155; padding-top: 0.5rem; }
    [data-testid="stMetricValue"] { font-size: 1.25rem !important; font-weight: 700; }
    [data-testid="stMetricLabel"] { font-size: 0.78rem !important; white-space: normal !important; }
</style>
""",
    unsafe_allow_html=True,
)

CATALOGO_ENTIDADES = {
    1: "AGUASCALIENTES",
    2: "BAJA CALIFORNIA",
    3: "BAJA CALIFORNIA SUR",
    4: "CAMPECHE",
    5: "COAHUILA",
    6: "COLIMA",
    7: "CHIAPAS",
    8: "CHIHUAHUA",
    9: "CIUDAD DE MÉXICO",
    10: "DURANGO",
    11: "GUANAJUATO",
    12: "GUERRERO",
    13: "HIDALGO",
    14: "JALISCO",
    15: "MÉXICO",
    16: "MICHOACÁN",
    17: "MORELOS",
    18: "NAYARIT",
    19: "NUEVO LEÓN",
    20: "OAXACA",
    21: "PUEBLA",
    22: "QUERÉTARO",
    23: "QUINTANA ROO",
    24: "SAN LUIS POTOSÍ",
    25: "SINALOA",
    26: "SONORA",
    27: "TABASCO",
    28: "TAMAULIPAS",
    29: "TLAXCALA",
    30: "VERACRUZ",
    31: "YUCATÁN",
    32: "ZACATECAS",
}


# ==============================================================================
# MOTOR DE NORMALIZACIÓN Y DETECCIÓN FLEXIBLE DE COLUMNAS
# ==============================================================================
def normalizar_txt(s):
  if not isinstance(s, str):
    return ""
  norm = "".join(
      c
      for c in unicodedata.normalize("NFD", s.upper())
      if unicodedata.category(c) != "Mn"
  )
  return norm.replace(" ", "_").replace(".", "").replace("\n", "_")


def col_exacta(tabla, kws_primary, kws_fallback=None):
  try:
    cols_db = pd.read_sql_query(f"PRAGMA table_info({tabla});", conn)[
        "name"
    ].tolist()
    for c in cols_db:
      c_norm = normalizar_txt(c)
      if all(k in c_norm for k in kws_primary):
        return f'"{c}"'
    if kws_fallback:
      for c in cols_db:
        c_norm = normalizar_txt(c)
        if all(k in c_norm for k in kws_fallback):
          return f'"{c}"'
  except Exception:
    pass
  return "0"


def formatear_corte(corte_val) -> str:
  c = str(corte_val).strip()
  c_up = c.upper()
  if "PJF" in c_up or "JUDICIAL" in c_up or c_up == "PEE_PJF_2025":
    return "PEE PJF 2025 (Elección Judicial)"
  elif "PEF" in c_up or "FEDERAL" in c_up or c_up == "PEF_2024":
    return "PEF 2024 (Elección Federal)"
  elif len(c) == 8 and c.isdigit():
    return f"{c[6:8]}/{c[4:6]}/{c[:4]}"
  return c


def calc_var_str(delta, base):
  if base > 0:
    return f"{delta:+,.0f} ({delta / base * 100:+.2f}%)"
  elif delta > 0:
    return f"{delta:+,.0f} (Nuevo)"
  else:
    return f"{delta:+,.0f} (0.00%)"


def obtener_cortes_ordenados():
  try:
    tables_db = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table'", conn
    )["name"].tolist()
    tabla_fechas = (
        "PE_SEX"
        if "PE_SEX" in tables_db
        else ("PE_EO" if "PE_EO" in tables_db else None)
    )
    if not tabla_fechas:
      return []

    df = pd.read_sql_query(
        f"SELECT DISTINCT FECHA_CORTE FROM {tabla_fechas}", conn
    )
    lista = [str(x) for x in df["FECHA_CORTE"].tolist()]

    def key_orden(val):
      if val.isdigit() and len(val) == 8:
        return (0, int(val))
      return (1, val)

    lista.sort(key=key_orden, reverse=True)
    return lista
  except Exception:
    return []


# ==============================================================================
# CONSULTA GLOBAL CON CLÁUSULA WHERE UNIFICADA
# ==============================================================================
def consultar_datos_agregados_seguro(corte, condicion_where):
  try:
    c_hp = col_exacta("PE_SEX", ["HOMBRE", "PADRON"], ["HOMBRE", "PAD"])
    c_hl = col_exacta("PE_SEX", ["HOMBRE", "LISTA"], ["HOMBRE", "LIS"])
    c_mp = col_exacta("PE_SEX", ["MUJER", "PADRON"], ["MUJER", "PAD"])
    c_ml = col_exacta("PE_SEX", ["MUJER", "LISTA"], ["MUJER", "LIS"])
    c_nbp = col_exacta("PE_SEX", ["BINARIO", "PADRON"], ["NB", "PAD"])
    c_nbl = col_exacta("PE_SEX", ["BINARIO", "LISTA"], ["NB", "LIS"])

    q_sex = f"""
            SELECT 
                COALESCE(SUM(CAST({c_hp} AS REAL)), 0) AS h_padron,
                COALESCE(SUM(CAST({c_hl} AS REAL)), 0) AS h_lista,
                COALESCE(SUM(CAST({c_mp} AS REAL)), 0) AS m_padron,
                COALESCE(SUM(CAST({c_ml} AS REAL)), 0) AS m_lista,
                COALESCE(SUM(CAST({c_nbp} AS REAL)), 0) AS nb_padron,
                COALESCE(SUM(CAST({c_nbl} AS REAL)), 0) AS nb_lista
            FROM PE_SEX
            WHERE TRIM(FECHA_CORTE) = TRIM('{corte}') {condicion_where}
        """
    df_sex = pd.read_sql_query(q_sex, conn)

    c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
    c_lnat = col_exacta("PE_EO", ["LISTA", "NATIVO"], ["LNE", "NATIVO"])
    c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
    c_lfor = col_exacta("PE_EO", ["LISTA", "FORANEO"], ["LNE", "FORANEO"])
    c_p87 = col_exacta(
        "PE_EO",
        ["PADRON", "HIJO"],
        ["PADRON", "MEXICANO"],
    )
    c_l87 = col_exacta("PE_EO", ["LISTA", "HIJO"], ["LNE", "HIJO"])
    c_p88 = col_exacta(
        "PE_EO", ["PADRON", "NATURALIZADO"], ["PADRON", "88"]
    )
    c_l88 = col_exacta(
        "PE_EO", ["LISTA", "NATURALIZADO"], ["LNE", "NATURALIZADO"]
    )

    q_eo = f"""
            SELECT 
                COALESCE(SUM(CAST({c_pnat} AS REAL)), 0) AS p_nat, COALESCE(SUM(CAST({c_lnat} AS REAL)), 0) AS l_nat,
                COALESCE(SUM(CAST({c_pfor} AS REAL)), 0) AS p_for, COALESCE(SUM(CAST({c_lfor} AS REAL)), 0) AS l_for,
                COALESCE(SUM(CAST({c_p87} AS REAL)), 0) AS p_87, COALESCE(SUM(CAST({c_l87} AS REAL)), 0) AS l_87,
                COALESCE(SUM(CAST({c_p88} AS REAL)), 0) AS p_88, COALESCE(SUM(CAST({c_l88} AS REAL)), 0) AS l_88
            FROM PE_EO
            WHERE TRIM(FECHA_CORTE) = TRIM('{corte}') {condicion_where}
        """
    df_eo = pd.read_sql_query(q_eo, conn)

    h_p = int(df_sex["h_padron"].iloc[0]) if not df_sex.empty else 0
    m_p = int(df_sex["m_padron"].iloc[0]) if not df_sex.empty else 0
    nb_p = int(df_sex["nb_padron"].iloc[0]) if not df_sex.empty else 0

    h_l = int(df_sex["h_lista"].iloc[0]) if not df_sex.empty else 0
    m_l = int(df_sex["m_lista"].iloc[0]) if not df_sex.empty else 0
    nb_l = int(df_sex["nb_lista"].iloc[0]) if not df_sex.empty else 0

    pad_sex_total = h_p + m_p + nb_p

    p_n = int(df_eo["p_nat"].iloc[0]) if not df_eo.empty else 0
    p_f = int(df_eo["p_for"].iloc[0]) if not df_eo.empty else 0
    p_7 = int(df_eo["p_87"].iloc[0]) if not df_eo.empty else 0
    p_8 = int(df_eo["p_88"].iloc[0]) if not df_eo.empty else 0
    pad_eo_total = p_n + p_f + p_7 + p_8

    lis_sex_total = h_l + m_l + nb_l

    l_n = int(df_eo["l_nat"].iloc[0]) if not df_eo.empty else 0
    l_f = int(df_eo["l_for"].iloc[0]) if not df_eo.empty else 0
    l_7 = int(df_eo["l_87"].iloc[0]) if not df_eo.empty else 0
    l_8 = int(df_eo["l_88"].iloc[0]) if not df_eo.empty else 0
    lis_eo_total = l_n + l_f + l_7 + l_8

    pad_final = max(pad_sex_total, pad_eo_total)
    lis_final = max(lis_sex_total, lis_eo_total)

    return pd.DataFrame([{
        "padron": pad_final,
        "lista": lis_final,
        "h_padron": h_p,
        "h_lista": h_l,
        "m_padron": m_p,
        "m_lista": m_l,
        "nb_padron": nb_p,
        "nb_lista": nb_l,
        "p_nat": p_n,
        "l_nat": l_n,
        "p_for": p_f,
        "l_for": l_f,
        "p_87": p_7,
        "l_87": l_7,
        "p_88": p_8,
        "l_88": l_8,
    }])
  except Exception:
    return pd.DataFrame([{
        "padron": 0,
        "lista": 0,
        "h_padron": 0,
        "h_lista": 0,
        "m_padron": 0,
        "m_lista": 0,
        "nb_padron": 0,
        "nb_lista": 0,
        "p_nat": 0,
        "l_nat": 0,
        "p_for": 0,
        "l_for": 0,
        "p_87": 0,
        "l_87": 0,
        "p_88": 0,
        "l_88": 0,
    }])


# ==============================================================================
# GENERACIÓN DE GRÁFICAS Y ANÁLISIS DISTRITAL
# ==============================================================================
def generar_grafico_top_jovenes(corte):
  try:
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table'", conn
    )["name"].tolist()
    if "PE_RE" in tables:
      q = f"""
                SELECT CLAVE_ENTIDAD, 
                       (SUM(CAST("PE_JOVENES_18_19" AS REAL)) * 100.0 / 
                        NULLIF((SELECT SUM(CAST("PADRON_ELECTORAL" AS REAL)) FROM PE_SEX S WHERE TRIM(S.FECHA_CORTE) = TRIM(PE_RE.FECHA_CORTE) AND S.CLAVE_ENTIDAD = PE_RE.CLAVE_ENTIDAD), 0)) AS pct_jovenes
                FROM PE_RE
                WHERE TRIM(FECHA_CORTE) = TRIM(?)
                GROUP BY CLAVE_ENTIDAD
                ORDER BY pct_jovenes DESC
                LIMIT 5
            """
      df = pd.read_sql_query(q, conn, params=[corte])
      if not df.empty and df["pct_jovenes"].sum() > 0:
        df = df.sort_values(by="pct_jovenes", ascending=True)
        df["ENTIDAD"] = df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        plt.figure(figsize=(6.5, 2.1))
        plt.barh(df["ENTIDAD"], df["pct_jovenes"], color="#10B981")
        plt.title(
            f"Top 5 Entidades: Mayor % de Jóvenes (18-19 años) -"
            f" {formatear_corte(corte)}",
            fontsize=9,
            fontweight="bold",
            color="#4A2E7A",
        )
        plt.xlabel("Porcentaje respecto al Padrón Estatal (%)", fontsize=7.5)
        plt.xticks(fontsize=7.5)
        plt.yticks(fontsize=8)
        plt.tight_layout()
        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=200)
        plt.close()
        buf.seek(0)
        return buf
  except Exception:
    pass
  return None


def generar_grafico_top_mayores(corte):
  try:
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table'", conn
    )["name"].tolist()
    if "PE_RE" in tables:
      q = f"""
                SELECT CLAVE_ENTIDAD, 
                       (SUM(CAST("PE_MAS_DE_65" AS REAL)) * 100.0 / 
                        NULLIF((SELECT SUM(CAST("PADRON_ELECTORAL" AS REAL)) FROM PE_SEX S WHERE TRIM(S.FECHA_CORTE) = TRIM(PE_RE.FECHA_CORTE) AND S.CLAVE_ENTIDAD = PE_RE.CLAVE_ENTIDAD), 0)) AS pct_mayores
                FROM PE_RE
                WHERE TRIM(FECHA_CORTE) = TRIM(?)
                GROUP BY CLAVE_ENTIDAD
                ORDER BY pct_mayores DESC
                LIMIT 5
            """
      df = pd.read_sql_query(q, conn, params=[corte])
      if not df.empty and df["pct_mayores"].sum() > 0:
        df = df.sort_values(by="pct_mayores", ascending=True)
        df["ENTIDAD"] = df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        plt.figure(figsize=(6.5, 2.1))
        plt.barh(df["ENTIDAD"], df["pct_mayores"], color="#F59E0B")
        plt.title(
            f"Top 5 Entidades: Mayor % de Adultos Mayores (65+ años) -"
            f" {formatear_corte(corte)}",
            fontsize=9,
            fontweight="bold",
            color="#4A2E7A",
        )
        plt.xlabel("Porcentaje respecto al Padrón Estatal (%)", fontsize=7.5)
        plt.xticks(fontsize=7.5)
        plt.yticks(fontsize=8)
        plt.tight_layout()
        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=200)
        plt.close()
        buf.seek(0)
        return buf
  except Exception:
    pass
  return None


def generar_grafico_top_extranjero(corte):
  try:
    c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
    c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
    c_pnat_z = col_exacta("PE_EO", ["NATURALIZADO"])
    q = f"""
            SELECT CLAVE_ENTIDAD, 
                   (SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_pnat_z},0) AS REAL)) * 100.0 / 
                   NULLIF((SELECT SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_pnat_z},0) AS REAL)) FROM PE_EO WHERE TRIM(FECHA_CORTE) = TRIM(?) AND CLAVE_MUNICIPIO = 0), 0)) AS pct_ext
            FROM PE_EO
            WHERE TRIM(FECHA_CORTE) = TRIM(?) AND CLAVE_MUNICIPIO = 0
            GROUP BY CLAVE_ENTIDAD
            ORDER BY pct_ext DESC
            LIMIT 5
        """
    df = pd.read_sql_query(q, conn, params=[corte, corte])
    if df.empty:
      return None
    df = df.sort_values(by="pct_ext", ascending=True)
    df["ENTIDAD"] = df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)

    plt.figure(figsize=(6.5, 2.1))
    plt.barh(df["ENTIDAD"], df["pct_ext"], color="#8C62B6")
    plt.title(
        f"Top 5 Entidades: Mayor % de Padrón en el Extranjero (ID 0) -"
        f" {formatear_corte(corte)}",
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
    )
    plt.xlabel(
        "Participación Porcentual Nacional en el Extranjero (%)", fontsize=7.5
    )
    plt.xticks(fontsize=7.5)
    plt.yticks(fontsize=8)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=200)
    plt.close()
    buf.seek(0)
    return buf
  except Exception:
    return None


def generar_grafico_distritos_negativos(corte_rec, corte_bas):
  try:
    if not corte_bas:
      return None
    c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
    c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
    c_p88 = col_exacta("PE_EO", ["PADRON", "NATURALIZADO"], ["PADRON", "88"])
    c_p87 = col_exacta(
        "PE_EO", ["PADRON", "HIJO"], ["PADRON", "HIJO_DE_PADRES_MEXICANOS"]
    )

    q = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_p88},0) + COALESCE({c_p87},0) AS REAL)) as padron
            FROM PE_EO
            WHERE TRIM(FECHA_CORTE) = TRIM(?) AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q, conn, params=[corte_rec])
    df_bas = pd.read_sql_query(q, conn, params=[corte_bas])

    df_merged = pd.merge(
        df_rec,
        df_bas,
        on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO"],
        suffixes=("_rec", "_bas"),
    )
    df_merged["pct_crecimiento"] = (
        (df_merged["padron_rec"] - df_merged["padron_bas"])
        / df_merged["padron_bas"]
    ) * 100

    df_negativos = df_merged.sort_values(
        by="pct_crecimiento", ascending=True
    ).head(15)
    if df_negativos.empty:
      return None

    df_negativos = df_negativos.sort_values(
        by="pct_crecimiento", ascending=True
    )
    df_negativos["etiqueta"] = (
        df_negativos["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        + " - Dist. "
        + df_negativos["CLAVE_DISTRITO"].astype(str)
    )

    plt.figure(figsize=(6.5, 2.8))
    plt.barh(
        df_negativos["etiqueta"],
        df_negativos["pct_crecimiento"],
        color="#EF4444",
    )
    plt.gca().invert_yaxis()
    plt.title(
        "Top 15 Distritos con Mayor Decremento / Menor Crecimiento (%)",
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
    )
    plt.xlabel("Variación Porcentual (%)", fontsize=7.5)
    plt.xticks(fontsize=7.5)
    plt.yticks(fontsize=7.0)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=200)
    plt.close()
    buf.seek(0)
    return buf
  except Exception:
    return None


def generar_grafico_distritos_positivos(corte_rec, corte_bas):
  try:
    if not corte_bas:
      return None
    c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
    c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
    c_p88 = col_exacta("PE_EO", ["PADRON", "NATURALIZADO"], ["PADRON", "88"])
    c_p87 = col_exacta(
        "PE_EO", ["PADRON", "HIJO"], ["PADRON", "HIJO_DE_PADRES_MEXICANOS"]
    )

    q = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_p88},0) + COALESCE({c_p87},0) AS REAL)) as padron
            FROM PE_EO
            WHERE TRIM(FECHA_CORTE) = TRIM(?) AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q, conn, params=[corte_rec])
    df_bas = pd.read_sql_query(q, conn, params=[corte_bas])

    df_merged = pd.merge(
        df_rec,
        df_bas,
        on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO"],
        suffixes=("_rec", "_bas"),
    )
    df_merged["pct_crecimiento"] = (
        (df_merged["padron_rec"] - df_merged["padron_bas"])
        / df_merged["padron_bas"]
    ) * 100

    df_positivos = df_merged.sort_values(
        by="pct_crecimiento", ascending=False
    ).head(15)
    if df_positivos.empty:
      return None

    df_positivos = df_positivos.sort_values(
        by="pct_crecimiento", ascending=True
    )
    df_positivos["etiqueta"] = (
        df_positivos["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        + " - Dist. "
        + df_positivos["CLAVE_DISTRITO"].astype(str)
    )

    plt.figure(figsize=(6.5, 2.8))
    plt.barh(
        df_positivos["etiqueta"],
        df_positivos["pct_crecimiento"],
        color="#10B981",
    )
    plt.gca().invert_yaxis()
    plt.title(
        "Top 15 Distritos con Mayor Crecimiento Positivo (%)",
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
    )
    plt.xlabel("Variación Porcentual (%)", fontsize=7.5)
    plt.xticks(fontsize=7.5)
    plt.yticks(fontsize=7.0)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=200)
    plt.close()
    buf.seek(0)
    return buf
  except Exception:
    return None


def generar_grafico_distritos_foraneos(corte):
  try:
    c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
    c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
    c_p88 = col_exacta("PE_EO", ["PADRON", "NATURALIZADO"], ["PADRON", "88"])
    c_p87 = col_exacta(
        "PE_EO", ["PADRON", "HIJO"], ["PADRON", "HIJO_DE_PADRES_MEXICANOS"]
    )

    q = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   (SUM(CAST(COALESCE({c_pfor},0) AS REAL)) * 100.0 / 
                    NULLIF(SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_p88},0) + COALESCE({c_p87},0) AS REAL)), 0)) AS pct_foraneo
            FROM PE_EO
            WHERE TRIM(FECHA_CORTE) = TRIM(?) AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
            ORDER BY pct_foraneo DESC
            LIMIT 15
        """
    df = pd.read_sql_query(q, conn, params=[corte])
    if df.empty:
      return None

    df = df.sort_values(by="pct_foraneo", ascending=True)
    df["etiqueta"] = (
        df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        + " - Dist. "
        + df["CLAVE_DISTRITO"].astype(str)
    )

    plt.figure(figsize=(6.5, 2.8))
    plt.barh(df["etiqueta"], df["pct_foraneo"], color="#3B82F6")
    plt.xlim(0, 100)
    plt.title(
        "Top 15 Distritos con Mayor Porcentaje de Población Foránea (%)",
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
    )
    plt.xlabel(
        "Porcentaje de Población Foránea en el Distrito (%)", fontsize=7.5
    )
    plt.xticks(fontsize=7.5)
    plt.yticks(fontsize=7.0)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=200)
    plt.close()
    buf.seek(0)
    return buf
  except Exception:
    return None


def generar_analisis_distrital_texto(corte_rec, corte_bas):
  try:
    if not corte_bas:
      return ""
    c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
    c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
    c_p88 = col_exacta("PE_EO", ["PADRON", "NATURALIZADO"], ["PADRON", "88"])
    c_p87 = col_exacta(
        "PE_EO", ["PADRON", "HIJO"], ["PADRON", "HIJO_DE_PADRES_MEXICANOS"]
    )

    q = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_p88},0) + COALESCE({c_p87},0) AS REAL)) as padron
            FROM PE_EO
            WHERE TRIM(FECHA_CORTE) = TRIM(?) AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q, conn, params=[corte_rec])
    df_bas = pd.read_sql_query(q, conn, params=[corte_bas])
    df_merged = pd.merge(
        df_rec,
        df_bas,
        on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO"],
        suffixes=("_rec", "_bas"),
    )
    df_merged["pct"] = (
        (df_merged["padron_rec"] - df_merged["padron_bas"])
        / df_merged["padron_bas"]
    ) * 100

    lentos = df_merged[df_merged["pct"] < 1.5]
    if lentos.empty:
      return ""

    resumen = []
    for ent, grupo in lentos.groupby("CLAVE_ENTIDAD"):
      tot_ent = df_merged[df_merged["CLAVE_ENTIDAD"] == ent][
          "CLAVE_DISTRITO"
      ].nunique()
      afectados = grupo["CLAVE_DISTRITO"].nunique()
      proporcion = (afectados / tot_ent) * 100
      nom_ent = CATALOGO_ENTIDADES.get(int(ent), "ESTADO")
      resumen.append((nom_ent, afectados, tot_ent, proporcion))

    resumen.sort(key=lambda x: x[3], reverse=True)
    textos = []
    for nom_ent, afec, tot, prop in resumen[:3]:
      textos.append(
          f"<b>{nom_ent}</b> presenta <b>{afec} de {tot} distritos</b> con un"
          f" crecimiento menor al 1.5% (incidencia del <b>{prop:.1f}%</b> de su"
          " estructura distrital)"
      )

    return (
        "<b>Análisis Geográfico de Comportamiento Distrital (Umbral <1.5%):</b>"
        " Se identifican concentraciones de bajo dinamismo o contracción"
        " registral. Destacan entidades como "
        + "; ".join(textos)
        + ", reflejando presiones demográficas o rezagos operativos en estas"
        " demarcaciones."
    )
  except Exception:
    pass
  return ""


def generar_analisis_positivo_texto(corte_rec, corte_bas):
  try:
    if not corte_bas:
      return ""
    c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
    c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
    c_p88 = col_exacta("PE_EO", ["PADRON", "NATURALIZADO"], ["PADRON", "88"])
    c_p87 = col_exacta(
        "PE_EO", ["PADRON", "HIJO"], ["PADRON", "HIJO_DE_PADRES_MEXICANOS"]
    )

    q = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_p88},0) + COALESCE({c_p87},0) AS REAL)) as padron
            FROM PE_EO
            WHERE TRIM(FECHA_CORTE) = TRIM(?) AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q, conn, params=[corte_rec])
    df_bas = pd.read_sql_query(q, conn, params=[corte_bas])
    df_merged = pd.merge(
        df_rec,
        df_bas,
        on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO"],
        suffixes=("_rec", "_bas"),
    )
    df_merged["pct"] = (
        (df_merged["padron_rec"] - df_merged["padron_bas"])
        / df_merged["padron_bas"]
    ) * 100

    acelerados = df_merged[df_merged["pct"] > 8.0]
    if acelerados.empty:
      return ""

    resumen = []
    for ent, grupo in acelerados.groupby("CLAVE_ENTIDAD"):
      tot_ent = df_merged[df_merged["CLAVE_ENTIDAD"] == ent][
          "CLAVE_DISTRITO"
      ].nunique()
      altos = grupo["CLAVE_DISTRITO"].nunique()
      proporcion = (altos / tot_ent) * 100
      nom_ent = CATALOGO_ENTIDADES.get(int(ent), "ESTADO")
      resumen.append((nom_ent, altos, tot_ent, proporcion))

    resumen.sort(key=lambda x: x[3], reverse=True)
    textos = []
    for nom_ent, altos, tot, prop in resumen[:3]:
      textos.append(
          f"<b>{nom_ent}</b> reporta <b>{altos} de {tot} distritos</b> con un"
          f" crecimiento por encima del 8.0% (representando el"
          f" <b>{prop:.1f}%</b> de su componente geográfico)"
      )

    return (
        "<b>Análisis de Empuje Demográfico y Atención Registral (Umbral"
        " >8%):</b> Se observa una fuerte expansión territorial. Entidades como"
        f" {'; '.join(textos)} evidencian una intensa atracción poblacional y"
        " dinámicas inmobiliarias aceleradas que concentran la mayor demanda"
        " operativa."
    )
  except Exception:
    pass
  return ""


def generar_analisis_foraneos_texto(corte_rec):
  try:
    c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
    c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
    c_p88 = col_exacta("PE_EO", ["PADRON", "NATURALIZADO"], ["PADRON", "88"])
    c_p87 = col_exacta(
        "PE_EO", ["PADRON", "HIJO"], ["PADRON", "HIJO_DE_PADRES_MEXICANOS"]
    )

    q_ent = f"""
            SELECT CLAVE_ENTIDAD,
                   SUM(CAST(COALESCE({c_pfor},0) AS REAL)) * 100.0 / 
                   NULLIF(SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_p88},0) + COALESCE({c_p87},0) AS REAL)), 0) AS pct_foraneo
            FROM PE_EO
            WHERE TRIM(FECHA_CORTE) = TRIM(?) AND CLAVE_MUNICIPIO != 0
            GROUP BY CLAVE_ENTIDAD
            ORDER BY pct_foraneo DESC
        """
    df_ent = pd.read_sql_query(q_ent, conn, params=[corte_rec])
    if df_ent.empty:
      return ""

    df_ent["ENTIDAD"] = df_ent["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
    top_max = df_ent.head(5)
    top_min = df_ent.tail(5).sort_values(by="pct_foraneo", ascending=True)

    max_str = ", ".join([
        f"<b>{row['ENTIDAD']}</b> ({row['pct_foraneo']:.1f}%)"
        for _, row in top_max.iterrows()
    ])
    min_str = ", ".join([
        f"<b>{row['ENTIDAD']}</b> ({row['pct_foraneo']:.1f}%)"
        for _, row in top_min.iterrows()
    ])

    return (
        "<b>Análisis de Movilidad y Población Foránea (Estatal):</b> Las"
        f" entidades con mayor atracción de población foránea son {max_str}; en"
        " contraste, las entidades con menor presencia de foráneos son"
        f" {min_str} (reflejando estabilidad y retención de población nativa)."
    )
  except Exception:
    pass
  return ""


# ==============================================================================
# REPORTE PDF EJECUTIVO CON TEXTO JUSTIFICADO Y ORTOGRAFÍA EN MAYÚSCULAS
# ==============================================================================
def generar_pdf_reporte(
    titulo_alcance,
    desc_cortes,
    p1,
    p2,
    l1,
    l2,
    cob1,
    cob2,
    g_data,
    dem_data,
    corte_rec,
    corte_bas,
    cve_ent,
    alcance_tipo,
):
  buffer = BytesIO()
  doc = SimpleDocTemplate(
      buffer,
      pagesize=letter,
      rightMargin=36,
      leftMargin=36,
      topMargin=26,
      bottomMargin=26,
  )
  story = []

  styles = getSampleStyleSheet()
  ine_purple = colors.HexColor("#5C3A92")
  ine_dark = colors.HexColor("#4A2E7A")

  title_style = ParagraphStyle(
      "TitleStyle",
      parent=styles["Heading1"],
      fontSize=11,
      textColor=ine_dark,
      spaceAfter=1,
      fontName="Helvetica-Bold",
      alignment=1,
  )
  subtitle_style = ParagraphStyle(
      "SubTitleStyle",
      parent=styles["Normal"],
      fontSize=7.5,
      textColor=colors.HexColor("#64748B"),
      spaceAfter=4,
      fontName="Helvetica",
      alignment=1,
  )
  heading_style = ParagraphStyle(
      "HeadingStyle",
      parent=styles["Heading2"],
      fontSize=9,
      textColor=ine_dark,
      spaceBefore=4,
      spaceAfter=2,
      fontName="Helvetica-Bold",
  )
  body_style = ParagraphStyle(
      "BodyStyle",
      parent=styles["Normal"],
      fontSize=7.5,
      textColor=colors.HexColor("#334155"),
      spaceAfter=3,
      leading=10,
      fontName="Helvetica",
      alignment=4,  # Justificado
  )
  warning_style = ParagraphStyle(
      "WarningStyle",
      parent=styles["Normal"],
      fontSize=7,
      textColor=colors.HexColor("#B91C1C"),
      spaceAfter=4,
      leading=9,
      fontName="Helvetica-Oblique",
      alignment=4,  # Justificado
  )
  footer_style = ParagraphStyle(
      "FooterStyle",
      parent=styles["Normal"],
      fontSize=6.5,
      textColor=colors.HexColor("#64748B"),
      leading=8,
      fontName="Helvetica-Oblique",
      alignment=1,
  )
  sign_style = ParagraphStyle(
      "SignStyle",
      parent=styles["Normal"],
      fontSize=9,
      textColor=ine_dark,
      alignment=2,
      fontName="Helvetica-Oblique",
      spaceBefore=4,
  )

  if LOGO_PATH.exists():
    img_logo = Image(str(LOGO_PATH), width=100, height=30)
    header_table = Table(
        [[
            img_logo,
            Paragraph(
                "<b>INSTITUTO NACIONAL ELECTORAL</b><br/><font size=6.5"
                " color='#5C3A92'>Dirección Ejecutiva del Registro Federal de"
                " Electores</font>",
                ParagraphStyle(
                    "HText",
                    parent=styles["Normal"],
                    fontSize=7.5,
                    leading=9,
                    alignment=1,
                ),
            ),
        ]],
        colWidths=[110, 394],
    )
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ])
    )
    story.append(header_table)
  else:
    story.append(
        Paragraph(
            "INSTITUTO NACIONAL ELECTORAL",
            ParagraphStyle(
                "INE",
                fontName="Helvetica-Bold",
                fontSize=7.5,
                textColor=ine_purple,
                spaceAfter=1,
                alignment=1,
            ),
        )
    )

  story.append(
      Paragraph(
          "Reporte Ejecutivo, Análisis Estructural y Top Geográfico",
          title_style,
      )
  )
  story.append(
      Paragraph(
          f"<b>Ámbito Geográfico:</b> {titulo_alcance} | {desc_cortes}",
          subtitle_style,
      )
  )
  story.append(
      HRFlowable(width="100%", thickness=1, color=ine_purple, spaceAfter=4)
  )

  txt_advertencia = (
      "<b>⚠️ Nota Metodológica de Validación:</b> La nueva distritación federal"
      " electoral rige a partir de mediados de 2023. Para análisis comparativo,"
      " se recomienda contrastar cortes que compartan el mismo marco geográfico"
      " para garantizar coherencia censal y cartográfica."
  )
  story.append(Paragraph(txt_advertencia, warning_style))

  story.append(
      Paragraph("1. Resumen Ejecutivo y Totales Superiores", heading_style)
  )
  dif_p = p1 - p2
  pct_p = (dif_p / p2 * 100) if p2 > 0 else 0
  dif_l = l1 - l2
  pct_l = (dif_l / l2 * 100) if l2 > 0 else 0

  txt_totales = (
      f"En el análisis comparativo, el <b>Padrón Electoral</b> registra un"
      f" total de <b>{p1:,.0f}</b> personas, con una variación de"
      f" <b>{dif_p:+,.0f}</b> registros ({pct_p:+.2f}%) respecto al corte"
      f" base. Por su parte, la <b>Lista Nominal</b> asciende a"
      f" <b>{l1:,.0f}</b> registros ({dif_l:+,.0f} personas, {pct_l:+.2f}%). La"
      f" cobertura registral actual se sitúa en <b>{cob1:.2f}%</b>."
  )
  story.append(Paragraph(txt_totales, body_style))

  story.append(
      Paragraph(
          "2. Composición Porcentual del Padrón y Lista Electoral por Origen",
          heading_style,
      )
  )
  nat_p, for_p, n88_p, n87_p = (
      dem_data["nat_p"],
      dem_data["for_p"],
      dem_data["n88_p"],
      dem_data["n87_p"],
  )
  tot_p_eo = (
      nat_p + for_p + n88_p + n87_p
      if (nat_p + for_p + n88_p + n87_p) > 0
      else 1
  )

  p_nat_pct = (nat_p / tot_p_eo) * 100
  p_for_pct = (for_p / tot_p_eo) * 100
  p_88_pct = (n88_p / tot_p_eo) * 100
  p_87_pct = (n87_p / tot_p_eo) * 100

  txt_origen_comp = (
      f"La suma de los componentes de origen (<b>{nat_p:,.0f}</b> Nativos +"
      f" <b>{for_p:,.0f}</b> Foráneos + <b>{n88_p:,.0f}</b> Naturalizados 88 +"
      f" <b>{n87_p:,.0f}</b> Hijos de Mexicanos 87) empareja al 100% con el"
      f" Padrón del ámbito seleccionado. Distribución: <b>Nativos</b>"
      f" ({p_nat_pct:.2f}%), <b>Foráneos</b> ({p_for_pct:.2f}%),"
      f" <b>Naturalizados 88</b> ({p_88_pct:.2f}%), e <b>Hijos de Mexicanos"
      f" 87</b> ({p_87_pct:.2f}%)."
  )
  story.append(Paragraph(txt_origen_comp, body_style))

  story.append(
      Paragraph(
          "3. Estructura Demográfica y Desglose por Género", heading_style
      )
  )
  h_p1, h_l1, m_p1, m_l1 = (
      g_data["h_p"],
      g_data["h_l"],
      g_data["m_p"],
      g_data["m_l"],
  )
  nb_p1, nb_l1 = g_data["nb_p"], g_data["nb_l"]
  txt_genero = (
      f"Emparejamiento: Hombres (<b>{h_p1:,.0f}</b>), Mujeres"
      f" (<b>{m_p1:,.0f}</b>) y No Binarios (<b>{nb_p1:,.0f}</b>). Cobertura:"
      f" Hombres (<b>{(h_l1/h_p1*100) if h_p1>0 else 0:.2f}%</b>), Mujeres"
      f" (<b>{(m_l1/m_p1*100) if m_p1>0 else 0:.2f}%</b>)."
  )
  story.append(Paragraph(txt_genero, body_style))

  story.append(
      Paragraph(
          "4. Radiografía Demográfica, Movilidad y Rankings Nacionales",
          heading_style,
      )
  )

  def agregar_imagen_centrada(buf_img, w=410, h=110):
    if buf_img:
      t_img = Table([[Image(buf_img, width=w, height=h)]], colWidths=[504])
      t_img.setStyle(
          TableStyle([
              ("ALIGN", (0, 0), (-1, -1), "CENTER"),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ])
      )
      story.append(t_img)
      story.append(Spacer(1, 2))

  img_jov = generar_grafico_top_jovenes(corte_rec)
  agregar_imagen_centrada(img_jov, 410, 110)

  img_may = generar_grafico_top_mayores(corte_rec)
  agregar_imagen_centrada(img_may, 410, 110)

  img_ext = generar_grafico_top_extranjero(corte_rec)
  agregar_imagen_centrada(img_ext, 410, 110)

  if corte_bas:
    img_neg = generar_grafico_distritos_negativos(corte_rec, corte_bas)
    agregar_imagen_centrada(img_neg, 410, 130)

    txt_desc_neg = generar_analisis_distrital_texto(corte_rec, corte_bas)
    if txt_desc_neg:
      story.append(Paragraph(txt_desc_neg, body_style))
      story.append(Spacer(1, 2))

    img_pos = generar_grafico_distritos_positivos(corte_rec, corte_bas)
    agregar_imagen_centrada(img_pos, 410, 130)

    txt_desc_pos = generar_analisis_positivo_texto(corte_rec, corte_bas)
    if txt_desc_pos:
      story.append(Paragraph(txt_desc_pos, body_style))
      story.append(Spacer(1, 2))

  story.append(
      Paragraph(
          "Dinámica de Movilidad e Intercambio Poblacional Foráneo",
          heading_style,
      )
  )
  img_for_dist = generar_grafico_distritos_foraneos(corte_rec)
  agregar_imagen_centrada(img_for_dist, 410, 130)

  txt_for = generar_analisis_foraneos_texto(corte_rec)
  if txt_for:
    story.append(Paragraph(txt_for, body_style))
    story.append(Spacer(1, 2))

  story.append(Spacer(1, 2))
  story.append(
      HRFlowable(
          width="100%",
          thickness=0.6,
          color=colors.HexColor("#CBD5E1"),
          spaceAfter=2,
      )
  )

  fecha_hora_actual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
  txt_fuente_pdf = (
      "Datos oficiales extraídos de la plataforma de Datos Abiertos del INE:"
      " https://ine.mx/transparencia/datos-abiertos/#/tematica/padron-electoral<br/><b>Fecha"
      f" y hora de impresión:</b> {fecha_hora_actual}"
  )

  story.append(Paragraph(txt_fuente_pdf, footer_style))
  story.append(Paragraph("Baez", sign_style))

  doc.build(story)
  buffer.seek(0)
  return buffer


# ==============================================================================
# BARRA LATERAL: CONFIGURACIÓN INTEGRAL Y DINÁMICA DE FILTROS
# ==============================================================================
with st.sidebar:
  st.markdown("### Configuración del Monitor")

  cortes_lista = obtener_cortes_ordenados()
  if not cortes_lista:
    st.error("⚠️ No se encontraron registros en la base de datos.")
    st.stop()

  modo = st.radio(
      "Objetivo:",
      ["Corte Actual", "Comparar con Periodo Previo"],
      index=0,
      key="radio_objetivo",
  )

  corte_reciente = st.selectbox(
      "Corte Principal (Reciente):",
      cortes_lista,
      index=0,
      format_func=lambda x: formatear_corte(x),
      key="sel_corte_reciente",
  )

  corte_base = None
  if modo == "Comparar con Periodo Previo":
    idx_base = (
        cortes_lista.index("PEF_2024")
        if "PEF_2024" in cortes_lista
        else (1 if len(cortes_lista) > 1 else 0)
    )
    corte_base = st.selectbox(
        "Corte Base a Comparar (Se recomienda 2024+ para misma distritación):",
        cortes_lista,
        index=idx_base,
        format_func=lambda x: formatear_corte(x),
        key="sel_corte_base",
    )

  st.markdown("---")
  alcance = st.radio(
      "Ámbito Geográfico:",
      [
          "Total Nacional + Extranjero",
          "Nacional (Sin Residentes en el Extranjero ID 0)",
          "Solo Residentes en el Extranjero (ID 0)",
          "Entidad Federativa Específica",
      ],
      index=0,
      key="radio_alcance",
  )

  sql_filtro_geo = ""
  nombre_header = "Total Nacional + Extranjero"
  cve_entidad_activa = None
  cve_distrito_activo = None
  mun_elegido_val = None
  nivel_geografico = None

  tables_db_sidebar = pd.read_sql_query(
      "SELECT name FROM sqlite_master WHERE type='table'", conn
  )["name"].tolist()
  tabla_ref = "PE_EO" if "PE_EO" in tables_db_sidebar else "PE_SEX"

  if alcance == "Total Nacional + Extranjero":
    sql_filtro_geo = ""
    nombre_header = "Consolidado Nacional + Extranjero"

  elif alcance == "Nacional (Sin Residentes en el Extranjero ID 0)":
    sql_filtro_geo = "AND CLAVE_MUNICIPIO != 0"
    nombre_header = "Territorio Nacional (Excluyendo Extranjero ID 0)"

  elif alcance == "Solo Residentes en el Extranjero (ID 0)":
    sql_filtro_geo = "AND CLAVE_MUNICIPIO = 0"
    nombre_header = "Residentes en el Extranjero (Nacional ID 0)"

  elif alcance == "Entidad Federativa Específica":
    st.markdown("---")
    cve = st.selectbox(
        "Selecciona Entidad:",
        options=list(CATALOGO_ENTIDADES.keys()),
        format_func=lambda x: f"{x:02d} - {CATALOGO_ENTIDADES[x]}",
        index=14,  # Por defecto Estado de México (15)
        key="sel_entidad_id",
    )
    cve_entidad_activa = cve
    nom_ent = CATALOGO_ENTIDADES[cve]

    nivel_geografico = st.radio(
        f"Granularidad para {nom_ent}:",
        [
            "Total Entidad (Municipios + Extranjero)",
            "Por Distrito Específico",
            "Solo Municipios (Sin Extranjero ID 0)",
            "Solo Extranjero (ID 0)",
            "Municipio Específico",
        ],
        index=0,
        key="radio_nivel_geo",
    )

    if nivel_geografico == "Total Entidad (Municipios + Extranjero)":
      sql_filtro_geo = f"AND CLAVE_ENTIDAD = {cve}"
      nombre_header = f"{nom_ent} [Total Estatal]"

    elif nivel_geografico == "Por Distrito Específico":
      try:
        q_dists = f"SELECT DISTINCT CLAVE_DISTRITO FROM {tabla_ref} WHERE CLAVE_ENTIDAD = {cve} AND CLAVE_DISTRITO != 0 ORDER BY CLAVE_DISTRITO ASC"
        df_dists = pd.read_sql_query(q_dists, conn)
        opciones_dists = [int(x) for x in df_dists["CLAVE_DISTRITO"].tolist()]
      except Exception:
        opciones_dists = list(range(1, 41))

      idx_def_dist = opciones_dists.index(17) if 17 in opciones_dists else 0
      cve_distrito_activo = st.selectbox(
          "Selecciona Distrito:",
          options=opciones_dists,
          index=idx_def_dist,
          format_func=lambda x: f"Distrito Federal {x:02d}",
          key="sel_distrito",
      )
      sql_filtro_geo = (
          f"AND CLAVE_ENTIDAD = {cve} AND CLAVE_DISTRITO ="
          f" {cve_distrito_activo}"
      )
      nombre_header = f"{nom_ent} [Distrito Federal {cve_distrito_activo:02d}]"

    elif nivel_geografico == "Solo Municipios (Sin Extranjero ID 0)":
      sql_filtro_geo = f"AND CLAVE_ENTIDAD = {cve} AND CLAVE_MUNICIPIO != 0"
      nombre_header = f"{nom_ent} [Territorio Estatal sin Extranjero]"

    elif nivel_geografico == "Solo Extranjero (ID 0)":
      sql_filtro_geo = f"AND CLAVE_ENTIDAD = {cve} AND CLAVE_MUNICIPIO = 0"
      nombre_header = f"{nom_ent} [Residentes en el Extranjero ID 0]"

    elif nivel_geografico == "Municipio Específico":
      c_nom_mun = (
          col_exacta(tabla_ref, ["NOMBRE", "MUNICIPIO"], ["MUNICIPIO"])
          if tabla_ref
          else "0"
      )
      try:
        if c_nom_mun != "0":
          q_muns = f"SELECT CLAVE_MUNICIPIO, MAX({c_nom_mun}) AS NOMBRE_MUNICIPIO FROM {tabla_ref} WHERE CLAVE_ENTIDAD = {cve} GROUP BY CLAVE_MUNICIPIO ORDER BY CLAVE_MUNICIPIO ASC"
        else:
          q_muns = f"SELECT DISTINCT CLAVE_MUNICIPIO, 'Municipio ' || CLAVE_MUNICIPIO AS NOMBRE_MUNICIPIO FROM {tabla_ref} WHERE CLAVE_ENTIDAD = {cve} ORDER BY CLAVE_MUNICIPIO ASC"
        df_muns = pd.read_sql_query(q_muns, conn)
        opciones_mun = [
            (int(row["CLAVE_MUNICIPIO"]), str(row["NOMBRE_MUNICIPIO"]))
            for _, row in df_muns.iterrows()
            if pd.notnull(row["CLAVE_MUNICIPIO"])
        ]
      except Exception:
        opciones_mun = []

      dict_nombres = dict(opciones_mun)
      mun_elegido_val = st.selectbox(
          "Selecciona Municipio:",
          options=[item[0] for item in opciones_mun] or [0],
          format_func=lambda x: (
              "0 - Residentes en el Extranjero"
              if int(x) == 0
              else f"{int(x):03d} - {dict_nombres.get(int(x), 'Desconocido')}"
          ),
          key="sel_municipio",
      )
      sql_filtro_geo = (
          f"AND CLAVE_ENTIDAD = {cve} AND CLAVE_MUNICIPIO = {mun_elegido_val}"
      )
      nombre_header = f"{nom_ent} [{dict_nombres.get(int(mun_elegido_val), f'Municipio ID {mun_elegido_val}')}]"

# ==============================================================================
# RENDERIZADO DEL ENCABEZADO Y MÉTRICAS SUPERIORES
# ==============================================================================
st.markdown(
    f"<div class='main-title notranslate'>Padrón Electoral y Lista Nominal:"
    f" {nombre_header}</div>",
    unsafe_allow_html=True,
)
if modo == "Comparar con Periodo Previo" and corte_base:
  st.markdown(
      "<div class='sub-title notranslate'>Evolución histórica: Corte Reciente"
      f" (<b>{formatear_corte(corte_reciente)}</b>) frente a Corte Base"
      f" (<b>{formatear_corte(corte_base)}</b>)</div>",
      unsafe_allow_html=True,
  )
else:
  st.markdown(
      "<div class='sub-title notranslate'>Corte de operación analizado:"
      f" <b>{formatear_corte(corte_reciente)}</b></div>",
      unsafe_allow_html=True,
  )

df_m1 = consultar_datos_agregados_seguro(corte_reciente, sql_filtro_geo)
p1 = int(df_m1["padron"].iloc[0] or 0)
l1 = int(df_m1["lista"].iloc[0] or 0)
cob1 = (l1 / p1 * 100) if p1 > 0 else 0

p2, l2, cob2 = p1, l1, cob1
if modo == "Comparar con Periodo Previo" and corte_base:
  df_m2 = consultar_datos_agregados_seguro(corte_base, sql_filtro_geo)
  p2 = int(df_m2["padron"].iloc[0] or 0)
  l2 = int(df_m2["lista"].iloc[0] or 0)
  cob2 = (l2 / p2 * 100) if p2 > 0 else 0

  dif_p = p1 - p2
  pct_p = (dif_p / p2 * 100) if p2 > 0 else 0
  dif_l = l1 - l2
  pct_l = (dif_l / l2 * 100) if l2 > 0 else 0
  dif_cob = cob1 - cob2

  k1, k2, k3 = st.columns(3)
  k1.metric("Padrón Electoral", f"{p1:,}", f"{dif_p:+,} ({pct_p:+.2f}%)")
  k2.metric("Lista Nominal", f"{l1:,}", f"{dif_l:+,} ({pct_l:+.2f}%)")
  k3.metric("Cobertura Registral", f"{cob1:.2f}%", f"{dif_cob:+.2f}%")
else:
  k1, k2, k3 = st.columns(3)
  k1.metric("Padrón Electoral", f"{p1:,}")
  k2.metric("Lista Nominal", f"{l1:,}")
  k3.metric("Cobertura Registral", f"{cob1:.2f}%")

st.markdown("---")
st.markdown("#### Desglose por Género (Emparejado al 100% con el Padrón)")
h_padron_1 = int(df_m1["h_padron"].iloc[0] or 0)
h_lista_1 = int(df_m1["h_lista"].iloc[0] or 0)
m_padron_1 = int(df_m1["m_padron"].iloc[0] or 0)
m_lista_1 = int(df_m1["m_lista"].iloc[0] or 0)
nb_padron_1 = int(df_m1["nb_padron"].iloc[0] or 0)
nb_lista_1 = int(df_m1["nb_lista"].iloc[0] or 0)

hcob_1 = (h_lista_1 / h_padron_1 * 100) if h_padron_1 > 0 else 0
mcob_1 = (m_lista_1 / m_padron_1 * 100) if m_padron_1 > 0 else 0
nbcob_1 = (nb_lista_1 / nb_padron_1 * 100) if nb_padron_1 > 0 else 0

if modo == "Comparar con Periodo Previo" and corte_base:
  h_padron_2 = int(df_m2["h_padron"].iloc[0] or 0)
  h_lista_2 = int(df_m2["h_lista"].iloc[0] or 0)
  m_padron_2 = int(df_m2["m_padron"].iloc[0] or 0)
  m_lista_2 = int(df_m2["m_lista"].iloc[0] or 0)
  nb_padron_2 = int(df_m2["nb_padron"].iloc[0] or 0)
  nb_lista_2 = int(df_m2["nb_lista"].iloc[0] or 0)

  dh_p = h_padron_1 - h_padron_2
  dh_l = h_lista_1 - h_lista_2
  dm_p = m_padron_1 - m_padron_2
  dm_l = m_lista_1 - m_lista_2
  dnb_p = nb_padron_1 - nb_padron_2
  dnb_l = nb_lista_1 - nb_lista_2

  gh1, gh2, gh3 = st.columns(3)
  with gh1:
    st.markdown("**👨 Hombres**")
    st.metric(
        "Padrón",
        f"{h_padron_1:,}",
        calc_var_str(dh_p, h_padron_2),
        delta_color="normal" if dh_p >= 0 else "inverse",
    )
    st.metric(
        "Lista Nominal",
        f"{h_lista_1:,}",
        calc_var_str(dh_l, h_lista_2),
        delta_color="normal" if dh_l >= 0 else "inverse",
    )
    st.text(f"Cobertura: {hcob_1:.2f}%")
  with gh2:
    st.markdown("**👩 Mujeres**")
    st.metric(
        "Padrón",
        f"{m_padron_1:,}",
        calc_var_str(dm_p, m_padron_2),
        delta_color="normal" if dm_p >= 0 else "inverse",
    )
    st.metric(
        "Lista Nominal",
        f"{m_lista_1:,}",
        calc_var_str(dm_l, m_lista_2),
        delta_color="normal" if dm_l >= 0 else "inverse",
    )
    st.text(f"Cobertura: {mcob_1:.2f}%")
  with gh3:
    st.markdown("**⚧ No Binarios**")
    st.metric(
        "Padrón",
        f"{nb_padron_1:,}",
        calc_var_str(dnb_p, nb_padron_2),
        delta_color="normal" if dnb_p >= 0 else "inverse",
    )
    st.metric(
        "Lista Nominal",
        f"{nb_lista_1:,}",
        calc_var_str(dnb_l, nb_lista_2),
        delta_color="normal" if dnb_l >= 0 else "inverse",
    )
    st.text(f"Cobertura: {nbcob_1:.2f}%")
else:
  gh1, gh2, gh3 = st.columns(3)
  with gh1:
    st.markdown("**👨 Hombres**")
    st.metric("Padrón Hombres", f"{h_padron_1:,}")
    st.metric("Lista Nominal Hombres", f"{h_lista_1:,}")
    st.text(f"Cobertura: {hcob_1:.2f}%")
  with gh2:
    st.markdown("**👩 Mujeres**")
    st.metric("Padrón Mujeres", f"{m_padron_1:,}")
    st.metric("Lista Nominal Mujeres", f"{m_lista_1:,}")
    st.text(f"Cobertura: {mcob_1:.2f}%")
  with gh3:
    st.markdown("**⚧ No Binarios**")
    st.metric("Padrón No Binarios", f"{nb_padron_1:,}")
    st.metric("Lista Nominal No Binarios", f"{nb_lista_1:,}")
    st.text(f"Cobertura: {nbcob_1:.2f}%")

st.markdown("---")
st.markdown(
    "### Perspectiva Territorial, Movilidad Nacional y Ciudadanía en el"
    " Extranjero"
)

tab_jovenes, tab_mayores, tab_origen = st.tabs([
    "🌱 Jóvenes de 18 y 19 Años",
    "👴 Población de 65 Años y Más",
    "📋 Comprobación de Origen y Movilidad (PE_EO)",
])

tables_db = pd.read_sql_query(
    "SELECT name FROM sqlite_master WHERE type='table'", conn
)["name"].tolist()
target_re = "PE_RE" if "PE_RE" in tables_db else None
target_eo = "PE_EO" if "PE_EO" in tables_db else None

pjov_1, ljov_1, pjov_2, ljov_2 = 0, 0, 0, 0
pmay_1, lmay_1, pmay_2, lmay_2 = 0, 0, 0, 0
p_nat_1, l_nat_1, p_for_1, l_for_1, p_87_1, l_87_1, p_88_1, l_88_1 = (
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
)
p_nat_2, l_nat_2, p_for_2, l_for_2, p_87_2, l_87_2, p_88_2, l_88_2 = (
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
)

with tab_jovenes:
  if target_re:
    q1 = f'SELECT SUM(CAST("PE_JOVENES_18_19" AS REAL)) AS p, SUM(CAST("LNE_JOVENES_18_19" AS REAL)) AS l FROM {target_re} WHERE TRIM(FECHA_CORTE) = TRIM("{corte_reciente}") {sql_filtro_geo}'
    try:
      df_tmp = pd.read_sql_query(q1, conn)
      pjov_1 = int(df_tmp["p"].iloc[0] or 0)
      ljov_1 = int(df_tmp["l"].iloc[0] or 0)
    except Exception:
      pass

    if modo == "Comparar con Periodo Previo" and corte_base:
      q2 = f'SELECT SUM(CAST("PE_JOVENES_18_19" AS REAL)) AS p, SUM(CAST("LNE_JOVENES_18_19" AS REAL)) AS l FROM {target_re} WHERE TRIM(FECHA_CORTE) = TRIM("{corte_base}") {sql_filtro_geo}'
      try:
        df_tmp2 = pd.read_sql_query(q2, conn)
        pjov_2 = int(df_tmp2["p"].iloc[0] or 0)
        ljov_2 = int(df_tmp2["l"].iloc[0] or 0)
      except Exception:
        pass

  cobjov_1 = (ljov_1 / pjov_1 * 100) if pjov_1 > 0 else 0
  if modo == "Comparar con Periodo Previo" and corte_base:
    dp_jov = pjov_1 - pjov_2
    dl_jov = ljov_1 - ljov_2

    j1, j2, j3, j4 = st.columns(4)
    j1.metric(
        "Padrón (18-19 años)",
        f"{pjov_1:,}",
        calc_var_str(dp_jov, pjov_2),
        delta_color="normal" if dp_jov >= 0 else "inverse",
    )
    j2.metric(
        "Lista Nominal (18-19 años)",
        f"{ljov_1:,}",
        calc_var_str(dl_jov, ljov_2),
        delta_color="normal" if dl_jov >= 0 else "inverse",
    )
    j3.metric("Cobertura Registral", f"{cobjov_1:.2f}%")
    j4.metric(
        "Peso en Padrón / Lista",
        f"{(pjov_1/p1*100) if p1>0 else 0:.2f}% /"
        f" {(ljov_1/l1*100) if l1>0 else 0:.2f}%",
    )
  else:
    j1, j2, j3, j4 = st.columns(4)
    j1.metric("Padrón (18-19 años)", f"{pjov_1:,}")
    j2.metric("Lista Nominal (18-19 años)", f"{ljov_1:,}")
    j3.metric("Cobertura Registral", f"{cobjov_1:.2f}%")
    j4.metric(
        "Peso en Padrón / Lista",
        f"{(pjov_1/p1*100) if p1>0 else 0:.2f}% /"
        f" {(ljov_1/l1*100) if l1>0 else 0:.2f}%",
    )

with tab_mayores:
  if target_re:
    q1 = f'SELECT SUM(CAST("PE_MAS_DE_65" AS REAL)) AS p, SUM(CAST("LNE_MAS_DE_65" AS REAL)) AS l FROM {target_re} WHERE TRIM(FECHA_CORTE) = TRIM("{corte_reciente}") {sql_filtro_geo}'
    try:
      df_tmp = pd.read_sql_query(q1, conn)
      pmay_1 = int(df_tmp["p"].iloc[0] or 0)
      lmay_1 = int(df_tmp["l"].iloc[0] or 0)
    except Exception:
      pass

    if modo == "Comparar con Periodo Previo" and corte_base:
      q2 = f'SELECT SUM(CAST("PE_MAS_DE_65" AS REAL)) AS p, SUM(CAST("LNE_MAS_DE_65" AS REAL)) AS l FROM {target_re} WHERE TRIM(FECHA_CORTE) = TRIM("{corte_base}") {sql_filtro_geo}'
      try:
        df_tmp2 = pd.read_sql_query(q2, conn)
        pmay_2 = int(df_tmp2["p"].iloc[0] or 0)
        lmay_2 = int(df_tmp2["l"].iloc[0] or 0)
      except Exception:
        pass

  cobmay_1 = (lmay_1 / pmay_1 * 100) if pmay_1 > 0 else 0
  if modo == "Comparar con Periodo Previo" and corte_base:
    dp_may = pmay_1 - pmay_2
    dl_may = lmay_1 - lmay_2

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Padrón (65 años y más)",
        f"{pmay_1:,}",
        calc_var_str(dp_may, pmay_2),
        delta_color="normal" if dp_may >= 0 else "inverse",
    )
    m2.metric(
        "Lista Nominal (65 años y más)",
        f"{lmay_1:,}",
        calc_var_str(dl_may, lmay_2),
        delta_color="normal" if dl_may >= 0 else "inverse",
    )
    m3.metric("Cobertura Registral", f"{cobmay_1:.2f}%")
    m4.metric(
        "Peso en Padrón / Lista",
        f"{(pmay_1/p1*100) if p1>0 else 0:.2f}% /"
        f" {(lmay_1/l1*100) if l1>0 else 0:.2f}%",
    )
  else:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Padrón (65 años y más)", f"{pmay_1:,}")
    m2.metric("Lista Nominal (65 años y más)", f"{lmay_1:,}")
    m3.metric("Cobertura Registral", f"{cobmay_1:.2f}%")
    m4.metric(
        "Peso en Padrón / Lista",
        f"{(pmay_1/p1*100) if p1>0 else 0:.2f}% /"
        f" {(lmay_1/l1*100) if l1>0 else 0:.2f}%",
    )

with tab_origen:
  st.markdown(
      "#### Comprobación de Origen y Movilidad (Suma emparejada al 100% con el"
      " Padrón)"
  )
  if target_eo:
    try:
      c_pnat = col_exacta("PE_EO", ["PADRON", "NATIVO"])
      c_lnat = col_exacta("PE_EO", ["LISTA", "NATIVO"], ["LNE", "NATIVO"])
      c_pfor = col_exacta("PE_EO", ["PADRON", "FORANEO"])
      c_lfor = col_exacta("PE_EO", ["LISTA", "FORANEO"], ["LNE", "FORANEO"])
      c_p87 = col_exacta(
          "PE_EO",
          ["PADRON", "HIJO"],
          ["PADRON", "MEXICANO"],
      )
      c_l87 = col_exacta("PE_EO", ["LISTA", "HIJO"], ["LNE", "HIJO"])
      c_p88 = col_exacta(
          "PE_EO", ["PADRON", "NATURALIZADO"], ["PADRON", "88"]
      )
      c_l88 = col_exacta(
          "PE_EO", ["LISTA", "NATURALIZADO"], ["LNE", "NATURALIZADO"]
      )

      q_eo1 = f"""
                SELECT 
                    COALESCE(SUM(CAST({c_pnat} AS REAL)), 0) AS p_nat, COALESCE(SUM(CAST({c_lnat} AS REAL)), 0) AS l_nat,
                    COALESCE(SUM(CAST({c_pfor} AS REAL)), 0) AS p_for, COALESCE(SUM(CAST({c_lfor} AS REAL)), 0) AS l_for,
                    COALESCE(SUM(CAST({c_p87} AS REAL)), 0) AS p_87, COALESCE(SUM(CAST({c_l87} AS REAL)), 0) AS l_87,
                    COALESCE(SUM(CAST({c_p88} AS REAL)), 0) AS p_88, COALESCE(SUM(CAST({c_l88} AS REAL)), 0) AS l_88
                FROM {target_eo}
                WHERE TRIM(FECHA_CORTE) = TRIM('{corte_reciente}') {sql_filtro_geo}
            """
      df_eo = pd.read_sql_query(q_eo1, conn)
      p_nat_1 = int(df_eo["p_nat"].iloc[0] or 0)
      l_nat_1 = int(df_eo["l_nat"].iloc[0] or 0)
      p_for_1 = int(df_eo["p_for"].iloc[0] or 0)
      l_for_1 = int(df_eo["l_for"].iloc[0] or 0)
      p_87_1 = int(df_eo["p_87"].iloc[0] or 0)
      l_87_1 = int(df_eo["l_87"].iloc[0] or 0)
      p_88_1 = int(df_eo["p_88"].iloc[0] or 0)
      l_88_1 = int(df_eo["l_88"].iloc[0] or 0)

      if modo == "Comparar con Periodo Previo" and corte_base:
        q_eo2 = f"""
                    SELECT 
                        COALESCE(SUM(CAST({c_pnat} AS REAL)), 0) AS p_nat, COALESCE(SUM(CAST({c_lnat} AS REAL)), 0) AS l_nat,
                        COALESCE(SUM(CAST({c_pfor} AS REAL)), 0) AS p_for, COALESCE(SUM(CAST({c_lfor} AS REAL)), 0) AS l_for,
                        COALESCE(SUM(CAST({c_p87} AS REAL)), 0) AS p_87, COALESCE(SUM(CAST({c_l87} AS REAL)), 0) AS l_87,
                        COALESCE(SUM(CAST({c_p88} AS REAL)), 0) AS p_88, COALESCE(SUM(CAST({c_l88} AS REAL)), 0) AS l_88
                    FROM {target_eo}
                    WHERE TRIM(FECHA_CORTE) = TRIM('{corte_base}') {sql_filtro_geo}
                """
        df_eo2 = pd.read_sql_query(q_eo2, conn)
        p_nat_2 = int(df_eo2["p_nat"].iloc[0] or 0)
        l_nat_2 = int(df_eo2["l_nat"].iloc[0] or 0)
        p_for_2 = int(df_eo2["p_for"].iloc[0] or 0)
        l_for_2 = int(df_eo2["l_for"].iloc[0] or 0)
        p_87_2 = int(df_eo2["p_87"].iloc[0] or 0)
        l_87_2 = int(df_eo2["l_87"].iloc[0] or 0)
        p_88_2 = int(df_eo2["p_88"].iloc[0] or 0)
        l_88_2 = int(df_eo2["l_88"].iloc[0] or 0)

      tot_origen_p = (
          p_nat_1 + p_for_1 + p_88_1 + p_87_1
          if (p_nat_1 + p_for_1 + p_88_1 + p_87_1) > 0
          else (p1 if p1 > 0 else 1)
      )
      tot_origen_l = (
          l_nat_1 + l_for_1 + l_88_1 + l_87_1
          if (l_nat_1 + l_for_1 + l_88_1 + l_87_1) > 0
          else (l1 if l1 > 0 else 1)
      )

      p_nat_pct = (p_nat_1 / tot_origen_p) * 100
      p_for_pct = (p_for_1 / tot_origen_p) * 100
      p_88_pct = (p_88_1 / tot_origen_p) * 100
      p_87_pct = (p_87_1 / tot_origen_p) * 100

      l_nat_pct = (l_nat_1 / tot_origen_l) * 100
      l_for_pct = (l_for_1 / tot_origen_l) * 100
      l_88_pct = (l_88_1 / tot_origen_l) * 100
      l_87_pct = (l_87_1 / tot_origen_l) * 100

      col_o1, col_o2 = st.columns(2)
      with col_o1:
        st.markdown("##### 📌 Padrón Electoral por Origen")
        if modo == "Comparar con Periodo Previo" and corte_base:
          dp_nat = p_nat_1 - p_nat_2
          dp_for = p_for_1 - p_for_2
          dp_88 = p_88_1 - p_88_2
          dp_87 = p_87_1 - p_87_2

          st.metric(
              "Padrón Nativo",
              f"{p_nat_1:,}",
              f"{calc_var_str(dp_nat, p_nat_2)} | Estructura:"
              f" {p_nat_pct:.2f}%",
              delta_color="normal" if dp_nat >= 0 else "inverse",
          )
          st.metric(
              "Padrón Foráneo",
              f"{p_for_1:,}",
              f"{calc_var_str(dp_for, p_for_2)} | Estructura:"
              f" {p_for_pct:.2f}%",
              delta_color="normal" if dp_for >= 0 else "inverse",
          )
          st.metric(
              "Padrón Naturalizado (88)",
              f"{p_88_1:,}",
              f"{calc_var_str(dp_88, p_88_2)} | Estructura: {p_88_pct:.2f}%",
              delta_color="normal" if dp_88 >= 0 else "inverse",
          )
          st.metric(
              "Padrón Hijos de Mex (87)",
              f"{p_87_1:,}",
              f"{calc_var_str(dp_87, p_87_2)} | Estructura: {p_87_pct:.2f}%",
              delta_color="normal" if dp_87 >= 0 else "inverse",
          )
        else:
          st.metric(
              "Padrón Nativo", f"{p_nat_1:,}", f"{p_nat_pct:.2f}% del Padrón"
          )
          st.metric(
              "Padrón Foráneo", f"{p_for_1:,}", f"{p_for_pct:.2f}% del Padrón"
          )
          st.metric(
              "Padrón Naturalizado (88)",
              f"{p_88_1:,}",
              f"{p_88_pct:.2f}% del Padrón",
          )
          st.metric(
              "Padrón Hijos de Mex (87)",
              f"{p_87_1:,}",
              f"{p_87_pct:.2f}% del Padrón",
          )

      with col_o2:
        st.markdown("##### 📌 Lista Nominal por Origen")
        if modo == "Comparar con Periodo Previo" and corte_base:
          dl_nat = l_nat_1 - l_nat_2
          dl_for = l_for_1 - l_for_2
          dl_88 = l_88_1 - l_88_2
          dl_87 = l_87_1 - l_87_2

          st.metric(
              "Lista Nativa",
              f"{l_nat_1:,}",
              f"{calc_var_str(dl_nat, l_nat_2)} | Estructura:"
              f" {l_nat_pct:.2f}%",
              delta_color="normal" if dl_nat >= 0 else "inverse",
          )
          st.metric(
              "Lista Foránea",
              f"{l_for_1:,}",
              f"{calc_var_str(dl_for, l_for_2)} | Estructura:"
              f" {l_for_pct:.2f}%",
              delta_color="normal" if dl_for >= 0 else "inverse",
          )
          st.metric(
              "Lista Naturalizada (88)",
              f"{l_88_1:,}",
              f"{calc_var_str(dl_88, l_88_2)} | Estructura: {l_88_pct:.2f}%",
              delta_color="normal" if dl_88 >= 0 else "inverse",
          )
          st.metric(
              "Lista Hijos de Mex (87)",
              f"{l_87_1:,}",
              f"{calc_var_str(dl_87, l_87_2)} | Estructura: {l_87_pct:.2f}%",
              delta_color="normal" if dl_87 >= 0 else "inverse",
          )
        else:
          st.metric(
              "Lista Nativa", f"{l_nat_1:,}", f"{l_nat_pct:.2f}% de Lista"
          )
          st.metric(
              "Lista Foránea", f"{l_for_1:,}", f"{l_for_pct:.2f}% de Lista"
          )
          st.metric(
              "Lista Naturalizada (88)",
              f"{l_88_1:,}",
              f"{l_88_pct:.2f}% de Lista",
          )
          st.metric(
              "Lista Hijos de Mex (87)",
              f"{l_87_1:,}",
              f"{l_87_pct:.2f}% de Lista",
          )
    except Exception:
      pass

st.markdown(
    "<div class='footer-fuente notranslate'>📊 Datos oficiales extraídos de la"
    " plataforma de Datos Abiertos del INE: <a"
    " href='https://ine.mx/transparencia/datos-abiertos/#/tematica/padron-electoral'"
    " target='_blank'>https://ine.mx/transparencia/datos-abiertos/#/tematica/padron-electoral</a></div>",
    unsafe_allow_html=True,
)

st.sidebar.markdown("---")
st.sidebar.subheader("📄 Exportar Informe")

g_dict = {
    "h_p": h_padron_1,
    "h_l": h_lista_1,
    "m_p": m_padron_1,
    "m_l": m_lista_1,
    "nb_p": nb_padron_1,
    "nb_l": nb_lista_1,
}
dem_dict = {
    "jov_p": pjov_1,
    "jov_l": ljov_1,
    "may_p": pmay_1,
    "may_l": lmay_1,
    "nat_p": p_nat_1,
    "for_p": p_for_1,
    "n88_p": p_88_1,
    "n87_p": p_87_1,
}
desc_texto = f"Corte Reciente: {formatear_corte(corte_reciente)}"
if modo == "Comparar con Periodo Previo" and corte_base:
  desc_texto += f" frente a Base: {formatear_corte(corte_base)}"

if st.sidebar.button("📥 Generar Reporte PDF"):
  pdf_file = generar_pdf_reporte(
      titulo_alcance=nombre_header,
      desc_cortes=desc_texto,
      p1=p1,
      p2=p2,
      l1=l1,
      l2=l2,
      cob1=cob1,
      cob2=cob2,
      g_data=g_dict,
      dem_data=dem_dict,
      corte_rec=corte_reciente,
      corte_bas=corte_base if modo == "Comparar con Periodo Previo" else None,
      cve_ent=cve_entidad_activa,
      alcance_tipo=alcance,
  )
  st.sidebar.download_button(
      label="⬇️ Descargar PDF Oficial",
      data=pdf_file,
      file_name=f"Reporte_Analitico_DERFE_{corte_reciente}.pdf",
      mime="application/pdf",
  )