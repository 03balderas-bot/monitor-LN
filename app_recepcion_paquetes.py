from modulo_proyeccion import render_tab_proyeccion
import time
import os
import shutil
import json
import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
import py7zr
import streamlit as st

st.set_page_config(
    page_title="Auditoría Logística PREP: Histórico y Comparativa",
    layout="wide"
)

# --- ARRANQUE DE BASE DE DATOS (descomprime derfe_web.7z si no hay .db) ---
DIR_RAIZ = Path(__file__).parent
DB_PATH = DIR_RAIZ / "derfe_web.db"
ARCHIVE_7Z_PATH = DIR_RAIZ / "derfe_web.7z"
LOCK_PATH = DIR_RAIZ / ".extrayendo.lock"
TMP_EXTRACCION = DIR_RAIZ / ".extraccion_tmp"
META_PATH = DIR_RAIZ / ".extraccion_ok.json"


def _bd_sana():
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()
        con.close()
        return True
    except Exception:
        return False


def _extraer_si_conviene():
    # Evita re-extraer cuando el .7z ya es el mismo que originó la .db actual
    # (al recomprimir, el .7z queda con mtime mayor que la .db y sin esto
    # cada arranque reintentaría la extracción de los 283 MB).
    if not DB_PATH.exists() or not _bd_sana():
        return True
    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        return not (
            meta.get("7z_mtime") == ARCHIVE_7Z_PATH.stat().st_mtime
            and meta.get("7z_size") == ARCHIVE_7Z_PATH.stat().st_size
        )
    except Exception:
        return True


def _extraer_bd_atomico():
    # Descomprime en carpeta temporal y solo al final mueve el archivo completo:
    # nunca queda una .db a la mitad aunque el contenedor se interrumpa.
    if TMP_EXTRACCION.exists():
        shutil.rmtree(TMP_EXTRACCION, ignore_errors=True)
    TMP_EXTRACCION.mkdir()
    try:
        with py7zr.SevenZipFile(ARCHIVE_7Z_PATH, mode="r") as z:
            z.extractall(path=TMP_EXTRACCION)
        tmp_db = TMP_EXTRACCION / "derfe_web.db"
        if not tmp_db.exists():
            raise RuntimeError("derfe_web.db no aparecio tras descomprimir")
        os.replace(tmp_db, DB_PATH)
    finally:
        shutil.rmtree(TMP_EXTRACCION, ignore_errors=True)


if ARCHIVE_7Z_PATH.exists():
    if _extraer_si_conviene():
        # Candado: si otra sesion del contenedor esta extrayendo, espera a que termine
        # (candado viejo de mas de 10 min = extraccion interrumpida, se retoma).
        extrajo = False
        for _ in range(2):
            try:
                fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                extrajo = True
                break
            except FileExistsError:
                if time.time() - LOCK_PATH.stat().st_mtime > 600:
                    LOCK_PATH.unlink(missing_ok=True)
                    continue
                for _ in range(180):
                    if not LOCK_PATH.exists() and DB_PATH.exists() and _bd_sana():
                        break
                    time.sleep(1)
                break
        if extrajo:
            try:
                _extraer_bd_atomico()
                META_PATH.write_text(json.dumps({
                    "7z_mtime": ARCHIVE_7Z_PATH.stat().st_mtime,
                    "7z_size": ARCHIVE_7Z_PATH.stat().st_size,
                }), encoding="utf-8")
            except Exception as e:
                st.error(f"Error al descomprimir derfe_web.7z: {e}")
            finally:
                LOCK_PATH.unlink(missing_ok=True)

DB_NAME = str(DB_PATH)

import modulo_proyeccion
modulo_proyeccion.DB_PATH = DB_NAME

# --- CONFIGURACIÓN MODULAR POR PROCESO ELECTORAL FEDERAL ---
PROCESOS_CONFIG = {
    "PEF 2024": {
        "tabla_hechos": "hechos_recepcion_paquetes_2024",
        "tabla_geo": "dim_geografia",
        "hora_inicio": "2024-06-02 18:00:00",
        "hora_medianoche": "2024-06-03 00:00:00",
        "hora_cierre_prep": "2024-06-03 20:05:00",
        "prefijo_corte_temprano": "2024-06-02 18:"
    },
    "PEF 2021": {
        "tabla_hechos": "hechos_recepcion_paquetes_2021",
        "tabla_geo": "dim_geografia_2021",
        "hora_inicio": "2021-06-06 18:00:00",
        "hora_medianoche": "2021-06-07 00:00:00",
        "hora_cierre_prep": "2021-06-07 20:00:00",
        "prefijo_corte_temprano": "2021-06-06 18:"
    }
}

# --- FUNCIONES AUXILIARES DE COLORIMETRÍA TÉRMICA (VERDE A ROJO) ---
def interpolar_color_pausa(factor_severidad):
    """
    Interpola suavemente de Verde (#28a745) a Amarillo (#ffc107) a Rojo Carmesí (#b71c1c).
    factor_severidad: float entre 0.0 (sin pausas) y 1.0 (máxima severidad de pausa del grupo).
    """
    f = max(0.0, min(1.0, factor_severidad))
    if f <= 0.5:
        # De Verde (40, 167, 69) a Amarillo (255, 193, 7)
        local_f = f / 0.5
        r = int(40 + (255 - 40) * local_f)
        g = int(167 + (193 - 167) * local_f)
        b = int(69 + (7 - 69) * local_f)
    else:
        # De Amarillo (255, 193, 7) a Rojo Carmesí (183, 28, 28)
        local_f = (f - 0.5) / 0.5
        r = int(255 + (183 - 255) * local_f)
        g = int(193 + (28 - 193) * local_f)
        b = int(7 + (28 - 7) * local_f)
    return f"rgb({r},{g},{b})"


