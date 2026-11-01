import os
import glob
import re
import sqlite3
import numpy as np
import pandas as pd
import streamlit as st

CATALOGO_ENTIDADES = {
    1: "01 - AGUASCALIENTES", 2: "02 - BAJA CALIFORNIA", 3: "03 - BAJA CALIFORNIA SUR",
    4: "04 - CAMPECHE", 5: "05 - COAHUILA", 6: "06 - COLIMA", 7: "07 - CHIAPAS",
    8: "08 - CHIHUAHUA", 9: "09 - CIUDAD DE MEXICO", 10: "10 - DURANGO",
    11: "11 - GUANAJUATO", 12: "12 - GUERRERO", 13: "13 - HIDALGO", 14: "14 - JALISCO",
    15: "15 - MEXICO", 16: "16 - MICHOACAN", 17: "17 - MORELOS", 18: "18 - NAYARIT",
    19: "19 - NUEVO LEON", 20: "20 - OAXACA", 21: "21 - PUEBLA", 22: "22 - QUERETARO",
    23: "23 - QUINTANA ROO", 24: "24 - SAN LUIS POTOSI", 25: "25 - SINALOA",
    26: "26 - SONORA", 27: "27 - TABASCO", 28: "28 - TAMAULIPAS", 29: "29 - TLAXCALA",
    30: "30 - VERACRUZ", 31: "31 - YUCATAN", 32: "32 - ZACATECAS"
}

DB_PATH = "derfe_web.db"

def extraer_fecha_corte(nombre_archivo):
    match = re.search(r"(\d{8})", nombre_archivo)
    if match:
        f = match.group(1)
        return f"{f[:4]}-{f[4:6]}-{f[6:]}"
    base = os.path.splitext(os.path.basename(nombre_archivo))[0]
    return base.replace("DatosAbiertos-", "").replace("DatosAbiertos_", "")

def listar_insumos_disponibles():
    patron = os.path.join("insumos_originales", "**", "*.xlsx")
    todos = glob.glob(patron, recursive=True)
    dict_cortes = {}
    for a in sorted(todos, reverse=True):
        nombre = os.path.basename(a).lower()
        if "eo_" in nombre or "mun" in nombre:
            continue
        try:
            cols = [str(c).upper().replace(" ", "_") for c in pd.read_excel(a, nrows=1).columns]
            if any("SECCION" in c or "SECC" in c for c in cols):
                fecha = extraer_fecha_corte(a)
                etiqueta = f"{fecha} | {os.path.basename(a)}"
                dict_cortes[etiqueta] = a
        except Exception:
            continue

    if not dict_cortes:
        por_sexo = glob.glob(os.path.join("insumos_originales", "Por sexo", "*.xlsx"))
        for a in por_sexo:
            fecha = extraer_fecha_corte(a)
            dict_cortes[f"{fecha} | {os.path.basename(a)}"] = a

    return dict_cortes

def homologar_columnas(df):
    nuevas = {}
    for col in df.columns:
        c = str(col).strip().upper().replace("\n", "_").replace(" ", "_")
        if any(k in c for k in ["ENTIDAD", "EDO", "ID_ENTIDAD", "CLAVE_ENT"]) and "NOMBRE" not in c:
            nuevas[col] = "CLAVE_ENTIDAD"
        elif any(k in c for k in ["DISTRITO", "DTO", "ID_DIST"]) and "NOMBRE" not in c and "CABECERA" not in c:
            nuevas[col] = "CLAVE_DISTRITO"
        elif any(k in c for k in ["SECCION", "SECC"]):
            nuevas[col] = "SECCION"
        elif any(k in c for k in ["PADRON", "PDLN"]) and not any(k in c for k in ["HOMBRES", "MUJERES", "NON_BINARY", "SEXO"]):
            nuevas[col] = "PADRON_ELECTORAL"
        elif any(k in c for k in ["LISTA", "NOMINAL", "LN"]) and not any(k in c for k in ["HOMBRES", "MUJERES", "NON_BINARY", "SEXO"]):
            nuevas[col] = "LISTA_NOMINAL"
            
    df_ren = df.rename(columns=nuevas)
    if "PADRON_ELECTORAL" not in df_ren.columns:
        cols_p = [c for c in df.columns if "PADRON" in str(c).upper() or "PD" in str(c).upper()]
        if cols_p:
            df_ren["PADRON_ELECTORAL"] = df[cols_p].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    if "LISTA_NOMINAL" not in df_ren.columns:
        cols_l = [c for c in df.columns if "LISTA" in str(c).upper() or "LN" in str(c).upper()]
        if cols_l:
            df_ren["LISTA_NOMINAL"] = df[cols_l].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    return df_ren

