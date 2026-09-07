import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from pathlib import Path

# ==============================================================================
# CONFIGURACIÓN DE PÁGINA Y ESTILO RESPONSIVO PARA MÓVILES Y ESCRITORIO
# ==============================================================================
st.set_page_config(
    page_title="Monitor DERFE | INE Oaxaca",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="auto"
)

# ==============================================================================
# TÍTULO VISIBLE Y VOCALÍA INSTITUCIONAL
# ==============================================================================
st.title("Análisis de Instrumentos registrales")
st.subheader("Vocalía del Registro Federal de Electores_Oaxaca")

# ==============================================================================
# CRÉDITO DE LA FUENTE DE DATOS EN LA BARRA LATERAL
# ==============================================================================
st.sidebar.markdown("---")
st.sidebar.markdown(
    "### Fuente de Información\n"
    "Datos recopilados de los [Datos Abiertos del Padrón Electoral - INE](https://ine.mx/transparencia/datos-abiertos/#/tematica/padron-electoral)."
)
st.sidebar.markdown("---")

st.markdown("""
<style>
    .main-title {
        font-size: 1.6rem !important;
        font-weight: 800;
        margin-bottom: 0.1rem;
        line-height: 1.2;
    }
    .sub-title {
        color: #8A99AD;
        font-size: 0.88rem !important;
        margin-bottom: 1rem;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.25rem !important;
        font-weight: 700;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.78rem !important;
        white-space: normal !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.75rem !important;
    }
    @media (max-width: 768px) {
        .main-title {
            font-size: 1.3rem !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.05rem !important;
        }
        [data-testid="column"] {
            min-width: 45% !important;
            margin-bottom: 0.5rem;
        }
    }
</style>
""", unsafe_allow_html=True)

DIR_RAIZ = Path(__file__).resolve().parent
DB_PATH = DIR_RAIZ / "derfe_web.db"

CATALOGO_ENTIDADES = {
    0: "EXTRANJERO (RESIDENTES EN EL EXTRANJERO)",
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

SINONIMOS_ORIGEN = {
    9: ("CIUDAD DE MEXICO", "DISTRITO FEDERAL", "CDMX", "DF"),
    15: ("MEXICO", "ESTADO DE MEXICO", "EDOMEX"),
    5: ("COAHUILA", "COAHUILA DE ZARAGOZA"),
    30: ("VERACRUZ", "VERACRUZ DE IGNACIO DE LA LLAVE"),
    16: ("MICHOACAN", "MICHOACAN DE OCAMPO")
}

OPCIONES_ENTIDADES = [f"{k:02d} - {v}" for k, v in CATALOGO_ENTIDADES.items() if k > 0]

PLOTLY_CONFIG = {
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": False
}

# ==============================================================================
# CONEXIÓN Y CONSULTAS EN CACHÉ ULTRARRÁPIDAS
# ==============================================================================
@st.cache_resource
def get_conn():
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)

conn = get_conn()

def formatear_corte(corte_val) -> str:
    c = str(corte_val).strip()
    if c == "PEE_PJF_2025":
        return "PEE PJF 2025 (Elección Judicial)"
    elif c == "PEF_2024":
        return "PEF 2024 (Elección Federal)"
    elif c == "PEF_0206":
        return "PEF 2024 (Corte 02/06)"
    elif len(c) == 8 and c.isdigit():
        return f"{c[6:8]}/{c[4:6]}/{c[:4]}"
    return c

@st.cache_data(ttl=3600)
def obtener_cortes_ordenados():
    try:
        df = pd.read_sql_query(
            "SELECT DISTINCT TRIM(CAST(corte AS TEXT)) AS c FROM derfe_sexo "
            "WHERE corte IS NOT NULL AND corte != 'DESCONOCIDO' AND corte != ''", 
            conn
        )
        lista = [str(x).strip() for x in df['c'].tolist() if str(x).strip()]
        numericos = sorted([x for x in lista if x.isdigit() and len(x) == 8], reverse=True)
        hitos = [x for x in ['PEE_PJF_2025', 'PEF_2024', 'PEF_0206'] if x in lista]
        otros = sorted([x for x in lista if x not in numericos and x not in hitos])
        return numericos + hitos + otros
    except Exception:
        return []

def extraer_clave(opcion_str: str) -> int:
    return int(opcion_str.split(" - ")[0])

# ==============================================================================
# BARRA LATERAL: FILTROS
# ==============================================================================
with st.sidebar:
    st.image("https://portalanterior.ine.mx/archivos3/portal/historico/contenido/interiores/logo_ine_transparente-img.png", width=180)
    st.markdown("### Configuración")
    
    cortes_lista = obtener_cortes_ordenados()
    if not cortes_lista:
        st.error(f"No se encontraron registros en la base de datos: {DB_PATH}")
        st.stop()

    modo = st.radio("Objetivo:", ["Corte Actual", "Comparar con Periodo Previo"], index=1)
    
    corte_reciente = st.selectbox(
        "Corte Principal (Reciente):", 
        cortes_lista, 
        index=0, 
        format_func=lambda x: f"{formatear_corte(x)} [{x}]"
    )

    corte_base = None
    if modo == "Comparar con Periodo Previo":
        idx_base = cortes_lista.index("PEE_PJF_2025") if "PEE_PJF_2025" in cortes_lista else (1 if len(cortes_lista) > 1 else 0)
        corte_base = st.selectbox(
            "Corte Base a Comparar:", 
            cortes_lista, 
            index=idx_base, 
            format_func=lambda x: f"{formatear_corte(x)} [{x}]"
        )

    st.markdown("---")
    alcance = st.radio(
        "Ámbito Geográfico:", 
        [
            "Total del Padrón (Nacional + Ext)",
            "Nacional (Solo Entidades sin Distrito 0)",
            "Extranjero (Solo Distrito 0 del País)",
            "Entidad Específica"
        ],
        index=3
    )
    
    claves_filtro = []
    distrito_seleccionado = None
    subfiltro_entidad = "Total Entidad (Territorio + Extranjero)"
    entidad_nombre_header = "Total País (Nacional + Extranjero)"

    if alcance == "Entidad Específica":
        def_oax = next((i for i, e in enumerate(OPCIONES_ENTIDADES) if "20 - OAXACA" in e), 0)
        entidad_sel = st.selectbox("Selecciona Entidad:", OPCIONES_ENTIDADES, index=def_oax)
        cve = extraer_clave(entidad_sel)
        claves_filtro = [cve]
        nom_ent_base = CATALOGO_ENTIDADES.get(cve, "Entidad")

        try:
            query_distritos = f"SELECT DISTINCT distrito FROM derfe_sexo WHERE clave_entidad = {cve} AND distrito IS NOT NULL ORDER BY CAST(distrito AS INT)"
            df_distritos = pd.read_sql_query(query_distritos, conn)
            if not df_distritos.empty:
                lista_distritos = ["Todos los Distritos"] + [str(d) for d in df_distritos['distrito'].tolist()]
                distrito_elegido = st.selectbox("Selecciona Distrito Electoral:", lista_distritos)
                if distrito_elegido != "Todos los Distritos":
                    distrito_seleccionado = int(distrito_elegido)
        except Exception:
            pass

        if distrito_seleccionado is not None:
            subfiltro_entidad = f"Distrito Federal {distrito_seleccionado}"
            entidad_nombre_header = f"{nom_ent_base} [Distrito {distrito_seleccionado}]"
        else:
            subfiltro_entidad = st.radio(
                f"Desglose para {nom_ent_base}:",
                [
                    "Total Entidad (Territorio + Extranjero)",
                    "Solo Territorio Estatal (Sin Distrito 0)",
                    "Solo Extranjero (Distrito 0)"
                ],
                index=0
            )
            entidad_nombre_header = f"{nom_ent_base} [{subfiltro_entidad}]"

    elif alcance == "Total del Padrón (Nacional + Ext)":
        entidad_nombre_header = "Total del Padrón (Nacional + Extranjero)"
    elif alcance == "Nacional (Solo Entidades sin Distrito 0)":
        entidad_nombre_header = "Territorio Nacional (300 Distritos sin Extranjero)"
    elif alcance == "Extranjero (Solo Distrito 0 del País)":
        entidad_nombre_header = "Residentes en el Extranjero (Distritos 0 Nacionales)"

