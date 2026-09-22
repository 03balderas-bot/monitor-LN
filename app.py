import streamlit as st
import pandas as pd
import sqlite3
import unicodedata
from pathlib import Path
from io import BytesIO
import matplotlib.pyplot as plt
import py7zr

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ==============================================================================
# EXTRACCIÓN AUTOMÁTICA DE LA BASE DE DATOS (.7Z) EN LA NUBE
# ==============================================================================
DIR_RAIZ = Path(__file__).resolve().parent
DB_PATH = DIR_RAIZ / "derfe_web.db"
ARCHIVE_7Z_PATH = DIR_RAIZ / "derfe_web.7z"
LOGO_PATH = DIR_RAIZ / "logo_ine.png"

if not DB_PATH.exists() and ARCHIVE_7Z_PATH.exists():
    with py7zr.SevenZipFile(ARCHIVE_7Z_PATH, mode='r') as z:
        z.extractall(path=DIR_RAIZ)

# ==============================================================================
# CONFIGURACIÓN DE PÁGINA Y ESTILO RESPONSIVO
# ==============================================================================
st.set_page_config(
    page_title="Monitor DERFE | Histórico Municipal/Distrital",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="auto"
)

@st.cache_resource
def get_conn():
    if not DB_PATH.exists():
        st.error(f"⚠️ Base de datos no encontrada en: {DB_PATH}. Asegúrate de incluir 'derfe_web.7z' en el repositorio.")
        st.stop()
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)

conn = get_conn()

# ==============================================================================
# ESTILOS CSS
# ==============================================================================
st.markdown("""
<style>
    .main-title { font-size: 1.6rem !important; font-weight: 800; margin-bottom: 0.1rem; line-height: 1.2; }
    .sub-title { color: #8A99AD; font-size: 0.88rem !important; margin-bottom: 0.5rem; }
    .footer-fuente { font-size: 0.78rem !important; color: #64748B; margin-top: 1.5rem; margin-bottom: 1rem; border-top: 1px solid #334155; padding-top: 0.5rem; }
    [data-testid="stMetricValue"] { font-size: 1.25rem !important; font-weight: 700; }
    [data-testid="stMetricLabel"] { font-size: 0.78rem !important; white-space: normal !important; }
</style>
""", unsafe_allow_html=True)

CATALOGO_ENTIDADES = {
    1: "AGUASCALIENTES", 2: "BAJA CALIFORNIA", 3: "BAJA CALIFORNIA SUR",
    4: "CAMPECHE", 5: "COAHUILA", 6: "COLIMA", 7: "CHIAPAS",
    8: "CHIHUAHUA", 9: "CIUDAD DE MEXICO", 10: "DURANGO", 11: "GUANAJUATO",
    12: "GUERRERO", 13: "HIDALGO", 14: "JALISCO", 15: "MEXICO",
    16: "MICHOACAN", 17: "MORELOS", 18: "NAYARIT", 19: "NUEVO LEON",
    20: "OAXACA", 21: "PUEBLA", 22: "QUERETARO", 23: "QUINTANA ROO",
    24: "SAN LUIS POTOSI", 25: "SINALOA", 26: "SONORA", 27: "TABASCO",
    28: "TAMAULIPAS", 29: "TLAXCALA", 30: "VERACRUZ", 31: "YUCATAN",
    32: "ZACATECAS"
}

# ==============================================================================
# MOTOR DE NORMALIZACIÓN Y BÚSQUEDA DE COLUMNAS
# ==============================================================================
def normalizar_txt(s):
    if not isinstance(s, str): return ""
    norm = ''.join(c for c in unicodedata.normalize('NFD', s.upper()) if unicodedata.category(c) != 'Mn')
    return norm.replace(" ", "_").replace(".", "").replace("\n", "_")

def col_exacta(tabla, kws_primary, kws_fallback=None):
    try:
        cols_db = pd.read_sql_query(f"PRAGMA table_info({tabla});", conn)['name'].tolist()
        for c in cols_db:
            if all(k in normalizar_txt(c) for k in kws_primary): return f'"{c}"'
        if kws_fallback:
            for c in cols_db:
                if all(k in normalizar_txt(c) for k in kws_fallback): return f'"{c}"'
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

def obtener_cortes_ordenados():
    try:
        tables_db = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist()
        tabla_fechas = 'PE_SEX' if 'PE_SEX' in tables_db else ('PE_EO' if 'PE_EO' in tables_db else None)
        if not tabla_fechas: return []
        
        df = pd.read_sql_query(f"SELECT DISTINCT FECHA_CORTE FROM {tabla_fechas}", conn)
        lista = [str(x) for x in df['FECHA_CORTE'].tolist()]
        def key_orden(val):
            if val.isdigit() and len(val) == 8:
                return (0, int(val))
            return (1, val)
        lista.sort(key=key_orden, reverse=True)
        return lista
    except Exception:
        return []