# --- RENDERIZADO DE LA CARRERA (métricas + gráfica) DENTRO DE UN CONTENEDOR ---
# Al pintarse en un placeholder propio, la animación actualiza solo la gráfica
# en lugar de redibujar toda la página en cada tramo (elimina el parpadeo).
def pintar_carrera(contenedor, paso_actual_str, df_universo, df_llegadas, cfg_proceso, proceso_sel, nivel_seleccionado):
    with contenedor.container():
        # Acumulado hasta el corte actual
        llegadas_hasta_corte = df_llegadas[df_llegadas["bloque_tiempo"] <= paso_actual_str]
        recibidos_dict = llegadas_hasta_corte.groupby("id_unidad")["recibidos_tramo"].sum().to_dict()

        ultimos_bloques_dict = llegadas_hasta_corte[llegadas_hasta_corte["recibidos_tramo"] > 0].groupby("id_unidad")["bloque_tiempo"].max().to_dict()

        df_estado = df_universo.copy()
        df_estado["recibidos"] = df_estado["id_unidad"].map(recibidos_dict).fillna(0).astype(int)
        df_estado["porcentaje"] = (df_estado["recibidos"] / df_estado["total_esperadas"]) * 100
        df_estado["ultimo_bloque"] = df_estado["id_unidad"].map(ultimos_bloques_dict).fillna(cfg_proceso["hora_inicio"][:16])

        # Máximo de horas de pausa acumuladas para calibrar el semáforo degradado Verde -> Rojo
        max_horas_pausa_grupo = df_estado["horas_pausa_total"].max()
        if max_horas_pausa_grupo == 0 or pd.isna(max_horas_pausa_grupo):
            max_horas_pausa_grupo = 1.0

        colores_barra = []
        textos_dentro = []
        colores_texto = []
        textos_hover = []

        es_segundo_dia = paso_actual_str >= cfg_proceso["hora_medianoche"][:16]
        dt_paso_actual = pd.to_datetime(paso_actual_str)

        for _, row in df_estado.iterrows():
            ya_concluyo = (paso_actual_str >= row["bloque_fin_real"]) and (row["total_recibidos_final"] > 0)

            dt_ult_bloque = pd.to_datetime(row["ultimo_bloque"])
            horas_inactivo_momento = (dt_paso_actual - dt_ult_bloque).total_seconds() / 3600.0

            n_pausas = int(row["num_pausas"])
            tot_h_pausa = float(row["horas_pausa_total"])
            h_pausa_entera = int(tot_h_pausa)
            m_pausa_entero = int(round((tot_h_pausa - h_pausa_entera) * 60))

            if ya_concluyo:
                # Degradado continuo en la barra: de Verde Esmeralda (sin pausas) a Rojo Carmesí (máximas pausas)
                if n_pausas > 0 and tot_h_pausa >= 0.5:
                    factor_severidad = tot_h_pausa / max_horas_pausa_grupo
                    color_termico = interpolar_color_pausa(factor_severidad)
                    colores_barra.append(color_termico)
                else:
                    colores_barra.append("#28a745")  # Verde puro continuo
                colores_texto.append("#ffffff")
            else:
                if es_segundo_dia:
                    colores_barra.append("#ffc107")  # 🟡 Amarillo día 2
                    colores_texto.append("#000000")
                else:
                    colores_barra.append("#dc3545")  # 🔴 Rojo día 1
                    colores_texto.append("#ffffff")

            recibidos_mostrar = row["total_recibidos_final"] if ya_concluyo else row["recibidos"]

            if row["porcentaje"] > 4:
                if ya_concluyo and n_pausas > 0:
                    textos_dentro.append(f"🏁 ({row['total_esperadas']}/{recibidos_mostrar}) [Pausas: {h_pausa_entera}h {m_pausa_entero:02d}m]")
                else:
                    textos_dentro.append(f"({row['total_esperadas']}/{recibidos_mostrar})")
            else:
                textos_dentro.append("")

            # Tooltip enriquecido
            detalle_hover = f"<b>{row['nombre_unidad']}</b><br>Esperadas: {row['total_esperadas']:,}<br>Recibidas: {row['recibidos']:,}<br>Avance: {row['porcentaje']:.2f}%"
            if ya_concluyo:
                detalle_hover += f"<br>🏁 <b>Conclusión de Acopio:</b> {row['hora_fin_real']}"
                if n_pausas > 0:
                    pct_severidad = round(tot_h_pausa / max_horas_pausa_grupo * 100, 1)
                    detalle_hover += (
                        f"<br><br>⏸️ <b>Auditoría de Pausas (≥ 30 min):</b>"
                        f"<br>• <b>Total de Pausas Registradas:</b> {n_pausas} evento(s)"
                        f"<br>• <b>Tiempo Acumulado en Pausa:</b> {h_pausa_entera}h {m_pausa_entero:02d}m"
                        f"<br>• <b>Pausa Continua Máxima:</b> {row['max_pausa_horas']:.1f} hrs"
                        f"<br>• <b>Tonalidad Térmica:</b> {pct_severidad}% de severidad relativa (Verde ➔ Rojo)"
                    )
                else:
                    detalle_hover += "<br>✅ <b>Flujo Continuo:</b> Sin pausas superiores a 30 minutos (Verde Esmeralda Puro)."
            else:
                if horas_inactivo_momento >= 0.5 and row["recibidos"] > 0:
                    h_inact_cur = int(horas_inactivo_momento)
                    m_inact_cur = int(round((horas_inactivo_momento - h_inact_cur) * 60))
                    detalle_hover += f"<br>⏳ <b>En pausa actual:</b> Lleva {h_inact_cur}h {m_inact_cur:02d}m sin paquetes nuevos."

            textos_hover.append(detalle_hover)

        df_estado["color"] = colores_barra
        df_estado["texto_dentro"] = textos_dentro
        df_estado["color_texto"] = colores_texto
        df_estado["hover_info"] = textos_hover

        df_estado = df_estado.sort_values(by="id_unidad", ascending=False)

        tot_esp = df_estado["total_esperadas"].sum()
        tot_rec = df_estado["recibidos"].sum()
        tot_fal = tot_esp - tot_rec
        pct_glob = (tot_rec / tot_esp * 100) if tot_esp > 0 else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Hora de Corte (Acopio)", paso_actual_str)
        m2.metric("Paquetes en Sede", f"{tot_rec:,} / {tot_esp:,}")
        m3.metric("Faltantes al Corte", f"{tot_fal:,}")
        m4.metric("% Recuperación", f"{pct_glob:.2f}%")

        st.divider()

        posiciones_y = list(range(len(df_estado)))

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=posiciones_y,
            x=df_estado["porcentaje"],
            orientation="h",
            marker=dict(
                color=df_estado["color"],
                line=dict(color="#111111", width=1)
            ),
            text=df_estado["texto_dentro"],
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color=df_estado["color_texto"], size=12, family="Arial Black"),
            cliponaxis=False,
            hoverinfo="text",
            hovertext=df_estado["hover_info"]
        ))

        fig.update_layout(
            title=dict(
                text=f"<b>Ritmo de Recepción ({proceso_sel} - {nivel_seleccionado}) | Corte: {paso_actual_str} hrs</b>",
                font=dict(size=18, color="#1f2937")
            ),
            xaxis=dict(
                title="% de Paquetes Recibidos (Verde = Flujo continuo | Ámbar / Rojo = Pausas acumuladas prolongadas)",
                range=[0, 102],
                ticksuffix="%",
                gridcolor="#d1d5db"
            ),
            yaxis=dict(
                tickmode="array",
                tickvals=posiciones_y,
                ticktext=list(df_estado["nombre_unidad"]),
                tickfont=dict(size=12, color="#374151"),
                automargin=True
            ),
            height=max(450, len(df_estado) * 32),
            margin=dict(l=260, r=20, t=50, b=40)
        )

        fig.add_vline(x=100, line_dash="dash", line_color="#334155", line_width=2, annotation_text=" 100%", annotation_font_color="#334155")
        st.plotly_chart(fig, width='stretch')

# --- CONSULTAS DE CATÁLOGOS BASE ---
@st.cache_data
def obtener_entidades(tabla_geo):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(f"SELECT DISTINCT CLAVE_ENTIDAD, NOMBRE_ENTIDAD FROM {tabla_geo} ORDER BY CLAVE_ENTIDAD;", conn)
    conn.close()
    return df

@st.cache_data
def obtener_distritos(c_entidad, tabla_geo):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(f"SELECT DISTINCT CLAVE_DISTRITO, CABECERA_DISTRITAL FROM {tabla_geo} WHERE CLAVE_ENTIDAD = {c_entidad} ORDER BY CLAVE_DISTRITO;", conn)
    conn.close()
    return df