# ==============================================================================
# ENCABEZADO PRINCIPAL
# ==============================================================================
st.markdown(f"<div class='main-title'>Padrón Electoral y Lista Nominal: {entidad_nombre_header}</div>", unsafe_allow_html=True)
if modo == "Comparar con Periodo Previo" and corte_base:
    st.markdown(f"<div class='sub-title'>Evolución histórica: <b>{formatear_corte(corte_reciente)}</b> frente al corte base seleccionado</div>", unsafe_allow_html=True)
else:
    st.markdown(f"<div class='sub-title'>Corte de operación: <b>{formatear_corte(corte_reciente)}</b></div>", unsafe_allow_html=True)

# FILTRADO SQL HOMOGÉNEO
if alcance == "Entidad Específica":
    cve_ent = claves_filtro[0]
    if distrito_seleccionado is not None:
        cond_filtro = f"AND CAST(clave_entidad AS INT) = {cve_ent} AND CAST(distrito AS INT) = {distrito_seleccionado}"
    elif subfiltro_entidad == "Solo Territorio Estatal (Sin Distrito 0)":
        cond_filtro = f"AND CAST(clave_entidad AS INT) = {cve_ent} AND CAST(distrito AS INT) > 0"
    elif subfiltro_entidad == "Solo Extranjero (Distrito 0)":
        cond_filtro = f"AND CAST(clave_entidad AS INT) = {cve_ent} AND CAST(distrito AS INT) = 0"
    else:
        cond_filtro = f"AND CAST(clave_entidad AS INT) = {cve_ent}"
elif alcance == "Total del Padrón (Nacional + Ext)":
    cond_filtro = "AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32"
elif alcance == "Nacional (Solo Entidades sin Distrito 0)":
    cond_filtro = "AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32 AND CAST(distrito AS INT) > 0"
elif alcance == "Extranjero (Solo Distrito 0 del País)":
    cond_filtro = "AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32 AND CAST(distrito AS INT) = 0"

# ==============================================================================
# SECCIÓN 1: KPIS Y COMPARATIVA PRINCIPAL (SEXO Y TOTALES)
# ==============================================================================
q_c1 = f"""
    SELECT 
        SUM(padron_electoral) AS padron, 
        SUM(lista_nominal) AS lista,
        SUM(hombres_padron) AS hombres,
        SUM(mujeres_padron) AS mujeres,
        SUM(no_binario_padron) AS nobin
    FROM derfe_sexo 
    WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' {cond_filtro}
"""
df_m1 = pd.read_sql_query(q_c1, conn)
p1 = int(df_m1['padron'].iloc[0] or 0)
l1 = int(df_m1['lista'].iloc[0] or 0)
h1 = int(df_m1['hombres'].iloc[0] or 0)
m1 = int(df_m1['mujeres'].iloc[0] or 0)
nob1 = int(df_m1['nobin'].iloc[0] or 0)
cob1 = (l1 / p1 * 100) if p1 > 0 else 0

p2, l2, h2, m2 = 0, 0, 0, 0
if modo == "Comparar con Periodo Previo" and corte_base:
    q_c2 = f"""
        SELECT 
            SUM(padron_electoral) AS padron, 
            SUM(lista_nominal) AS lista,
            SUM(hombres_padron) AS hombres,
            SUM(mujeres_padron) AS mujeres
        FROM derfe_sexo 
        WHERE TRIM(CAST(corte AS TEXT)) = '{corte_base}' {cond_filtro}
    """
    df_m2 = pd.read_sql_query(q_c2, conn)
    p2 = int(df_m2['padron'].iloc[0] or 0)
    l2 = int(df_m2['lista'].iloc[0] or 0)
    h2 = int(df_m2['hombres'].iloc[0] or 0)
    m2 = int(df_m2['mujeres'].iloc[0] or 0)
    cob2 = (l2 / p2 * 100) if p2 > 0 else 0

    dif_p = p1 - p2
    pct_p = (dif_p / p2 * 100) if p2 > 0 else 0
    dif_l = l1 - l2
    pct_l = (dif_l / l2 * 100) if p2 > 0 else 0
    dif_cob = cob1 - cob2

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Padrón Electoral", f"{p1:,}", f"{dif_p:+,} ({pct_p:+.2f}%)")
    k2.metric("Lista Nominal", f"{l1:,}", f"{dif_l:+,} ({pct_l:+.2f}%)")
    k3.metric("Cobertura Registral", f"{cob1:.2f}%", f"{dif_cob:+.2f}%")
    k4.metric("Hombres en Padrón", f"{h1:,}", f"{(h1-h2):+,}")
    k5.metric("Mujeres en Padrón", f"{m1:,}", f"{(m1-m2):+,}")