def consultar_datos_agregados_seguro(corte, condicion_sql):
    try:
        c_hp = col_exacta('PE_SEX', ['HOMBRE', 'PADRON'], ['HOMBRE', 'PAD'])
        c_hl = col_exacta('PE_SEX', ['HOMBRE', 'LISTA'], ['HOMBRE', 'LIS'])
        c_mp = col_exacta('PE_SEX', ['MUJER', 'PADRON'], ['MUJER', 'PAD'])
        c_ml = col_exacta('PE_SEX', ['MUJER', 'LISTA'], ['MUJER', 'LIS'])
        c_nbp = col_exacta('PE_SEX', ['BINARIO', 'PADRON'], ['NB', 'PAD'])
        c_nbl = col_exacta('PE_SEX', ['BINARIO', 'LISTA'], ['NB', 'LIS'])

        q_sex = f"""
            SELECT 
                COALESCE(SUM(CAST({c_hp} AS REAL)), 0) AS h_padron,
                COALESCE(SUM(CAST({c_hl} AS REAL)), 0) AS h_lista,
                COALESCE(SUM(CAST({c_mp} AS REAL)), 0) AS m_padron,
                COALESCE(SUM(CAST({c_ml} AS REAL)), 0) AS m_lista,
                COALESCE(SUM(CAST({c_nbp} AS REAL)), 0) AS nb_padron,
                COALESCE(SUM(CAST({c_nbl} AS REAL)), 0) AS nb_lista
            FROM PE_SEX
            WHERE FECHA_CORTE = '{corte}' {condicion_sql}
        """
        df_sex = pd.read_sql_query(q_sex, conn)

        c_pnat = col_exacta('PE_EO', ['PADRON', 'NATIVO'])
        c_lnat = col_exacta('PE_EO', ['LISTA', 'NATIVO'], ['LNE', 'NATIVO'])
        c_pfor = col_exacta('PE_EO', ['PADRON', 'FORANEO'])
        c_lfor = col_exacta('PE_EO', ['LISTA', 'FORANEO'], ['LNE', 'FORANEO'])
        c_p87 = col_exacta('PE_EO', ['PADRON', 'HIJO'], ['PADRON', 'MEXICANO'])
        c_l87 = col_exacta('PE_EO', ['LISTA', 'HIJO'], ['LNE', 'HIJO'])
        c_p88 = col_exacta('PE_EO', ['PADRON', 'NATURALIZADO'], ['PADRON', '88'])
        c_l88 = col_exacta('PE_EO', ['LISTA', 'NATURALIZADO'], ['LNE', 'NATURALIZADO'])

        q_eo = f"""
            SELECT 
                (COALESCE(SUM(CAST({c_pnat} AS REAL)), 0) + COALESCE(SUM(CAST({c_pfor} AS REAL)), 0) + COALESCE(SUM(CAST({c_p87} AS REAL)), 0) + COALESCE(SUM(CAST({c_p88} AS REAL)), 0)) AS padron_eo,
                (COALESCE(SUM(CAST({c_lnat} AS REAL)), 0) + COALESCE(SUM(CAST({c_lfor} AS REAL)), 0) + COALESCE(SUM(CAST({c_l87} AS REAL)), 0) + COALESCE(SUM(CAST({c_l88} AS REAL)), 0)) AS lista_eo
            FROM PE_EO
            WHERE FECHA_CORTE = '{corte}' {condicion_sql}
        """
        df_eo = pd.read_sql_query(q_eo, conn)

        h_p = int(df_sex['h_padron'].iloc[0]) if not df_sex.empty else 0
        m_p = int(df_sex['m_padron'].iloc[0]) if not df_sex.empty else 0
        nb_p = int(df_sex['nb_padron'].iloc[0]) if not df_sex.empty else 0
        
        h_l = int(df_sex['h_lista'].iloc[0]) if not df_sex.empty else 0
        m_l = int(df_sex['m_lista'].iloc[0]) if not df_sex.empty else 0
        nb_l = int(df_sex['nb_lista'].iloc[0]) if not df_sex.empty else 0

        pad_sex_total = h_p + m_p + nb_p
        pad_eo_total = int(df_eo['padron_eo'].iloc[0]) if not df_eo.empty else 0
        
        lis_sex_total = h_l + m_l + nb_l
        lis_eo_total = int(df_eo['lista_eo'].iloc[0]) if not df_eo.empty else 0

        pad_final = max(pad_sex_total, pad_eo_total)
        lis_final = max(lis_sex_total, lis_eo_total)

        return pd.DataFrame([{
            'padron': pad_final, 'lista': lis_final, 
            'h_padron': h_p, 'h_lista': h_l, 
            'm_padron': m_p, 'm_lista': m_l, 
            'nb_padron': nb_p, 'nb_lista': nb_l
        }])
    except Exception:
        return pd.DataFrame([{'padron':0, 'lista':0, 'h_padron':0, 'h_lista':0, 'm_padron':0, 'm_lista':0, 'nb_padron':0, 'nb_lista':0}])

# ==============================================================================
# FUNCIONES DE INTELIGENCIA VISUAL Y GRÁFICAS
# ==============================================================================
def generar_grafico_top_jovenes(corte):
    try:
        tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist()
        if 'PE_RE' in tables:
            c_jov = col_exacta('PE_RE', ['18_19', 'PADRON'], ['18_19'])
            if c_jov != "0":
                q = f"""
                    SELECT CLAVE_ENTIDAD, 
                           (SUM(CAST({c_jov} AS REAL)) * 100.0 / SUM(CAST(PADRON_NATIVO + PADRON_FORANEO + PADRON_NATURALIZADO AS REAL))) AS pct_jovenes
                    FROM PE_RE
                    WHERE FECHA_CORTE = ?
                    GROUP BY CLAVE_ENTIDAD
                    ORDER BY pct_jovenes DESC
                    LIMIT 5
                """
                df = pd.read_sql_query(q, conn, params=[corte])
                if not df.empty:
                    df['ENTIDAD'] = df['CLAVE_ENTIDAD'].map(CATALOGO_ENTIDADES)
                    plt.figure(figsize=(6.5, 2.2))
                    plt.barh(df['ENTIDAD'][::-1], df['pct_jovenes'][::-1], color='#10B981')
                    plt.title(f"Top 5 Entidades: Mayor % de Jóvenes (18-19 años) - {formatear_corte(corte)}", fontsize=9, fontweight='bold', color='#4A2E7A')
                    plt.xlabel("Porcentaje respecto al Padrón Estatal (%)", fontsize=8)
                    plt.xticks(fontsize=7.5)
                    plt.yticks(fontsize=8)
                    plt.tight_layout()
                    buf = BytesIO()
                    plt.savefig(buf, format='png', dpi=200)
                    plt.close()
                    buf.seek(0)
                    return buf
        
        q_alt = """
            SELECT CLAVE_ENTIDAD, (SUM(CAST("PADRON ELECTORAL" AS REAL)) * 100.0 / (SELECT SUM(CAST("PADRON ELECTORAL" AS REAL)) FROM PE_SEX WHERE FECHA_CORTE = ?)) as pct
            FROM PE_SEX WHERE FECHA_CORTE = ? GROUP BY CLAVE_ENTIDAD ORDER BY pct DESC LIMIT 5
        """
        df_alt = pd.read_sql_query(q_alt, conn, params=[corte, corte])
        if not df_alt.empty:
            df_alt['ENTIDAD'] = df_alt['CLAVE_ENTIDAD'].map(CATALOGO_ENTIDADES)
            plt.figure(figsize=(6.5, 2.2))
            plt.barh(df_alt['ENTIDAD'][::-1], df_alt['pct'][::-1], color='#10B981')
            plt.title(f"Top 5 Entidades con Mayor Padrón Electoral - {formatear_corte(corte)}", fontsize=9, fontweight='bold', color='#4A2E7A')
            plt.xlabel("Participación en el Padrón Nacional (%)", fontsize=8)
            plt.xticks(fontsize=7.5)
            plt.yticks(fontsize=8)
            plt.tight_layout()
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=200)
            plt.close()
            buf.seek(0)
            return buf
    except Exception:
        pass
    return None

