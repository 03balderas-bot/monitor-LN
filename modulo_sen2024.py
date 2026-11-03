"""Pestaña independiente del PREP: proyección de casillas 2026 anclada en las
actas de Senadores 2024 (100% de las casillas), catálogos seccionales y de
localidades, y el reseccionamiento.

Proyección: Padrón Electoral del corte seleccionado.
Votación y atipicidades: Lista Nominal de las actas.
Las casillas tipo A se excluyen de todos los cálculos.
"""

import sqlite3
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import modulo_proyeccion as mp

AZUL = "#1f3864"
GRIS = "#94a3b8"

ANCHO = "stretch"


def _db():
    return mp.DB_PATH


@st.cache_data(show_spinner=False)
def consultar_hist_sen2024(entidad=None, distrito=None):
    """Casillas instaladas 2024 por sección, desde Resultados Senadores 2024."""
    cond = ["r.TIPO_CASILLA IN ('B','C','E','S')"]
    if entidad not in (None, "Todas"):
        cond.append(f"r.CLAVE_ENTIDAD = {int(entidad)}")
    if distrito is not None:
        cond.append(f"r.CLAVE_DISTRITO = {int(distrito)}")
    where = f"WHERE {' AND '.join(cond)}"

    conn = sqlite3.connect(_db())
    query = f"""
        SELECT
            r.CLAVE_ENTIDAD,
            r.CLAVE_DISTRITO,
            r.SECCION,
            COUNT(*) AS TOT_HIST,
            SUM(CASE WHEN r.TIPO_CASILLA = 'B' THEN 1 ELSE 0 END) AS B_HIST,
            SUM(CASE WHEN r.TIPO_CASILLA = 'C' THEN 1 ELSE 0 END) AS C_HIST,
            SUM(CASE WHEN r.TIPO_CASILLA = 'E' THEN 1 ELSE 0 END) AS E_HIST,
            SUM(CASE WHEN r.TIPO_CASILLA = 'S' THEN 1 ELSE 0 END) AS S_HIST,
            SUM(CASE WHEN r.TIPO_CASILLA IN ('B','C') THEN r.LISTA_NOMINAL ELSE 0 END) AS LN_ORD_24,
            SUM(CASE WHEN r.TIPO_CASILLA = 'E' THEN r.LISTA_NOMINAL ELSE 0 END) AS LN_E_24,
            SUM(r.LISTA_NOMINAL) AS LN_2024,
            SUM(r.TOTAL_VOTOS) AS TV_2024,
            SUM(r.VOTOS_NULOS) AS NU_2024
        FROM resultados_sen_2024 r
        {where}
        GROUP BY 1, 2, 3
    """
    df = pd.read_sql_query(query, conn)

    t = pd.read_sql_query(
        "SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, TIPO_3 FROM cat_secciones", conn
    )
    l = pd.read_sql_query(
        """SELECT CLAVE_ENTIDAD, SECCION, COUNT(DISTINCT LOCALIDAD) AS N_LOCALIDADES
           FROM cat_localidades_seccion GROUP BY 1, 2""",
        conn,
    )
    conn.close()

    df = df.merge(t, on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO", "SECCION"], how="left")
    df = df.merge(l, on=["CLAVE_ENTIDAD", "SECCION"], how="left")
    enteros = ["CLAVE_ENTIDAD", "CLAVE_DISTRITO", "SECCION", "TOT_HIST", "B_HIST", "C_HIST",
               "E_HIST", "S_HIST", "N_LOCALIDADES"]
    for c in enteros:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    for c in ["LN_ORD_24", "LN_E_24", "LN_2024", "TV_2024", "NU_2024"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(float)
    return df


@st.cache_data(show_spinner=False)
def consultar_secciones_nuevas(entidad=None, distrito=None):
    cond = []
    if entidad not in (None, "Todas"):
        cond.append(f"CLAVE_ENTIDAD = {int(entidad)}")
    if distrito is not None:
        cond.append(f"CLAVE_DISTRITO = {int(distrito)}")
    where = f"WHERE {' AND '.join(cond)}" if cond else ""
    conn = sqlite3.connect(_db())
    try:
        df = pd.read_sql_query(
            f"SELECT DISTINCT SECCION_NUEVA FROM cat_equivalencias_reseccionamiento {where}", conn
        )
        nuevas = set(pd.to_numeric(df["SECCION_NUEVA"], errors="coerce").dropna().astype(int))
    except Exception:
        nuevas = set()
    conn.close()
    return nuevas


@st.cache_data(show_spinner=False)
def consultar_votacion_sen2024(entidad=None, distrito=None, agrupacion="tipo"):
    """Votación 2024 agregada. % votación = (Total_Votos + Votos_Nulos) / Lista_Nominal."""
    cond = ["r.TIPO_CASILLA IN ('B','C','E','S')"]
    if entidad not in (None, "Todas"):
        cond.append(f"r.CLAVE_ENTIDAD = {int(entidad)}")
    if distrito is not None:
        cond.append(f"r.CLAVE_DISTRITO = {int(distrito)}")
    where = f"WHERE {' AND '.join(cond)}"

    if agrupacion == "tipo":
        select = "r.TIPO_CASILLA AS GRUPO"
        extra_join = ""
        group = "1"
    elif agrupacion == "tipo_seccion":
        select = "COALESCE(t.TIPO_3, 'SIN CLASIFICAR') AS GRUPO"
        extra_join = """LEFT JOIN (
            SELECT DISTINCT CLAVE_ENTIDAD, CLAVE_DISTRITO, SECCION, TIPO_3 FROM cat_secciones
        ) t ON r.CLAVE_ENTIDAD = t.CLAVE_ENTIDAD
           AND r.CLAVE_DISTRITO = t.CLAVE_DISTRITO
           AND r.SECCION = t.SECCION"""
        group = "1"
    elif agrupacion == "distrito":
        select = "r.CLAVE_DISTRITO AS GRUPO"
        extra_join = ""
        group = "1"
    else:
        raise ValueError(f"Agrupación no soportada: {agrupacion}")

    conn = sqlite3.connect(_db())
    query = f"""
        SELECT
            {select},
            COUNT(*) AS CASILLAS,
            SUM(r.LISTA_NOMINAL) AS LN,
            SUM(r.TOTAL_VOTOS) AS TV,
            SUM(r.VOTOS_NULOS) AS NU
        FROM resultados_sen_2024 r
        {extra_join}
        {where}
        GROUP BY {group}
        ORDER BY 1
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    for c in ["CASILLAS", "LN", "TV", "NU"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(float)
    return df


def _pct_votacion(tv, nu, ln):
    if ln and ln > 0:
        return (tv + nu) / ln * 100
    return None


def _fmt_pct(v):
    return "N/A" if v is None or pd.isna(v) else f"{v:.2f}%"


def _proyectar(df):
    """Aplica las reglas LGIPE sobre el Padrón Electoral 2026.

    Validado contra 2024: B+C = techo(LN_ordinaria / 750) en 99.97% de las
    secciones, donde la LN ordinaria excluye a los electores de casillas E.
    Para proyectar se usa el padrón; la proporción de electores que en 2024
    votó en casillas E se estima con esa misma acta y se aplica al padrón.
    """
    df = df.copy()
    pad26 = df["PADRON_ELECTORAL"].to_numpy(dtype=float)
    ln24 = df["LN_2024"].to_numpy(dtype=float)
    ln_e24 = df["LN_E_24"].to_numpy(dtype=float)

    proporcion_e = np.divide(ln_e24, ln24, out=np.zeros_like(ln24), where=ln24 > 0)
    pad_e26 = pad26 * proporcion_e
    pad_ord26 = np.clip(pad26 - pad_e26, 0, None)

    con_padron = pad26 >= 1

    # Básica: una por sección (ID 01), siempre que la sección tenga electores.
    df["B_2026"] = con_padron.astype(int)
    # Contiguas: una ordinaria por cada 750 electores de padrón de la parte no extraordinaria.
    esp_ord = np.where(con_padron, np.maximum(np.ceil(pad_ord26 / 750.0), 1), 0)
    df["C_2026"] = np.maximum(esp_ord - 1, 0).astype(int)
    # Extraordinarias: se conservan las de 2024 y, si la parte rural creció, se
    # aplica el piso de 750 electores por casilla extraordinaria.
    piso_e = np.ceil(np.divide(pad_e26, 750.0, out=np.zeros_like(pad_e26), where=pad_e26 > 0))
    df["E_2026"] = np.maximum(df["E_HIST"].to_numpy(dtype=int), piso_e).astype(int)
    # Especiales: independientes del criterio de 750; 1,000 boletas fijas y LN = 0.
    df["S_2026"] = df["S_HIST"].to_numpy(dtype=int)
    df["PAD_ORD_2026"] = pad_ord26

    # Secciones sin padrón 2026 (y sin equivalencia): no se inventa su desaparición.
    arrastre = df["sin_padron_proyectable"].to_numpy()
    for col_h, col_26 in [("B_HIST", "B_2026"), ("C_HIST", "C_2026"),
                          ("E_HIST", "E_2026"), ("S_HIST", "S_2026")]:
        df.loc[arrastre, col_26] = df.loc[arrastre, col_h]

    # Secciones matriz extintas por reseccionamiento: regla cero para B/C/E.
    # Las Especiales no dependen del padrón ni del criterio de 750, así que se
    # conservan tal cual 2024 para no alterar su total.
    df.loc[df["es_matriz"], ["B_2026", "C_2026", "E_2026"]] = 0

    df["TOT_2026"] = df[["B_2026", "C_2026", "E_2026", "S_2026"]].sum(axis=1).astype(int)
    df["DIF_TOTAL"] = df["TOT_2026"] - df["TOT_HIST"]
    return df


def _clasificar_causa(row, matrices, nuevas):
    if int(row["SECCION"]) in matrices:
        return "Reseccionamiento (matriz extinta)"
    if row["sin_padron_proyectable"]:
        return "Sin padrón 2026 (se conserva 2024)"
    if row["TOT_HIST"] == 0 and row["TOT_2026"] > 0:
        if int(row["SECCION"]) in nuevas:
            return "Reseccionamiento (sección nueva)"
        return "Sección nueva incorporada"
    if row["TOT_2026"] > row["TOT_HIST"]:
        return "Crecimiento de padrón"
    if row["TOT_2026"] < row["TOT_HIST"]:
        return "Decremento de padrón"
    if (row["B_2026"] != row["B_HIST"] or row["C_2026"] != row["C_HIST"]
            or row["E_2026"] != row["E_HIST"] or row["S_2026"] != row["S_HIST"]):
        return "Recomposición de casillas (mismo total)"
    return "Sin variación"


def _tabla_votacion(df, etiqueta_grupo):
    filas = []
    for _, r in df.iterrows():
        pct = _pct_votacion(r["TV"], r["NU"], r["LN"]) if r["LN"] > 0 else None
        filas.append({
            etiqueta_grupo: r["GRUPO"],
            "Casillas": int(r["CASILLAS"]),
            "Lista Nominal": int(r["LN"]),
            "Votos calculados": int(r["TV"]),
            "Votos nulos": int(r["NU"]),
            "% Votación": _fmt_pct(pct) if pct is not None else "N/A (LN = 0)",
        })
    return pd.DataFrame(filas)


def render_tab_sen2024(c_entidad_sel=None, c_distrito_sel=None):
    st.title("🗳️ Proyección de Casillas 2026 — Base Senadores 2024")
    st.caption(
        "Cálculo independiente del PREP. Usa el 100% de las actas de Senadores 2024 "
        "(incluidas las que no llegaron al PREP), los catálogos seccionales y de localidades, "
        "y el reseccionamiento. La proyección se calcula con el **Padrón Electoral**; la "
        "**Lista Nominal** se usa solo para el porcentaje de votación y los análisis atípicos."
    )

    cortes = mp.obtener_cortes_padron_bd()
    if not cortes:
        st.error("⚠️ No se encontraron tablas de Padrón Electoral en la base de datos.")
        return

    fechas = list(cortes.keys())
    col_corte, col_ent, col_dist = st.columns([1.4, 1.6, 1.2])
    with col_corte:
        fecha_sel = st.selectbox("📅 Corte de padrón a proyectar:", fechas, index=0)
    with col_ent:
        entidades = list(mp.CATALOGO_ENTIDADES.keys())
        idx_e = entidades.index(c_entidad_sel) if c_entidad_sel in entidades else entidades.index(20)
        entidad = st.selectbox(
            "🏛️ Entidad Federativa (Sen 2024):", entidades, index=idx_e,
            format_func=lambda x: mp.CATALOGO_ENTIDADES.get(x, str(x)),
        )
    with col_dist:
        opciones_d = ["Todos"] + list(range(1, 33))
        idx_d = opciones_d.index(c_distrito_sel) if c_distrito_sel in opciones_d else 0
        distrito = st.selectbox(
            "📍 Distrito Federal (Sen 2024):", opciones_d, index=idx_d,
            format_func=lambda x: f"Distrito {x:02d}" if isinstance(x, int) else "Todos los Distritos",
        )
    dist_num = None if distrito == "Todos" else distrito
    nombre_entidad = mp.CATALOGO_ENTIDADES.get(entidad, "").split(" - ", 1)[-1]
    ambito = (f"Distrito {dist_num:02d} — {nombre_entidad}"
              if dist_num else f"Estado de {nombre_entidad}")

    df_padron = mp.consultar_padron_bd(cortes[fecha_sel], entidad=entidad, distrito=dist_num)
    df_hist = consultar_hist_sen2024(entidad=entidad, distrito=dist_num)
    matrices = mp.consultar_matrices_extintas(entidad=entidad, distrito=dist_num)
    nuevas = consultar_secciones_nuevas(entidad=entidad, distrito=dist_num)

    if df_padron.empty and df_hist.empty:
        st.warning("⚠️ No hay datos de padrón ni de Senadores 2024 para el ámbito seleccionado.")
        return

    if df_padron.empty:
        df_padron_secc = pd.DataFrame(columns=["SECCION", "PADRON_ELECTORAL", "LISTA_NOMINAL",
                                               "CLAVE_DISTRITO_P"])
    else:
        df_padron_secc = df_padron.groupby("SECCION", as_index=False).agg(
            PADRON_ELECTORAL=("PADRON_ELECTORAL", "sum"),
            LISTA_NOMINAL=("LISTA_NOMINAL", "sum"),
            CLAVE_DISTRITO_P=("CLAVE_DISTRITO", "first"),
        )

    df = df_padron_secc.merge(df_hist, on="SECCION", how="outer")
    for c in ["PADRON_ELECTORAL", "LISTA_NOMINAL", "TOT_HIST", "B_HIST", "C_HIST", "E_HIST",
              "S_HIST", "LN_ORD_24", "LN_E_24", "LN_2024", "TV_2024", "NU_2024",
              "N_LOCALIDADES"]:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(float)
    df["SECCION"] = df["SECCION"].astype(int)
    if "CLAVE_DISTRITO" in df.columns:
        distrito_2024 = pd.to_numeric(df["CLAVE_DISTRITO"], errors="coerce").fillna(0)
    else:
        distrito_2024 = pd.Series(0.0, index=df.index)
    df["CLAVE_DISTRITO"] = distrito_2024.where(
        distrito_2024 > 0, df["CLAVE_DISTRITO_P"]
    ).fillna(0).astype(int)

    df["es_matriz"] = df["SECCION"].isin(matrices)
    df["tiene_padron"] = df["PADRON_ELECTORAL"] > 0
    df["sin_padron_proyectable"] = (~df["tiene_padron"]) & (~df["es_matriz"]) & (df["LN_2024"] > 0)

    df = _proyectar(df)
    df["CAUSA"] = df.apply(lambda r: _clasificar_causa(r, matrices, nuevas), axis=1)

    # --- KPIs ---
    vot = consultar_votacion_sen2024(entidad=entidad, distrito=dist_num, agrupacion="tipo")
    vot_ln = vot[vot["LN"] > 0]
    pct_global = _pct_votacion(vot_ln["TV"].sum(), vot_ln["NU"].sum(), vot_ln["LN"].sum())

    tot_b_h, tot_c_h = int(df["B_HIST"].sum()), int(df["C_HIST"].sum())
    tot_e_h, tot_s_h = int(df["E_HIST"].sum()), int(df["S_HIST"].sum())
    tot_hist = int(df["TOT_HIST"].sum())
    tot_b, tot_c = int(df["B_2026"].sum()), int(df["C_2026"].sum())
    tot_e, tot_s = int(df["E_2026"].sum()), int(df["S_2026"].sum())
    tot_26 = int(df["TOT_2026"].sum())
    dif = tot_26 - tot_hist
    var_pct = (dif / tot_hist * 100) if tot_hist else 0
    secc_hist = int((df["TOT_HIST"] > 0).sum())
    secc_padron = int(((df["TOT_HIST"] > 0) & df["tiene_padron"]).sum())
    cobertura = (secc_padron / secc_hist * 100) if secc_hist else 0
    secc_sin_padron = int(df["sin_padron_proyectable"].sum())
    casillas_sin_padron = int(df.loc[df["sin_padron_proyectable"], "TOT_HIST"].sum())

    st.markdown("---")
    st.subheader(f"📊 Balance general — {ambito}")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(
        "% Votación 2024", _fmt_pct(pct_global),
        help="(Votos Nulos + Total_Votos) ÷ Lista Nominal. Excluye casillas Especiales "
             "porque su Lista Nominal es 0 por diseño.",
    )
    k2.metric("Casillas instaladas 2024", f"{tot_hist:,}")
    k3.metric("Casillas proyectadas 2026", f"{tot_26:,}", delta=f"{dif:+d} casillas")
    k4.metric("Variación", f"{var_pct:+.2f}%")
    k5.metric(
        "Cobertura de padrón", f"{cobertura:.1f}%",
        help=f"Secciones 2024 con registro en el corte {fecha_sel}: {secc_padron:,} de {secc_hist:,}.",
    )
    if secc_sin_padron:
        st.caption(
            f"⚠️ {secc_sin_padron:,} secciones ({casillas_sin_padron:,} casillas instaladas en 2024) "
            "no tienen registro en el padrón 2026 ni equivalencia de reseccionamiento. "
            "Se conservan con sus casillas 2024 y se listan en la auditoría causal."
        )

    # --- Conteo por tipo de casilla ---
    st.markdown("---")
    st.subheader("📑 Cantidad de casillas por tipo (B / C / E / S)")
    tipos = [
        ("B — Básicas", tot_b_h, tot_b),
        ("C — Contiguas", tot_c_h, tot_c),
        ("E — Extraordinarias", tot_e_h, tot_e),
        ("S — Especiales", tot_s_h, tot_s),
    ]
    datos_tipos = [{
        "Tipo de casilla": n,
        "Instaladas 2024": h,
        "Proyectadas 2026": p,
        "Diferencia": p - h,
    } for n, h, p in tipos]
    datos_tipos.append({
        "Tipo de casilla": "Total",
        "Instaladas 2024": tot_hist,
        "Proyectadas 2026": tot_26,
        "Diferencia": dif,
    })
    st.dataframe(pd.DataFrame(datos_tipos), width=ANCHO, hide_index=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Instaladas 2024", x=[t[0].split(" —")[0] for t in tipos],
        y=[t[1] for t in tipos], marker_color=GRIS,
        text=[f"{t[1]:,}" for t in tipos], textposition="outside",
    ))
    fig.add_trace(go.Bar(
        name="Proyectadas 2026", x=[t[0].split(" —")[0] for t in tipos],
        y=[t[2] for t in tipos], marker_color=AZUL,
        text=[f"{t[2]:,}" for t in tipos], textposition="outside",
    ))
    fig.update_layout(
        barmode="group", height=340, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title="Casillas",
    )
    st.plotly_chart(fig, width=ANCHO)

    with st.expander("🧾 Premisas y validación empírica de la proyección"):
        h = df[df["TOT_HIST"] > 0].copy()
        bc_h = h["B_HIST"] + h["C_HIST"]
        esperado_bc = np.where(h["LN_ORD_24"] > 0,
                               np.maximum(np.ceil(h["LN_ORD_24"] / 750.0), 1), 0)
        match = float((bc_h.to_numpy() == esperado_bc).mean() * 100) if len(h) else 0.0
        pruebas = pd.DataFrame([
            ("Secciones con B ≠ 1 (con electores ordinarios)",
             f"{int(((h['B_HIST'] != 1) & (h['LN_ORD_24'] > 0)).sum()):,}"),
            ("Secciones donde B+C = techo(LN ordinaria / 750)", f"{match:.2f}%"),
            ("Secciones urbanas con Extraordinarias (E > 0)",
             f"{int(((h['TIPO_3'] == 'URBANA') & (h['E_HIST'] > 0)).sum()):,}"),
            ("Secciones con Especiales (S) instaladas", f"{int((h['S_HIST'] > 0).sum()):,}"),
        ], columns=["Prueba", "Resultado"])
        st.dataframe(pruebas, width=ANCHO, hide_index=True)
        st.markdown(
            "- **Base de proyección:** Padrón Electoral del corte seleccionado.\n"
            "- **B (Básica):** una por sección, ID 01; el padrón se divide cada 750 electores.\n"
            "- **C (Contigua):** techo(padrón ordinario / 750) − 1.\n"
            "- **E (Extraordinaria):** se instala fuera de la parte urbana y agrupa localidades. Se "
            "conserva la estructura 2024 y se aplica el piso de 750 electores sobre la parte del "
            "padrón que en 2024 correspondió a casillas E (proporción tomada del acta). No se reduce.\n"
            "- **S (Especial):** no se calcula. Se conserva exactamente la cantidad de 2024 "
            "en todo el ámbito (1,000 boletas fijas y LN = 0), incluso en secciones matriz.\n"
            "- **Casillas A:** se excluyen de todos los cálculos.\n"
            "- Las secciones sin padrón 2026 conservan sus casillas 2024; las secciones matriz "
            "extintas por reseccionamiento se llevan a cero en B/C/E."
            "- La Lista Nominal solo se usa para el % de votación y el análisis de atipicidades."
        )

    # --- % de votación ---
    st.markdown("---")
    st.subheader("🗳️ Porcentaje de votación 2024")
    st.caption(
        "% Votación = (Votos Nulos + Total_Votos) ÷ Lista Nominal. Las casillas Especiales (S) "
        "no tienen Lista Nominal por diseño (1,000 boletas fijas), por lo que se reportan aparte."
    )
    vot_tipo = vot.copy()
    orden_tipo = {"B": 1, "C": 2, "E": 3, "S": 4}
    vot_tipo["_o"] = vot_tipo["GRUPO"].map(orden_tipo).fillna(99)
    vot_tipo = vot_tipo.sort_values("_o").drop(columns="_o")
    st.markdown("**Por tipo de casilla**")
    st.dataframe(_tabla_votacion(vot_tipo, "Tipo de casilla"), width=ANCHO, hide_index=True)

    vot_ts = consultar_votacion_sen2024(entidad=entidad, distrito=dist_num, agrupacion="tipo_seccion")
    st.markdown("**Por tipo de sección (catálogo INE)**")
    st.dataframe(_tabla_votacion(vot_ts, "Tipo de sección"), width=ANCHO, hide_index=True)

    if dist_num is None:
        vot_d = consultar_votacion_sen2024(entidad=entidad, distrito=None, agrupacion="distrito")
        vot_d["GRUPO"] = vot_d["GRUPO"].apply(lambda d: f"Distrito {int(d):02d}")
        with st.expander("📋 Ver % de votación por distrito"):
            st.dataframe(_tabla_votacion(vot_d, "Distrito"), width=ANCHO, hide_index=True)

    # --- Auditoría causal ---
    st.markdown("---")
    st.subheader("🔍 Auditoría causal: origen de las diferencias (2024 → 2026)")
    df_cambios = df[df["CAUSA"] != "Sin variación"].copy()
    if df_cambios.empty:
        st.success("✅ No hay diferencias entre las casillas instaladas 2024 y las proyectadas 2026.")
    else:
        resumen = df_cambios.groupby("CAUSA").agg(
            Secciones=("SECCION", "count"),
            Impacto_Neto=("DIF_TOTAL", "sum"),
        ).reset_index().rename(columns={"CAUSA": "Causa explicativa",
                                        "Impacto_Neto": "Impacto neto en casillas"})
        st.dataframe(resumen, width=ANCHO, hide_index=True)

        with st.expander("📋 Ver detalle seccional de las diferencias"):
            causas = sorted(df_cambios["CAUSA"].unique().tolist())
            f1, f2 = st.columns([3, 1])
            with f1:
                causas_sel = st.multiselect("Filtrar por causa:", causas, default=causas)
            with f2:
                st.metric("Secciones visibles",
                          f"{len(df_cambios[df_cambios['CAUSA'].isin(causas_sel)]):,}")

            detalle = df_cambios[df_cambios["CAUSA"].isin(causas_sel)].sort_values("SECCION").copy()
            detalle["DISTRITO"] = detalle["CLAVE_DISTRITO"].apply(lambda d: f"{int(d):02d}")
            cols = ["SECCION", "DISTRITO", "TIPO_3", "N_LOCALIDADES", "PADRON_ELECTORAL",
                    "LISTA_NOMINAL", "LN_2024", "B_HIST", "C_HIST", "E_HIST", "S_HIST", "TOT_HIST",
                    "B_2026", "C_2026", "E_2026", "S_2026", "TOT_2026", "DIF_TOTAL", "CAUSA"]
            detalle = detalle[cols].rename(columns={
                "SECCION": "Sección", "DISTRITO": "Distrito", "TIPO_3": "Tipo sección",
                "N_LOCALIDADES": "Localidades", "PADRON_ELECTORAL": "Padrón 2026",
                "LISTA_NOMINAL": "LN 2026", "LN_2024": "LN 2024",
                "B_HIST": "B 24", "C_HIST": "C 24", "E_HIST": "E 24", "S_HIST": "S 24",
                "TOT_HIST": "Total 24", "B_2026": "B 26", "C_2026": "C 26", "E_2026": "E 26",
                "S_2026": "S 26", "TOT_2026": "Total 26", "DIF_TOTAL": "Diferencia",
                "CAUSA": "Causa",
            })
            st.dataframe(detalle, width=ANCHO, hide_index=True)

    # --- Riesgos y acuerdo del Consejo ---
    df_rie = df[df["PADRON_ELECTORAL"] > 0].copy()
    df_rie["DISTRITO"] = df_rie["CLAVE_DISTRITO"].apply(lambda d: f"Distrito {int(d):02d}")
    df_rie["CASILLAS_ORD"] = np.maximum(np.ceil(df_rie["PAD_ORD_2026"] / 750.0), 1).astype(int)
    df_rie["TECHO"] = (df_rie["CASILLAS_ORD"] * 750 + 1).astype(int)
    df_rie["FALTAN_1"] = (df_rie["TECHO"] - df_rie["PAD_ORD_2026"]).astype(int)
    df_rie["PISO"] = np.where(df_rie["CASILLAS_ORD"] > 1,
                              (df_rie["CASILLAS_ORD"] - 1) * 750 + 1, 50)
    df_rie["MARGEN_CAER"] = (df_rie["PAD_ORD_2026"] - df_rie["PISO"]).astype(int)

    st.markdown("---")
    st.subheader("🏛️ Casillas susceptibles de acuerdo del Consejo Distrital (50 a 99 electores)")
    st.caption(
        "Art. 253, párrafo 3 de la LGIPE. Se usa el Padrón Electoral del corte seleccionado."
    )
    df_consejo = df_rie[(df_rie["PADRON_ELECTORAL"] >= 50) & (df_rie["PADRON_ELECTORAL"] < 100)]
    if df_consejo.empty:
        st.success("✅ No hay secciones en el rango de 50 a 99 electores en este ámbito.")
    else:
        st.metric("Casillas básicas proyectadas sujetas a acuerdo", f"{len(df_consejo):,}")
        st.dataframe(
            df_consejo.sort_values("PADRON_ELECTORAL")[
                ["DISTRITO", "SECCION", "PADRON_ELECTORAL", "LISTA_NOMINAL"]
            ],
            width=ANCHO, hide_index=True,
        )

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.subheader("⚠️ Margen antes de perder una casilla (≤ 10 electores)")
        st.caption("Bajas de padrón necesarias para quedar por debajo del umbral inferior de su rango.")
        df_baja = df_rie[(df_rie["CASILLAS_ORD"] > 1) & (df_rie["MARGEN_CAER"] <= 10)]
        if df_baja.empty:
            st.info("No hay secciones a ≤ 10 electores de perder una casilla.")
        else:
            st.metric("Secciones en riesgo", f"{len(df_baja):,}")
            st.dataframe(
                df_baja.sort_values("MARGEN_CAER")[
                    ["DISTRITO", "SECCION", "PADRON_ELECTORAL", "LISTA_NOMINAL",
                     "PAD_ORD_2026", "CASILLAS_ORD", "MARGEN_CAER"]
                ].rename(columns={"PAD_ORD_2026": "Padrón ordinario", "CASILLAS_ORD": "Ordinarias",
                                  "MARGEN_CAER": "Bajas para caer"}),
                width=ANCHO, hide_index=True,
            )
    with col_r2:
        st.subheader("🚨 A punto de detonar +1 casilla (faltan ≤ 10 electores)")
        df_alta = df_rie[df_rie["FALTAN_1"] <= 10]
        if df_alta.empty:
            st.info("No hay secciones a ≤ 10 electores de detonar otra casilla.")
        else:
            st.metric("Secciones por disparar casilla", f"{len(df_alta):,}")
            st.dataframe(
                df_alta.sort_values("FALTAN_1")[
                    ["DISTRITO", "SECCION", "PADRON_ELECTORAL", "LISTA_NOMINAL",
                     "PAD_ORD_2026", "CASILLAS_ORD", "FALTAN_1"]
                ].rename(columns={"PAD_ORD_2026": "Padrón ordinario", "CASILLAS_ORD": "Ordinarias",
                                  "FALTAN_1": "Faltan para +1"}),
                width=ANCHO, hide_index=True,
            )

    # --- Validación territorial con catálogos ---
    st.markdown("---")
    with st.expander("🧭 Validación territorial con catálogos (B/C/E/S y localidades)"):
        h = df[df["TOT_HIST"] > 0].copy()
        h["BC_HIST"] = h["B_HIST"] + h["C_HIST"]
        h["ESPERADO_BC"] = np.where(h["LN_ORD_24"] > 0,
                                    np.maximum(np.ceil(h["LN_ORD_24"] / 750.0), 1), 0).astype(int)
        pruebas = [
            ("Secciones con más de una casilla Básica", int((h["B_HIST"] > 1).sum())),
            ("Secciones urbanas con Extraordinarias (E > 0)",
             int(((h["TIPO_3"] == "URBANA") & (h["E_HIST"] > 0)).sum())),
            ("Secciones con E pero sin localidades en el catálogo",
             int(((h["E_HIST"] > 0) & (h["N_LOCALIDADES"] == 0)).sum())),
            ("Secciones sin tipo de sección en el catálogo", int(h["TIPO_3"].isna().sum())),
            ("Secciones donde B+C se desvía de techo(LN ordinaria/750)",
             int((h["BC_HIST"] != h["ESPERADO_BC"]).sum())),
        ]
        st.dataframe(
            pd.DataFrame(pruebas, columns=["Prueba de consistencia", "Secciones"]),
            width=ANCHO, hide_index=True,
        )
        st.caption(
            "La clasificación urbana/mixta/rural y el número de localidades provienen de los "
            "catálogos del INE."
        )

    st.markdown("---")
    st.download_button(
        "📥 Descargar proyección seccional en CSV",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"proyeccion_sen2024_{fecha_sel}_{entidad}_{distrito}.csv",
        mime="text/csv",
    )