@st.cache_data(show_spinner=False)
def obtener_cortes_padron_bd():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE 'padron_202%' OR name LIKE 'padron_19%') ORDER BY name DESC LIMIT 10;")
    tablas = [r[0] for r in c.fetchall()]
    conn.close()
    opciones = {}
    for t in tablas:
        partes = t.split('_')
        if len(partes) >= 4 and partes[1].isdigit():
            etiqueta = f'{partes[1]}-{partes[2]}-{partes[3]}'
            opciones[etiqueta] = t
    return opciones

@st.cache_data(show_spinner=False)
def consultar_padron_bd(tabla_corte, entidad=None, distrito=None):
    conn = sqlite3.connect(DB_PATH)
    condiciones = []
    if entidad is not None and entidad != 'Todas':
        condiciones.append(f'CLAVE_ENTIDAD = {int(entidad)}')
    if distrito is not None:
        condiciones.append(f'CLAVE_DISTRITO = {int(distrito)}')
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ''
    
    query = f"""
        SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, PADRON_ELECTORAL, LISTA_NOMINAL
        FROM {tabla_corte}
        {where}
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    for col in ['CLAVE_ENTIDAD', 'CLAVE_DISTRITO', 'SECCION', 'PADRON_ELECTORAL', 'LISTA_NOMINAL']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    return df

@st.cache_data(show_spinner=False)
def consultar_historico_bd(tabla_hechos, entidad=None, distrito=None):
    conn = sqlite3.connect(DB_PATH)
    condiciones = []
    if entidad is not None and entidad != 'Todas':
        condiciones.append(f'CLAVE_ENTIDAD = {int(entidad)}')
    if distrito is not None:
        condiciones.append(f'CLAVE_DISTRITO = {int(distrito)}')
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ''
    
    query = f"""
        SELECT 
            SECCION,
            SUM(CASE WHEN TIPO_CASILLA = 'B' THEN 1 ELSE 0 END) AS B_HIST,
            SUM(CASE WHEN TIPO_CASILLA = 'C' THEN 1 ELSE 0 END) AS C_HIST,
            SUM(CASE WHEN TIPO_CASILLA = 'E' THEN 1 ELSE 0 END) AS E_HIST,
            SUM(CASE WHEN TIPO_CASILLA = 'S' THEN 1 ELSE 0 END) AS S_HIST,
            COUNT(*) AS TOT_HIST
        FROM {tabla_hechos}
        {where}
        GROUP BY SECCION
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    for col in ['SECCION', 'B_HIST', 'C_HIST', 'E_HIST', 'S_HIST', 'TOT_HIST']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    return df

@st.cache_data(show_spinner=False)
def consultar_matrices_extintas(entidad=None, distrito=None):
    conn = sqlite3.connect(DB_PATH)
    condiciones = []
    if entidad is not None and entidad != 'Todas':
        condiciones.append(f'CLAVE_ENTIDAD = {int(entidad)}')
    if distrito is not None:
        condiciones.append(f'CLAVE_DISTRITO = {int(distrito)}')
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ''
    
    query = f"""
        SELECT DISTINCT SECCION_MATRIZ 
        FROM cat_equivalencias_reseccionamiento 
        {where}
    """
    try:
        df = pd.read_sql_query(query, conn)
        lista = df['SECCION_MATRIZ'].tolist()
    except:
        lista = []
    conn.close()
    return lista

def proyectar_seccion_lgipe(p):
    if p < 50:
        return 0, 0, 0
    elif p <= 750:
        return 1, 0, 1
    else:
        tot = int(np.ceil(p / 750.0))
        return 1, tot - 1, tot