def generar_grafico_top_mayores(corte):
    try:
        tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist()
        if 'PE_RE' in tables:
            c_may = col_exacta('PE_RE', ['65', 'PADRON'], ['65'])
            if c_may != "0":
                q = f"""
                    SELECT CLAVE_ENTIDAD, 
                           (SUM(CAST({c_may} AS REAL)) * 100.0 / SUM(CAST(PADRON_NATIVO + PADRON_FORANEO + PADRON_NATURALIZADO AS REAL))) AS pct_mayores
                    FROM PE_RE
                    WHERE FECHA_CORTE = ?
                    GROUP BY CLAVE_ENTIDAD
                    ORDER BY pct_mayores DESC
                    LIMIT 5
                """
                df = pd.read_sql_query(q, conn, params=[corte])
                if not df.empty:
                    df['ENTIDAD'] = df['CLAVE_ENTIDAD'].map(CATALOGO_ENTIDADES)
                    plt.figure(figsize=(6.5, 2.2))
                    plt.barh(df['ENTIDAD'][::-1], df['pct_mayores'][::-1], color='#F59E0B')
                    plt.title(f"Top 5 Entidades: Mayor % de Adultos Mayores (65+ años) - {formatear_corte(corte)}", fontsize=9, fontweight='bold', color='#4A2E7A')
                    plt.xlabel("Porcentaje respecto al Padrón Estatal (%)", fontsize=8)
                    plt.xticks(fontsize=7.5)
                    plt.yticks(fontsize=8)
                    plt.tight_layout()
                    buf = BytesIO()
                    plt.savefig(buf, format='png', dpi=200)
                    plt.close()
                    buf.seek(0)
                    return buf

        q_alt = """
            SELECT CLAVE_ENTIDAD, (SUM(CAST("LISTA NOMINAL" AS REAL)) * 100.0 / SUM(CAST("PADRON ELECTORAL" AS REAL))) as cob
            FROM PE_SEX WHERE FECHA_CORTE = ? GROUP BY CLAVE_ENTIDAD ORDER BY cob DESC LIMIT 5
        """
        df_alt = pd.read_sql_query(q_alt, conn, params=[corte])
        if not df_alt.empty:
            df_alt['ENTIDAD'] = df_alt['CLAVE_ENTIDAD'].map(CATALOGO_ENTIDADES)
            plt.figure(figsize=(6.5, 2.2))
            plt.barh(df_alt['ENTIDAD'][::-1], df_alt['cob'][::-1], color='#F59E0B')
            plt.title(f"Top 5 Entidades con Mayor Cobertura Registral (%) - {formatear_corte(corte)}", fontsize=9, fontweight='bold', color='#4A2E7A')
            plt.xlabel("Cobertura Registral (%)", fontsize=8)
            plt.xticks(fontsize=7.5)
            plt.yticks(fontsize=8)
            plt.tight_layout()
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=200)
            plt.close()
            buf.seek(0)
            return buf
    except Exception:
        pass
    return None

def generar_grafico_top_extranjero(corte):
    try:
        q = f"""
            SELECT CLAVE_ENTIDAD, 
                   (SUM(CAST(PADRON_NATIVO + PADRON_FORANEO + PADRON_NATURALIZADO AS REAL)) * 100.0 / 
                   (SELECT SUM(CAST(PADRON_NATIVO + PADRON_FORANEO + PADRON_NATURALIZADO AS REAL)) FROM PE_EO WHERE FECHA_CORTE = ? AND CLAVE_MUNICIPIO = 0)) AS pct_ext
            FROM PE_EO
            WHERE FECHA_CORTE = ? AND CLAVE_MUNICIPIO = 0
            GROUP BY CLAVE_ENTIDAD
            ORDER BY pct_ext DESC
            LIMIT 5
        """
        df = pd.read_sql_query(q, conn, params=[corte, corte])
        if df.empty: return None
        df['ENTIDAD'] = df['CLAVE_ENTIDAD'].map(CATALOGO_ENTIDADES)
        
        plt.figure(figsize=(6.5, 2.2))
        plt.barh(df['ENTIDAD'][::-1], df['pct_ext'][::-1], color='#8C62B6')
        plt.title(f"Top 5 Entidades: Mayor % de Padrón en el Extranjero (ID 0) - {formatear_corte(corte)}", fontsize=9, fontweight='bold', color='#4A2E7A')
        plt.xlabel("Participación Porcentual Nacional en el Extranjero (%)", fontsize=8)
        plt.xticks(fontsize=7.5)
        plt.yticks(fontsize=8)
        plt.tight_layout()
        
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=200)
        plt.close()
        buf.seek(0)
        return buf
    except Exception:
        return None

def generar_grafico_distritos_negativos(corte_rec, corte_bas):
    try:
        if not corte_bas: return None
        q = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST(PADRON_NATIVO + PADRON_FORANEO + PADRON_NATURALIZADO AS REAL)) as padron
            FROM PE_EO
            WHERE FECHA_CORTE = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
        df_rec = pd.read_sql_query(q, conn, params=[corte_rec])
        df_bas = pd.read_sql_query(q, conn, params=[corte_bas])
        
        df_merged = pd.merge(df_rec, df_bas, on=['CLAVE_ENTIDAD', 'CLAVE_DISTRITO'], suffixes=('_rec', '_bas'))
        df_merged['pct_crecimiento'] = ((df_merged['padron_rec'] - df_merged['padron_bas']) / df_merged['padron_bas']) * 100
        
        df_negativos = df_merged.sort_values(by='pct_crecimiento', ascending=True).head(15)
        if df_negativos.empty: return None
        
        df_negativos['etiqueta'] = df_negativos['CLAVE_ENTIDAD'].map(CATALOGO_ENTIDADES) + " - Dist. " + df_negativos['CLAVE_DISTRITO'].astype(str)
        
        plt.figure(figsize=(6.5, 3.2))
        plt.barh(df_negativos['etiqueta'][::-1], df_negativos['pct_crecimiento'][::-1], color='#EF4444')
        plt.title(f"Top 15 Distritos con Mayor Decremento / Crecimiento Negativo (%)", fontsize=9, fontweight='bold', color='#4A2E7A')
        plt.xlabel("Variación Porcentual (%)", fontsize=8)
        plt.xticks(fontsize=7.5)
        plt.yticks(fontsize=7.0)
        plt.tight_layout()
        
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=200)
        plt.close()
        buf.seek(0)
        return buf
    except Exception:
        return None