else:
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Padrón Electoral", f"{p1:,}")
    k2.metric("Lista Nominal", f"{l1:,}")
    k3.metric("Cobertura Registral", f"{cob1:.2f}%")
    k4.metric("Hombres en Padrón", f"{h1:,}")
    k5.metric("Mujeres en Padrón", f"{m1:,}")

st.write("")

# ==============================================================================
# SECCIÓN 2: GRÁFICOS VISUALES
# ==============================================================================
col_izq, col_der = st.columns([3, 2])

with col_izq:
    if alcance == "Entidad Específica" and distrito_seleccionado is None:
        q_dist = f"""
            SELECT 
                CASE WHEN CAST(distrito AS INT) = 0 THEN 'Extranjero' ELSE 'Dto ' || CAST(distrito AS TEXT) END AS 'Distrito Federal',
                padron_electoral AS Padrón, lista_nominal AS Lista
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' {cond_filtro}
            ORDER BY CAST(distrito AS INT)
        """
        df_dist = pd.read_sql_query(q_dist, conn)
        fig_principal = px.bar(
            df_dist, x="Distrito Federal", y=["Padrón", "Lista"],
            barmode="group",
            title=f"Distribución Distrital ({entidad_nombre_header})",
            color_discrete_sequence=["#1f77b4", "#2ca02c"]
        )
    elif alcance == "Entidad Específica" and distrito_seleccionado is not None:
        q_dist_esp = f"""
            SELECT 
                'Distrito ' || CAST(distrito AS TEXT) AS 'Distrito Federal',
                padron_electoral AS Padrón, lista_nominal AS Lista
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' {cond_filtro}
        """
        df_dist_esp = pd.read_sql_query(q_dist_esp, conn)
        fig_principal = px.bar(
            df_dist_esp, x="Distrito Federal", y=["Padrón", "Lista"],
            barmode="group",
            title=f"Detalle del {entidad_nombre_header}",
            color_discrete_sequence=["#1f77b4", "#2ca02c"]
        )
    elif "Extranjero" in alcance:
        q_ext_top = f"""
            SELECT clave_entidad, SUM(padron_electoral) AS Padrón, SUM(lista_nominal) AS Lista
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32 AND CAST(distrito AS INT) = 0
            GROUP BY clave_entidad
            ORDER BY Padrón DESC
            LIMIT 12
        """
        df_ext_top = pd.read_sql_query(q_ext_top, conn)
        df_ext_top['Entidad de Origen'] = df_ext_top['clave_entidad'].map(CATALOGO_ENTIDADES)

        fig_principal = px.bar(
            df_ext_top, x="Entidad de Origen", y=["Padrón", "Lista"],
            barmode="group",
            title="Top 12 Entidades de Origen en el Extranjero (Distrito 0)",
            color_discrete_sequence=["#1f77b4", "#2ca02c"]
        )
    elif "sin Distrito 0" in alcance:
        q_est_nac = f"""
            SELECT clave_entidad, SUM(padron_electoral) AS Padrón, SUM(lista_nominal) AS Lista
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32 AND CAST(distrito AS INT) > 0
            GROUP BY clave_entidad
            ORDER BY Padrón DESC
            LIMIT 12
        """
        df_est_nac = pd.read_sql_query(q_est_nac, conn)
        df_est_nac['Entidad'] = df_est_nac['clave_entidad'].map(CATALOGO_ENTIDADES)
        
        fig_principal = px.bar(
            df_est_nac, x="Entidad", y=["Padrón", "Lista"],
            barmode="group",
            title="Top 12 Entidades en Territorio Nacional (Sin Distrito 0)",
            color_discrete_sequence=["#1f77b4", "#2ca02c"]
        )
    else:
        q_est_tot = f"""
            SELECT clave_entidad, SUM(padron_electoral) AS Padrón, SUM(lista_nominal) AS Lista
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32
            GROUP BY clave_entidad
            ORDER BY Padrón DESC
            LIMIT 12
        """
        df_est_tot = pd.read_sql_query(q_est_tot, conn)
        df_est_tot['Entidad'] = df_est_tot['clave_entidad'].map(CATALOGO_ENTIDADES)
        
        fig_principal = px.bar(
            df_est_tot, x="Entidad", y=["Padrón", "Lista"],
            barmode="group",
            title="Top 12 Entidades (Padrón Integral: Nacional + Extranjero)",
            color_discrete_sequence=["#1f77b4", "#2ca02c"]
        )
    
    fig_principal.update_traces(
        hovertemplate="<b>%{x}</b><br>%{data.name}: %{y:,.0f}<extra></extra>"
    )
    fig_principal.update_layout(
        margin=dict(l=15, r=15, t=40, b=20),
        legend_title_text="",
        yaxis=dict(tickformat=","),
        height=320
    )
    st.plotly_chart(fig_principal, use_container_width=True, config=PLOTLY_CONFIG)

with col_der:
    fig_genero = px.pie(
        names=["Mujeres", "Hombres", "No Binario"],
        values=[m1, h1, nob1],
        title=f"Composición por Sexo ({entidad_nombre_header})",
        hole=0.45,
        color_discrete_sequence=["#E377C2", "#1F77B4", "#7F7F7F"]
    )
    fig_genero.update_traces(
        textposition='inside', 
        textinfo='percent+label',
        hovertemplate="<b>%{label}</b><br>Personas: %{value:,.0f} (%{percent})<extra></extra>"
    )
    fig_genero.update_layout(margin=dict(l=15, r=15, t=40, b=20), showlegend=False, height=320)
    st.plotly_chart(fig_genero, use_container_width=True, config=PLOTLY_CONFIG)

# ==============================================================================
# SECCIÓN 3: CONTEXTO DEMOGRÁFICO POR GRUPOS CLAVE (18-19 Y 65 Y MÁS)
# ==============================================================================
st.markdown("### Contexto Demográfico y Grupos de Edad Clave")

q_edad1 = f"""
    SELECT 
        SUM(COALESCE(padron_jovenes_18_19, 0)) AS pe_jov, 
        SUM(COALESCE(lista_jovenes_18_19, 0)) AS ln_jov,
        SUM(COALESCE(padron_65_y_mas, 0)) AS pe_65,
        SUM(COALESCE(lista_65_y_mas, 0)) AS ln_65
    FROM derfe_edad
    WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' {cond_filtro}
"""
try:
    df_e1 = pd.read_sql_query(q_edad1, conn)
except Exception:
    df_e1 = pd.DataFrame([{"pe_jov": 0, "ln_jov": 0, "pe_65": 0, "ln_65": 0}])