def clasificar_causa(row, lista_matrices_extintas):
    p = row.get('PADRON_ELECTORAL', 0)
    ant = row.get('TOT_BC_HIST', row.get('TOT_BC_2024', 0))
    proy = row.get('TOT_BC_2026', 0)
    seccion = row.get('SECCION', -1)

    if seccion in lista_matrices_extintas:
        return '🗂️ Reseccionamiento (Sección Matriz Extinta / Fraccionada)'
    elif 0 < p < 50 and ant > 0:
        return '⚠️ Infralímite normativo (< 50 electores)'
    elif ant == 0 and proy > 0:
        return '🆕 Reseccionamiento (Nueva sección incorporada)'
    elif proy > ant:
        return '📈 Crecimiento Demográfico (+ Contiguas)'
    elif proy < ant:
        return '📉 Decremento Demográfico (- Contiguas)'
    else:
        return 'Sin Variación'

def render_tab_proyeccion(c_entidad_sel=None, c_distrito_sel=None):
    cortes_dict = obtener_cortes_padron_bd()
    if not cortes_dict:
        st.error('⚠️ No se encontraron tablas de Padrón Electoral en la base de datos.')
        return

    fechas_disponibles = list(cortes_dict.keys())

    # --- FILA DE CONTROL SUPERIOR (4 SELECTORES) ---
    col_corte, col_hist, col_ent, col_dist = st.columns([1.5, 1.2, 1.5, 1.5])

    with col_corte:
        fecha_sel = st.selectbox('📅 Corte de Padrón a Proyectar:', options=fechas_disponibles, index=0)
        tabla_corte_sel = cortes_dict[fecha_sel]

    with col_hist:
        base_comparativa = st.selectbox('⚖️ Comparar vs:', options=['PEF 2024', 'PEF 2021'], index=0)
        tabla_hist = 'hechos_recepcion_paquetes_2024' if '2024' in base_comparativa else 'hechos_recepcion_paquetes_2021'
        lbl_hist = '2024' if '2024' in base_comparativa else '2021'

    with col_ent:
        entidades_disp = list(CATALOGO_ENTIDADES.keys())
        idx_e = entidades_disp.index(c_entidad_sel) if c_entidad_sel in entidades_disp else (entidades_disp.index(20) if 20 in entidades_disp else 0)
        entidad_activa = st.selectbox('🏛️ Entidad Federativa:', options=entidades_disp, index=idx_e, format_func=lambda x: f'{x:02d} - {CATALOGO_ENTIDADES.get(x, "")}')

    with col_dist:
        opciones_dist = ['Todos'] + list(range(1, 33))
        idx_d = opciones_dist.index(c_distrito_sel) if c_distrito_sel in opciones_dist else 3
        distrito_sel = st.selectbox('📍 Distrito Federal:', options=opciones_dist, index=idx_d, format_func=lambda x: f'Distrito {x:02d}' if isinstance(x, int) else 'Todos los Distritos')

    dist_num = None if distrito_sel == 'Todos' else distrito_sel
    ver_ambito = 'Nacional' if entidad_activa == 'Todas' else ('Estatal' if dist_num is None else 'Distrital')
    etiqueta_ambito = f'Distrito {dist_num:02d} ({entidad_activa:02d} - {CATALOGO_ENTIDADES.get(entidad_activa, "")})' if dist_num else f'Estado de {CATALOGO_ENTIDADES.get(entidad_activa, "")}'

    # --- CONSULTA ULTRA RÁPIDA DESDE SQLITE ---
    df_padron = consultar_padron_bd(tabla_corte_sel, entidad=entidad_activa, distrito=dist_num)
    df_hist = consultar_historico_bd(tabla_hist, entidad=entidad_activa, distrito=dist_num)
    lista_matrices_extintas = consultar_matrices_extintas(entidad=entidad_activa, distrito=dist_num)

    if df_padron.empty:
        st.warning('⚠️ No se registraron datos de Padrón Electoral para el ámbito y corte seleccionados.')
        return

    df_base_u = df_padron.copy()
    df_padron_secc = df_padron.groupby('SECCION', as_index=False).agg({
        'PADRON_ELECTORAL': 'sum',
        'LISTA_NOMINAL': 'sum'
    })

    # Proyección ordinaria LGIPE
    res_proy = [proyectar_seccion_lgipe(p) for p in df_padron_secc['PADRON_ELECTORAL']]
    df_padron_secc['B_2026'] = [r[0] for r in res_proy]
    df_padron_secc['C_2026'] = [r[1] for r in res_proy]
    df_padron_secc['TOT_BC_2026'] = [r[2] for r in res_proy]

    df_proy = pd.merge(df_padron_secc, df_hist, on='SECCION', how='outer').fillna(0)

    # Asignación de Casillas Extraordinarias y Especiales (previas)
    df_proy['E_2026'] = np.where(df_proy['PADRON_ELECTORAL'] >= 50, df_proy['E_HIST'], 0)
    df_proy['S_2026'] = np.where(df_proy['PADRON_ELECTORAL'] >= 50, df_proy['S_HIST'], 0)
    df_proy['TOT_2026'] = df_proy['TOT_BC_2026'] + df_proy['E_2026'] + df_proy['S_2026']

    # 🔴 REGLA CERO ESTRICTA PARA MATRICES EXTINTAS 🔴
    # Aseguramos matemáticamente que toda matriz extinta caiga a 0 casillas, anulando proyecciones previas.
    es_matriz = df_proy['SECCION'].isin(lista_matrices_extintas)
    df_proy.loc[es_matriz, 'B_2026'] = 0
    df_proy.loc[es_matriz, 'C_2026'] = 0
    df_proy.loc[es_matriz, 'TOT_BC_2026'] = 0
    df_proy.loc[es_matriz, 'E_2026'] = 0
    df_proy.loc[es_matriz, 'S_2026'] = 0
    df_proy.loc[es_matriz, 'TOT_2026'] = 0

    tot_e_fijas = int(df_proy['E_2026'].sum())
    tot_s_fijas = int(df_proy['S_2026'].sum())

    tot_padron = int(df_padron_secc['PADRON_ELECTORAL'].sum())
    tot_ln = int(df_padron_secc['LISTA_NOMINAL'].sum())
    tot_b_2026 = int(df_proy['B_2026'].sum())
    tot_c_2026 = int(df_proy['C_2026'].sum())
    tot_bc_2026 = tot_b_2026 + tot_c_2026
    gran_total_2026 = int(df_proy['TOT_2026'].sum())

    tot_b_hist = int(df_proy['B_HIST'].sum())
    tot_c_hist = int(df_proy['C_HIST'].sum())
    tot_bc_hist = tot_b_hist + tot_c_hist
    gran_total_hist = int(df_proy['TOT_HIST'].sum())

    dif_neto = gran_total_2026 - gran_total_hist
    df_proy['TOT_BC_HIST'] = df_proy['B_HIST'] + df_proy['C_HIST']
    df_proy['TOT_BC_2024'] = df_proy['TOT_BC_HIST'] 
    df_proy['DIF_TOTAL'] = df_proy['TOT_2026'] - df_proy['TOT_HIST']
    df_proy['DIF_ORDINARIAS'] = df_proy['DIF_TOTAL']

    # --- 1. BALANCE GENERAL ---
    st.markdown('---')
    st.subheader(f'📊 Balance General — {etiqueta_ambito}')
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(f'Padrón ({fecha_sel})', f'{tot_padron:,}')
    k2.metric(f'Lista Nominal ({fecha_sel})', f'{tot_ln:,}')
    k3.metric(f'Instaladas {lbl_hist}', f'{gran_total_hist:,}')
    k4.metric('Proyectadas PEF', f'{gran_total_2026:,}', delta=f'{dif_neto:+d} casillas')
    k5.metric('Variación', f'{(dif_neto / gran_total_hist * 100):+.2f}%' if gran_total_hist > 0 else 'N/A')

    # --- 2. DESGLOSE TÉCNICO ---
    st.markdown('---')
    st.subheader('📑 Desglose Técnico por Tipo de Casilla')
    datos_tabla = {
        'Tipo de Casilla': ['Básicas', 'Contiguas', 'Subtotal Ordinarias (B+C)', 'Extraordinarias (Fijas)', 'Especiales (Fijas)', 'GRAN TOTAL DE CASILLAS'],
        f'Instaladas {lbl_hist}': [tot_b_hist, tot_c_hist, tot_bc_hist, tot_e_fijas, tot_s_fijas, gran_total_hist],
        'Proyectadas PEF': [tot_b_2026, tot_c_2026, tot_bc_2026, tot_e_fijas, tot_s_fijas, gran_total_2026],
        'Diferencia': [tot_b_2026 - tot_b_hist, tot_c_2026 - tot_c_hist, tot_bc_2026 - tot_bc_hist, 0, 0, dif_neto]
    }
    st.dataframe(pd.DataFrame(datos_tabla), use_container_width=True, hide_index=True)

    # --- 3. AUDITORÍA CAUSAL ---
    st.markdown('---')
    st.subheader(f'🔍 Auditoría Causal: Origen de las Diferencias (vs. {lbl_hist})')
    dif_mask = df_proy['DIF_ORDINARIAS'] != 0
    df_dif = df_proy[dif_mask].copy()

    if df_dif.empty:
        st.success(f'✅ No hay variaciones en casillas ordinarias respecto al proceso {lbl_hist}.')
    else:
        # Aquí inyectamos nuestra lista de matrices a la función validadora
        df_dif['Causa'] = df_dif.apply(lambda row: clasificar_causa(row, lista_matrices_extintas), axis=1)
        resumen_causas = df_dif.groupby('Causa')['DIF_ORDINARIAS'].agg(['count', 'sum']).reset_index()
        resumen_causas.columns = ['Causa Explicativa', 'Secciones Afectadas', 'Impacto Neto en Casillas']
        st.dataframe(resumen_causas, use_container_width=True, hide_index=True)

        with st.expander(f'📋 Ver detalle seccional de las diferencias vs. {lbl_hist}'):
            causas_disponibles = sorted(df_dif['Causa'].unique().tolist())
            col_f1, col_f2 = st.columns([3, 1])
            with col_f1:
                causas_sel = st.multiselect(
                    'Filtrar por Causa Explicativa:',
                    options=causas_disponibles,
                    default=causas_disponibles,
                    help='Selecciona una o más causas para acotar el listado seccional.'
                )
            with col_f2:
                st.metric('Secciones Visibles', f"{len(df_dif[df_dif['Causa'].isin(causas_sel)]):,}")

            mostrar = df_dif[df_dif['Causa'].isin(causas_sel)].sort_values(by='SECCION')
            cols_disp = ['SECCION']
            if 'Origen Matriz' in mostrar.columns:
                cols_disp.append('Origen Matriz')
            cols_disp += ['PADRON_ELECTORAL', 'LISTA_NOMINAL', 'TOT_HIST', 'TOT_2026', 'DIF_TOTAL', 'Causa']
            mostrar = mostrar[cols_disp]
            nombres = ['Sección']
            if 'Origen Matriz' in cols_disp:
                nombres.append('Sección Origen / Matriz')
            nombres += ['Padrón', 'Lista Nominal', f'Total Casillas {lbl_hist}', 'Total Proyectadas', 'Diferencia', 'Causa Explicativa']
            mostrar.columns = nombres
            st.dataframe(mostrar, use_container_width=True, hide_index=True)

    # Cálculo vectorial para semáforo operativo
    padron = pd.to_numeric(df_base_u['PADRON_ELECTORAL'], errors='coerce').fillna(0).values
    casillas = np.where(padron < 50, 0, np.maximum(1, np.ceil(padron / 750.0).astype(int)))
    siguiente_umbral = np.where(casillas == 0, 50, (casillas * 750) + 1)
    faltan_para_otra = np.where(padron < 50, 50 - padron, siguiente_umbral - padron)
    alerta_detonacion = (padron >= 50) & (faltan_para_otra <= 10)
    margen_caer = np.maximum(0, padron - 49)
    
    df_base_u['Casillas Actuales'] = casillas
    df_base_u['Faltan para +1 Casilla'] = faltan_para_otra
    df_base_u['Alerta Detonacion'] = alerta_detonacion
    df_base_u['Margen antes de caer'] = margen_caer

    # --- SECCIONES 50 A 99 ELECTORES: SUSCEPTIBLES DE ACUERDO DEL CONSEJO (ART. 253 LGIPE) ---
    st.markdown('---')
    st.subheader('🏛️ Casillas Susceptibles de Acuerdo del Consejo Distrital (50 a 99 electores)')
    st.caption('De conformidad con el Art. 253, párrafo 3 de la LGIPE, estas secciones proyectan preliminarmente su casilla básica, quedando sujeta su instalación o incorporación contigua a la determinación expresa del Consejo Distrital.')
    
    cond_consejo = (df_base_u['PADRON_ELECTORAL'] >= 50) & (df_base_u['PADRON_ELECTORAL'] < 100)
    df_consejo = df_base_u[cond_consejo].copy()
    
    if df_consejo.empty:
        st.success('✅ No existen secciones en el rango de 50 a 99 electores en el ámbito seleccionado.')
    else:
        st.metric('Casillas Básicas Proyectadas (Sujetas a Acuerdo)', f'{len(df_consejo):,}')
        df_consejo = df_consejo.sort_values(by='PADRON_ELECTORAL', ascending=True)
        df_consejo['DISTRITO'] = df_consejo['CLAVE_DISTRITO'].apply(lambda d: f'Distrito {int(d):02d}')
        if 'Nacional' in ver_ambito:
            df_consejo['ENTIDAD'] = df_consejo['CLAVE_ENTIDAD'].map(CATALOGO_ENTIDADES)
            cols_c = ['ENTIDAD', 'DISTRITO', 'SECCION', 'PADRON_ELECTORAL', 'LISTA_NOMINAL']
        else:
            cols_c = ['DISTRITO', 'SECCION', 'PADRON_ELECTORAL', 'LISTA_NOMINAL']
        st.dataframe(df_consejo[cols_c], use_container_width=True, hide_index=True)
    
    col_u1, col_u2 = st.columns(2)

    with col_u1:
        st.subheader("⚠️ Riesgo de Infralímite (100 a 110 electores)")
        st.caption("Padrón a ≤ 10 bajas de perder la casilla básica (< 100 electores).")
        cond_baja = (df_base_u["PADRON_ELECTORAL"] >= 100) & (df_base_u["PADRON_ELECTORAL"] <= 110)
        df_u_baja = df_base_u[cond_baja].copy()
        
        if df_u_baja.empty:
            st.success("No hay secciones en riesgo de infralímite en este ámbito.")
        else:
            st.metric("Secciones en Riesgo Infralímite", f"{len(df_u_baja):,}")
            df_u_baja = df_u_baja.sort_values(by="Margen antes de caer", ascending=True)
            df_u_baja["DISTRITO"] = df_u_baja["CLAVE_DISTRITO"].apply(lambda d: f"Distrito {int(d):02d}")
            if "Nacional" in ver_ambito:
                df_u_baja["ENTIDAD"] = df_u_baja["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
                cols_baja = ["ENTIDAD", "DISTRITO", "SECCION", "PADRON_ELECTORAL", "LISTA_NOMINAL", "Margen antes de caer"]
            else:
                cols_baja = ["DISTRITO", "SECCION", "PADRON_ELECTORAL", "LISTA_NOMINAL", "Margen antes de caer"]
            st.dataframe(df_u_baja[cols_baja], use_container_width=True, hide_index=True)

    with col_u2:
        st.subheader("🚨 A Punto de Detonar +1 Casilla (Faltan ≤ 10 electores)")
        st.caption("Padrón a ≤ 10 altas de rebasar múltiplos de 750 (750, 1500, 2250, etc.).")
        cond_alta = df_base_u["Alerta Detonacion"] == True
        df_u_alta = df_base_u[cond_alta].copy()
        
        if df_u_alta.empty:
            st.info("No hay secciones a ≤ 10 electores de detonar otra casilla.")
        else:
            st.metric("Secciones por Disparar Casilla", f"{len(df_u_alta):,}")
            df_u_alta = df_u_alta.sort_values(by="Faltan para +1 Casilla", ascending=True)
            df_u_alta["DISTRITO"] = df_u_alta["CLAVE_DISTRITO"].apply(lambda d: f"Distrito {int(d):02d}")
            if "Nacional" in ver_ambito:
                df_u_alta["ENTIDAD"] = df_u_alta["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
                cols_alta = ["ENTIDAD", "DISTRITO", "SECCION", "PADRON_ELECTORAL", "Casillas Actuales", "Faltan para +1 Casilla"]
            else:
                cols_alta = ["DISTRITO", "SECCION", "PADRON_ELECTORAL", "Casillas Actuales", "Faltan para +1 Casilla"]
            st.dataframe(df_u_alta[cols_alta], use_container_width=True, hide_index=True)

    st.markdown("---")

    st.download_button(
        f"📥 Descargar Proyección Seccional ({fecha_sel}) en CSV",
        data=df_proy.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"proyeccion_casillas_{fecha_sel}_{entidad_activa}_{distrito_sel}.csv",
        mime="text/csv"
    )