def generar_grafico_distritos_positivos(corte_rec, corte_bas):
    try:
        if not corte_bas: return None
        q = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST(PADRON_NATIVO + PADRON_FORANEO + PADRON_NATURALIZADO AS REAL)) as padron
            FROM PE_EO
            WHERE FECHA_CORTE = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
        df_rec = pd.read_sql_query(q, conn, params=[corte_rec])
        df_bas = pd.read_sql_query(q, conn, params=[corte_bas])
        
        df_merged = pd.merge(df_rec, df_bas, on=['CLAVE_ENTIDAD', 'CLAVE_DISTRITO'], suffixes=('_rec', '_bas'))
        df_merged['pct_crecimiento'] = ((df_merged['padron_rec'] - df_merged['padron_bas']) / df_merged['padron_bas']) * 100
        
        df_positivos = df_merged.sort_values(by='pct_crecimiento', ascending=False).head(15)
        if df_positivos.empty: return None
        
        df_positivos['etiqueta'] = df_positivos['CLAVE_ENTIDAD'].map(CATALOGO_ENTIDADES) + " - Dist. " + df_positivos['CLAVE_DISTRITO'].astype(str)
        
        plt.figure(figsize=(6.5, 3.2))
        plt.barh(df_positivos['etiqueta'][::-1], df_positivos['pct_crecimiento'][::-1], color='#10B981')
        plt.title(f"Top 15 Distritos con Mayor Crecimiento Positivo (%)", fontsize=9, fontweight='bold', color='#4A2E7A')
        plt.xlabel("Variación Porcentual (%)", fontsize=8)
        plt.xticks(fontsize=7.5)
        plt.yticks(fontsize=7.0)
        plt.tight_layout()
        
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=200)
        plt.close()
        buf.seek(0)
        return buf
    except Exception:
        return None