pjov1 = int(df_e1['pe_jov'].iloc[0] or 0)
ljov1 = int(df_e1['ln_jov'].iloc[0] or 0)
p65_1 = int(df_e1['pe_65'].iloc[0] or 0)
l65_1 = int(df_e1['ln_65'].iloc[0] or 0)

cobjov1 = (ljov1 / pjov1 * 100) if pjov1 > 0 else 0
cob65_1 = (l65_1 / p65_1 * 100) if p65_1 > 0 else 0
pct_pe_jov1 = (pjov1 / p1 * 100) if p1 > 0 else 0
pct_pe_65_1 = (p65_1 / p1 * 100) if p1 > 0 else 0

tab_jovenes, tab_mayores, tab_movilidad = st.tabs([
    "🌱 Jóvenes de 18 y 19 Años", 
    "👴 Población de 65 Años y Más", 
    "📍 Movilidad y Registro Especial"
])

with tab_jovenes:
    col_j1, col_j2 = st.columns([3, 2])
    with col_j1:
        if modo == "Comparar con Periodo Previo" and corte_base:
            q_edad2 = f"""
                SELECT 
                    SUM(COALESCE(padron_jovenes_18_19, 0)) AS pe_jov, 
                    SUM(COALESCE(lista_jovenes_18_19, 0)) AS ln_jov
                FROM derfe_edad
                WHERE TRIM(CAST(corte AS TEXT)) = '{corte_base}' {cond_filtro}
            """
            try:
                df_e2 = pd.read_sql_query(q_edad2, conn)
                pjov2 = int(df_e2['pe_jov'].iloc[0] or 0)
                ljov2 = int(df_e2['ln_jov'].iloc[0] or 0)
            except Exception:
                pjov2, ljov2 = 0, 0

            cobjov2 = (ljov2 / pjov2 * 100) if pjov2 > 0 else 0
            pct_pe_jov2 = (pjov2 / p2 * 100) if p2 > 0 else 0

            dif_pjov = pjov1 - pjov2
            pct_crec_pjov = (dif_pjov / pjov2 * 100) if pjov2 > 0 else 0
            dif_ljov = ljov1 - ljov2
            pct_crec_ljov = (dif_ljov / ljov2 * 100) if ljov2 > 0 else 0
            dif_cobjov = cobjov1 - cobjov2
            dif_pct_pe = pct_pe_jov1 - pct_pe_jov2

            cj1, cj2, cj3, cj4 = st.columns(4)
            cj1.metric("Padrón (18 y 19)", f"{pjov1:,}", f"{dif_pjov:+,} ({pct_crec_pjov:+.2f}%)")
            cj2.metric("Lista Nominal (18 y 19)", f"{ljov1:,}", f"{dif_ljov:+,} ({pct_crec_ljov:+.2f}%)")
            cj3.metric("Cobertura Registral", f"{cobjov1:.2f}%", f"{dif_cobjov:+.2f}%")
            cj4.metric("Peso en Padrón", f"{pct_pe_jov1:.2f}%", f"{dif_pct_pe:+.2f}%")
        else:
            cj1, cj2, cj3, cj4 = st.columns(4)
            cj1.metric("Padrón (18 y 19)", f"{pjov1:,}")
            cj2.metric("Lista Nominal (18 y 19)", f"{ljov1:,}")
            cj3.metric("Cobertura Registral", f"{cobjov1:.2f}%")
            cj4.metric("Peso en Padrón", f"{pct_pe_jov1:.2f}%")

    with col_j2:
        q_top5_jov = f"""
            SELECT 
                CAST(e.clave_entidad AS INT) AS cve,
                SUM(COALESCE(e.lista_jovenes_18_19, 0)) AS ln_jov,
                SUM(COALESCE(s.lista_nominal, 0)) AS ln_ent,
                ROUND(SUM(COALESCE(e.lista_jovenes_18_19, 0)) * 100.0 / NULLIF(SUM(s.lista_nominal), 0), 2) AS pct_local
            FROM derfe_edad e
            INNER JOIN derfe_sexo s 
                ON TRIM(CAST(e.corte AS TEXT)) = TRIM(CAST(s.corte AS TEXT))
               AND CAST(e.clave_entidad AS INT) = CAST(s.clave_entidad AS INT)
               AND CAST(e.distrito AS INT) = CAST(s.distrito AS INT)
            WHERE TRIM(CAST(e.corte AS TEXT)) = '{corte_reciente}' 
              AND CAST(e.clave_entidad AS INT) BETWEEN 1 AND 32
            GROUP BY cve
            ORDER BY pct_local DESC
            LIMIT 5
        """
        try:
            df_top5_j = pd.read_sql_query(q_top5_jov, conn)
            df_top5_j['Entidad'] = df_top5_j['cve'].map(CATALOGO_ENTIDADES)
            df_top5_j['Etiqueta'] = df_top5_j.apply(lambda r: f"{r['pct_local']:.2f}% ({r['ln_jov']:,})", axis=1)

            df_top5_j_plot = df_top5_j.iloc[::-1]

            fig_top_j = px.bar(
                df_top5_j_plot, 
                x="pct_local", 
                y="Entidad", 
                orientation="h",
                text="Etiqueta",
                title="Top 5 Entidades: Mayor % Jóvenes 18-19",
                labels={"pct_local": "% de la LN Estatal", "Entidad": ""},
                color_discrete_sequence=["#1f77b4"]
            )
            fig_top_j.update_traces(
                textposition='inside', 
                insidetextanchor='middle',
                hovertemplate="<b>%{y}</b><br>Proporción: %{x:.2f}%<extra></extra>"
            )
            fig_top_j.update_layout(
                margin=dict(l=5, r=5, t=30, b=10),
                height=250,
                xaxis=dict(showticklabels=False, title="")
            )
            st.plotly_chart(fig_top_j, use_container_width=True, config=PLOTLY_CONFIG)
        except Exception as err:
            st.caption(f"No fue posible graficar el Top 5: {err}")