@st.cache_data
def obtener_mecanismos_digitalizacion(tabla_hechos):
    conn = sqlite3.connect(DB_NAME)
    query = f"""
        SELECT DISTINCT DIGITALIZACION 
        FROM {tabla_hechos} 
        WHERE DIGITALIZACION IS NOT NULL AND DIGITALIZACION != '' AND DIGITALIZACION != '-'
        ORDER BY DIGITALIZACION;
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return [d for d in df["DIGITALIZACION"].tolist() if d]

# --- CONSULTA DETALLE DE CASILLAS (CRUCE GEOGRÁFICO DESACOPLADO) ---
@st.cache_data
def obtener_detalle_casillas(cfg, nivel, c_entidad=None, c_distrito=None, f_digitalizacion=None):
    tabla_hechos = cfg["tabla_hechos"]
    tabla_geo = cfg["tabla_geo"]
    
    conn = sqlite3.connect(DB_NAME)
    condiciones = ["1=1"]
    if nivel in ["Estatal", "Distrital"] and c_entidad:
        condiciones.append(f"r.CLAVE_ENTIDAD = {c_entidad}")
    if nivel == "Distrital" and c_distrito:
        condiciones.append(f"r.CLAVE_DISTRITO = {c_distrito}")
    if f_digitalizacion:
        condiciones.append(f"r.DIGITALIZACION = '{f_digitalizacion}'")
        
    where_sql = " AND ".join(condiciones)
    query = f"""
        SELECT 
            r.CLAVE_CASILLA,
            r.CLAVE_ENTIDAD,
            COALESCE(ent.NOMBRE_ENTIDAD, 'ENTIDAD ' || printf('%02d', r.CLAVE_ENTIDAD)) AS NOMBRE_ENTIDAD,
            r.CLAVE_DISTRITO,
            COALESCE(dist.CABECERA_DISTRITAL, 'DISTRITO ' || printf('%02d', r.CLAVE_DISTRITO)) AS CABECERA_DISTRITAL,
            COALESCE(sec.NOMBRE_MUNICIPIO, 'Revisar Afectación al MGE') AS NOMBRE_MUNICIPIO,
            r.SECCION,
            r.TIPO_CASILLA,
            r.EXT_CONTIGUA,
            r.MECANISMO_TRASLADO,
            r.ORIGEN,
            r.DIGITALIZACION,
            r.FECHA_HORA_ACOPIO,
            r.RECIBIDO
        FROM {tabla_hechos} r
        LEFT JOIN (
            SELECT DISTINCT CLAVE_ENTIDAD, NOMBRE_ENTIDAD 
            FROM {tabla_geo}
        ) ent ON r.CLAVE_ENTIDAD = ent.CLAVE_ENTIDAD
        LEFT JOIN (
            SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, CABECERA_DISTRITAL 
            FROM {tabla_geo}
        ) dist ON r.CLAVE_ENTIDAD = dist.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = dist.CLAVE_DISTRITO
        LEFT JOIN (
            SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, NOMBRE_MUNICIPIO 
            FROM {tabla_geo}
        ) sec ON r.CLAVE_ENTIDAD = sec.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = sec.CLAVE_DISTRITO AND r.SECCION = sec.SECCION
        WHERE {where_sql}
        ORDER BY r.CLAVE_ENTIDAD, r.CLAVE_DISTRITO, r.SECCION, r.TIPO_CASILLA;
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# --- CONSULTA DE CASILLAS ATÍPICAS ---
@st.cache_data
def obtener_casillas_atipicas(cfg, umbral_str, nivel, c_entidad=None, c_distrito=None, f_digitalizacion=None):
    tabla_hechos = cfg["tabla_hechos"]
    tabla_geo = cfg["tabla_geo"]
    hora_inicio = cfg["hora_inicio"]

    conn = sqlite3.connect(DB_NAME)
    condiciones = [
        "r.RECIBIDO = 1",
        f"r.FECHA_HORA_ACOPIO >= '{hora_inicio}'",
        f"r.FECHA_HORA_ACOPIO <= '{umbral_str}'"
    ]
    if nivel in ["Estatal", "Distrital"] and c_entidad:
        condiciones.append(f"r.CLAVE_ENTIDAD = {c_entidad}")
    if nivel == "Distrital" and c_distrito:
        condiciones.append(f"r.CLAVE_DISTRITO = {c_distrito}")
    if f_digitalizacion:
        condiciones.append(f"r.DIGITALIZACION = '{f_digitalizacion}'")

    where_sql = " AND ".join(condiciones)
    query = f"""
        SELECT 
            r.CLAVE_CASILLA,
            r.CLAVE_ENTIDAD,
            COALESCE(ent.NOMBRE_ENTIDAD, 'ENTIDAD ' || printf('%02d', r.CLAVE_ENTIDAD)) AS NOMBRE_ENTIDAD,
            r.CLAVE_DISTRITO,
            COALESCE(dist.CABECERA_DISTRITAL, 'DISTRITO ' || printf('%02d', r.CLAVE_DISTRITO)) AS CABECERA_DISTRITAL,
            COALESCE(sec.NOMBRE_MUNICIPIO, 'Revisar Afectación al MGE') AS NOMBRE_MUNICIPIO,
            r.SECCION,
            r.TIPO_CASILLA,
            r.EXT_CONTIGUA,
            r.ORIGEN,
            r.DIGITALIZACION,
            r.MECANISMO_TRASLADO,
            r.FECHA_HORA_ACOPIO
        FROM {tabla_hechos} r
        LEFT JOIN (
            SELECT DISTINCT CLAVE_ENTIDAD, NOMBRE_ENTIDAD 
            FROM {tabla_geo}
        ) ent ON r.CLAVE_ENTIDAD = ent.CLAVE_ENTIDAD
        LEFT JOIN (
            SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, CABECERA_DISTRITAL 
            FROM {tabla_geo}
        ) dist ON r.CLAVE_ENTIDAD = dist.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = dist.CLAVE_DISTRITO
        LEFT JOIN (
            SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, NOMBRE_MUNICIPIO 
            FROM {tabla_geo}
        ) sec ON r.CLAVE_ENTIDAD = sec.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = sec.CLAVE_DISTRITO AND r.SECCION = sec.SECCION
        WHERE {where_sql}
        ORDER BY r.FECHA_HORA_ACOPIO ASC, r.CLAVE_ENTIDAD, r.CLAVE_DISTRITO;
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# --- CONSULTA DE DATOS PARA LA CARRERA DE RATAS Y CORTES LOGÍSTICOS ---
@st.cache_data
def cargar_datos_carrera(cfg, nivel, c_entidad=None, c_distrito=None, f_digitalizacion=None):
    tabla_hechos = cfg["tabla_hechos"]
    tabla_geo = cfg["tabla_geo"]
    hora_inicio = cfg["hora_inicio"]
    hora_cierre_prep = cfg["hora_cierre_prep"]
    hora_medianoche = cfg["hora_medianoche"]

    conn = sqlite3.connect(DB_NAME)
    filtro_dig_sql = f"AND r.DIGITALIZACION = '{f_digitalizacion}'" if f_digitalizacion else ""
    
    prefijo_dia2 = hora_medianoche[:10]
    corte_04 = f"{prefijo_dia2} 04:00:00"
    corte_08 = f"{prefijo_dia2} 08:00:00"
    corte_12 = f"{prefijo_dia2} 12:00:00"

    if nivel == "Nacional":
        query_universo = f"""
            SELECT 
                r.CLAVE_ENTIDAD AS id_unidad,
                printf('%02d', r.CLAVE_ENTIDAD) || ' - ' || COALESCE(g.NOMBRE_ENTIDAD, 'ENTIDAD ' || printf('%02d', r.CLAVE_ENTIDAD)) AS nombre_unidad,
                COUNT(*) AS total_esperadas,
                COALESCE(MAX(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN r.FECHA_HORA_ACOPIO ELSE NULL END), '{hora_inicio}') AS hora_fin_real,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN 1 ELSE 0 END) AS total_recibidos_final
            FROM {tabla_hechos} r
            LEFT JOIN (SELECT DISTINCT CLAVE_ENTIDAD, NOMBRE_ENTIDAD FROM {tabla_geo}) g ON r.CLAVE_ENTIDAD = g.CLAVE_ENTIDAD
            WHERE 1=1 {filtro_dig_sql}
            GROUP BY r.CLAVE_ENTIDAD, g.NOMBRE_ENTIDAD
            ORDER BY r.CLAVE_ENTIDAD ASC;
        """
        query_recepcion = f"""
            SELECT 
                CLAVE_ENTIDAD AS id_unidad,
                strftime('%Y-%m-%d %H:', FECHA_HORA_ACOPIO) || 
                CASE 
                    WHEN cast(strftime('%M', FECHA_HORA_ACOPIO) as integer) < 15 THEN '00'
                    WHEN cast(strftime('%M', FECHA_HORA_ACOPIO) as integer) < 30 THEN '15'
                    WHEN cast(strftime('%M', FECHA_HORA_ACOPIO) as integer) < 45 THEN '30'
                    ELSE '45'
                END AS bloque_tiempo,
                COUNT(*) AS recibidos_tramo
            FROM {tabla_hechos} r
            WHERE r.RECIBIDO = 1 
              AND r.FECHA_HORA_ACOPIO >= '{hora_inicio}' 
              AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}'
              {filtro_dig_sql}
            GROUP BY CLAVE_ENTIDAD, bloque_tiempo
            ORDER BY bloque_tiempo ASC;
        """
        query_tabla = f"""
            SELECT 
                r.CLAVE_ENTIDAD AS id_unidad,
                printf('%02d', r.CLAVE_ENTIDAD) || ' - ' || COALESCE(g.NOMBRE_ENTIDAD, 'ENTIDAD ' || printf('%02d', r.CLAVE_ENTIDAD)) AS Unidad,
                COUNT(*) AS Total_Esperadas,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO < '{hora_medianoche}' THEN 1 ELSE 0 END) AS Rec_00hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_04}' THEN 1 ELSE 0 END) AS Rec_04hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_08}' THEN 1 ELSE 0 END) AS Rec_08hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_12}' THEN 1 ELSE 0 END) AS Rec_12hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN 1 ELSE 0 END) AS Rec_Final
            FROM {tabla_hechos} r
            LEFT JOIN (SELECT DISTINCT CLAVE_ENTIDAD, NOMBRE_ENTIDAD FROM {tabla_geo}) g ON r.CLAVE_ENTIDAD = g.CLAVE_ENTIDAD
            WHERE 1=1 {filtro_dig_sql}
            GROUP BY r.CLAVE_ENTIDAD, g.NOMBRE_ENTIDAD
            ORDER BY r.CLAVE_ENTIDAD ASC;
        """

    elif nivel == "Estatal":
        query_universo = f"""
            SELECT 
                r.CLAVE_DISTRITO AS id_unidad,
                'Dto ' || printf('%02d', r.CLAVE_DISTRITO) || ' - ' || COALESCE(g.CABECERA_DISTRITAL, 'CABECERA ' || printf('%02d', r.CLAVE_DISTRITO)) AS nombre_unidad,
                COUNT(*) AS total_esperadas,
                COALESCE(MAX(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN r.FECHA_HORA_ACOPIO ELSE NULL END), '{hora_inicio}') AS hora_fin_real,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN 1 ELSE 0 END) AS total_recibidos_final
            FROM {tabla_hechos} r
            LEFT JOIN (SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, CABECERA_DISTRITAL FROM {tabla_geo}) g 
                ON r.CLAVE_ENTIDAD = g.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = g.CLAVE_DISTRITO
            WHERE r.CLAVE_ENTIDAD = {c_entidad} {filtro_dig_sql}
            GROUP BY r.CLAVE_DISTRITO, g.CABECERA_DISTRITAL
            ORDER BY r.CLAVE_DISTRITO ASC;
        """
        query_recepcion = f"""
            SELECT 
                CLAVE_DISTRITO AS id_unidad,
                strftime('%Y-%m-%d %H:', FECHA_HORA_ACOPIO) || 
                CASE 
                    WHEN cast(strftime('%M', FECHA_HORA_ACOPIO) as integer) < 15 THEN '00'
                    WHEN cast(strftime('%M', FECHA_HORA_ACOPIO) as integer) < 30 THEN '15'
                    WHEN cast(strftime('%M', FECHA_HORA_ACOPIO) as integer) < 45 THEN '30'
                    ELSE '45'
                END AS bloque_tiempo,
                COUNT(*) AS recibidos_tramo
            FROM {tabla_hechos} r
            WHERE r.CLAVE_ENTIDAD = {c_entidad}
              AND r.RECIBIDO = 1 
              AND r.FECHA_HORA_ACOPIO >= '{hora_inicio}' 
              AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}'
              {filtro_dig_sql}
            GROUP BY CLAVE_DISTRITO, bloque_tiempo
            ORDER BY bloque_tiempo ASC;
        """
        query_tabla = f"""
            SELECT 
                r.CLAVE_DISTRITO AS id_unidad,
                'Dto ' || printf('%02d', r.CLAVE_DISTRITO) || ' - ' || COALESCE(g.CABECERA_DISTRITAL, 'CABECERA ' || printf('%02d', r.CLAVE_DISTRITO)) AS Unidad,
                COUNT(*) AS Total_Esperadas,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO < '{hora_medianoche}' THEN 1 ELSE 0 END) AS Rec_00hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_04}' THEN 1 ELSE 0 END) AS Rec_04hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_08}' THEN 1 ELSE 0 END) AS Rec_08hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_12}' THEN 1 ELSE 0 END) AS Rec_12hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN 1 ELSE 0 END) AS Rec_Final
            FROM {tabla_hechos} r
            LEFT JOIN (SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, CABECERA_DISTRITAL FROM {tabla_geo}) g 
                ON r.CLAVE_ENTIDAD = g.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = g.CLAVE_DISTRITO
            WHERE r.CLAVE_ENTIDAD = {c_entidad} {filtro_dig_sql}
            GROUP BY r.CLAVE_DISTRITO, g.CABECERA_DISTRITAL
            ORDER BY r.CLAVE_DISTRITO ASC;
        """

    else:  # Nivel Distrital (Municipios)
        query_universo = f"""
            SELECT 
                COALESCE(g.CLAVE_MUNICIPIO, 999) AS id_unidad,
                printf('%03d', COALESCE(g.CLAVE_MUNICIPIO, 999)) || ' - ' || COALESCE(g.NOMBRE_MUNICIPIO, 'Revisar Afectación al MGE') AS nombre_unidad,
                COUNT(*) AS total_esperadas,
                COALESCE(MAX(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN r.FECHA_HORA_ACOPIO ELSE NULL END), '{hora_inicio}') AS hora_fin_real,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN 1 ELSE 0 END) AS total_recibidos_final
            FROM {tabla_hechos} r
            LEFT JOIN (
                SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, CLAVE_MUNICIPIO, NOMBRE_MUNICIPIO 
                FROM {tabla_geo}
            ) g ON r.CLAVE_ENTIDAD = g.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = g.CLAVE_DISTRITO AND r.SECCION = g.SECCION
            WHERE r.CLAVE_ENTIDAD = {c_entidad} AND r.CLAVE_DISTRITO = {c_distrito} {filtro_dig_sql}
            GROUP BY id_unidad, nombre_unidad
            ORDER BY id_unidad ASC;
        """
        query_recepcion = f"""
            SELECT 
                COALESCE(g.CLAVE_MUNICIPIO, 999) AS id_unidad,
                strftime('%Y-%m-%d %H:', r.FECHA_HORA_ACOPIO) || 
                CASE 
                    WHEN cast(strftime('%M', r.FECHA_HORA_ACOPIO) as integer) < 15 THEN '00'
                    WHEN cast(strftime('%M', r.FECHA_HORA_ACOPIO) as integer) < 30 THEN '15'
                    WHEN cast(strftime('%M', r.FECHA_HORA_ACOPIO) as integer) < 45 THEN '30'
                    ELSE '45'
                END AS bloque_tiempo,
                COUNT(*) AS recibidos_tramo
            FROM {tabla_hechos} r
            LEFT JOIN (
                SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, CLAVE_MUNICIPIO, NOMBRE_MUNICIPIO 
                FROM {tabla_geo}
            ) g ON r.CLAVE_ENTIDAD = g.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = g.CLAVE_DISTRITO AND r.SECCION = g.SECCION
            WHERE r.CLAVE_ENTIDAD = {c_entidad} AND r.CLAVE_DISTRITO = {c_distrito} 
              AND r.RECIBIDO = 1 
              AND r.FECHA_HORA_ACOPIO >= '{hora_inicio}' 
              AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}'
              {filtro_dig_sql}
            GROUP BY id_unidad, bloque_tiempo
            ORDER BY bloque_tiempo ASC;
        """
        query_tabla = f"""
            SELECT 
                COALESCE(g.CLAVE_MUNICIPIO, 999) AS id_unidad,
                printf('%03d', COALESCE(g.CLAVE_MUNICIPIO, 999)) || ' - ' || COALESCE(g.NOMBRE_MUNICIPIO, 'Revisar Afectación al MGE') AS Unidad,
                COUNT(*) AS Total_Esperadas,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO < '{hora_medianoche}' THEN 1 ELSE 0 END) AS Rec_00hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_04}' THEN 1 ELSE 0 END) AS Rec_04hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_08}' THEN 1 ELSE 0 END) AS Rec_08hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{corte_12}' THEN 1 ELSE 0 END) AS Rec_12hrs,
                SUM(CASE WHEN r.RECIBIDO = 1 AND r.FECHA_HORA_ACOPIO <= '{hora_cierre_prep}' THEN 1 ELSE 0 END) AS Rec_Final
            FROM {tabla_hechos} r
            LEFT JOIN (
                SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, CLAVE_MUNICIPIO, NOMBRE_MUNICIPIO 
                FROM {tabla_geo}
            ) g ON r.CLAVE_ENTIDAD = g.CLAVE_ENTIDAD AND r.CLAVE_DISTRITO = g.CLAVE_DISTRITO AND r.SECCION = g.SECCION
            WHERE r.CLAVE_ENTIDAD = {c_entidad} AND r.CLAVE_DISTRITO = {c_distrito} {filtro_dig_sql}
            GROUP BY id_unidad, Unidad
            ORDER BY id_unidad ASC;
        """

    df_universo = pd.read_sql_query(query_universo, conn)
    df_llegadas = pd.read_sql_query(query_recepcion, conn)
    df_tabla = pd.read_sql_query(query_tabla, conn)
    conn.close()

    def redondear_bloque_15m(fecha_str):
        if not fecha_str or fecha_str <= hora_inicio:
            return hora_inicio[:16]
        dt = pd.to_datetime(fecha_str)
        minuto_redondeado = (dt.minute // 15) * 15
        dt_bloque = dt.replace(minute=minuto_redondeado, second=0)
        return dt_bloque.strftime("%Y-%m-%d %H:%M")

    df_universo["bloque_fin_real"] = df_universo["hora_fin_real"].apply(redondear_bloque_15m)

    # --- AUDITORÍA DE PAUSAS (>= 30 MINUTOS TRAS EL ARRANQUE) ---
    conteo_pausas = {}
    suma_horas_pausas = {}
    max_pausa_horas = {}

    for uid, g_lleg in df_llegadas.groupby("id_unidad"):
        g_lleg = g_lleg.sort_values(by="bloque_tiempo")
        if len(g_lleg) > 1:
            dts = pd.to_datetime(g_lleg["bloque_tiempo"]).tolist()
            pausas_ge_30m = []
            for i in range(1, len(dts)):
                delta_h = (dts[i] - dts[i-1]).total_seconds() / 3600.0
                if delta_h >= 0.5:  # Pausa >= 30 minutos
                    pausas_ge_30m.append(delta_h)

            conteo_pausas[uid] = len(pausas_ge_30m)
            suma_horas_pausas[uid] = sum(pausas_ge_30m)
            max_pausa_horas[uid] = max(pausas_ge_30m) if pausas_ge_30m else 0.0
        else:
            conteo_pausas[uid] = 0
            suma_horas_pausas[uid] = 0.0
            max_pausa_horas[uid] = 0.0

    df_universo["num_pausas"] = df_universo["id_unidad"].map(conteo_pausas).fillna(0).astype(int)
    df_universo["horas_pausa_total"] = df_universo["id_unidad"].map(suma_horas_pausas).fillna(0.0)
    df_universo["max_pausa_horas"] = df_universo["id_unidad"].map(max_pausa_horas).fillna(0.0)

    return df_universo, df_llegadas, df_tabla


# --- CONSULTA DE CURVAS COMPARATIVAS Y ONDAS DE FLUJO (0 a 26 HORAS) ---
@st.cache_data
def obtener_serie_temporal_comparada(nivel, c_entidad=None, c_distrito=None):
    conn = sqlite3.connect(DB_NAME)
    series_res = {}

    for proc_key in ["PEF 2021", "PEF 2024"]:
        cfg = PROCESOS_CONFIG[proc_key]
        cond_filtro = ["1=1"]
        if nivel in ["Estatal", "Distrital"] and c_entidad:
            cond_filtro.append(f"CLAVE_ENTIDAD = {c_entidad}")
        if nivel == "Distrital" and c_distrito:
            cond_filtro.append(f"CLAVE_DISTRITO = {c_distrito}")

        cond_sql_total = " AND ".join(cond_filtro)
        tot_query = f"SELECT COUNT(*) FROM {cfg['tabla_hechos']} WHERE {cond_sql_total};"
        total_esp = conn.cursor().execute(tot_query).fetchone()[0]

        cond_llegadas = cond_filtro + [
            "RECIBIDO = 1",
            f"FECHA_HORA_ACOPIO >= '{cfg['hora_inicio']}'",
            f"FECHA_HORA_ACOPIO <= '{cfg['hora_cierre_prep']}'"
        ]
        llegadas_query = f"""
            SELECT FECHA_HORA_ACOPIO 
            FROM {cfg['tabla_hechos']} 
            WHERE {" AND ".join(cond_llegadas)}
            ORDER BY FECHA_HORA_ACOPIO ASC;
        """
        df_llegadas = pd.read_sql_query(llegadas_query, conn)

        if total_esp > 0 and not df_llegadas.empty:
            df_llegadas["dt"] = pd.to_datetime(df_llegadas["FECHA_HORA_ACOPIO"])
            dt_inicio = pd.to_datetime(cfg["hora_inicio"])
            df_llegadas["horas_transcurridas"] = (df_llegadas["dt"] - dt_inicio).dt.total_seconds() / 3600.0

            tramos_h = np.arange(0.0, 26.5, 0.5)
            conteos_acum = [
                int((df_llegadas["horas_transcurridas"] <= h).sum()) for h in tramos_h
            ]
            pcts_acum = [(c / total_esp) * 100.0 for c in conteos_acum]

            horas_enteras = np.arange(0, 27, 1)
            flujo_por_hora = []
            for h in horas_enteras:
                cnt = int(((df_llegadas["horas_transcurridas"] >= h) & (df_llegadas["horas_transcurridas"] < h + 1)).sum())
                flujo_por_hora.append(cnt)

            hora_ultimo = df_llegadas["FECHA_HORA_ACOPIO"].max()
            h_trans_ultimo = (df_llegadas["dt"].max() - dt_inicio).total_seconds() / 3600.0
            pct_medianoche = (df_llegadas["horas_transcurridas"] <= 6.0).sum() / total_esp * 100.0

            series_res[proc_key] = {
                "tramos_horas": tramos_h,
                "pcts_acum": pcts_acum,
                "horas_enteras": horas_enteras,
                "flujo_por_hora": flujo_por_hora,
                "total_esperadas": total_esp,
                "total_recibidas": len(df_llegadas),
                "hora_ultimo": hora_ultimo,
                "h_trans_ultimo": h_trans_ultimo,
                "pct_medianoche": pct_medianoche
            }
        else:
            series_res[proc_key] = None

    conn.close()
    return series_res


# --- BARRA LATERAL (SIDEBAR) ---
st.sidebar.header("Filtros de Auditoría")

proceso_sel = st.sidebar.selectbox(
    "Proceso Electoral Activo:",
    options=list(PROCESOS_CONFIG.keys()),
    index=0
)
cfg_proceso = PROCESOS_CONFIG[proceso_sel]

nivel_seleccionado = st.sidebar.radio(
    "Nivel de Análisis:",
    options=["Nacional", "Estatal", "Distrital"]
)

c_entidad_sel = None
c_distrito_sel = None

entidades_df = obtener_entidades(cfg_proceso["tabla_geo"])

if nivel_seleccionado in ["Estatal", "Distrital"]:
    idx_default_ent = int(entidades_df[entidades_df["CLAVE_ENTIDAD"] == 20].index[0]) if 20 in entidades_df["CLAVE_ENTIDAD"].values else 0
    c_entidad_sel = st.sidebar.selectbox(
        "Entidad Federativa:",
        options=list(entidades_df["CLAVE_ENTIDAD"]),
        index=idx_default_ent,
        format_func=lambda x: f"{x:02d} - {entidades_df.loc[entidades_df['CLAVE_ENTIDAD'] == x, 'NOMBRE_ENTIDAD'].values[0]}"
    )

if nivel_seleccionado == "Distrital":
    distritos_df = obtener_distritos(c_entidad_sel, cfg_proceso["tabla_geo"])
    c_distrito_sel = st.sidebar.selectbox(
        "Distrito Federal:",
        options=list(distritos_df["CLAVE_DISTRITO"]),
        format_func=lambda x: f"Dto {x:02d} - {distritos_df.loc[distritos_df['CLAVE_DISTRITO'] == x, 'CABECERA_DISTRITAL'].values[0]}"
    )

lista_mecanismos = obtener_mecanismos_digitalizacion(cfg_proceso["tabla_hechos"])
f_digitalizacion_sel = st.sidebar.selectbox(
    "Mecanismo de Digitalización:",
    options=[None] + lista_mecanismos,
    format_func=lambda x: "Todos los Mecanismos" if x is None else str(x)
)

st.sidebar.markdown("---")
st.sidebar.subheader("💾 Exportar Base de Datos")
df_casillas_descarga = obtener_detalle_casillas(cfg_proceso, nivel_seleccionado, c_entidad_sel, c_distrito_sel, f_digitalizacion_sel)
csv_casillas = df_casillas_descarga.to_csv(index=False).encode('utf-8-sig')

st.sidebar.download_button(
    label=f"⬇️ Descargar Casillas ({len(df_casillas_descarga):,} reg.)",
    data=csv_casillas,
    file_name=f"casillas_{proceso_sel.lower().replace(' ', '_')}_{nivel_seleccionado.lower()}_audit.csv",
    mime="text/csv",
    help="Exporta la base de casillas individual con su fecha exacta de acopio, mecanismo y tipo de casilla."
)

if "modo_auditoria" not in st.session_state:
    st.session_state.modo_auditoria = False

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Auditoría Forense")

minutos_ventana = st.sidebar.slider(
    "Ventana de corte temprano (minutos):",
    min_value=5,
    max_value=30,
    value=15,
    step=1,
    help="Rango de minutos tras el cierre formal (18:00 hrs) para auditar recepciones tempranas."
)
hora_corte_dinamica = f"{cfg_proceso['prefijo_corte_temprano']}{minutos_ventana:02d}:00"

if st.sidebar.button(f"⚠️ Auditoría Casillas (≤ 18:{minutos_ventana:02d} hrs)"):
    st.session_state.modo_auditoria = True
    st.session_state.reproduciendo = False

clave_sesion = f"{proceso_sel}_{nivel_seleccionado}_{c_entidad_sel}_{c_distrito_sel}_{f_digitalizacion_sel}"
if "filtro_actual" not in st.session_state or st.session_state.filtro_actual != clave_sesion:
    st.session_state.filtro_actual = clave_sesion
    st.session_state.paso_idx = 0
    st.session_state.reproduciendo = False


# ==============================================================================
# PESTAÑAS PRINCIPALES DEL SISTEMA
# ==============================================================================
tab_monitoreo, tab_comparativa, tab_proyeccion = st.tabs([
    '🏁 Carrera de Ratas (Monitoreo por Proceso)',
    '⚖️ Comparativa Frente a Frente (2021 vs. 2024)',
    '🔮 Proyección de Casillas 2026'
])

with tab_monitoreo:


    # ------------------------------------------------------------------------------
    # PESTAÑA 1: CARRERA DE RATAS Y AUDITORÍA FORENSE INDIVIDUAL
    # ------------------------------------------------------------------------------
    if st.session_state.modo_auditoria:
        st.title(f"⚠️ Auditoría Forense: Recepciones Atípicas Tempranas ({proceso_sel})")
        st.caption(f"Casillas con fecha y hora de acopio registrada entre {cfg_proceso['hora_inicio']} y las 18:{minutos_ventana:02d}:00 hrs ({minutos_ventana} minutos post-cierre).")

        if st.button("🔙 Volver a la Carrera de Ratas"):
            st.session_state.modo_auditoria = False
            st.rerun()

        df_atipicas = obtener_casillas_atipicas(cfg_proceso, hora_corte_dinamica, nivel_seleccionado, c_entidad_sel, c_distrito_sel, f_digitalizacion_sel)

        if df_atipicas.empty:
            st.success(f"No se detectaron casillas recibidas antes de las 18:{minutos_ventana:02d} hrs para la selección: {nivel_seleccionado}.")
        else:
            tot_atipicas = len(df_atipicas)
            esp = len(df_atipicas[df_atipicas["TIPO_CASILLA"] == "S"])
            ordinarias = len(df_atipicas[df_atipicas["TIPO_CASILLA"].isin(["B", "C"])])
            extraordinarias = len(df_atipicas[df_atipicas["TIPO_CASILLA"] == "E"])
            modalidades_esp = len(df_atipicas[df_atipicas["TIPO_CASILLA"].isin(["M", "VA", "VPPP", "EXT", "V"])])

            col_a1, col_a2, col_a3, col_a4, col_a5 = st.columns(5)
            col_a1.metric(f"Total Casillas ≤ 18:{minutos_ventana:02d} hrs", f"{tot_atipicas:,}")
            col_a2.metric("Casillas Especiales (S)", f"{esp:,}", help="Cierran al agotar boletas.")
            col_a3.metric("Básicas / Contiguas (B, C)", f"{ordinarias:,}", help="Escrutinio ciudadano ordinario a revisar prioritariamente.")
            col_a4.metric("Extraordinarias (E)", f"{extraordinarias:,}", help="Casillas en zonas complejas con escrutinio y traslado prolongado.")
            col_a5.metric("Modalidades Excepcionales", f"{modalidades_esp:,}", help="Voto Anticipado, Prisión Preventiva, Voto Postal/Extranjero.")

            st.markdown("---")
            st.subheader("📋 Detalle Individual de Casillas Tempranas")

            csv_atipicas = df_atipicas.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label=f"💾 Descargar Cuadro de Casillas Atípicas (≤ 18:{minutos_ventana:02d} hrs) en CSV",
                data=csv_atipicas,
                file_name=f"auditoria_casillas_tempranas_{proceso_sel.lower().replace(' ', '_')}_18{minutos_ventana:02d}_{nivel_seleccionado.lower()}.csv",
                mime="text/csv"
            )

            st.dataframe(
                df_atipicas,
                hide_index=True,
                width='stretch',
                column_config={
                    "CLAVE_ENTIDAD": st.column_config.NumberColumn(format="%d"),
                    "CLAVE_DISTRITO": st.column_config.NumberColumn(format="%d"),
                    "SECCION": st.column_config.NumberColumn(format="%d")
                }
            )

    else:
        st.title(f"🏁 Auditoría Logística: Carrera de Ratas PREP ({proceso_sel})")

        df_universo, df_llegadas, df_tabla = cargar_datos_carrera(cfg_proceso, nivel_seleccionado, c_entidad_sel, c_distrito_sel, f_digitalizacion_sel)

        if df_universo.empty:
            st.warning("No se encontraron registros para la combinación de filtros solicitada.")
        else:
            rango_tiempos = pd.date_range(start=cfg_proceso["hora_inicio"], end=cfg_proceso["hora_cierre_prep"], freq="15min")
            etiquetas_tiempo = [d.strftime("%Y-%m-%d %H:%M") for d in rango_tiempos]
            total_pasos = len(etiquetas_tiempo)

            if "paso_idx" not in st.session_state:
                st.session_state.paso_idx = 0
            if "reproduciendo" not in st.session_state:
                st.session_state.reproduciendo = False

            st.sidebar.subheader("🕹️ Controles de Carrera")

            col_btn1, col_btn2, col_btn3 = st.sidebar.columns(3)
            if col_btn1.button("▶️ Play"):
                st.session_state.reproduciendo = True
            if col_btn2.button("⏸️ Pausa"):
                st.session_state.reproduciendo = False
            if col_btn3.button("🔄 Reset"):
                st.session_state.paso_idx = 0
                st.session_state.reproduciendo = False

            velocidad_sec = st.sidebar.slider(
                "Velocidad (segundos por tramo):",
                min_value=0.05,
                max_value=1.00,
                value=0.20,
                step=0.05
            )

            def actualizar_slider():
                st.session_state.paso_idx = etiquetas_tiempo.index(st.session_state.slider_tiempo)

            paso_actual_str = etiquetas_tiempo[st.session_state.paso_idx]
            st.sidebar.select_slider(
                "Línea de tiempo manual:",
                options=etiquetas_tiempo,
                value=paso_actual_str,
                key="slider_tiempo",
                on_change=actualizar_slider
            )

            # Métricas + gráfica en un placeholder: la animación los actualiza en
            # su propio contenedor sin redibujar toda la página (sin parpadeo).
            ph_carrera = st.empty()
            pintar_carrera(ph_carrera, paso_actual_str, df_universo, df_llegadas, cfg_proceso, proceso_sel, nivel_seleccionado)

            if st.session_state.get("carrera_terminada"):
                st.session_state.carrera_terminada = False
                st.success(f"🏁 Fin de la ventana oficial PREP ({cfg_proceso['hora_cierre_prep']} hrs).")

            st.markdown("### 🏆 Orden de Conclusión de la Recepción de Paquetes")
            st.caption("Orden cronológico en que las unidades recibieron físicamente su último paquete en PREP con desglose de pausas operativas.")

            df_cierre = df_universo.copy()
            df_cierre = df_cierre.sort_values(by="hora_fin_real", ascending=True).reset_index(drop=True)
            df_cierre["Lugar"] = df_cierre.index + 1
            df_cierre["Pct_Cumplimiento"] = ((df_cierre["total_recibidos_final"] / df_cierre["total_esperadas"]) * 100.0).round(2)

            dt_cierre_prep = pd.to_datetime(cfg_proceso["hora_cierre_prep"])
            df_cierre["dt_fin"] = pd.to_datetime(df_cierre["hora_fin_real"])
            df_cierre["Horas_Ociosas"] = (dt_cierre_prep - df_cierre["dt_fin"]).dt.total_seconds() / 3600.0
            df_cierre["Tiempo_Muerto_Final"] = df_cierre["Horas_Ociosas"].apply(
                lambda h: f"{int(max(0, h))}h {int((max(0, h)*60)%60):02d}m" if pd.notna(h) else "-"
            )

            df_cierre["Pausas_Acumuladas_Texto"] = df_cierre["horas_pausa_total"].apply(
                lambda h: f"{int(h)}h {int(round((h-int(h))*60)):02d}m" if h > 0 else "0h 00m"
            )

            df_cierre_mostrar = df_cierre[[
                "Lugar",
                "nombre_unidad",
                "hora_fin_real",
                "total_esperadas",
                "total_recibidos_final",
                "Pct_Cumplimiento",
                "num_pausas",
                "Pausas_Acumuladas_Texto",
                "max_pausa_horas",
                "Tiempo_Muerto_Final"
            ]].rename(columns={
                "nombre_unidad": "Unidad Operativa",
                "hora_fin_real": "Hora Último Paquete (Acopio)",
                "total_esperadas": "Paquetes Esperados",
                "total_recibidos_final": "Paquetes Recibidos",
                "Pct_Cumplimiento": "% Recibidos vs Esperados",
                "num_pausas": "Eventos de Pausa (≥ 30m)",
                "Pausas_Acumuladas_Texto": "Tiempo Total de Pausas",
                "max_pausa_horas": "Pausa Máxima (hrs)",
                "Tiempo_Muerto_Final": "Inactividad hasta Cierre PREP"
            })

            st.dataframe(
                df_cierre_mostrar,
                hide_index=True,
                width='stretch',
                column_config={
                    "Lugar": st.column_config.NumberColumn(format="%d"),
                    "Paquetes Esperados": st.column_config.NumberColumn(format="%d"),
                    "Paquetes Recibidos": st.column_config.NumberColumn(format="%d"),
                    "% Recibidos vs Esperados": st.column_config.NumberColumn(format="%.2f%%"),
                    "Eventos de Pausa (≥ 30m)": st.column_config.NumberColumn(format="%d"),
                    "Pausa Máxima (hrs)": st.column_config.NumberColumn(format="%.1f hrs")
                }
            )

            with st.expander("📥 Descargar / Consultar Auditoría por Cortes Logísticos"):
                df_tabla["Pct_00hrs"] = ((df_tabla["Rec_00hrs"] / df_tabla["Total_Esperadas"]) * 100.0).round(2)
                df_tabla["Pct_04hrs"] = ((df_tabla["Rec_04hrs"] / df_tabla["Total_Esperadas"]) * 100.0).round(2)
                df_tabla["Pct_08hrs"] = ((df_tabla["Rec_08hrs"] / df_tabla["Total_Esperadas"]) * 100.0).round(2)
                df_tabla["Pct_12hrs"] = ((df_tabla["Rec_12hrs"] / df_tabla["Total_Esperadas"]) * 100.0).round(2)
                df_tabla["Pct_Faltante"] = (((df_tabla["Total_Esperadas"] - df_tabla["Rec_Final"]) / df_tabla["Total_Esperadas"]) * 100.0).round(2)

                columnas_cortes = ["Unidad", "Pct_00hrs", "Pct_04hrs", "Pct_08hrs", "Pct_12hrs", "Pct_Faltante"]
                df_cortes_mostrar = df_tabla[columnas_cortes].rename(columns={
                    "Pct_00hrs": "% Antes 00:00 (Día 1)",
                    "Pct_04hrs": "% Hasta 04:00 (Día 2)",
                    "Pct_08hrs": "% Hasta 08:00 (Día 2)",
                    "Pct_12hrs": "% Hasta 12:00 (Día 2)",
                    "Pct_Faltante": "% Restante Faltante"
                })

                csv_cortes = df_cortes_mostrar.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="💾 Descargar Cortes Logísticos en CSV",
                    data=csv_cortes,
                    file_name=f"cortes_logisticos_{proceso_sel.lower().replace(' ', '_')}_{nivel_seleccionado.lower()}.csv",
                    mime="text/csv"
                )

                st.dataframe(
                    df_cortes_mostrar,
                    hide_index=True,
                    width='stretch',
                    column_config={
                        "% Antes 00:00 (Día 1)": st.column_config.NumberColumn(format="%.2f%%"),
                        "% Hasta 04:00 (Día 2)": st.column_config.NumberColumn(format="%.2f%%"),
                        "% Hasta 08:00 (Día 2)": st.column_config.NumberColumn(format="%.2f%%"),
                        "% Hasta 12:00 (Día 2)": st.column_config.NumberColumn(format="%.2f%%"),
                        "% Restante Faltante": st.column_config.NumberColumn(format="%.2f%%")
                    }
                )

            if st.session_state.reproduciendo:
                if st.session_state.paso_idx < total_pasos - 1:
                    avances = 0
                    while st.session_state.paso_idx < total_pasos - 1:
                        st.session_state.paso_idx += 1
                        avances += 1
                        pintar_carrera(
                            ph_carrera, etiquetas_tiempo[st.session_state.paso_idx],
                            df_universo, df_llegadas, cfg_proceso, proceso_sel, nivel_seleccionado
                        )
                        time.sleep(velocidad_sec)
                        if avances % 5 == 0:
                            st.rerun()  # punto de control: aplica Pausa/Reset y sincroniza el slider
                    st.session_state.reproduciendo = False
                    st.session_state.carrera_terminada = True
                    st.rerun()
                else:
                    st.session_state.reproduciendo = False
                    st.success(f"🏁 Fin de la ventana oficial PREP ({cfg_proceso['hora_cierre_prep']} hrs).")


with tab_comparativa:
    st.title("⚖️ Diagnóstico Comparativo: PEF 2021 vs. PEF 2024")
    st.caption("Comparación de curvas de recuperación sobre una escala de tiempo normalizada (horas transcurridas post-cierre de votación: 18:00 hrs = Hora 0).")

    series_comp = obtener_serie_temporal_comparada(nivel_seleccionado, c_entidad_sel, c_distrito_sel)
    s21 = series_comp.get("PEF 2021")
    s24 = series_comp.get("PEF 2024")

    if s21 is None or s24 is None:
        st.warning("No se cuenta con información suficiente para comparar ambos procesos en la selección actual.")
    else:
        c_kpi1, c_kpi2, c_kpi3, c_kpi4 = st.columns(4)

        diff_casillas = s24["total_esperadas"] - s21["total_esperadas"]
        c_kpi1.metric(
            "Casillas Esperadas",
            f"2024: {s24['total_esperadas']:,}",
            delta=f"{diff_casillas:+,} vs 2021 ({s21['total_esperadas']:,})"
        )

        diff_med = s24["pct_medianoche"] - s21["pct_medianoche"]
        c_kpi2.metric(
            "% Recibido a Medianoche (00:00 hrs)",
            f"{s24['pct_medianoche']:.2f}% (2024)",
            delta=f"{diff_med:+.2f}% vs 2021 ({s21['pct_medianoche']:.2f}%)"
        )

        c_kpi3.metric(
            "Hora Término (Último Paquete)",
            f"2024: +{s24['h_trans_ultimo']:.1f} hrs",
            help=f"2021 concluyó a las +{s21['h_trans_ultimo']:.1f} hrs ({s21['hora_ultimo']}). 2024 concluyó a las {s24['hora_ultimo']}."
        )

        diff_duracion = s24["h_trans_ultimo"] - s21["h_trans_ultimo"]
        c_kpi4.metric(
            "Diferencial Logístico Total",
            f"{abs(diff_duracion):.1f} horas " + ("más tarde" if diff_duracion > 0 else "más rápido"),
            delta=f"{-diff_duracion:+.1f} hrs eficiencia",
            delta_color="normal"
        )

        st.markdown("---")

        # 1. GRÁFICA DE CURVAS DE RECUPERACIÓN SUPERPUESTAS (0% A 105%)
        fig_comp = go.Figure()

        fig_comp.add_trace(go.Scatter(
            x=s21["tramos_horas"],
            y=s21["pcts_acum"],
            mode="lines+markers",
            name="🔵 PEF 2021",
            line=dict(color="#007bff", width=3),
            marker=dict(size=4),
            hovertemplate="<b>PEF 2021</b><br>Hora: +%{x}h<br>Avance: %{y:.2f}%<extra></extra>"
        ))

        fig_comp.add_trace(go.Scatter(
            x=s24["tramos_horas"],
            y=s24["pcts_acum"],
            mode="lines+markers",
            name="🟣 PEF 2024",
            line=dict(color="#e83e8c", width=3),
            marker=dict(size=4),
            hovertemplate="<b>PEF 2024</b><br>Hora: +%{x}h<br>Avance: %{y:.2f}%<extra></extra>"
        ))

        fig_comp.add_vline(x=6, line_dash="dot", line_color="#ffc107", annotation_text=" Medianoche (00:00 hrs)", annotation_position="top right")
        fig_comp.add_vline(x=14, line_dash="dot", line_color="#17a2b8", annotation_text=" 08:00 hrs (Día 2)", annotation_position="top right")
        fig_comp.add_vline(x=26, line_dash="dot", line_color="#aaaaaa")
        fig_comp.add_hline(y=100, line_dash="dash", line_color="#28a745")

        fig_comp.update_layout(
            title=dict(
                text=f"<b>Curva Acumulada de Acopio (% Recuperación) | {nivel_seleccionado}</b>",
                font=dict(size=18, color="#1f2937")
            ),
            xaxis=dict(
                title="Horas Transcurridas desde el Cierre de Casillas (18:00 hrs = Hora 0)",
                range=[0, 26.5],
                dtick=2,
                ticksuffix=" hrs",
                gridcolor="#d1d5db"
            ),
            yaxis=dict(
                title="% Acumulado de Paquetes Recibidos",
                range=[0, 105],
                autorange=False,
                ticksuffix="%",
                gridcolor="#d1d5db"
            ),
            height=460,
            margin=dict(l=60, r=40, t=50, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        st.plotly_chart(fig_comp, width='stretch')

        # 2. HISTOGRAMA DE ONDAS DE FLUJO Y DETECCIÓN DE VALLES/PAUSAS
        st.markdown("### 🌊 Histograma de Ondas de Flujo y Valles de Pausa")
        st.caption("Muestra la intensidad de llegada de paquetes por cada hora. Permite diagnosticar con exactitud las horas en que el flujo cayó a cero y los picos posteriores de escaneo masivo.")

        fig_ondas = go.Figure()
        fig_ondas.add_trace(go.Bar(
            x=s21["horas_enteras"],
            y=s21["flujo_por_hora"],
            name="Paquetes/Hora (PEF 2021)",
            marker_color="rgba(0, 123, 255, 0.6)",
            hovertemplate="<b>2021</b> Tramo +%{x}h a +%{x}+1h: %{y:,} paquetes<extra></extra>"
        ))
        fig_ondas.add_trace(go.Bar(
            x=s24["horas_enteras"],
            y=s24["flujo_por_hora"],
            name="Paquetes/Hora (PEF 2024)",
            marker_color="rgba(232, 62, 140, 0.6)",
            hovertemplate="<b>2024</b> Tramo +%{x}h a +%{x}+1h: %{y:,} paquetes<extra></extra>"
        ))

        fig_ondas.add_vline(x=6, line_dash="dot", line_color="#ffc107", annotation_text=" Medianoche (00:00 hrs)")
        fig_ondas.add_vline(x=14, line_dash="dot", line_color="#17a2b8", annotation_text=" 08:00 hrs")

        fig_ondas.update_layout(
            barmode="group",
            title=dict(
                text=f"<b>Ritmo Instantáneo de Llegadas por Hora | {nivel_seleccionado}</b>",
                font=dict(size=17, color="#1f2937")
            ),
            xaxis=dict(
                title="Hora Transcurrida desde el Cierre (18:00 hrs = Hora 0)",
                range=[-0.5, 26.5],
                dtick=1,
                ticksuffix="h",
                gridcolor="#d1d5db"
            ),
            yaxis=dict(
                title="Cantidad de Paquetes Recibidos en la Hora",
                gridcolor="#d1d5db"
            ),
            height=380,
            margin=dict(l=60, r=40, t=50, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        st.plotly_chart(fig_ondas, width='stretch')

        # 3. MATRIZ COMPARATIVA DE UNIDADES Y RUTAS CRÍTICAS
        st.markdown("### 📋 Matriz Diagnóstica de Rutas Críticas y Desempeño Territorial")
        st.caption("Comparativo directo a nivel de unidad territorial emparejado por clave oficial (`id_unidad`).")

        _, _, df_t21 = cargar_datos_carrera(PROCESOS_CONFIG["PEF 2021"], nivel_seleccionado, c_entidad_sel, c_distrito_sel)
        _, _, df_t24 = cargar_datos_carrera(PROCESOS_CONFIG["PEF 2024"], nivel_seleccionado, c_entidad_sel, c_distrito_sel)

        df_t21["Pct_00h_2021"] = ((df_t21["Rec_00hrs"] / df_t21["Total_Esperadas"]) * 100.0).round(2)
        df_t24["Pct_00h_2024"] = ((df_t24["Rec_00hrs"] / df_t24["Total_Esperadas"]) * 100.0).round(2)

        df_mrg = pd.merge(
            df_t21[["id_unidad", "Unidad", "Total_Esperadas", "Pct_00h_2021"]].rename(columns={
                "Unidad": "Unidad_2021",
                "Total_Esperadas": "Esp_2021"
            }),
            df_t24[["id_unidad", "Unidad", "Total_Esperadas", "Pct_00h_2024"]].rename(columns={
                "Unidad": "Unidad_2024",
                "Total_Esperadas": "Esp_2024"
            }),
            on="id_unidad",
            how="outer"
        )

        df_mrg["Unidad"] = df_mrg["Unidad_2024"].combine_first(df_mrg["Unidad_2021"])
        df_mrg["Esp_2021"] = df_mrg["Esp_2021"].fillna(0).astype(int)
        df_mrg["Pct_00h_2021"] = df_mrg["Pct_00h_2021"].fillna(0.0)
        df_mrg["Esp_2024"] = df_mrg["Esp_2024"].fillna(0).astype(int)
        df_mrg["Pct_00h_2024"] = df_mrg["Pct_00h_2024"].fillna(0.0)

        df_mrg["Dif_Medianoche"] = (df_mrg["Pct_00h_2024"] - df_mrg["Pct_00h_2021"]).round(2)

        df_mrg_mostrar = df_mrg[[
            "Unidad",
            "Esp_2021",
            "Pct_00h_2021",
            "Esp_2024",
            "Pct_00h_2024",
            "Dif_Medianoche"
        ]].sort_values(by="Pct_00h_2024", ascending=True)

        csv_comp = df_mrg_mostrar.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="💾 Descargar Matriz Comparativa en CSV",
            data=csv_comp,
            file_name=f"matriz_comparativa_2021_2024_{nivel_seleccionado.lower()}.csv",
            mime="text/csv"
        )

        st.dataframe(
            df_mrg_mostrar,
            hide_index=True,
            width='stretch',
            column_config={
                "Esp_2021": st.column_config.NumberColumn(format="%d"),
                "Pct_00h_2021": st.column_config.NumberColumn(format="%.2f%%"),
                "Esp_2024": st.column_config.NumberColumn(format="%d"),
                "Pct_00h_2024": st.column_config.NumberColumn(format="%.2f%%"),
                "Dif_Medianoche": st.column_config.NumberColumn(format="%+.2f%%")
            }
        )


with tab_proyeccion:
    render_tab_proyeccion(
        c_entidad_sel=locals().get('c_entidad_sel', None),
        c_distrito_sel=locals().get('c_distrito_sel', None)
    )