# ==============================================================================
# FUNCIÓN GENERADORA DE REPORTE PDF EJECUTIVO CENTRADO Y MULTIPÁGINA (2 HOJAS)
# ==============================================================================
def generar_pdf_reporte(titulo_alcance, desc_cortes, p1, p2, l1, l2, cob1, cob2, g_data, dem_data, corte_rec, corte_bas, cve_ent, alcance_tipo):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    
    styles = getSampleStyleSheet()
    ine_purple = colors.HexColor('#5C3A92')
    ine_dark = colors.HexColor('#4A2E7A')
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=12, textColor=ine_dark, spaceAfter=2, fontName='Helvetica-Bold', alignment=1)
    subtitle_style = ParagraphStyle('SubTitleStyle', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#64748B'), spaceAfter=6, fontName='Helvetica', alignment=1)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontSize=9.5, textColor=ine_dark, spaceBefore=6, spaceAfter=3, fontName='Helvetica-Bold')
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#334155'), spaceAfter=4, leading=11, fontName='Helvetica')
    warning_style = ParagraphStyle('WarningStyle', parent=styles['Normal'], fontSize=7.5, textColor=colors.HexColor('#B91C1C'), spaceAfter=6, leading=10, fontName='Helvetica-Oblique', alignment=1)
    footer_style = ParagraphStyle('FooterStyle', parent=styles['Normal'], fontSize=7, textColor=colors.HexColor('#64748B'), leading=9, fontName='Helvetica-Oblique', alignment=1)
    sign_style = ParagraphStyle('SignStyle', parent=styles['Normal'], fontSize=10, textColor=ine_dark, alignment=2, fontName='Helvetica-Oblique', spaceBefore=8)
    
    if LOGO_PATH.exists():
        img_logo = Image(str(LOGO_PATH), width=110, height=35)
        header_table = Table([[img_logo, Paragraph("<b>INSTITUTO NACIONAL ELECTORAL</b><br/><font size=7 color='#5C3A92'>Dirección Ejecutiva del Registro Federal de Electores</font>", ParagraphStyle('HText', parent=styles['Normal'], fontSize=8, leading=10, alignment=1))]], colWidths=[120, 384])
        header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        story.append(header_table)
    else:
        story.append(Paragraph("INSTITUTO NACIONAL ELECTORAL", ParagraphStyle('INE', fontName='Helvetica-Bold', fontSize=8, textColor=ine_purple, spaceAfter=2, alignment=1)))
    
    story.append(Paragraph("Reporte Ejecutivo, Análisis Estructural y Top Geográfico", title_style))
    story.append(Paragraph(f"<b>Ámbito Geográfico:</b> {titulo_alcance} | {desc_cortes}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.2, color=ine_purple, spaceAfter=6))
    
    txt_advertencia = (
        "<b>⚠️ Nota Metodológica de Validación:</b> La nueva demarcación distrital federal entró en vigor a partir de los "
        "cortes de mediados de 2023 (ej. Puebla ganó un distrito, pasando de 15 a 16 distritos). "
        "Se recomienda extremar precaución y comparar únicamente entre semanas operativas que compartan la misma distritación "
        "para evitar distorsiones territoriales."
    )
    story.append(Paragraph(txt_advertencia, warning_style))
    
    story.append(Paragraph("1. Resumen Ejecutivo y Totales Superiores", heading_style))
    dif_p = p1 - p2
    pct_p = (dif_p / p2 * 100) if p2 > 0 else 0
    dif_l = l1 - l2
    pct_l = (dif_l / l2 * 100) if l2 > 0 else 0
    
    txt_totales = (
        f"En el análisis comparativo, el <b>Padrón Electoral</b> registra un total de <b>{p1:,.0f}</b> personas, "
        f"lo que representa una variación de <b>{dif_p:+,.0f}</b> registros ({pct_p:+.2f}%) respecto al periodo base. "
        f"Por su parte, la <b>Lista Nominal</b> asciende a <b>{l1:,.0f}</b> ciudadanos, "
        f"reflejando un cambio de <b>{dif_l:+,.0f}</b> registros ({pct_l:+.2f}%). "
        f"La cobertura registral actual se sitúa en <b>{cob1:.2f}%</b>."
    )
    story.append(Paragraph(txt_totales, body_style))
    
    story.append(Paragraph("2. Composición Porcentual del Padrón y Lista Electoral por Origen", heading_style))
    nat_p, for_p, n88_p, n87_p = dem_data['nat_p'], dem_data['for_p'], dem_data['n88_p'], dem_data['n87_p']
    tot_p_eo = nat_p + for_p + n88_p + n87_p if (nat_p + for_p + n88_p + n87_p) > 0 else 1
    
    p_nat_pct = (nat_p / tot_p_eo) * 100
    p_for_pct = (for_p / tot_p_eo) * 100
    p_88_pct  = (n88_p / tot_p_eo) * 100
    p_87_pct  = (n87_p / tot_p_eo) * 100
    
    txt_origen_comp = (
        f"A nivel estructural, la composición porcentual del <b>Padrón Electoral</b> se distribuye en: "
        f"<b>Nativos</b> ({p_nat_pct:.2f}% / {nat_p:,.0f}), "
        f"<b>Foráneos</b> ({p_for_pct:.2f}% / {for_p:,.0f}), "
        f"<b>Naturalizados 88</b> ({p_88_pct:.2f}% / {n88_p:,.0f}), e "
        f"<b>Hijos de Mexicanos 87</b> ({p_87_pct:.2f}% / {n87_p:,.0f})."
    )
    story.append(Paragraph(txt_origen_comp, body_style))
    
    story.append(Paragraph("3. Estructura Demográfica y Desglose por Género", heading_style))
    h_p1, h_l1, m_p1, m_l1 = g_data['h_p'], g_data['h_l'], g_data['m_p'], g_data['m_l']
    txt_genero = (
        f"• <b>Hombres:</b> Padrón de {h_p1:,.0f} | Lista de {h_l1:,.0f} (Cob: {(h_l1/h_p1*100) if h_p1>0 else 0:.2f}%).<br/>"
        f"• <b>Mujeres:</b> Padrón de {m_p1:,.0f} | Lista de {m_l1:,.0f} (Cob: {(m_l1/m_p1*100) if m_p1>0 else 0:.2f}%)."
    )
    story.append(Paragraph(txt_genero, body_style))
    
    # SALTO A LA SEGUNDA PÁGINA
    story.append(PageBreak())
    
    story.append(Paragraph("4. Radiografía Demográfica y Rankings Nacionales (Porcentajes)", heading_style))
    
    def agregar_imagen_centrada(buf_img, w=410, h=130):
        if buf_img:
            t_img = Table([[Image(buf_img, width=w, height=h)]], colWidths=[504])
            t_img.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
            story.append(t_img)
            story.append(Spacer(1, 4))

    img_jov = generar_grafico_top_jovenes(corte_rec)
    agregar_imagen_centrada(img_jov, 410, 120)
    
    img_may = generar_grafico_top_mayores(corte_rec)
    agregar_imagen_centrada(img_may, 410, 120)
    
    img_ext = generar_grafico_top_extranjero(corte_rec)
    agregar_imagen_centrada(img_ext, 410, 120)
    
    if corte_bas:
        img_neg = generar_grafico_distritos_negativos(corte_rec, corte_bas)
        agregar_imagen_centrada(img_neg, 410, 160)

        img_pos = generar_grafico_distritos_positivos(corte_rec, corte_bas)
        agregar_imagen_centrada(img_pos, 410, 160)

    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#CBD5E1'), spaceAfter=4))
    txt_fuente_pdf = "Datos oficiales extraídos de la plataforma de Datos Abiertos del INE: https://ine.mx/transparencia/datos-abiertos/#/tematica/padron-electoral"
    story.append(Paragraph(txt_fuente_pdf, footer_style))
    story.append(Paragraph("Baez", sign_style))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# ==============================================================================
# BARRA LATERAL Y COMPONENTES DEL DASHBOARD (OMITIENDO AUDITORÍAS OBSOLETAS)
# ==============================================================================
with st.sidebar:
    st.markdown("### Configuración del Monitor")
    
    cortes_lista = obtener_cortes_ordenados()
    if not cortes_lista:
        st.error(f"⚠️ No se encontraron registros en la base de datos.")
        st.stop()

    modo = st.radio("Objetivo:", ["Corte Actual", "Comparar con Periodo Previo"], index=0, key="radio_objetivo")
    
    corte_reciente = st.selectbox(
        "Corte Principal (Reciente):", 
        cortes_lista, 
        index=0, 
        format_func=lambda x: formatear_corte(x),
        key="sel_corte_reciente"
    )

    corte_base = None
    if modo == "Comparar con Periodo Previo":
        idx_base = cortes_lista.index("PEF_2024") if "PEF_2024" in cortes_lista else (1 if len(cortes_lista) > 1 else 0)
        corte_base = st.selectbox(
            "Corte Base a Comparar (Se recomienda 2024+ para misma distritación):", 
            cortes_lista, 
            index=idx_base, 
            format_func=lambda x: formatear_corte(x),
            key="sel_corte_base"
        )

    st.markdown("---")
    alcance = st.radio(
        "Ámbito Geográfico:", 
        [
            "Total Nacional + Extranjero",
            "Nacional (Sin Residentes en el Extranjero ID 0)",
            "Solo Residentes en el Extranjero (ID 0)",
            "Entidad Federativa Específica"
        ],
        index=0,
        key="radio_alcance"
    )
    
    sql_filtro_local = ""
    nombre_header = "Total Nacional + Extranjero"
    cve_entidad_activa = None
    cve_distrito_activo = None
    mun_elegido_val = None
    nivel_geografico = None

    tables_db_sidebar = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist()
    tabla_geo_sidebar = 'PE_EO' if 'PE_EO' in tables_db_sidebar else None

    col_dist_db = None
    if tabla_geo_sidebar:
        col_dist_db = col_exacta(tabla_geo_sidebar, ['DISTRITO'])
        if col_dist_db == "0": col_dist_db = None

    if alcance == "Entidad Federativa Específica":
        st.markdown("---")
        cve = st.selectbox(
            "Selecciona Entidad:",
            options=list(CATALOGO_ENTIDADES.keys()),
            format_func=lambda x: f"{x:02d} - {CATALOGO_ENTIDADES[x]}",
            index=19, 
            key="sel_entidad_id"
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
                "Municipio Específico"
            ],
            index=0,
            key="radio_nivel_geo"
        )

        if nivel_geografico == "Total Entidad (Municipios + Extranjero)":
            sql_filtro_local = f"AND CLAVE_ENTIDAD = {cve}"
            nombre_header = f"{nom_ent} [Total Estatal]"
        elif nivel_geografico == "Por Distrito Específico":
            if col_dist_db and tabla_geo_sidebar:
                q_dists = f"SELECT DISTINCT {col_dist_db} AS DISTRITO FROM {tabla_geo_sidebar} WHERE CLAVE_ENTIDAD = {cve} ORDER BY {col_dist_db} ASC"
                try:
                    df_dists = pd.read_sql_query(q_dists, conn)
                    opciones_dists = [int(x) for x in df_dists['DISTRITO'].dropna().tolist() if int(x) != 0]
                except Exception:
                    opciones_dists = list(range(1, 11))
            else:
                opciones_dists = list(range(1, 11))

            cve_distrito_activo = st.selectbox("Selecciona Distrito:", options=opciones_dists, format_func=lambda x: f"Distrito Federal {x:02d}", key="sel_distrito")
            if col_dist_db:
                sql_filtro_local = f"AND CLAVE_ENTIDAD = {cve} AND {col_dist_db} = {cve_distrito_activo}"
            else:
                sql_filtro_local = f"AND CLAVE_ENTIDAD = {cve}"
            nombre_header = f"{nom_ent} [Distrito Federal {cve_distrito_activo:02d}]"
        elif nivel_geografico == "Solo Municipios (Sin Extranjero ID 0)":
            sql_filtro_local = f"AND CLAVE_ENTIDAD = {cve} AND CLAVE_MUNICIPIO != 0"
            nombre_header = f"{nom_ent} [Territorio Estatal sin Extranjero]"
        elif nivel_geografico == "Solo Extranjero (ID 0)":
            sql_filtro_local = f"AND CLAVE_ENTIDAD = {cve} AND CLAVE_MUNICIPIO = 0"
            nombre_header = f"{nom_ent} [Residentes en el Extranjero]"
        elif nivel_geografico == "Municipio Específico":
            c_nom_mun = col_exacta(tabla_geo_sidebar, ['NOMBRE', 'MUNICIPIO'], ['MUNICIPIO']) if tabla_geo_sidebar else "0"
            try:
                if c_nom_mun != "0":
                    q_muns = f"SELECT CLAVE_MUNICIPIO, MAX({c_nom_mun}) AS NOMBRE_MUNICIPIO FROM {tabla_geo_sidebar} WHERE CLAVE_ENTIDAD = {cve} GROUP BY CLAVE_MUNICIPIO ORDER BY CLAVE_MUNICIPIO ASC"
                else:
                    q_muns = f"SELECT DISTINCT CLAVE_MUNICIPIO, 'Municipio ' || CLAVE_MUNICIPIO AS NOMBRE_MUNICIPIO FROM {tabla_geo_sidebar} WHERE CLAVE_ENTIDAD = {cve} ORDER BY CLAVE_MUNICIPIO ASC"
                df_muns = pd.read_sql_query(q_muns, conn)
                opciones_mun = [(int(row['CLAVE_MUNICIPIO']), str(row['NOMBRE_MUNICIPIO'])) for _, row in df_muns.iterrows() if pd.notnull(row['CLAVE_MUNICIPIO'])]
            except Exception:
                opciones_mun = []

            dict_nombres = dict(opciones_mun)
            mun_elegido_val = st.selectbox(
                "Selecciona Municipio:", 
                options=[item[0] for item in opciones_mun] or [0], 
                format_func=lambda x: "0 - Residentes en el Extranjero" if int(x) == 0 else f"{int(x):03d} - {dict_nombres.get(int(x), 'Desconocido')}", 
                key="sel_municipio"
            )
            sql_filtro_local = f"AND CLAVE_ENTIDAD = {cve} AND CLAVE_MUNICIPIO = {mun_elegido_val}"
            nombre_header = f"{nom_ent} [{dict_nombres.get(int(mun_elegido_val), f'Municipio ID {mun_elegido_val}')}]"

    elif alcance == "Total Nacional + Extranjero":
        sql_filtro_local = ""
        nombre_header = "Consolidado Nacional + Extranjero"
    elif alcance == "Nacional (Sin Residentes en el Extranjero ID 0)":
        sql_filtro_local = "AND CLAVE_MUNICIPIO != 0"
        nombre_header = "Territorio Nacional (Excluyendo ID 0)"
    elif alcance == "Solo Residentes en el Extranjero (ID 0)":
        sql_filtro_local = "AND CLAVE_MUNICIPIO = 0"
        nombre_header = "Residentes en el Extranjero (Todos los Estados)"

where_aux_str = f"FECHA_CORTE = '{corte_reciente}'"
where_aux_base_str = f"FECHA_CORTE = '{corte_base}'" if corte_base else ""

if alcance == "Nacional (Sin Residentes en el Extranjero ID 0)":
    where_aux_str += " AND CLAVE_MUNICIPIO != 0"
    if where_aux_base_str: where_aux_base_str += " AND CLAVE_MUNICIPIO != 0"
elif alcance == "Solo Residentes en el Extranjero (ID 0)":
    where_aux_str += " AND CLAVE_MUNICIPIO = 0"
    if where_aux_base_str: where_aux_base_str += " AND CLAVE_MUNICIPIO = 0"

if cve_entidad_activa is not None:
    where_aux_str += f" AND CLAVE_ENTIDAD = {cve_entidad_activa}"
    if where_aux_base_str: where_aux_base_str += f" AND CLAVE_ENTIDAD = {cve_entidad_activa}"
    if nivel_geografico == "Solo Municipios (Sin Extranjero ID 0)":
        where_aux_str += " AND CLAVE_MUNICIPIO != 0"
        if where_aux_base_str: where_aux_base_str += " AND CLAVE_MUNICIPIO != 0"
    elif nivel_geografico == "Solo Extranjero (ID 0)":
        where_aux_str += " AND CLAVE_MUNICIPIO = 0"
        if where_aux_base_str: where_aux_base_str += " AND CLAVE_MUNICIPIO = 0"

if cve_distrito_activo is not None:
    where_aux_str += f" AND CLAVE_DISTRITO = {cve_distrito_activo}"
    if where_aux_base_str: where_aux_base_str += f" AND CLAVE_DISTRITO = {cve_distrito_activo}"
elif mun_elegido_val is not None:
    where_aux_str += f" AND CLAVE_MUNICIPIO = {mun_elegido_val}"
    if where_aux_base_str: where_aux_base_str += f" AND CLAVE_MUNICIPIO = {mun_elegido_val}"

st.markdown(f"<div class='main-title'>Padrón Electoral y Lista Nominal: {nombre_header}</div>", unsafe_allow_html=True)
if modo == "Comparar con Periodo Previo" and corte_base:
    st.markdown(f"<div class='sub-title'>Evolución histórica: Corte Reciente (<b>{formatear_corte(corte_reciente)}</b>) frente a Corte Base (<b>{formatear_corte(corte_base)}</b>)</div>", unsafe_allow_html=True)
else:
    st.markdown(f"<div class='sub-title'>Corte de operación analizado: <b>{formatear_corte(corte_reciente)}</b></div>", unsafe_allow_html=True)

df_m1 = consultar_datos_agregados_seguro(corte_reciente, sql_filtro_local)
p1 = int(df_m1['padron'].iloc[0] or 0)
l1 = int(df_m1['lista'].iloc[0] or 0)
cob1 = (l1 / p1 * 100) if p1 > 0 else 0

p2, l2, cob2 = p1, l1, cob1
if modo == "Comparar con Periodo Previo" and corte_base:
    df_m2 = consultar_datos_agregados_seguro(corte_base, sql_filtro_local)
    p2 = int(df_m2['padron'].iloc[0] or 0)
    l2 = int(df_m2['lista'].iloc[0] or 0)
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
st.markdown("#### Desglose por Género")
h_padron_1 = int(df_m1['h_padron'].iloc[0] or 0)
h_lista_1 = int(df_m1['h_lista'].iloc[0] or 0)
m_padron_1 = int(df_m1['m_padron'].iloc[0] or 0)
m_lista_1 = int(df_m1['m_lista'].iloc[0] or 0)
nb_padron_1 = int(df_m1['nb_padron'].iloc[0] or 0)
nb_lista_1 = int(df_m1['nb_lista'].iloc[0] or 0)

hcob_1 = (h_lista_1 / h_padron_1 * 100) if h_padron_1 > 0 else 0
mcob_1 = (m_lista_1 / m_padron_1 * 100) if m_padron_1 > 0 else 0
nbcob_1 = (nb_lista_1 / nb_padron_1 * 100) if nb_padron_1 > 0 else 0

if modo == "Comparar con Periodo Previo" and corte_base:
    h_padron_2 = int(df_m2['h_padron'].iloc[0] or 0)
    h_lista_2 = int(df_m2['h_lista'].iloc[0] or 0)
    m_padron_2 = int(df_m2['m_padron'].iloc[0] or 0)
    m_lista_2 = int(df_m2['m_lista'].iloc[0] or 0)
    nb_padron_2 = int(df_m2['nb_padron'].iloc[0] or 0)
    nb_lista_2 = int(df_m2['nb_lista'].iloc[0] or 0)

    dh_p = h_padron_1 - h_padron_2
    pct_hp = (dh_p / h_padron_2 * 100) if h_padron_2 > 0 else 0
    dh_l = h_lista_1 - h_lista_2
    pct_hl = (dh_l / h_lista_2 * 100) if h_lista_2 > 0 else 0

    dm_p = m_padron_1 - m_padron_2
    pct_mp = (dm_p / m_padron_2 * 100) if m_padron_2 > 0 else 0
    dm_l = m_lista_1 - m_lista_2
    pct_ml = (dm_l / m_lista_2 * 100) if m_lista_2 > 0 else 0

    dnb_p = nb_padron_1 - nb_padron_2
    pct_nbp = (dnb_p / nb_padron_2 * 100) if nb_padron_2 > 0 else 0
    dnb_l = nb_lista_1 - nb_lista_2
    pct_nbl = (dnb_l / nb_lista_2 * 100) if nb_lista_2 > 0 else 0

    gh1, gh2, gh3 = st.columns(3)
    with gh1:
        st.markdown("**👨 Hombres**")
        st.metric("Padrón", f"{h_padron_1:,}", f"{dh_p:+,} ({pct_hp:+.2f}%)")
        st.metric("Lista Nominal", f"{h_lista_1:,}", f"{dh_l:+,} ({pct_hl:+.2f}%)")
        st.text(f"Cobertura: {hcob_1:.2f}%")
    with gh2:
        st.markdown("**👩 Mujeres**")
        st.metric("Padrón", f"{m_padron_1:,}", f"{dm_p:+,} ({pct_mp:+.2f}%)")
        st.metric("Lista Nominal", f"{m_lista_1:,}", f"{dm_l:+,} ({pct_ml:+.2f}%)")
        st.text(f"Cobertura: {mcob_1:.2f}%")
    with gh3:
        st.markdown("**⚧ No Binarios**")
        st.metric("Padrón", f"{nb_padron_1:,}", f"{dnb_p:+,} ({pct_nbp:+.2f}%)")
        st.metric("Lista Nominal", f"{nb_lista_1:,}", f"{dnb_l:+,} ({pct_nbl:+.2f}%)")
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
st.markdown("### Contexto Demográfico y Analítico")

tab_jovenes, tab_mayores, tab_origen = st.tabs([
    "🌱 Jóvenes de 18 y 19 Años", 
    "👴 Población de 65 Años y Más",
    "📋 Entidad de Origen y Claves Especiales"
])

tables_db = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist()
target_re = 'PE_RE' if 'PE_RE' in tables_db else None
target_eo = 'PE_EO' if 'PE_EO' in tables_db else None

pjov_1, ljov_1 = 0, 0
pmay_1, lmay_1 = 0, 0
p_nat_1, l_nat_1, p_for_1, l_for_1, p_87_1, l_87_1, p_88_1, l_88_1 = 0, 0, 0, 0, 0, 0, 0, 0

with tab_jovenes:
    if target_re:
        c_jov_p = col_exacta(target_re, ['18_19', 'PADRON'], ['18_19'])
        c_jov_l = col_exacta(target_re, ['18_19', 'LISTA'], ['LNE', '18_19'])
        q = f'SELECT SUM(CAST({c_jov_p} AS REAL)) AS p, SUM(CAST({c_jov_l} AS REAL)) AS l FROM {target_re} WHERE {where_aux_str}'
        try:
            df_tmp = pd.read_sql_query(q, conn)
            pjov_1 = int(df_tmp['p'].iloc[0] or 0)
            ljov_1 = int(df_tmp['l'].iloc[0] or 0)
        except Exception: pass
    cobjov_1 = (ljov_1 / pjov_1 * 100) if pjov_1 > 0 else 0
    j1, j2, j3, j4 = st.columns(4)
    j1.metric("Padrón (18-19 años)", f"{pjov_1:,}")
    j2.metric("Lista Nominal (18-19 años)", f"{ljov_1:,}")
    j3.metric("Cobertura Registral", f"{cobjov_1:.2f}%")
    j4.metric("Peso en Padrón / Lista Total", f"{(pjov_1/p1*100) if p1>0 else 0:.2f}% / {(ljov_1/l1*100) if l1>0 else 0:.2f}%")

with tab_mayores:
    if target_re:
        c_may_p = col_exacta(target_re, ['65', 'PADRON'], ['65'])
        c_may_l = col_exacta(target_re, ['65', 'LISTA'], ['LNE', '65'])
        q = f'SELECT SUM(CAST({c_may_p} AS REAL)) AS p, SUM(CAST({c_may_l} AS REAL)) AS l FROM {target_re} WHERE {where_aux_str}'
        try:
            df_tmp = pd.read_sql_query(q, conn)
            pmay_1 = int(df_tmp['p'].iloc[0] or 0)
            lmay_1 = int(df_tmp['l'].iloc[0] or 0)
        except Exception: pass
    cobmay_1 = (lmay_1 / pmay_1 * 100) if pmay_1 > 0 else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Padrón (65 años y más)", f"{pmay_1:,}")
    m2.metric("Lista Nominal (65 años y más)", f"{lmay_1:,}")
    m3.metric("Cobertura Registral", f"{cobmay_1:.2f}%")
    m4.metric("Peso en Padrón / Lista Total", f"{(pmay_1/p1*100) if p1>0 else 0:.2f}% / {(lmay_1/l1*100) if l1>0 else 0:.2f}%")

with tab_origen:
    st.markdown("#### Consolidado de Origen, Extranjero y Claves Especiales (PE_EO)")
    if target_eo:
        try:
            filtro_eo_sql = "1=1"
            params_eo = []
            if alcance == "Nacional (Sin Residentes en el Extranjero ID 0)":
                filtro_eo_sql += " AND CLAVE_MUNICIPIO != 0"
            elif alcance == "Solo Residentes en el Extranjero (ID 0)":
                filtro_eo_sql += " AND CLAVE_MUNICIPIO = 0"
            if cve_entidad_activa is not None:
                filtro_eo_sql += " AND CLAVE_ENTIDAD = ?"
                params_eo.append(cve_entidad_activa)

            cols_eo_db = pd.read_sql_query(f"PRAGMA table_info({target_eo});", conn)['name'].tolist()
            def buscar_col(keywords, exclusion=[]):
                for c in cols_eo_db:
                    c_norm = normalizar_txt(c)
                    if all(kw in c_norm for kw in keywords) and not any(ex in c_norm for ex in exclusion):
                        return f'"{c}"'
                return "0"

            c_pnat = buscar_col(['PADRON', 'NATIVO'])
            c_lnat = buscar_col(['LISTA', 'NATIVO'], ['PADRON'])
            if c_lnat == "0": c_lnat = buscar_col(['LNE', 'NATIVO'])
            c_pfor = buscar_col(['PADRON', 'FORANEO'])
            c_lfor = buscar_col(['LISTA', 'FORANEO'], ['PADRON'])
            if c_lfor == "0": c_lfor = buscar_col(['LNE', 'FORANEO'])
            c_p87 = buscar_col(['PADRON', '87'])
            if c_p87 == "0": c_p87 = buscar_col(['PADRON', 'HIJO'])
            c_l87 = buscar_col(['LISTA', '87'])
            if c_l87 == "0": c_l87 = buscar_col(['LISTA', 'HIJO'])
            c_p88 = buscar_col(['PADRON', '88'])
            if c_p88 == "0": c_p88 = buscar_col(['PADRON', 'NATURALIZADO'])
            c_l88 = buscar_col(['LISTA', '88'])
            if c_l88 == "0": c_l88 = buscar_col(['LISTA', 'NATURALIZADO'])

            q_eo = f"""
                SELECT 
                    SUM(CAST({c_pnat} AS REAL)) AS p_nat, SUM(CAST({c_lnat} AS REAL)) AS l_nat,
                    SUM(CAST({c_pfor} AS REAL)) AS p_for, SUM(CAST({c_lfor} AS REAL)) AS l_for,
                    SUM(CAST({c_p87} AS REAL)) AS p_87, SUM(CAST({c_l87} AS REAL)) AS l_87,
                    SUM(CAST({c_p88} AS REAL)) AS p_88, SUM(CAST({c_l88} AS REAL)) AS l_88
                FROM {target_eo}
                WHERE FECHA_CORTE = ? AND {filtro_eo_sql}
            """
            df_eo = pd.read_sql_query(q_eo, conn, params=[str(corte_reciente)] + params_eo)
            p_nat_1 = int(df_eo['p_nat'].iloc[0] or 0)
            l_nat_1 = int(df_eo['l_nat'].iloc[0] or 0)
            p_for_1 = int(df_eo['p_for'].iloc[0] or 0)
            l_for_1 = int(df_eo['l_for'].iloc[0] or 0)
            p_87_1  = int(df_eo['p_87'].iloc[0] or 0)
            l_87_1  = int(df_eo['l_87'].iloc[0] or 0)
            p_88_1  = int(df_eo['p_88'].iloc[0] or 0)
            l_88_1  = int(df_eo['l_88'].iloc[0] or 0)

            p_nat_pct = (p_nat_1 / p1 * 100) if p1 > 0 else 0
            p_for_pct = (p_for_1 / p1 * 100) if p1 > 0 else 0
            p_88_pct  = (p_88_1  / p1 * 100) if p1 > 0 else 0
            p_87_pct  = (p_87_1  / p1 * 100) if p1 > 0 else 0

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Padrón Nativo", f"{p_nat_1:,}", f"{p_nat_pct:.2f}% del Padrón")
                st.metric("Padrón Foráneo", f"{p_for_1:,}", f"{p_for_pct:.2f}% del Padrón")
            with c2:
                st.metric("Padrón Naturalizado (88)", f"{p_88_1:,}", f"{p_88_pct:.2f}% del Padrón")
                st.metric("Padrón Hijos de Mex (87)", f"{p_87_1:,}", f"{p_87_pct:.2f}% del Padrón")
            with c3:
                st.caption(f"**Padrón Electoral Superior**: {p1:,}")
                st.caption(f"**Lista Nominal Superior**: {l1:,}")
        except Exception:
            pass

st.markdown(
    "<div class='footer-fuente'>📊 Datos oficiales extraídos de la plataforma de Datos Abiertos del INE: "
    "<a href='https://ine.mx/transparencia/datos-abiertos/#/tematica/padron-electoral' target='_blank'>https://ine.mx/transparencia/datos-abiertos/#/tematica/padron-electoral</a></div>",
    unsafe_allow_html=True
)

st.sidebar.markdown("---")
st.sidebar.subheader("📄 Exportar Informe")

g_dict = {
    'h_p': h_padron_1, 'h_l': h_lista_1,
    'm_p': m_padron_1, 'm_l': m_lista_1,
    'nb_p': nb_padron_1, 'nb_l': nb_lista_1
}
dem_dict = {
    'jov_p': pjov_1, 'jov_l': ljov_1,
    'may_p': pmay_1, 'may_l': lmay_1,
    'nat_p': p_nat_1, 'for_p': p_for_1,
    'n88_p': p_88_1, 'n87_p': p_87_1
}
desc_texto = f"Corte Reciente: {formatear_corte(corte_reciente)}"
if modo == "Comparar con Periodo Previo" and corte_base:
    desc_texto += f" frente a Base: {formatear_corte(corte_base)}"

if st.sidebar.button("📥 Generar Reporte PDF"):
    pdf_file = generar_pdf_reporte(
        titulo_alcance=nombre_header,
        desc_cortes=desc_texto,
        p1=p1, p2=p2,
        l1=l1, l2=l2,
        cob1=cob1, cob2=cob2,
        g_data=g_dict,
        dem_data=dem_dict,
        corte_rec=corte_reciente,
        corte_bas=corte_base if modo == "Comparar con Periodo Previo" else None,
        cve_ent=cve_entidad_activa,
        alcance_tipo=alcance
    )
    st.sidebar.download_button(
        label="⬇️ Descargar PDF Oficial",
        data=pdf_file,
        file_name=f"Reporte_Analitico_DERFE_{corte_reciente}.pdf",
        mime="application/pdf"
    )