with tab_mayores:
    col_m1, col_m2 = st.columns([3, 2])
    with col_m1:
        if modo == "Comparar con Periodo Previo" and corte_base:
            q_edad65_2 = f"""
                SELECT 
                    SUM(COALESCE(padron_65_y_mas, 0)) AS pe_65, 
                    SUM(COALESCE(lista_65_y_mas, 0)) AS ln_65
                FROM derfe_edad
                WHERE TRIM(CAST(corte AS TEXT)) = '{corte_base}' {cond_filtro}
            """
            try:
                df_e65_2 = pd.read_sql_query(q_edad65_2, conn)
                p65_2 = int(df_e65_2['pe_65'].iloc[0] or 0)
                l65_2 = int(df_e65_2['ln_65'].iloc[0] or 0)
            except Exception:
                p65_2, l65_2 = 0, 0

            cob65_2 = (l65_2 / p65_2 * 100) if p65_2 > 0 else 0
            pct_pe_65_2 = (p65_2 / p2 * 100) if p2 > 0 else 0

            dif_p65 = p65_1 - p65_2
            pct_crec_p65 = (dif_p65 / p65_2 * 100) if p65_2 > 0 else 0
            dif_l65 = l65_1 - l65_2
            pct_crec_l65 = (dif_l65 / l65_2 * 100) if l65_2 > 0 else 0
            dif_cob65 = cob65_1 - cob65_2
            dif_pct_pe65 = pct_pe_65_1 - pct_pe_65_2

            cm1, cm2, cm3, cm4 = st.columns(4)
            cm1.metric("Padrón (65 y Más)", f"{p65_1:,}", f"{dif_p65:+,} ({pct_crec_p65:+.2f}%)")
            cm2.metric("Lista Nominal (65 y Más)", f"{l65_1:,}", f"{dif_l65:+,} ({pct_crec_l65:+.2f}%)")
            cm3.metric("Cobertura Registral", f"{cob65_1:.2f}%", f"{dif_cob65:+.2f}%")
            cm4.metric("Peso en Padrón", f"{pct_pe_65_1:.2f}%", f"{dif_pct_pe65:+.2f}%")
        else:
            cm1, cm2, cm3, cm4 = st.columns(4)
            cm1.metric("Padrón (65 y Más)", f"{p65_1:,}")
            cm2.metric("Lista Nominal (65 y Más)", f"{l65_1:,}")
            cm3.metric("Cobertura Registral", f"{cob65_1:.2f}%")
            cm4.metric("Peso en Padrón", f"{pct_pe_65_1:.2f}%")

    with col_m2:
        q_top5_65 = f"""
            SELECT 
                CAST(e.clave_entidad AS INT) AS cve,
                SUM(COALESCE(e.lista_65_y_mas, 0)) AS ln_65,
                SUM(COALESCE(s.lista_nominal, 0)) AS ln_ent,
                ROUND(SUM(COALESCE(e.lista_65_y_mas, 0)) * 100.0 / NULLIF(SUM(s.lista_nominal), 0), 2) AS pct_local
            FROM derfe_edad e
            INNER JOIN derfe_sexo s 
                ON TRIM(CAST(e.corte AS TEXT)) = TRIM(CAST(s.corte AS TEXT))
               AND CAST(e.clave_entidad AS INT) = CAST(s.clave_entidad AS INT)
               AND CAST(e.distrito AS INT) = CAST(s.distrito AS INT)
            WHERE TRIM(CAST(e.corte AS TEXT)) = '{corte_reciente}' 
              AND CAST(e.clave_entidad AS INT) BETWEEN 1 AND 32
            GROUP BY cve
            ORDER BY pct_local DESC
            LIMIT 5
        """
        try:
            df_top5_65 = pd.read_sql_query(q_top5_65, conn)
            df_top5_65['Entidad'] = df_top5_65['cve'].map(CATALOGO_ENTIDADES)
            df_top5_65['Etiqueta'] = df_top5_65.apply(lambda r: f"{r['pct_local']:.2f}% ({r['ln_65']:,})", axis=1)

            df_top5_65_plot = df_top5_65.iloc[::-1]

            fig_top_65 = px.bar(
                df_top5_65_plot, 
                x="pct_local", 
                y="Entidad", 
                orientation="h",
                text="Etiqueta",
                title="Top 5 Entidades: Mayor % 65 y Más",
                labels={"pct_local": "% de la LN Estatal", "Entidad": ""},
                color_discrete_sequence=["#ff7f0e"]
            )
            fig_top_65.update_traces(
                textposition='inside', 
                insidetextanchor='middle',
                hovertemplate="<b>%{y}</b><br>Proporción: %{x:.2f}%<extra></extra>"
            )
            fig_top_65.update_layout(
                margin=dict(l=5, r=5, t=30, b=10),
                height=250,
                xaxis=dict(showticklabels=False, title="")
            )
            st.plotly_chart(fig_top_65, use_container_width=True, config=PLOTLY_CONFIG)
        except Exception as err:
            st.caption(f"No fue posible graficar el Top 5: {err}")

with tab_movilidad:
    try:
        q_chk = f"SELECT corte FROM derfe_origen WHERE corte = '{corte_reciente}' LIMIT 1"
        row_c = conn.execute(q_chk).fetchone()
        corte_usar = row_c[0] if row_c else None
        
        if not corte_usar:
            q_max = f"SELECT corte FROM derfe_origen WHERE corte <= '{corte_reciente}' ORDER BY corte DESC LIMIT 1"
            row_max = conn.execute(q_max).fetchone()
            corte_usar = row_max[0] if row_max else None

        if corte_usar:
            cve_ent_num = claves_filtro[0] if (alcance == "Entidad Específica" and claves_filtro) else None

            if alcance == "Entidad Específica" and cve_ent_num is not None:
                nom_ent_str = CATALOGO_ENTIDADES[cve_ent_num]

                sinonimos = SINONIMOS_ORIGEN.get(cve_ent_num, (nom_ent_str,))
                sinonimos_sql = ", ".join([f"'{s}'" for s in sinonimos])

                q_nac = f"""
                    SELECT 
                        CASE 
                            WHEN UPPER(TRIM(entidad_origen)) IN ({sinonimos_sql}) THEN 'NATIVOS' 
                            ELSE 'FORANEOS' 
                        END AS tipo,
                        SUM(COALESCE(padron_electoral, 0)) AS pe
                    FROM derfe_origen
                    WHERE corte = '{corte_usar}' 
                      AND CAST(clave_entidad_residencia AS INT) = {cve_ent_num}
                      AND ambito = 'NACIONAL'
                    GROUP BY tipo
                """
                df_nac = pd.read_sql_query(q_nac, conn)
                pe_nat = int(df_nac[df_nac['tipo'] == 'NATIVOS']['pe'].sum()) if not df_nac.empty else 0
                pe_foran = int(df_nac[df_nac['tipo'] == 'FORANEOS']['pe'].sum()) if not df_nac.empty else 0

                q_ext = f"""
                    SELECT SUM(COALESCE(padron_electoral, 0)) AS pe_ext
                    FROM derfe_origen
                    WHERE corte = '{corte_usar}' 
                      AND CAST(clave_entidad_residencia AS INT) = {cve_ent_num}
                      AND ambito = 'EXTRANJERO'
                """
                row_ext = conn.execute(q_ext).fetchone()
                pe_ext = int(row_ext[0] or 0) if (row_ext and row_ext[0] is not None) else 0

                # SOLUCIÓN DEFINITIVA: Cargamos toda la tabla especial de la entidad a Pandas y filtramos localmente 
                # (evitando errores de nombres de columnas de distrito en SQLite)
                q_esp_entidad = f"""
                    SELECT * FROM derfe_especiales 
                    WHERE corte = '{corte_usar}' AND CAST(clave_entidad AS INT) = {cve_ent_num}
                """
                df_esp_local = pd.read_sql_query(q_esp_entidad, conn)

                if distrito_seleccionado is not None and not df_esp_local.empty:
                    # Buscamos dinámicamente qué columna representa el distrito en esta tabla
                    col_dto_encontrada = next((col for col in df_esp_local.columns if 'distrito' in col.lower() or 'dto' in col.lower()), None)
                    if col_dto_encontrada:
                        df_esp_local = df_esp_local[df_esp_local[col_dto_encontrada].astype(int) == distrito_seleccionado]

                pe_87 = int(df_esp_local['pe_87'].sum() or 0) if 'pe_87' in df_esp_local.columns else 0
                pe_88 = int(df_esp_local['pe_88'].sum() or 0) if 'pe_88' in df_esp_local.columns else 0
                ln_87 = int(df_esp_local['ln_87'].sum() or 0) if 'ln_87' in df_esp_local.columns else 0
                ln_88 = int(df_esp_local['ln_88'].sum() or 0) if 'ln_88' in df_esp_local.columns else 0

                pe_tot_local = pe_nat + pe_foran + pe_87 + pe_88
                pct_nat = (pe_nat / pe_tot_local * 100) if pe_tot_local > 0 else 0
                pct_for = (pe_foran / pe_tot_local * 100) if pe_tot_local > 0 else 0
                pct_87 = (pe_87 / pe_tot_local * 100) if pe_tot_local > 0 else 0
                pct_88 = (pe_88 / pe_tot_local * 100) if pe_tot_local > 0 else 0

                c_m1, c_m2, c_m3, c_m4, c_m5 = st.columns(5)
                c_m1.metric("Nativos en la Entidad", f"{pe_nat:,}", f"{pct_nat:.1f}% del Padrón")
                c_m2.metric("Foráneos Residentes", f"{pe_foran:,}", f"{pct_for:.1f}% del Padrón")
                c_m3.metric("Clave 87: Nac. Ext. (Hijos Mex)", f"{pe_87:,}", f"{pct_87:.2f}% | LN: {ln_87:,}" if ln_87 > 0 else f"{pct_87:.2f}% del Padrón")
                c_m4.metric("Clave 88: Naturalizados", f"{pe_88:,}", f"{pct_88:.2f}% | LN: {ln_88:,}" if ln_88 > 0 else f"{pct_88:.2f}% del Padrón")
                c_m5.metric("Residentes en el ext.", f"{pe_ext:,}", help="Ciudadanos originarios registrados en el extranjero (Distrito 0)")

                st.markdown("---")
                col_g1, col_g2 = st.columns([1, 1])

                with col_g1:
                    fig_pie_mov = px.pie(
                        names=[
                            "Nativos", 
                            "Foráneos (Otras Entidades)", 
                            "Clave 87: Nac. Ext. (Hijos Mex)", 
                            "Clave 88: Naturalizados"
                        ],
                        values=[pe_nat, pe_foran, pe_87, pe_88],
                        title=f"Composición del Padrón Electoral en {nom_ent_str}",
                        hole=0.45,
                        color_discrete_sequence=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
                    )
                    fig_pie_mov.update_traces(
                        textposition='inside', 
                        textinfo='percent+label',
                        hovertemplate="<b>%{label}</b><br>Personas: %{value:,.0f} (%{percent})<extra></extra>"
                    )
                    fig_pie_mov.update_layout(margin=dict(l=10, r=10, t=40, b=10), showlegend=False, height=310)
                    st.plotly_chart(fig_pie_mov, use_container_width=True, config=PLOTLY_CONFIG)

                with col_g2:
                    df_comp = pd.DataFrame({
                        "Categoría": ["Nativos", "Foráneos", "Clave 87 (Hijos Mex)", "Clave 88 (Naturalizados)", "Residentes en el ext."],
                        "Padrón Electoral": [pe_nat, pe_foran, pe_87, pe_88, pe_ext]
                    })
                    total_p_ent = pe_tot_local if pe_tot_local > 0 else 1
                    df_comp['pct'] = df_comp['Padrón Electoral'] * 100.0 / total_p_ent
                    df_comp['etiqueta_barra'] = df_comp.apply(lambda r: f"{r['Padrón Electoral']:,} ({r['pct']:.1f}%)", axis=1)

                    fig_bar_mov = px.bar(
                        df_comp, 
                        x="Categoría", 
                        y="Padrón Electoral",
                        text="etiqueta_barra",
                        title=f"Distribución por Condición Jurídica y Residencia ({nom_ent_str})",
                        color_discrete_sequence=["#4B6584"]
                    )
                    fig_bar_mov.update_traces(
                        textposition="outside",
                        cliponaxis=False,
                        hovertemplate="<b>%{x}</b><br>Padrón Electoral: %{y:,.0f}<br>Porcentaje: %{customdata:.2f}%<extra></extra>",
                        customdata=df_comp['pct']
                    )
                    max_y_ent = df_comp['Padrón Electoral'].max() if not df_comp.empty else 100
                    fig_bar_mov.update_layout(
                        margin=dict(l=10, r=10, t=40, b=10), 
                        height=330,
                        yaxis=dict(tickformat=",", range=[0, max_y_ent * 1.22])
                    )
                    st.plotly_chart(fig_bar_mov, use_container_width=True, config=PLOTLY_CONFIG)

                st.caption(f"Corte analizado: **{formatear_corte(corte_usar)}** • Entidad: **{nom_ent_str}**")

            elif alcance in ["Total del Padrón (Nacional + Ext)", "Nacional (Solo Entidades sin Distrito 0)"]:
                q_nac_alt = f"""
                    SELECT 
                        CASE 
                            WHEN (
                                UPPER(TRIM(entidad_origen)) = UPPER(TRIM(entidad_residencia))
                                OR (UPPER(TRIM(entidad_origen)) IN ('CIUDAD DE MEXICO', 'DISTRITO FEDERAL', 'DF', 'CDMX') AND UPPER(TRIM(entidad_residencia)) IN ('CIUDAD DE MEXICO', 'DISTRITO FEDERAL', 'DF', 'CDMX'))
                                OR (UPPER(TRIM(entidad_origen)) IN ('MEXICO', 'ESTADO DE MEXICO', 'EDOMEX') AND UPPER(TRIM(entidad_residencia)) IN ('MEXICO', 'ESTADO DE MEXICO', 'EDOMEX'))
                            ) THEN 'NATIVOS'
                            ELSE 'FORANEOS'
                        END AS tipo,
                        SUM(COALESCE(padron_electoral, 0)) AS pe
                    FROM derfe_origen
                    WHERE corte = '{corte_usar}' AND ambito = 'NACIONAL'
                    GROUP BY tipo
                """
                df_nac_alt = pd.read_sql_query(q_nac_alt, conn)
                pe_nat_nac = int(df_nac_alt[df_nac_alt['tipo'] == 'NATIVOS']['pe'].sum()) if not df_nac_alt.empty else 0
                pe_foran_nac = int(df_nac_alt[df_nac_alt['tipo'] == 'FORANEOS']['pe'].sum()) if not df_nac_alt.empty else 0

                q_ext_nac = f"""
                    SELECT SUM(COALESCE(padron_electoral, 0)) AS pe_ext
                    FROM derfe_origen
                    WHERE corte = '{corte_usar}' AND ambito = 'EXTRANJERO'
                """
                row_ext_nac = conn.execute(q_ext_nac).fetchone()
                pe_ext_nac = int(row_ext_nac[0] or 0) if (row_ext_nac and row_ext_nac[0] is not None) else 0

                q_esp_nac = f"SELECT SUM(pe_87) as pe_87, SUM(pe_88) as pe_88, SUM(ln_87) as ln_87, SUM(ln_88) as ln_88 FROM derfe_especiales WHERE corte = '{corte_usar}'"
                df_esp_n = pd.read_sql_query(q_esp_nac, conn)
                pe_87_nac = int(df_esp_n['pe_87'].iloc[0] or 0) if not df_esp_n.empty else 0
                pe_88_nac = int(df_esp_n['pe_88'].iloc[0] or 0) if not df_esp_n.empty else 0
                ln_87_nac = int(df_esp_n['ln_87'].iloc[0] or 0) if not df_esp_n.empty else 0
                ln_88_nac = int(df_esp_n['ln_88'].iloc[0] or 0) if not df_esp_n.empty else 0

                pe_tot_pais = pe_nat_nac + pe_foran_nac + pe_87_nac + pe_88_nac
                pct_nat_nac = (pe_nat_nac / pe_tot_pais * 100) if pe_tot_pais > 0 else 0
                pct_for_nac = (pe_foran_nac / pe_tot_pais * 100) if pe_tot_pais > 0 else 0
                pct_87_nac = (pe_87_nac / pe_tot_pais * 100) if pe_tot_pais > 0 else 0
                pct_88_nac = (pe_88_nac / pe_tot_pais * 100) if pe_tot_pais > 0 else 0

                cn1, cn2, cn3, cn4, cn5 = st.columns(5)
                cn1.metric("Nativos en su Estado", f"{pe_nat_nac:,}", f"{pct_nat_nac:.1f}% del Padrón")
                cn2.metric("Migración Interna (Foráneos)", f"{pe_foran_nac:,}", f"{pct_for_nac:.1f}% del Padrón")
                cn3.metric("Clave 87: Nac. Ext. (Hijos Mex)", f"{pe_87_nac:,}", f"{pct_87_nac:.2f}% | LN: {ln_87_nac:,}" if ln_87_nac > 0 else f"{pct_87_nac:.2f}% del Padrón")
                cn4.metric("Clave 88: Naturalizados", f"{pe_88_nac:,}", f"{pct_88_nac:.2f}% | LN: {ln_88_nac:,}" if ln_88_nac > 0 else f"{pct_88_nac:.2f}% del Padrón")
                cn5.metric("Residentes en el ext.", f"{pe_ext_nac:,}", help="Total nacional empadronado en el extranjero (Distritos 0)")

                st.markdown("---")
                col_gn1, col_gn2 = st.columns([1, 1])

                with col_gn1:
                    fig_pie_nac = px.pie(
                        names=[
                            "Nativos (Residen en su estado)", 
                            "Foráneos (Migración interestatal)", 
                            "Clave 87: Nac. Ext. (Hijos Mex)", 
                            "Clave 88: Naturalizados"
                        ],
                        values=[pe_nat_nac, pe_foran_nac, pe_87_nac, pe_88_nac],
                        title="Composición Nacional del Padrón por Condición de Origen",
                        hole=0.45,
                        color_discrete_sequence=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
                    )
                    fig_pie_nac.update_traces(
                        textposition='inside', 
                        textinfo='percent+label',
                        hovertemplate="<b>%{label}</b><br>Personas: %{value:,.0f} (%{percent})<extra></extra>"
                    )
                    fig_pie_nac.update_layout(margin=dict(l=10, r=10, t=40, b=10), showlegend=False, height=310)
                    st.plotly_chart(fig_pie_nac, use_container_width=True, config=PLOTLY_CONFIG)

                with col_gn2:
                    q_ranking_esp = f"""
                        SELECT clave_entidad, SUM(pe_87) as pe_87, SUM(pe_88) as pe_88 
                        FROM derfe_especiales 
                        WHERE corte = '{corte_usar}' 
                        GROUP BY clave_entidad
                    """
                    df_esp_rank = pd.read_sql_query(q_ranking_esp, conn)
                    df_esp_rank['Entidad'] = df_esp_rank['clave_entidad'].astype(int).map(CATALOGO_ENTIDADES)
                    df_esp_rank['Total Especial'] = df_esp_rank['pe_87'] + df_esp_rank['pe_88']
                    df_esp_rank = df_esp_rank.sort_values(by="Total Especial", ascending=False).head(8)

                    fig_bar_esp = px.bar(
                        df_esp_rank,
                        x="Entidad",
                        y=["pe_87", "pe_88"],
                        barmode="stack",
                        title="Top 8 Entidades Receptoras de Claves 87 y 88",
                        labels={"value": "Padrón Electoral", "variable": "Clave Especial"},
                        color_discrete_sequence=["#2ca02c", "#d62728"]
                    )
                    fig_bar_esp.update_traces(
                        hovertemplate="<b>%{x}</b><br>%{data.name}: %{y:,.0f}<extra></extra>"
                    )
                    fig_bar_esp.update_layout(
                        margin=dict(l=10, r=10, t=40, b=10), 
                        height=310,
                        yaxis=dict(tickformat=","),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_bar_esp, use_container_width=True, config=PLOTLY_CONFIG)

                st.caption(f"Corte analizado: **{formatear_corte(corte_usar)}** • Ámbito: **Consolidado Nacional**")

            elif alcance == "Extranjero (Solo Distrito 0 del País)":
                q_ext_diag = f"""
                    SELECT clave_entidad_residencia, SUM(COALESCE(padron_electoral, 0)) AS pe
                    FROM derfe_origen
                    WHERE corte = '{corte_usar}' AND ambito = 'EXTRANJERO'
                    GROUP BY clave_entidad_residencia
                    ORDER BY pe DESC
                    LIMIT 10
                """
                df_ext_diag = pd.read_sql_query(q_ext_diag, conn)
                df_ext_diag['Entidad de Origen'] = df_ext_diag['clave_entidad_residencia'].astype(int).map(CATALOGO_ENTIDADES)

                q_ext_tot_global = f"SELECT SUM(COALESCE(padron_electoral, 0)) FROM derfe_origen WHERE corte = '{corte_usar}' AND ambito = 'EXTRANJERO'"
                r_tot_ext = conn.execute(q_ext_tot_global).fetchone()
                pe_ext_tot = float(r_tot_ext[0]) if (r_tot_ext and r_tot_ext[0]) else 1.0

                df_ext_diag['pct'] = (df_ext_diag['pe'] * 100.0 / pe_ext_tot)
                df_ext_diag['etiqueta_barra'] = df_ext_diag.apply(lambda r: f"{r['pe']:,} ({r['pct']:.1f}%)", axis=1)

                fig_ext_rank = px.bar(
                    df_ext_diag,
                    x="Entidad de Origen",
                    y="pe",
                    text="etiqueta_barra",
                    title="Top 10 Entidades de Origen con Mayor Población (Residentes en el Extranjero - Distrito 0)",
                    color_discrete_sequence=["#1f77b4"],
                    labels={"pe": "Padrón Electoral", "Entidad de Origen": "Entidad de Origen"}
                )
                fig_ext_rank.update_traces(
                    textposition="outside",
                    cliponaxis=False,
                    hovertemplate="<b>%{x}</b><br>Padrón Electoral: %{y:,.0f}<br>Porcentaje Nacional: %{customdata:.2f}%<extra></extra>",
                    customdata=df_ext_diag['pct']
                )
                max_y = df_ext_diag['pe'].max() if not df_ext_diag.empty else 100
                fig_ext_rank.update_layout(
                    margin=dict(l=15, r=15, t=45, b=20),
                    yaxis=dict(tickformat=",", range=[0, max_y * 1.20]),
                    height=340
                )
                st.plotly_chart(fig_ext_rank, use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.warning("No hay cortes registrados en la tabla de origen.")
    except Exception as e_or:
        st.error(f"Error al procesar la movilidad geográfica: {e_or}")

# ==============================================================================
# SECCIÓN 4: DETALLE TABULAR
# ==============================================================================
with st.expander("📋 Ver Tabla Detallada de Datos y Exportar"):
    if alcance == "Entidad Específica" and distrito_seleccionado is None:
        q_tab = f"""
            SELECT 
                CASE WHEN CAST(distrito AS INT) = 0 THEN 'Extranjero' ELSE 'Distrito ' || CAST(distrito AS TEXT) END AS 'Distrito Federal',
                padron_electoral AS 'Padrón Electoral', lista_nominal AS 'Lista Nominal',
                hombres_padron AS 'Hombres', mujeres_padron AS 'Mujeres',
                ROUND(lista_nominal*100.0/padron_electoral, 2) AS 'Cobertura (%)'
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' {cond_filtro}
            ORDER BY CAST(distrito AS INT)
        """
    elif alcance == "Entidad Específica" and distrito_seleccionado is not None:
        q_tab = f"""
            SELECT 
                'Distrito ' || CAST(distrito AS TEXT) AS 'Distrito Federal',
                padron_electoral AS 'Padrón Electoral', lista_nominal AS 'Lista Nominal',
                hombres_padron AS 'Hombres', mujeres_padron AS 'Mujeres',
                ROUND(lista_nominal*100.0/padron_electoral, 2) AS 'Cobertura (%)'
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' {cond_filtro}
        """
    elif "Extranjero" in alcance:
        q_tab = f"""
            SELECT clave_entidad AS 'Clave',
                   entidad AS 'Entidad de Origen',
                   SUM(padron_electoral) AS 'Padrón en Extranjero', SUM(lista_nominal) AS 'Lista en Extranjero',
                   ROUND(SUM(lista_nominal)*100.0/SUM(padron_electoral), 2) AS 'Cobertura (%)'
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32 AND CAST(distrito AS INT) = 0
            GROUP BY clave_entidad
            ORDER BY CAST(clave_entidad AS INT)
        """
    elif "sin Distrito 0" in alcance:
        q_tab = f"""
            SELECT clave_entidad AS 'Clave',
                   entidad AS 'Entidad',
                   SUM(padron_electoral) AS 'Padrón Nacional', SUM(lista_nominal) AS 'Lista Nacional',
                   ROUND(SUM(lista_nominal)*100.0/SUM(padron_electoral), 2) AS 'Cobertura (%)'
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32 AND CAST(distrito AS INT) > 0
            GROUP BY clave_entidad
            ORDER BY CAST(clave_entidad AS INT)
        """
    else:
        q_tab = f"""
            SELECT clave_entidad AS 'Clave',
                   entidad AS 'Entidad',
                   SUM(padron_electoral) AS 'Padrón Total (Nac+Ext)', SUM(lista_nominal) AS 'Lista Total (Nac+Ext)',
                   ROUND(SUM(lista_nominal)*100.0/SUM(padron_electoral), 2) AS 'Cobertura (%)'
            FROM derfe_sexo
            WHERE TRIM(CAST(corte AS TEXT)) = '{corte_reciente}' AND CAST(clave_entidad AS INT) BETWEEN 1 AND 32
            GROUP BY clave_entidad
            ORDER BY CAST(clave_entidad AS INT)
        """
    try:
        df_tabla = pd.read_sql_query(q_tab, conn)
        st.dataframe(df_tabla, use_container_width=True)
    except Exception as e:
        st.error(f"Error al generar la tabla: {e}")