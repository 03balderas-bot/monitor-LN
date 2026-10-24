# ==============================================================================
# BLOQUE 1: FUNCIONES DE CONSULTA SQL Y GRÁFICAS (CON FECHAS BLINDADAS)
# ==============================================================================

import streamlit as st
def obtener_cortes_ordenados():
    try:
        import re  # Aseguramos que la librería esté cargada
        tables_db = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'", conn
        )["name"].tolist()
        
        tabla_fechas = "PE_SEX" if "PE_SEX" in tables_db else ("PE_EO" if "PE_EO" in tables_db else None)
        
        if not tabla_fechas:
            st.sidebar.error(f"Tablas detectadas en la BD: {tables_db}")
            return []

        df = pd.read_sql_query(f"SELECT DISTINCT FECHA_CORTE FROM {tabla_fechas}", conn)
        lista = sorted({str(x).strip() for x in df["FECHA_CORTE"].tolist() if str(x).strip()})

        def key_orden(val):
            v = val.strip().upper()
            if v.isdigit() and len(v) == 8:
                return (int(v[:4]), int(v[4:6]), int(v[6:8]), v)
            anio = re.search(r"(\d{4})", v)
            return (int(anio.group(1)) if anio else 0, 0, 0, v)

        lista.sort(key=key_orden, reverse=True)
        return lista
    except Exception as e:
        st.sidebar.error(f"Error técnico al leer fechas: {e}")
        return []
def consultar_datos_agregados_seguro(corte, condicion_where):
    try:
        corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
        
        c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"], ["HOMBRE"], exclude=["LIS", "LNE"])
        c_hl = col_dinamica("PE_SEX", ["HOMBRE", "LIS"], ["HOMBRE", "LNE"], ["HOMBRE"], exclude=["PAD", "PE"])
        c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"], ["MUJER"], exclude=["LIS", "LNE"])
        c_ml = col_dinamica("PE_SEX", ["MUJER", "LIS"], ["MUJER", "LNE"], ["MUJER"], exclude=["PAD", "PE"])
        c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"], ["NB"], exclude=["LIS", "LNE", "MUJER"])
        c_nbl = col_dinamica("PE_SEX", ["BINARIO", "LIS"], ["NB", "LIS"], ["NO_BINARIO", "LIS"], ["NB"], exclude=["PAD", "PE", "MUJER"])

        q_sex = f"""
                SELECT 
                    COALESCE(SUM(CAST({c_hp} AS REAL)), 0) AS h_padron,
                    COALESCE(SUM(CAST({c_hl} AS REAL)), 0) AS h_lista,
                    COALESCE(SUM(CAST({c_mp} AS REAL)), 0) AS m_padron,
                    COALESCE(SUM(CAST({c_ml} AS REAL)), 0) AS m_lista,
                    COALESCE(SUM(CAST({c_nbp} AS REAL)), 0) AS nb_padron,
                    COALESCE(SUM(CAST({c_nbl} AS REAL)), 0) AS nb_lista
                FROM PE_SEX
                WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_limpio}' {condicion_where}
            """
        df_sex = pd.read_sql_query(q_sex, conn)

        c_pnat = col_dinamica("PE_EO", ["NATIVO", "PAD"], ["NATIVO", "PE"], ["NAT", "PAD"], ["NATIVO"], exclude=["LIS", "LNE"])
        c_lnat = col_dinamica("PE_EO", ["NATIVO", "LIS"], ["NATIVO", "LNE"], ["NAT", "LIS"], ["NATIVO"], exclude=["PAD", "PE"])
        c_pfor = col_dinamica("PE_EO", ["FORANEO", "PAD"], ["FORANEO", "PE"], ["FOR", "PAD"], ["FORANEO"], exclude=["LIS", "LNE"])
        c_lfor = col_dinamica("PE_EO", ["FORANEO", "LIS"], ["FORANEO", "LNE"], ["FOR", "LIS"], ["FORANEO"], exclude=["PAD", "PE"])
        c_p87 = col_dinamica("PE_EO", ["HIJO", "PAD"], ["HIJO", "PE"], ["MEXICANO", "PAD"], ["HIJO"], ["MEXICANO"], ["87"], exclude=["LIS", "LNE", "88", "NATURALIZADO"])
        c_l87 = col_dinamica("PE_EO", ["HIJO", "LIS"], ["HIJO", "LNE"], ["MEXICANO", "LIS"], ["HIJO"], ["MEXICANO"], ["87"], exclude=["PAD", "PE", "88", "NATURALIZADO"])
        c_p88 = col_dinamica("PE_EO", ["NATURALIZADO", "PAD"], ["NATURALIZADO", "PE"], ["88", "PAD"], ["NATURALIZADO"], ["88"], exclude=["LIS", "LNE", "87", "HIJO", "MEXICANO"])
        c_l88 = col_dinamica("PE_EO", ["NATURALIZADO", "LIS"], ["NATURALIZADO", "LNE"], ["88", "LIS"], ["NATURALIZADO"], ["88"], exclude=["PAD", "PE", "87", "HIJO", "MEXICANO"])

        q_eo = f"""
                SELECT 
                    COALESCE(SUM(CAST({c_pnat} AS REAL)), 0) AS p_nat, COALESCE(SUM(CAST({c_lnat} AS REAL)), 0) AS l_nat,
                    COALESCE(SUM(CAST({c_pfor} AS REAL)), 0) AS p_for, COALESCE(SUM(CAST({c_lfor} AS REAL)), 0) AS l_for,
                    COALESCE(SUM(CAST({c_p87} AS REAL)), 0) AS p_87, COALESCE(SUM(CAST({c_l87} AS REAL)), 0) AS l_87,
                    COALESCE(SUM(CAST({c_p88} AS REAL)), 0) AS p_88, COALESCE(SUM(CAST({c_l88} AS REAL)), 0) AS l_88
                FROM PE_EO
                WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_limpio}' {condicion_where}
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

        pad_final = max(pad_sex_total, pad_eo_total) if max(pad_sex_total, pad_eo_total) > 0 else pad_sex_total
        lis_final = max(lis_sex_total, lis_eo_total) if max(lis_sex_total, lis_eo_total) > 0 else lis_sex_total

        return pd.DataFrame([{
            "padron": pad_final, "lista": lis_final,
            "h_padron": h_p, "h_lista": h_l, "m_padron": m_p, "m_lista": m_l, "nb_padron": nb_p, "nb_lista": nb_l,
            "p_nat": p_n, "l_nat": l_n, "p_for": p_f, "l_for": l_f, "p_87": p_7, "l_87": l_7, "p_88": p_8, "l_88": l_8,
        }])
    except Exception:
        return pd.DataFrame([{
            "padron": 0, "lista": 0, "h_padron": 0, "h_lista": 0, "m_padron": 0, "m_lista": 0, "nb_padron": 0, "nb_lista": 0,
            "p_nat": 0, "l_nat": 0, "p_for": 0, "l_for": 0, "p_87": 0, "l_87": 0, "p_88": 0, "l_88": 0,
        }])

def obtener_tabla_edad(tables_db):
    if "PE_RE" in tables_db:
        return "PE_RE"
    return next(
        (t for t in tables_db if "EDAD" in t.upper() or "RANGO" in t.upper()),
        "PE_SEX" if "PE_SEX" in tables_db else "",
    )

def filtro_para_tabla(condicion_where, cols_tabla):
    if not condicion_where:
        return ""
    cols = {str(c).upper() for c in cols_tabla}
    validas = []
    for frag in condicion_where.split("AND"):
        frag = frag.strip()
        if not frag:
            continue
        m = re.match(r"(CLAVE_[A-Z_]+)\s*(!=|=)\s*(-?\d+)\s*$", frag.upper())
        if m and m.group(1) in cols:
            validas.append(frag)
    return (" AND " + " AND ".join(validas)) if validas else ""

def condicion_corte(corte, cols_tabla):
    if "FECHA_CORTE" not in {str(c).upper() for c in cols_tabla}:
        return "1=1", []
    expr = (
        "UPPER(REPLACE(REPLACE(REPLACE(TRIM(FECHA_CORTE), '-', ''), '_', ''), ' ', ''))"
    )
    corte_limpio = str(corte).replace("-", "").replace("_", "").strip().upper()
    return f"{expr} = ?", [corte_limpio]

def consultar_datos_jovenes_seguro(corte, condicion_where):
    try:
        tabla_edad = "PE_RE"
        cols_tabla = pd.read_sql_query(f"PRAGMA table_info({tabla_edad})", conn)["name"].tolist()
        c_pjov = "PE_JOVENES_18_19" if "PE_JOVENES_18_19" in cols_tabla else col_dinamica(tabla_edad, ["18", "19", "PAD"], ["18_19", "PAD"], exclude=["LIS", "LNE"])
        c_ljov = "LNE_JOVENES_18_19" if "LNE_JOVENES_18_19" in cols_tabla else col_dinamica(tabla_edad, ["18", "19", "LIS"], ["18_19", "LIS"], exclude=["PAD", "PE"])
        cond_segura = condicion_where if "CLAVE_ENTIDAD" in cols_tabla or "CLAVE_ENTIDAD" not in condicion_where else ""
        corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
        q = f"SELECT COALESCE(SUM(CAST({c_pjov} AS REAL)), 0) AS p, COALESCE(SUM(CAST({c_ljov} AS REAL)), 0) AS l FROM {tabla_edad} WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_limpio}' {cond_segura}"
        df_tmp = pd.read_sql_query(q, conn)
        return int(df_tmp["p"].iloc[0] if not df_tmp.empty else 0), int(df_tmp["l"].iloc[0] if not df_tmp.empty else 0)
    except Exception:
        return 0, 0

def consultar_datos_mayores_seguro(corte, condicion_where):
    try:
        tabla_edad = "PE_RE"
        cols_tabla = pd.read_sql_query(f"PRAGMA table_info({tabla_edad})", conn)["name"].tolist()
        c_pmay = "PE_MAS_DE_65" if "PE_MAS_DE_65" in cols_tabla else col_dinamica(tabla_edad, ["65", "PAD"], ["65_MAS", "PAD"], exclude=["LIS", "LNE"])
        c_lmay = "LNE_MAS_DE_65" if "LNE_MAS_DE_65" in cols_tabla else col_dinamica(tabla_edad, ["65", "LIS"], ["65_MAS", "LIS"], exclude=["PAD", "PE"])
        cond_segura = condicion_where if "CLAVE_ENTIDAD" in cols_tabla or "CLAVE_ENTIDAD" not in condicion_where else ""
        corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
        q = f"SELECT COALESCE(SUM(CAST({c_pmay} AS REAL)), 0) AS p, COALESCE(SUM(CAST({c_lmay} AS REAL)), 0) AS l FROM {tabla_edad} WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_limpio}' {cond_segura}"
        df_tmp = pd.read_sql_query(q, conn)
        return int(df_tmp["p"].iloc[0] if not df_tmp.empty else 0), int(df_tmp["l"].iloc[0] if not df_tmp.empty else 0)
    except Exception:
        return 0, 0
   
def renderizar_grafica_posicionamiento(
    corte, alcance_tipo, cve_ent, cve_dist, modo_comp=False, corte_base_comp=None
):
  corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
  c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
  c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
  c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])
  c_hl = col_dinamica("PE_SEX", ["HOMBRE", "LIS"], ["HOMBRE", "LNE"])
  c_ml = col_dinamica("PE_SEX", ["MUJER", "LIS"], ["MUJER", "LNE"])
  c_nbl = col_dinamica("PE_SEX", ["BINARIO", "LIS"], ["NB", "LIS"], ["NO_BINARIO", "LIS"])

  if cve_ent:
    nom_entidad = CATALOGO_ENTIDADES.get(cve_ent, "Entidad")
    c_cab = col_dinamica("PE_SEX", ["CABECERA"])

    q_rec = f"""
            SELECT CLAVE_DISTRITO,
                   MAX({c_cab}) AS CABECERA,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_REC
            FROM PE_SEX
            WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_limpio}'
              AND CLAVE_ENTIDAD = {cve_ent}
              AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q_rec, conn)
    if df_rec.empty:
      return

    df_rec["CABECERA_TXT"] = (
        df_rec["CABECERA"].fillna("").astype(str).str.strip()
    )
    df_rec["ETIQUETA"] = df_rec.apply(
        lambda r: (
            f"Dist. {int(r['CLAVE_DISTRITO']):02d} -"
            f" {r['CABECERA_TXT'][:18]}"
            if r["CABECERA_TXT"] and r["CABECERA_TXT"] != "0"
            else f"Distrito {int(r['CLAVE_DISTRITO']):02d}"
        ),
        axis=1,
    )

    df_vol = df_rec.sort_values(by="PADRON_REC", ascending=True).copy()
    promedio_vol = df_vol["PADRON_REC"].mean()

    colores_vol = [
        "#D946EF" if cve_dist and int(d) == int(cve_dist) else "#3B82F6"
        for d in df_vol["CLAVE_DISTRITO"]
    ]

    fig_vol = go.Figure()
    fig_vol.add_trace(
        go.Bar(
            y=df_vol["ETIQUETA"],
            x=df_vol["PADRON_REC"],
            orientation="h",
            marker=dict(color=colores_vol, line=dict(width=0)),
            text=[f"{int(x):,}" for x in df_vol["PADRON_REC"]],
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color="#FFFFFF", size=10),
            hovertemplate=(
                "<b>%{y}</b><br>Padrón: <b>%{x:,.0f}</b><extra></extra>"
            ),
        )
    )
    fig_vol.add_vline(
        x=promedio_vol,
        line_width=1.5,
        line_dash="dash",
        line_color="#F59E0B",
        annotation_text=f"Media: {promedio_vol:,.0f}",
        annotation_position="top right",
        annotation_font=dict(size=10, color="#F59E0B"),
    )
    subtitulo_vol = (
        f"<b>1. Volumen del Padrón Electoral en {nom_entidad}</b>"
        + (f" (Distrito {cve_dist:02d} resaltado)" if cve_dist else "")
    )
    fig_vol.update_layout(
        title=dict(text=subtitulo_vol, font=dict(size=13, color="#E2E8F0")),
        xaxis=dict(
            title="Padrón Electoral (Personas)",
            showgrid=True,
            gridcolor="#334155",
            zeroline=False,
        ),
        yaxis=dict(showgrid=False, tickfont=dict(size=10.5)),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#94A3B8"),
        margin=dict(l=20, r=20, t=40, b=30),
        height=max(340, len(df_vol) * 32),
    )

    if modo_comp and corte_base_comp:
      corte_base_limpio = str(corte_base_comp).strip().replace("-", "").replace("_", "")
      q_bas = f"""
                SELECT CLAVE_DISTRITO,
                       SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_BAS
                FROM PE_SEX
                WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_base_limpio}'
                  AND CLAVE_ENTIDAD = {cve_ent}
                  AND CLAVE_DISTRITO != 0
                GROUP BY CLAVE_DISTRITO
            """
      df_bas = pd.read_sql_query(q_bas, conn)
      df_comp = pd.merge(df_rec, df_bas, on="CLAVE_DISTRITO")
      df_comp["CREC_PCT"] = (
          (df_comp["PADRON_REC"] - df_comp["PADRON_BAS"])
          / df_comp["PADRON_BAS"]
      ) * 100
      df_comp["DIF_ABS"] = df_comp["PADRON_REC"] - df_comp["PADRON_BAS"]
      df_comp = df_comp.sort_values(by="CREC_PCT", ascending=True)

      promedio_crec = (
          (df_comp["PADRON_REC"].sum() - df_comp["PADRON_BAS"].sum())
          / df_comp["PADRON_BAS"].sum()
      ) * 100

      colores_crec = [
          "#D946EF"
          if cve_dist and int(d) == int(cve_dist)
          else (
              "#10B981"
              if x >= promedio_crec
              else ("#EF4444" if x < 1.0 else "#64748B")
          )
          for d, x in zip(df_comp["CLAVE_DISTRITO"], df_comp["CREC_PCT"])
      ]

      fig_crec = go.Figure()
      fig_crec.add_trace(
          go.Bar(
              y=df_comp["ETIQUETA"],
              x=df_comp["CREC_PCT"],
              orientation="h",
              marker=dict(color=colores_crec, line=dict(width=0)),
              text=[f"{x:+.2f}%" for x in df_comp["CREC_PCT"]],
              textposition="inside",
              insidetextanchor="middle",
              textfont=dict(color="#FFFFFF", size=10),
              hovertemplate=(
                  "<b>%{y}</b><br>Crecimiento: <b>%{x:+.2f}%</b><br>Variación"
                  " Neta: %{customdata:+,.0f}<extra></extra>"
              ),
              customdata=df_comp["DIF_ABS"],
          )
      )
      fig_crec.add_vline(
          x=promedio_crec,
          line_width=1.5,
          line_dash="dash",
          line_color="#F59E0B",
          annotation_text=f"Media: {promedio_crec:+.2f}%",
          annotation_position="top right",
          annotation_font=dict(size=10, color="#F59E0B"),
      )
      subtitulo_crec = (
          f"<b>2. Ritmo de Crecimiento del Padrón (%) en {nom_entidad}</b>"
          + (f" (Distrito {cve_dist:02d} resaltado)" if cve_dist else "")
      )
      fig_crec.update_layout(
          title=dict(text=subtitulo_crec, font=dict(size=13, color="#E2E8F0")),
          xaxis=dict(
              title="Variación Porcentual (%)",
              showgrid=True,
              gridcolor="#334155",
              zeroline=True,
              zerolinecolor="#64748B",
          ),
          yaxis=dict(showgrid=False, tickfont=dict(size=10.5)),
          plot_bgcolor="rgba(0,0,0,0)",
          paper_bgcolor="rgba(0,0,0,0)",
          font=dict(color="#94A3B8"),
          margin=dict(l=20, r=20, t=40, b=30),
          height=max(340, len(df_comp) * 32),
      )

      col_v1, col_v2 = st.columns(2)
      with col_v1:
        st.plotly_chart(fig_vol, width="stretch")
      with col_v2:
        st.plotly_chart(fig_crec, width="stretch")
    else:
      q_cob = f"""
                SELECT CLAVE_DISTRITO,
                       SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON,
                       SUM(CAST({c_hl} AS REAL) + CAST({c_ml} AS REAL) + CAST({c_nbl} AS REAL)) AS LISTA
                FROM PE_SEX 
                WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_limpio}' 
                  AND CLAVE_ENTIDAD = {cve_ent} AND CLAVE_DISTRITO != 0
                GROUP BY CLAVE_DISTRITO
            """
      df_cob = pd.read_sql_query(q_cob, conn)
      if df_cob.empty:
        return
      df_cob["COB"] = (df_cob["LISTA"] / df_cob["PADRON"]) * 100
      df_cob = df_cob.sort_values(by="COB", ascending=True)
      promedio_cob = (df_cob["LISTA"].sum() / df_cob["PADRON"].sum()) * 100

      colores_cob = [
          "#D946EF" if cve_dist and int(d) == int(cve_dist) else "#10B981"
          for d in df_cob["CLAVE_DISTRITO"]
      ]

      fig_cob = go.Figure()
      fig_cob.add_trace(
          go.Bar(
              y=df_rec.set_index("CLAVE_DISTRITO")
              .loc[df_cob["CLAVE_DISTRITO"], "ETIQUETA"]
              .tolist(),
              x=df_cob["COB"],
              orientation="h",
              marker=dict(color=colores_cob, line=dict(width=0)),
              text=[f"{x:.2f}%" for x in df_cob["COB"]],
              textposition="inside",
              insidetextanchor="middle",
              textfont=dict(color="#FFFFFF", size=10),
              hovertemplate=(
                  "<b>%{y}</b><br>Cobertura: <b>%{x:.2f}%</b><extra></extra>"
              ),
          )
      )
      fig_cob.add_vline(
          x=promedio_cob,
          line_width=1.5,
          line_dash="dash",
          line_color="#F59E0B",
          annotation_text=f"Media Estatal: {promedio_cob:.2f}%",
          annotation_position="top right",
          annotation_font=dict(size=10, color="#F59E0B"),
      )
      subtitulo_cob = (
          f"<b>2. Cobertura Registral (%) por Distrito en {nom_entidad}</b>"
          + (f" (Distrito {cve_dist:02d} resaltado)" if cve_dist else "")
      )
      fig_cob.update_layout(
          title=dict(text=subtitulo_cob, font=dict(size=13, color="#E2E8F0")),
          xaxis=dict(
              title="Cobertura Registral (%)",
              showgrid=True,
              gridcolor="#334155",
              zeroline=False,
          ),
          yaxis=dict(showgrid=False, tickfont=dict(size=10.5)),
          plot_bgcolor="rgba(0,0,0,0)",
          paper_bgcolor="rgba(0,0,0,0)",
          font=dict(color="#94A3B8"),
          margin=dict(l=20, r=20, t=40, b=30),
          height=max(340, len(df_cob) * 32),
      )

      st.plotly_chart(fig_vol, width="stretch")

  elif "Nacional" in alcance_tipo:
    if modo_comp and corte_base_comp:
      corte_base_limpio = str(corte_base_comp).strip().replace("-", "").replace("_", "")
      q_rec = f"""
                SELECT CLAVE_ENTIDAD,
                       SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_REC
                FROM PE_SEX 
                WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_limpio}' 
                  AND CLAVE_ENTIDAD BETWEEN 1 AND 32
                GROUP BY CLAVE_ENTIDAD
            """
      q_bas = f"""
                SELECT CLAVE_ENTIDAD,
                       SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_BAS
                FROM PE_SEX 
                WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_base_limpio}' 
                  AND CLAVE_ENTIDAD BETWEEN 1 AND 32
                GROUP BY CLAVE_ENTIDAD
            """
      df_r = pd.read_sql_query(q_rec, conn)
      df_b = pd.read_sql_query(q_bas, conn)
      df = pd.merge(df_r, df_b, on="CLAVE_ENTIDAD")
      df["CREC_PCT"] = (
          (df["PADRON_REC"] - df["PADRON_BAS"]) / df["PADRON_BAS"]
      ) * 100
      df["ENTIDAD"] = df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)

      df_vol_nal = df.sort_values(by="PADRON_REC", ascending=True).copy()
      prom_vol_nal = df_vol_nal["PADRON_REC"].mean()

      fig_v_nal = go.Figure()
      fig_v_nal.add_trace(
          go.Bar(
              y=df_vol_nal["ENTIDAD"],
              x=df_vol_nal["PADRON_REC"],
              orientation="h",
              marker=dict(color="#3B82F6", line=dict(width=0)),
              text=[f"{int(x):,}" for x in df_vol_nal["PADRON_REC"]],
              textposition="inside",
              insidetextanchor="middle",
              textfont=dict(color="#FFFFFF", size=9),
              hovertemplate=(
                  "<b>%{y}</b><br>Padrón: <b>%{x:,.0f}</b><extra></extra>"
              ),
          )
      )
      fig_v_nal.add_vline(
          x=prom_vol_nal,
          line_width=1.5,
          line_dash="dash",
          line_color="#F59E0B",
          annotation_text=f"Media: {prom_vol_nal:,.0f}",
          annotation_position="top right",
          annotation_font=dict(size=9.5, color="#F59E0B"),
      )
      fig_v_nal.update_layout(
          title=dict(
              text=(
                  "<b>1. Volumen del Padrón Electoral por Entidad"
                  " Federativa</b>"
              ),
              font=dict(size=13, color="#E2E8F0"),
          ),
          xaxis=dict(
              title="Padrón Electoral (Personas)",
              showgrid=True,
              gridcolor="#334155",
              zeroline=False,
          ),
          yaxis=dict(showgrid=False, tickfont=dict(size=10)),
          plot_bgcolor="rgba(0,0,0,0)",
          paper_bgcolor="rgba(0,0,0,0)",
          font=dict(color="#94A3B8"),
          margin=dict(l=20, r=20, t=40, b=30),
          height=780,
      )

      df_crec_nal = df.sort_values(by="CREC_PCT", ascending=True).copy()
      prom_crec_nal = (
          (df["PADRON_REC"].sum() - df["PADRON_BAS"].sum())
          / df["PADRON_BAS"].sum()
      ) * 100
      colores_cn = [
          (
              "#10B981"
              if x >= prom_crec_nal
              else ("#EF4444" if x < 1.0 else "#64748B")
          )
          for x in df_crec_nal["CREC_PCT"]
      ]

      fig_c_nal = go.Figure()
      fig_c_nal.add_trace(
          go.Bar(
              y=df_crec_nal["ENTIDAD"],
              x=df_crec_nal["CREC_PCT"],
              orientation="h",
              marker=dict(color=colores_cn, line=dict(width=0)),
              text=[f"{x:+.2f}%" for x in df_crec_nal["CREC_PCT"]],
              textposition="inside",
              insidetextanchor="middle",
              textfont=dict(color="#FFFFFF", size=9),
              hovertemplate=(
                  "<b>%{y}</b><br>Crecimiento: <b>%{x:+.2f}%</b><extra></extra>"
              ),
          )
      )
      fig_c_nal.add_vline(
          x=prom_crec_nal,
          line_width=1.5,
          line_dash="dash",
          line_color="#F59E0B",
          annotation_text=f"Media: {prom_crec_nal:+.2f}%",
          annotation_position="top right",
          annotation_font=dict(size=9.5, color="#F59E0B"),
      )
      fig_c_nal.update_layout(
          title=dict(
              text=(
                  "<b>2. Ritmo de Crecimiento del Padrón (%) por Entidad"
                  " Federativa</b>"
              ),
              font=dict(size=13, color="#E2E8F0"),
          ),
          xaxis=dict(
              title="Variación Porcentual (%)",
              showgrid=True,
              gridcolor="#334155",
              zeroline=True,
              zerolinecolor="#64748B",
          ),
          yaxis=dict(showgrid=False, tickfont=dict(size=10)),
          plot_bgcolor="rgba(0,0,0,0)",
          paper_bgcolor="rgba(0,0,0,0)",
          font=dict(color="#94A3B8"),
          margin=dict(l=20, r=20, t=40, b=30),
          height=780,
      )

      col_n1, col_n2 = st.columns(2)
      with col_n1:
        st.plotly_chart(fig_v_nal, width="stretch")
      with col_n2:
        st.plotly_chart(fig_c_nal, width="stretch")

    else:
      q = f"""
                SELECT CLAVE_ENTIDAD,
                       SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON
                FROM PE_SEX 
                WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_limpio}' 
                  AND CLAVE_ENTIDAD BETWEEN 1 AND 32
                GROUP BY CLAVE_ENTIDAD
            """
      df = pd.read_sql_query(q, conn)
      df["ENTIDAD"] = df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
      df = df.sort_values(by="PADRON", ascending=True).copy()
      prom_nal = df["PADRON"].mean()

      fig = go.Figure()
      fig.add_trace(
          go.Bar(
              y=df["ENTIDAD"],
              x=df["PADRON"],
              orientation="h",
              marker=dict(color="#3B82F6", line=dict(width=0)),
              text=[f"{int(x):,}" for x in df["PADRON"]],
              textposition="inside",
              insidetextanchor="middle",
              textfont=dict(color="#FFFFFF", size=9),
              hovertemplate=(
                  "<b>%{y}</b><br>Padrón: <b>%{x:,.0f}</b><extra></extra>"
              ),
          )
      )
      fig.add_vline(
          x=prom_nal,
          line_width=1.5,
          line_dash="dash",
          line_color="#F59E0B",
          annotation_text=f"Media Estatal/Nal: {prom_nal:,.0f}",
          annotation_position="top right",
          annotation_font=dict(size=10, color="#F59E0B"),
      )
      fig.update_layout(
          title=dict(
              text=(
                  "<b>Volumen del Padrón Electoral por Entidad Federativa"
                  " (Orden Descendente)</b>"
              ),
              font=dict(size=13, color="#E2E8F0"),
          ),
          xaxis=dict(
              title="Padrón Electoral (Personas)",
              showgrid=True,
              gridcolor="#334155",
              zeroline=False,
          ),
          yaxis=dict(showgrid=False, tickfont=dict(size=10)),
          plot_bgcolor="rgba(0,0,0,0)",
          paper_bgcolor="rgba(0,0,0,0)",
          font=dict(color="#94A3B8"),
          margin=dict(l=20, r=20, t=40, b=30),
          height=780,
      )
      st.plotly_chart(fig, width="stretch")
def generar_grafico_volumen_pdf(corte, cve_ent, cve_dist):
  try:
    if not cve_ent:
      return None
    nom_ent = CATALOGO_ENTIDADES.get(cve_ent, "Entidad")
    c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
    c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
    c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])

    corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
    q = f"""
            SELECT CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_ENTIDAD = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_DISTRITO ORDER BY PADRON ASC
        """
    df = pd.read_sql_query(q, conn, params=[corte_limpio, int(cve_ent)])
    if df.empty:
      return None

    promedio = df["PADRON"].mean()
    colores = [
        "#D946EF" if cve_dist and int(d) == int(cve_dist) else "#3B82F6"
        for d in df["CLAVE_DISTRITO"]
    ]
    etiquetas = [f"Dist. {int(d):02d}" for d in df["CLAVE_DISTRITO"]]

    alt = max(2.2, min(4.0, len(df) * 0.25))
    plt.figure(figsize=(6.8, alt))
    plt.barh(etiquetas, df["PADRON"], color=colores, height=0.65)
    plt.axvline(
        promedio,
        color="#F59E0B",
        linestyle="--",
        linewidth=1.2,
        label=f"Media: {promedio:,.0f}",
    )
    plt.title(
        f"1. Volumen del Padrón Electoral en {nom_ent}"
        + (f" (Dist. {cve_dist:02d} resaltado)" if cve_dist else ""),
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
    )
    plt.xlabel("Padrón Electoral (Personas)", fontsize=8)
    plt.xticks(fontsize=7.5)
    plt.yticks(fontsize=7.5)
    plt.legend(loc="lower right", fontsize=7.5)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=220)
    plt.close()
    buf.seek(0)
    return buf
  except Exception as e:
    print(f"Error en generar_grafico_volumen_pdf: {e}")
    return None

def generar_grafico_posicionamiento_pdf(
    corte, alcance_tipo, cve_ent, cve_dist, modo_comp=False, corte_base_comp=None
):
  try:
    c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
    c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
    c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])
    c_hl = col_dinamica("PE_SEX", ["HOMBRE", "LIS"], ["HOMBRE", "LNE"])
    c_ml = col_dinamica("PE_SEX", ["MUJER", "LIS"], ["MUJER", "LNE"])
    c_nbl = col_dinamica("PE_SEX", ["BINARIO", "LIS"], ["NB", "LIS"], ["NO_BINARIO", "LIS"])

    corte_limpio = str(corte).strip().replace("-", "").replace("_", "")

    if cve_ent:
      nom_ent = CATALOGO_ENTIDADES.get(cve_ent, "Entidad")
      c_cab = col_dinamica("PE_SEX", ["CABECERA"])

      if modo_comp and corte_base_comp:
        corte_base_limpio = str(corte_base_comp).strip().replace("-", "").replace("_", "")
        q_rec = f"""
                    SELECT CLAVE_DISTRITO, MAX({c_cab}) AS CABECERA,
                           SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_REC
                    FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_ENTIDAD = ? AND CLAVE_DISTRITO != 0
                    GROUP BY CLAVE_DISTRITO
                """
        q_bas = f"""
                    SELECT CLAVE_DISTRITO,
                           SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_BAS
                    FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_ENTIDAD = ? AND CLAVE_DISTRITO != 0
                    GROUP BY CLAVE_DISTRITO
                """
        df_r = pd.read_sql_query(q_rec, conn, params=[corte_limpio, int(cve_ent)])
        df_b = pd.read_sql_query(q_bas, conn, params=[corte_base_limpio, int(cve_ent)])
        df = pd.merge(df_r, df_b, on="CLAVE_DISTRITO")
        if df.empty:
          return None

        df["VALOR"] = ((df["PADRON_REC"] - df["PADRON_BAS"]) / df["PADRON_BAS"]) * 100
        df = df.sort_values(by="VALOR", ascending=True)
        promedio = ((df["PADRON_REC"].sum() - df["PADRON_BAS"].sum()) / df["PADRON_BAS"].sum()) * 100

        colores = [
            "#D946EF" if cve_dist and int(d) == int(cve_dist) else "#64748B"
            for d in df["CLAVE_DISTRITO"]
        ]
        etiquetas = [f"Dist. {int(d):02d}" for d in df["CLAVE_DISTRITO"]]
        titulo = f"2. Ritmo de Crecimiento del Padrón (%) en {nom_ent}" + (f" (Dist. {cve_dist:02d} resaltado)" if cve_dist else "")
        x_label = "Variación Porcentual (%)"

      else:
        q = f"""
                    SELECT CLAVE_DISTRITO,
                           SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON,
                           SUM(CAST({c_hl} AS REAL) + CAST({c_ml} AS REAL) + CAST({c_nbl} AS REAL)) AS LISTA
                    FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_ENTIDAD = ? AND CLAVE_DISTRITO != 0
                    GROUP BY CLAVE_DISTRITO
                """
        df = pd.read_sql_query(q, conn, params=[corte_limpio, int(cve_ent)])
        if df.empty:
          return None

        df["VALOR"] = (df["LISTA"] / df["PADRON"]) * 100
        df = df.sort_values(by="VALOR", ascending=True)
        promedio = (df["LISTA"].sum() / df["PADRON"].sum()) * 100

        colores = [
            "#D946EF" if cve_dist and int(d) == int(cve_dist) else "#10B981"
            for d in df["CLAVE_DISTRITO"]
        ]
        etiquetas = [f"Dist. {int(d):02d}" for d in df["CLAVE_DISTRITO"]]
        titulo = f"2. Cobertura Registral (%) en {nom_ent}" + (f" (Dist. {cve_dist:02d} resaltado)" if cve_dist else "")
        x_label = "Cobertura Registral (%)"

      alt = max(2.2, min(4.0, len(df) * 0.25))
      plt.figure(figsize=(6.8, alt))
      plt.barh(etiquetas, df["VALOR"], color=colores, height=0.65)
      plt.axvline(
          promedio,
          color="#F59E0B",
          linestyle="--",
          linewidth=1.2,
          label=f"Media: {promedio:.2f}%",
      )
      plt.title(titulo, fontsize=9, fontweight="bold", color="#4A2E7A")
      plt.xlabel(x_label, fontsize=8)
      plt.xticks(fontsize=7.5)
      plt.yticks(fontsize=7.5)
      plt.legend(loc="lower right", fontsize=7.5)
      plt.tight_layout()

      buf = BytesIO()
      plt.savefig(buf, format="png", dpi=220)
      plt.close()
      buf.seek(0)
      return buf
  except Exception as e:
    print(f"Error en generar_grafico_posicionamiento_pdf: {e}")
    return None

def generar_grafico_distritos_menor_1(corte_rec, corte_bas):
  try:
    if not corte_bas:
      return None
    c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
    c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
    c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])

    corte_rec_limpio = str(corte_rec).strip().replace("-", "").replace("_", "")
    corte_bas_limpio = str(corte_bas).strip().replace("-", "").replace("_", "")

    q_rec = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_REC
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    q_bas = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_BAS
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q_rec, conn, params=[corte_rec_limpio])
    df_bas = pd.read_sql_query(q_bas, conn, params=[corte_bas_limpio])
    df_merged = pd.merge(
        df_rec,
        df_bas,
        on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO"],
        suffixes=("_rec", "_bas"),
    )
    df_merged["pct"] = (
        (df_merged["PADRON_REC"] - df_merged["PADRON_BAS"])
        / df_merged["PADRON_BAS"]
    ) * 100

    df_sub = df_merged[df_merged["pct"] <= 1.0].sort_values(
        by="pct", ascending=True
    )
    if df_sub.empty:
      return None

    df_sub["etiqueta"] = (
        df_sub["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        + " - D."
        + df_sub["CLAVE_DISTRITO"].astype(str)
    )

    alt = max(3.0, min(5.8, len(df_sub) * 0.28 + 0.8))
    fig, ax = plt.subplots(figsize=(7.2, alt))
    ax.barh(df_sub["etiqueta"], df_sub["pct"], color="#EF4444", height=0.65)
    ax.axvline(0, color="#334155", linewidth=0.8)
    ax.axvline(
        1.0,
        color="#F59E0B",
        linestyle="--",
        linewidth=1.0,
        label="Umbral de Alerta (1.0%)",
    )
    ax.invert_yaxis()
    ax.set_title(
        f"Distritos Federales con Menor Dinamismo / Contracción (Crecimiento ≤"
        f" 1.0%) - Total: {len(df_sub)}",
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
        pad=10,
    )
    ax.set_xlabel(
        "Variación Porcentual del Padrón (%)", fontsize=8, labelpad=6
    )
    ax.tick_params(axis="x", labelsize=7.5)
    ax.tick_params(axis="y", labelsize=7.5)
    ax.legend(loc="lower right", fontsize=7.5)
    fig.subplots_adjust(left=0.28, right=0.96, top=0.92, bottom=0.10)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=220)
    plt.close(fig)
    buf.seek(0)
    return buf
  except Exception as e:
    print(f"Error en generar_grafico_distritos_menor_1: {e}")
    return None

def generar_grafico_distritos_mayor_10(corte_rec, corte_bas):
  try:
    if not corte_bas:
      return None
    c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
    c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
    c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])

    corte_rec_limpio = str(corte_rec).strip().replace("-", "").replace("_", "")
    corte_bas_limpio = str(corte_bas).strip().replace("-", "").replace("_", "")

    q_rec = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_REC
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    q_bas = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_BAS
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q_rec, conn, params=[corte_rec_limpio])
    df_bas = pd.read_sql_query(q_bas, conn, params=[corte_bas_limpio])
    df_merged = pd.merge(
        df_rec,
        df_bas,
        on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO"],
        suffixes=("_rec", "_bas"),
    )
    df_merged["pct"] = (
        (df_merged["PADRON_REC"] - df_merged["PADRON_BAS"])
        / df_merged["PADRON_BAS"]
    ) * 100

    df_sub = df_merged[df_merged["pct"] >= 10.0].sort_values(
        by="pct", ascending=True
    )
    if df_sub.empty:
      return None

    df_sub["etiqueta"] = (
        df_sub["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        + " - D."
        + df_sub["CLAVE_DISTRITO"].astype(str)
    )

    alt = max(3.0, min(5.8, len(df_sub) * 0.28 + 0.8))
    fig, ax = plt.subplots(figsize=(7.2, alt))
    ax.barh(df_sub["etiqueta"], df_sub["pct"], color="#10B981", height=0.65)
    ax.axvline(
        10.0,
        color="#F59E0B",
        linestyle="--",
        linewidth=1.0,
        label="Umbral de Expansión (10.0%)",
    )
    ax.invert_yaxis()
    ax.set_title(
        f"Distritos Federales con Fuerte Expansión Demográfica (Crecimiento ≥"
        f" 10.0%) - Total: {len(df_sub)}",
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
        pad=10,
    )
    ax.set_xlabel(
        "Variación Porcentual del Padrón (%)", fontsize=8, labelpad=6
    )
    ax.tick_params(axis="x", labelsize=7.5)
    ax.tick_params(axis="y", labelsize=7.5)
    ax.legend(loc="lower right", fontsize=7.5)
    fig.subplots_adjust(left=0.28, right=0.96, top=0.92, bottom=0.10)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=220)
    plt.close(fig)
    buf.seek(0)
    return buf
  except Exception as e:
    print(f"Error en generar_grafico_distritos_mayor_10: {e}")
    return None

def generar_grafico_top_jovenes(corte):
  try:
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table'", conn
    )["name"].tolist()
    if "PE_RE" in tables:
      c_pj = col_dinamica(
          "PE_RE",
          ["18", "19", "PAD"],
          ["18", "19", "PE"],
          exclude=["LIS", "LNE", "HOMBRE", "MUJER", "BINARIO", "NB"],
          default=None,
      )
      if not c_pj:
        return None
      c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
      c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
      c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])

      corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
      q = f"""
                SELECT CLAVE_ENTIDAD, 
                       (SUM(CAST({c_pj} AS REAL)) * 100.0 / 
                        NULLIF((SELECT SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) FROM PE_SEX S WHERE TRIM(REPLACE(REPLACE(S.FECHA_CORTE, '-', ''), '_', '')) = TRIM(REPLACE(REPLACE(PE_RE.FECHA_CORTE, '-', ''), '_', '')) AND S.CLAVE_ENTIDAD = PE_RE.CLAVE_ENTIDAD), 0)) AS pct_jovenes
                FROM PE_RE WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ?
                GROUP BY CLAVE_ENTIDAD ORDER BY pct_jovenes DESC LIMIT 5
            """
      df = pd.read_sql_query(q, conn, params=[corte_limpio])
      if not df.empty and df["pct_jovenes"].sum() > 0:
        df = df.sort_values(by="pct_jovenes", ascending=True)
        df["ENTIDAD"] = df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        plt.figure(figsize=(6.8, 2.0))
        plt.barh(df["ENTIDAD"], df["pct_jovenes"], color="#10B981")
        plt.title(
            f"Top 5 Entidades: Mayor % de Jóvenes (18-19 años) -"
            f" {formatear_corte(corte)}",
            fontsize=9,
            fontweight="bold",
            color="#4A2E7A",
        )
        plt.xlabel("Porcentaje respecto al Padrón Estatal (%)", fontsize=8)
        plt.xticks(fontsize=7.5)
        plt.yticks(fontsize=7.5)
        plt.tight_layout()
        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=220)
        plt.close()
        buf.seek(0)
        return buf
  except Exception as e:
    print(f"Error en generar_grafico_top_jovenes: {e}")
  return None

def generar_grafico_top_mayores(corte):
  try:
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table'", conn
    )["name"].tolist()
    if "PE_RE" in tables:
      c_pm = col_dinamica(
          "PE_RE",
          ["65", "MAS", "PAD"],
          ["65_MAS", "PAD"],
          ["MAYOR", "PAD"],
          ["ADULTO", "PAD"],
          ["65", "PAD"],
          exclude=["LIS", "LNE", "HOMBRE", "MUJER", "BINARIO", "NB"],
          default=None,
      )
      if not c_pm:
        return None
      c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
      c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
      c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])

      corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
      q = f"""
                SELECT CLAVE_ENTIDAD, 
                       (SUM(CAST({c_pm} AS REAL)) * 100.0 / 
                        NULLIF((SELECT SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) FROM PE_SEX S WHERE TRIM(REPLACE(REPLACE(S.FECHA_CORTE, '-', ''), '_', '')) = TRIM(REPLACE(REPLACE(PE_RE.FECHA_CORTE, '-', ''), '_', '')) AND S.CLAVE_ENTIDAD = PE_RE.CLAVE_ENTIDAD), 0)) AS pct_mayores
                FROM PE_RE WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ?
                GROUP BY CLAVE_ENTIDAD ORDER BY pct_mayores DESC LIMIT 5
            """
      df = pd.read_sql_query(q, conn, params=[corte_limpio])
      if not df.empty and df["pct_mayores"].sum() > 0:
        df = df.sort_values(by="pct_mayores", ascending=True)
        df["ENTIDAD"] = df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        plt.figure(figsize=(6.8, 2.0))
        plt.barh(df["ENTIDAD"], df["pct_mayores"], color="#F59E0B")
        plt.title(
            f"Top 5 Entidades: Mayor % de Adultos Mayores (65+ años) -"
            f" {formatear_corte(corte)}",
            fontsize=9,
            fontweight="bold",
            color="#4A2E7A",
        )
        plt.xlabel("Porcentaje respecto al Padrón Estatal (%)", fontsize=8)
        plt.xticks(fontsize=7.5)
        plt.yticks(fontsize=7.5)
        plt.tight_layout()
        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=220)
        plt.close()
        buf.seek(0)
        return buf
  except Exception as e:
    print(f"Error en generar_grafico_top_mayores: {e}")
  return None

def generar_grafico_top_extranjero(corte):
  try:
    c_pnat = col_dinamica("PE_EO", ["NATIVO", "PAD"], ["NATIVO", "PE"], ["NAT", "PAD"])
    c_pfor = col_dinamica("PE_EO", ["FORANEO", "PAD"], ["FORANEO", "PE"], ["FOR", "PAD"])
    c_pnat_z = col_dinamica("PE_EO", ["NATURALIZADO", "PAD"], ["NATURALIZADO", "PE"], ["88", "PAD"])
    
    corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
    q = f"""
            SELECT CLAVE_ENTIDAD, 
                   (SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_pnat_z},0) AS REAL)) * 100.0 / 
                   NULLIF((SELECT SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_pnat_z},0) AS REAL)) FROM PE_EO WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_MUNICIPIO = 0), 0)) AS pct_ext
            FROM PE_EO WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_MUNICIPIO = 0
            GROUP BY CLAVE_ENTIDAD ORDER BY pct_ext DESC LIMIT 5
        """
    df = pd.read_sql_query(q, conn, params=[corte_limpio, corte_limpio])
    if df.empty:
      return None
    df = df.sort_values(by="pct_ext", ascending=True)
    df["ENTIDAD"] = df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)

    plt.figure(figsize=(6.8, 2.0))
    plt.barh(df["ENTIDAD"], df["pct_ext"], color="#8C62B6")
    plt.title(
        f"Top 5 Entidades: Mayor % de Padrón en el Extranjero (ID 0) -"
        f" {formatear_corte(corte)}",
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
    )
    plt.xlabel(
        "Participación Porcentual Nacional en el Extranjero (%)", fontsize=8
    )
    plt.xticks(fontsize=7.5)
    plt.yticks(fontsize=7.5)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=220)
    plt.close()
    buf.seek(0)
    return buf
  except Exception as e:
    print(f"Error en generar_grafico_top_extranjero: {e}")
  return None

def generar_grafico_distritos_foraneos(corte):
  try:
    c_pnat = col_dinamica("PE_EO", ["NATIVO", "PAD"], ["NATIVO", "PE"], ["NAT", "PAD"])
    c_pfor = col_dinamica("PE_EO", ["FORANEO", "PAD"], ["FORANEO", "PE"], ["FOR", "PAD"])
    c_p88 = col_dinamica("PE_EO", ["NATURALIZADO", "PAD"], ["NATURALIZADO", "PE"], ["88", "PAD"])
    c_p87 = col_dinamica("PE_EO", ["HIJO", "PAD"], ["HIJO", "PE"], ["MEXICANO", "PAD"])

    corte_limpio = str(corte).strip().replace("-", "").replace("_", "")
    q = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   (SUM(CAST(COALESCE({c_pfor},0) AS REAL)) * 100.0 / 
                    NULLIF(SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_p88},0) + COALESCE({c_p87},0) AS REAL)), 0)) AS pct_foraneo
            FROM PE_EO WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO ORDER BY pct_foraneo DESC LIMIT 10
        """
    df = pd.read_sql_query(q, conn, params=[corte_limpio])
    if df.empty:
      return None

    df = df.sort_values(by="pct_foraneo", ascending=True)
    df["etiqueta"] = (
        df["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
        + " - D."
        + df["CLAVE_DISTRITO"].astype(str)
    )

    plt.figure(figsize=(6.8, 2.4))
    plt.barh(df["etiqueta"], df["pct_foraneo"], color="#3B82F6")
    plt.xlim(0, 100)
    plt.title(
        "Top 10 Distritos con Mayor Población Foránea (%)",
        fontsize=9,
        fontweight="bold",
        color="#4A2E7A",
    )
    plt.xlabel("Porcentaje de Población Foránea (%)", fontsize=8)
    plt.xticks(fontsize=7.5)
    plt.yticks(fontsize=7.5)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=220)
    plt.close()
    buf.seek(0)
    return buf
  except Exception as e:
    print(f"Error en generar_grafico_distritos_foraneos: {e}")
  return None

def generar_analisis_distrital_texto(corte_rec, corte_bas):
  try:
    if not corte_bas:
      return ""
    c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
    c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
    c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])

    corte_rec_limpio = str(corte_rec).strip().replace("-", "").replace("_", "")
    corte_bas_limpio = str(corte_bas).strip().replace("-", "").replace("_", "")

    q_rec = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_REC
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    q_bas = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_BAS
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q_rec, conn, params=[corte_rec_limpio])
    df_bas = pd.read_sql_query(q_bas, conn, params=[corte_bas_limpio])
    df_merged = pd.merge(
        df_rec,
        df_bas,
        on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO"],
        suffixes=("_rec", "_bas"),
    )
    df_merged["pct"] = (
        (df_merged["PADRON_REC"] - df_merged["PADRON_BAS"])
        / df_merged["PADRON_BAS"]
    ) * 100

    lentos = df_merged[df_merged["pct"] <= 1.0]
    if lentos.empty:
      return ""

    resumen = []
    for ent, grupo in lentos.groupby("CLAVE_ENTIDAD"):
      tot_ent = df_merged[df_merged["CLAVE_ENTIDAD"] == ent][
          "CLAVE_DISTRITO"
      ].nunique()
      afectados = grupo["CLAVE_DISTRITO"].nunique()
      nom_ent = CATALOGO_ENTIDADES.get(int(ent), "ESTADO")
      resumen.append((nom_ent, afectados, tot_ent))

    resumen.sort(key=lambda x: x[1], reverse=True)
    textos = [
        f"<b>{nom_ent}</b> ({afec} de {tot} distritos)"
        for nom_ent, afec, tot in resumen[:3]
    ]

    return (
        "<b>Análisis de Rezago Operativo (Crecimiento ≤ 1.0%):</b> Se identifican"
        f" demarcaciones en situación de bajo dinamismo en {'; '.join(textos)}."
        " Estas zonas requieren seguimiento prioritario en campañas especiales"
        " de credencialización y depuración cartográfica."
    )
  except Exception:
    pass
  return ""

def generar_analisis_positivo_texto(corte_rec, corte_bas):
  try:
    if not corte_bas:
      return ""
    c_hp = col_dinamica("PE_SEX", ["HOMBRE", "PAD"], ["HOMBRE", "PE"])
    c_mp = col_dinamica("PE_SEX", ["MUJER", "PAD"], ["MUJER", "PE"])
    c_nbp = col_dinamica("PE_SEX", ["BINARIO", "PAD"], ["NB", "PAD"], ["NO_BINARIO", "PAD"])

    corte_rec_limpio = str(corte_rec).strip().replace("-", "").replace("_", "")
    corte_bas_limpio = str(corte_bas).strip().replace("-", "").replace("_", "")

    q_rec = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_REC
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    q_bas = f"""
            SELECT CLAVE_ENTIDAD, CLAVE_DISTRITO,
                   SUM(CAST({c_hp} AS REAL) + CAST({c_mp} AS REAL) + CAST({c_nbp} AS REAL)) AS PADRON_BAS
            FROM PE_SEX WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_DISTRITO != 0
            GROUP BY CLAVE_ENTIDAD, CLAVE_DISTRITO
        """
    df_rec = pd.read_sql_query(q_rec, conn, params=[corte_rec_limpio])
    df_bas = pd.read_sql_query(q_bas, conn, params=[corte_bas_limpio])
    df_merged = pd.merge(
        df_rec,
        df_bas,
        on=["CLAVE_ENTIDAD", "CLAVE_DISTRITO"],
        suffixes=("_rec", "_bas"),
    )
    df_merged["pct"] = (
        (df_merged["PADRON_REC"] - df_merged["PADRON_BAS"])
        / df_merged["PADRON_BAS"]
    ) * 100

    acelerados = df_merged[df_merged["pct"] >= 10.0]
    if acelerados.empty:
      return ""

    resumen = []
    for ent, grupo in acelerados.groupby("CLAVE_ENTIDAD"):
      altos = grupo["CLAVE_DISTRITO"].nunique()
      nom_ent = CATALOGO_ENTIDADES.get(int(ent), "ESTADO")
      resumen.append((nom_ent, altos))

    resumen.sort(key=lambda x: x[1], reverse=True)
    textos = [f"<b>{nom_ent}</b> ({altos} distritos)" for nom_ent, altos in resumen[:3]]

    return (
        "<b>Análisis de Expansión Territorial (Crecimiento ≥ 10.0%):</b>"
        " Destacan polos con marcada atracción demográfica y desarrollo urbano"
        f" en entidades como {'; '.join(textos)}, concentrando la mayor demanda"
        " sobre la capacidad instalada de Módulos de Atención Ciudadana."
    )
  except Exception:
    pass
  return ""

def generar_analisis_foraneos_texto(corte_rec):
  try:
    c_pnat = col_dinamica("PE_EO", ["NATIVO", "PAD"], ["NATIVO", "PE"], ["NAT", "PAD"])
    c_pfor = col_dinamica("PE_EO", ["FORANEO", "PAD"], ["FORANEO", "PE"], ["FOR", "PAD"])
    c_p88 = col_dinamica("PE_EO", ["NATURALIZADO", "PAD"], ["NATURALIZADO", "PE"], ["88", "PAD"])
    c_p87 = col_dinamica("PE_EO", ["HIJO", "PAD"], ["HIJO", "PE"], ["MEXICANO", "PAD"])

    corte_limpio = str(corte_rec).strip().replace("-", "").replace("_", "")
    q_ent = f"""
            SELECT CLAVE_ENTIDAD,
                   SUM(CAST(COALESCE({c_pfor},0) AS REAL)) * 100.0 / 
                   NULLIF(SUM(CAST(COALESCE({c_pnat},0) + COALESCE({c_pfor},0) + COALESCE({c_p88},0) + COALESCE({c_p87},0) AS REAL)), 0) AS pct_foraneo
            FROM PE_EO WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = ? AND CLAVE_MUNICIPIO != 0
            GROUP BY CLAVE_ENTIDAD ORDER BY pct_foraneo DESC
        """
    df_ent = pd.read_sql_query(q_ent, conn, params=[corte_limpio])
    if df_ent.empty:
      return ""

    df_ent["ENTIDAD"] = df_ent["CLAVE_ENTIDAD"].map(CATALOGO_ENTIDADES)
    top_max = df_ent.head(3)
    top_min = df_ent.tail(3).sort_values(by="pct_foraneo", ascending=True)

    max_str = ", ".join([
        f"<b>{row['ENTIDAD']}</b> ({row['pct_foraneo']:.1f}%)"
        for _, row in top_max.iterrows()
    ])
    min_str = ", ".join([
        f"<b>{row['ENTIDAD']}</b> ({row['pct_foraneo']:.1f}%)"
        for _, row in top_min.iterrows()
    ])

    return (
        "<b>Dinámica de Población Foránea (Nacional):</b> Las entidades con"
        f" mayor atracción de población foránea son {max_str}; en contraste,"
        f" las de menor presencia de foráneos son {min_str} (estabilidad y"
        " arraigo de población nativa)."
    )
  except Exception:
    pass
  return ""

# ==============================================================================
# REPORTE PDF EJECUTIVO
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
    cve_dist,
    alcance_tipo,
):
  buffer = BytesIO()
  doc = SimpleDocTemplate(
      buffer,
      pagesize=letter,
      rightMargin=36,
      leftMargin=36,
      topMargin=24,
      bottomMargin=24,
  )
  story = []

  title_style = ParagraphStyle(
      "TitleStyle",
      parent=styles_pdf["Heading1"],
      fontSize=11,
      textColor=ine_dark,
      spaceAfter=1,
      fontName="Helvetica-Bold",
      alignment=1,
  )
  subtitle_style = ParagraphStyle(
      "SubTitleStyle",
      parent=styles_pdf["Normal"],
      fontSize=7.5,
      textColor=colors.HexColor("#64748B"),
      spaceAfter=3,
      fontName="Helvetica",
      alignment=1,
  )
  heading_style = ParagraphStyle(
      "HeadingStyle",
      parent=styles_pdf["Heading2"],
      fontSize=8.5,
      textColor=ine_dark,
      spaceBefore=4,
      spaceAfter=2,
      fontName="Helvetica-Bold",
  )
  body_style = ParagraphStyle(
      "BodyStyle",
      parent=styles_pdf["Normal"],
      fontSize=7.3,
      textColor=colors.HexColor("#334155"),
      spaceAfter=3,
      leading=9.8,
      fontName="Helvetica",
      alignment=4,
  )
  warning_style = ParagraphStyle(
      "WarningStyle",
      parent=styles_pdf["Normal"],
      fontSize=6.8,
      textColor=colors.HexColor("#B91C1C"),
      spaceAfter=3,
      leading=8.5,
      fontName="Helvetica-Oblique",
      alignment=4,
  )
  footer_style = ParagraphStyle(
      "FooterStyle",
      parent=styles_pdf["Normal"],
      fontSize=6.5,
      textColor=colors.HexColor("#64748B"),
      leading=8,
      fontName="Helvetica-Oblique",
      alignment=1,
  )
  sign_style = ParagraphStyle(
      "SignStyle",
      parent=styles_pdf["Normal"],
      fontSize=8.5,
      textColor=ine_dark,
      alignment=2,
      fontName="Helvetica-Oblique",
      spaceBefore=2,
  )

  if LOGO_PATH.exists():
    img_logo = Image(str(LOGO_PATH), width=100, height=28)
    header_table = Table(
        [[
            img_logo,
            Paragraph(
                "<b>INSTITUTO NACIONAL ELECTORAL</b><br/><font size=6.5"
                " color='#5C3A92'>Dirección Ejecutiva del Registro Federal de"
                " Electores</font>",
                ParagraphStyle(
                    "HText",
                    parent=styles_pdf["Normal"],
                    fontSize=7.5,
                    leading=9,
                    alignment=1,
                ),
            ),
        ]],
        colWidths=[110, 426],
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

  story.append(Paragraph("Reporte Ejecutivo de Situación Registral", title_style))
  story.append(
      Paragraph(
          f"<b>Ámbito Geográfico:</b> {titulo_alcance} | {desc_cortes}",
          subtitle_style,
      )
  )
  story.append(
      HRFlowable(width="100%", thickness=1, color=ine_purple, spaceAfter=2)
  )

  story.append(
      Paragraph(
          "<b>Nota Metodológica:</b> Para mantener coherencia distrital y"
          " censal en análisis comparativo, se recomienda contrastar cortes que"
          " compartan el marco geográfico posterior a la distritación 2023.",
          warning_style,
      )
  )

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
      f" <b>{l1:,.0f}</b> personas ({dif_l:+,.0f} personas, {pct_l:+.2f}%). La"
      f" cobertura registral actual se sitúa en <b>{cob1:.2f}%</b>."
  )
  story.append(Paragraph(txt_totales, body_style))

  story.append(
      Paragraph(
          "2. Estructura de Género y Componentes de Origen", heading_style
      )
  )
  h_p1, h_l1, m_p1, m_l1 = (
      g_data.get("h_p", 0),
      g_data.get("h_l", 0),
      g_data.get("m_p", 0),
      g_data.get("m_l", 0),
  )
  nb_p1, nb_l1 = g_data.get("nb_p", 0), g_data.get("nb_l", 0)
  nat_p, for_p = dem_data.get("nat_p", 0), dem_data.get("for_p", 0)

  txt_demog = (
      f"<b>Género:</b> Hombres (<b>{h_p1:,.0f}</b> en Padrón,"
      f" <b>{(h_l1/h_p1*100) if h_p1>0 else 0:.2f}%</b> cobertura); Mujeres"
      f" (<b>{m_p1:,.0f}</b> en Padrón,"
      f" <b>{(m_l1/m_p1*100) if m_p1>0 else 0:.2f}%</b> cobertura); No Binarios"
      f" (<b>{nb_p1:,.0f}</b> personas).<br/><b>Composición de Origen:</b>"
      f" Nativos (<b>{nat_p:,.0f}</b> |"
      f" <b>{(nat_p/p1*100) if p1>0 else 0:.2f}%</b>) y Población Foránea"
      f" (<b>{for_p:,.0f}</b> |"
      f" <b>{(for_p/p1*100) if p1>0 else 0:.2f}%</b>)."
  )
  story.append(Paragraph(txt_demog, body_style))

  story.append(
      Paragraph(
          "3. Posicionamiento Territorial Comparativo (Focus + Context)",
          heading_style,
      )
  )

  img_vol = (
      generar_grafico_volumen_pdf(corte_rec, cve_ent, cve_dist)
      if cve_ent
      else None
  )
  img_fc = generar_grafico_posicionamiento_pdf(
      corte=corte_rec,
      alcance_tipo=alcance_tipo,
      cve_ent=cve_ent,
      cve_dist=cve_dist,
      modo_comp=bool(corte_bas),
      corte_base_comp=corte_bas,
  )

  if img_vol and img_fc:
    t_duo = Table(
        [[
            Image(img_vol, width=265, height=130),
            Image(img_fc, width=265, height=130),
        ]],
        colWidths=[268, 268],
    )
    t_duo.setStyle(
        TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(t_duo)
    story.append(Spacer(1, 4))
  elif img_fc:
    t_single = Table([[Image(img_fc, width=440, height=130)]], colWidths=[536])
    t_single.setStyle(
        TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    story.append(t_single)
    story.append(Spacer(1, 4))

  story.append(
      Paragraph(
          "4. Radiografía Demográfica y Movilidad Foránea", heading_style
      )
  )

  def agregar_imagen_centrada(buf_img, w=430, h=105):
    if buf_img:
      t_img = Table([[Image(buf_img, width=w, height=h)]], colWidths=[536])
      t_img.setStyle(
          TableStyle([
              ("ALIGN", (0, 0), (-1, -1), "CENTER"),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("TOPPADDING", (0, 0), (-1, -1), 1),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
          ])
      )
      story.append(t_img)

  img_jov = generar_grafico_top_jovenes(corte_rec)
  agregar_imagen_centrada(img_jov, 430, 100)

  img_may = generar_grafico_top_mayores(corte_rec)
  agregar_imagen_centrada(img_may, 430, 100)

  img_ext = generar_grafico_top_extranjero(corte_rec)
  agregar_imagen_centrada(img_ext, 430, 100)

  img_for_dist = generar_grafico_distritos_foraneos(corte_rec)
  agregar_imagen_centrada(img_for_dist, 430, 115)

  txt_for = generar_analisis_foraneos_texto(corte_rec)
  if txt_for:
    story.append(Paragraph(txt_for, body_style))
    story.append(Spacer(1, 3))

  if corte_bas:
    story.append(PageBreak())
    story.append(
        Paragraph(
            "5. Diagnóstico de Extremos Operativos: Rezagos y Polos de"
            " Expansión",
            heading_style,
        )
    )

    img_menor_1 = generar_grafico_distritos_menor_1(corte_rec, corte_bas)
    if img_menor_1:
      agregar_imagen_centrada(img_menor_1, 450, 140)

    txt_diag_lentos = generar_analisis_distrital_texto(corte_rec, corte_bas)
    if txt_diag_lentos:
      story.append(Paragraph(txt_diag_lentos, body_style))
      story.append(Spacer(1, 3))

    img_mayor_10 = generar_grafico_distritos_mayor_10(corte_rec, corte_bas)
    if img_mayor_10:
      agregar_imagen_centrada(img_mayor_10, 450, 140)

    txt_diag_rapidos = generar_analisis_positivo_texto(corte_rec, corte_bas)
    if txt_diag_rapidos:
      story.append(Paragraph(txt_diag_rapidos, body_style))
      story.append(Spacer(1, 3))

  story.append(Spacer(1, 4))
  story.append(
      HRFlowable(
          width="100%",
          thickness=0.6,
          color=colors.HexColor("#CBD5E1"),
          spaceAfter=3,
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

  doc.build(story, canvasmaker=NumberedCanvas)
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
        format_func=lambda x: f"{x:02d} {CATALOGO_ENTIDADES[x]}",
        index=14,
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
        try:
            q_muns = f"""
                SELECT CLAVE_MUNICIPIO, MAX(NOMBRE_DE_MUNICIPIO) AS NOMBRE_MUNICIPIO 
                FROM PE_EO 
                WHERE CLAVE_ENTIDAD = {cve} 
                  AND TRIM(FECHA_CORTE) = TRIM('{corte_reciente}')
                  AND CLAVE_MUNICIPIO != 0
                  AND NOMBRE_DE_MUNICIPIO IS NOT NULL 
                  AND TRIM(NOMBRE_DE_MUNICIPIO) != ''
                  AND TRIM(NOMBRE_DE_MUNICIPIO) != '0'
                  AND UPPER(NOMBRE_DE_MUNICIPIO) NOT LIKE '%ACTUALIZACION%'
                GROUP BY CLAVE_MUNICIPIO 
                ORDER BY CLAVE_MUNICIPIO ASC
            """
            df_muns = pd.read_sql_query(q_muns, conn)

            if (
                df_muns.empty
                or df_muns["NOMBRE_MUNICIPIO"].str.strip().eq("").all()
            ):
                q_muns_fallback = f"""
                    SELECT CLAVE_MUNICIPIO, MAX(NOMBRE_DE_MUNICIPIO) AS NOMBRE_MUNICIPIO 
                    FROM PE_EO 
                    WHERE CLAVE_ENTIDAD = {cve} 
                      AND CLAVE_MUNICIPIO != 0
                      AND NOMBRE_DE_MUNICIPIO IS NOT NULL 
                      AND TRIM(NOMBRE_DE_MUNICIPIO) != ''
                      AND TRIM(NOMBRE_DE_MUNICIPIO) != '0'
                      AND UPPER(NOMBRE_DE_MUNICIPIO) NOT LIKE '%ACTUALIZACION%'
                      AND FECHA_CORTE NOT BETWEEN '20230101' AND '20230630'
                    GROUP BY CLAVE_MUNICIPIO 
                    ORDER BY CLAVE_MUNICIPIO ASC
                """
                df_muns = pd.read_sql_query(q_muns_fallback, conn)

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
                else f"{int(x):03d} {dict_nombres.get(int(x), 'Desconocido')}"
            ),
            key="sel_municipio",
        )
        sql_filtro_geo = (
            f"AND CLAVE_ENTIDAD = {cve} AND CLAVE_MUNICIPIO = {mun_elegido_val}"
        )
        nombre_header = (
            f"{nom_ent} [{dict_nombres.get(int(mun_elegido_val), f'Municipio ID {mun_elegido_val}')}]"
        )

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
        st.metric("Padrón", f"{h_padron_1:,}", calc_var_str(dh_p, h_padron_2), delta_color="normal" if dh_p >= 0 else "inverse")
        st.metric("Lista Nominal", f"{h_lista_1:,}", calc_var_str(dh_l, h_lista_2), delta_color="normal" if dh_l >= 0 else "inverse")
        st.text(f"Cobertura: {hcob_1:.2f}%")
    with gh2:
        st.markdown("**👩 Mujeres**")
        st.metric("Padrón", f"{m_padron_1:,}", calc_var_str(dm_p, m_padron_2), delta_color="normal" if dm_p >= 0 else "inverse")
        st.metric("Lista Nominal", f"{m_lista_1:,}", calc_var_str(dm_l, m_lista_2), delta_color="normal" if dm_l >= 0 else "inverse")
        st.text(f"Cobertura: {mcob_1:.2f}%")
    with gh3:
        st.markdown("**⚧ No Binarios**")
        st.metric("Padrón", f"{nb_padron_1:,}", calc_var_str(dnb_p, nb_padron_2), delta_color="normal" if dnb_p >= 0 else "inverse")
        st.metric("Lista Nominal", f"{nb_lista_1:,}", calc_var_str(dnb_l, nb_lista_2), delta_color="normal" if dnb_l >= 0 else "inverse")
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

if "Nacional" in alcance or cve_entidad_activa:
    st.markdown("---")
    with st.expander("📍 Posicionamiento y Contexto Geográfico Comparativo", expanded=True):
        renderizar_grafica_posicionamiento(
            corte=corte_reciente,
            alcance_tipo=alcance,
            cve_ent=cve_entidad_activa,
            cve_dist=cve_distrito_activo,
            modo_comp=(modo == "Comparar con Periodo Previo"),
            corte_base_comp=corte_base,
        )

st.markdown("---")
st.markdown("### Perspectiva Territorial, Movilidad Nacional y Ciudadanía en el Extranjero")

tables_db_sidebar = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)["name"].tolist()
target_eo = "PE_EO" if "PE_EO" in tables_db_sidebar else "PE_SEX"

tab_jovenes, tab_mayores, tab_origen = st.tabs([
    "🌱 Jóvenes de 18 y 19 Años",
    "👴 Población de 65 años y Más",
    "📋 Comprobación de Origen y Movilidad (PE_EO)",
])

pjov_1, ljov_1, pjov_2, ljov_2 = 0, 0, 0, 0
pmay_1, lmay_1, pmay_2, lmay_2 = 0, 0, 0, 0
p_nat_1 = l_nat_1 = p_for_1 = l_for_1 = 0
p_87_1 = l_87_1 = p_88_1 = l_88_1 = 0

pjov_1, ljov_1 = consultar_datos_jovenes_seguro(corte_reciente, sql_filtro_geo)
if modo == "Comparar con Periodo Previo" and corte_base:
    pjov_2, ljov_2 = consultar_datos_jovenes_seguro(corte_base, sql_filtro_geo)

pmay_1, lmay_1 = consultar_datos_mayores_seguro(corte_reciente, sql_filtro_geo)
if modo == "Comparar con Periodo Previo" and corte_base:
    pmay_2, lmay_2 = consultar_datos_mayores_seguro(corte_base, sql_filtro_geo)

with tab_jovenes:
    cobjov_1 = (ljov_1 / pjov_1 * 100) if pjov_1 > 0 else 0
    if modo == "Comparar con Periodo Previo" and corte_base:
        dp_jov = pjov_1 - pjov_2
        dl_jov = ljov_1 - ljov_2
        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Padrón (18-19 años)", f"{pjov_1:,}", calc_var_str(dp_jov, pjov_2), delta_color="normal" if dp_jov >= 0 else "inverse")
        j2.metric("Lista Nominal (18-19 años)", f"{ljov_1:,}", calc_var_str(dl_jov, ljov_2), delta_color="normal" if dl_jov >= 0 else "inverse")
        j3.metric("Cobertura Registral", f"{cobjov_1:.2f}%")
        j4.metric("Peso en Padrón / Lista", f"{(pjov_1/p1*100) if p1>0 else 0:.2f}% / {(ljov_1/l1*100) if l1>0 else 0:.2f}%")
    else:
        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Padrón (18-19 años)", f"{pjov_1:,}")
        j2.metric("Lista Nominal (18-19 años)", f"{ljov_1:,}")
        j3.metric("Cobertura Registral", f"{cobjov_1:.2f}%")
        j4.metric("Peso en Padrón / Lista", f"{(pjov_1/p1*100) if p1>0 else 0:.2f}% / {(ljov_1/l1*100) if l1>0 else 0:.2f}%")

with tab_mayores:
    cobmay_1 = (lmay_1 / pmay_1 * 100) if pmay_1 > 0 else 0
    if modo == "Comparar con Periodo Previo" and corte_base:
        dp_may = pmay_1 - pmay_2
        dl_may = lmay_1 - lmay_2
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Padrón (65 años y más)", f"{pmay_1:,}", calc_var_str(dp_may, pmay_2), delta_color="normal" if dp_may >= 0 else "inverse")
        m2.metric("Lista Nominal (65 años y más)", f"{lmay_1:,}", calc_var_str(dl_may, lmay_2), delta_color="normal" if dl_may >= 0 else "inverse")
        m3.metric("Cobertura Registral", f"{cobmay_1:.2f}%")
        m4.metric("Peso en Padrón / Lista", f"{(pmay_1/p1*100) if p1>0 else 0:.2f}% / {(lmay_1/l1*100) if l1>0 else 0:.2f}%")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Padrón (65 años y más)", f"{pmay_1:,}")
        m2.metric("Lista Nominal (65 años y más)", f"{lmay_1:,}")
        m3.metric("Cobertura Registral", f"{cobmay_1:.2f}%")
        m4.metric("Peso en Padrón / Lista", f"{(pmay_1/p1*100) if p1>0 else 0:.2f}% / {(lmay_1/l1*100) if l1>0 else 0:.2f}%")

with tab_origen:
    st.markdown("#### Comprobación de Origen y Movilidad (Suma emparejada al 100% con el Padrón)")
    if target_eo:
        try:
            c_pnat = col_dinamica(target_eo, ["NATIVO", "PAD"], ["NATIVO", "PE"], ["NAT", "PAD"], ["NATIVO"], exclude=["LIS", "LNE"])
            c_lnat = col_dinamica(target_eo, ["NATIVO", "LIS"], ["NATIVO", "LNE"], ["NAT", "LIS"], ["NATIVO"], exclude=["PAD", "PE"])
            c_pfor = col_dinamica(target_eo, ["FORANEO", "PAD"], ["FORANEO", "PE"], ["FOR", "PAD"], ["FORANEO"], exclude=["LIS", "LNE"])
            c_lfor = col_dinamica(target_eo, ["FORANEO", "LIS"], ["FORANEO", "LNE"], ["FOR", "LIS"], ["FORANEO"], exclude=["PAD", "PE"])
            c_p87 = col_dinamica(target_eo, ["HIJO", "PAD"], ["HIJO", "PE"], ["MEXICANO", "PAD"], ["HIJO"], ["87"], exclude=["LIS", "LNE", "88", "NATURALIZADO"])
            c_l87 = col_dinamica(target_eo, ["HIJO", "LIS"], ["HIJO", "LNE"], ["MEXICANO", "LIS"], ["HIJO"], ["87"], exclude=["PAD", "PE", "88", "NATURALIZADO"])
            c_p88 = col_dinamica(target_eo, ["NATURALIZADO", "PAD"], ["NATURALIZADO", "PE"], ["88", "PAD"], ["NATURALIZADO"], ["88"], exclude=["LIS", "LNE", "87", "HIJO"])
            c_l88 = col_dinamica(target_eo, ["NATURALIZADO", "LIS"], ["NATURALIZADO", "LNE"], ["88", "LIS"], ["NATURALIZADO"], ["88"], exclude=["PAD", "PE", "87", "HIJO"])

            corte_reciente_limpio = str(corte_reciente).strip().replace("-", "").replace("_", "")
            q_eo1 = f"""
                SELECT 
                    COALESCE(SUM(CAST({c_pnat} AS REAL)), 0) AS p_nat, COALESCE(SUM(CAST({c_lnat} AS REAL)), 0) AS l_nat,
                    COALESCE(SUM(CAST({c_pfor} AS REAL)), 0) AS p_for, COALESCE(SUM(CAST({c_lfor} AS REAL)), 0) AS l_for,
                    COALESCE(SUM(CAST({c_p87} AS REAL)), 0) AS p_87, COALESCE(SUM(CAST({c_l87} AS REAL)), 0) AS l_87,
                    COALESCE(SUM(CAST({c_p88} AS REAL)), 0) AS p_88, COALESCE(SUM(CAST({c_l88} AS REAL)), 0) AS l_88
                FROM {target_eo}
                WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_reciente_limpio}' {sql_filtro_geo}
            """
            df_eo = pd.read_sql_query(q_eo1, conn)
            p_nat_1 = int(df_eo["p_nat"].iloc[0] if not df_eo.empty else 0)
            l_nat_1 = int(df_eo["l_nat"].iloc[0] if not df_eo.empty else 0)
            p_for_1 = int(df_eo["p_for"].iloc[0] if not df_eo.empty else 0)
            l_for_1 = int(df_eo["l_for"].iloc[0] if not df_eo.empty else 0)
            p_87_1 = int(df_eo["p_87"].iloc[0] if not df_eo.empty else 0)
            l_87_1 = int(df_eo["l_87"].iloc[0] if not df_eo.empty else 0)
            p_88_1 = int(df_eo["p_88"].iloc[0] if not df_eo.empty else 0)
            l_88_1 = int(df_eo["l_88"].iloc[0] if not df_eo.empty else 0)

            if modo == "Comparar con Periodo Previo" and corte_base:
                corte_base_limpio = str(corte_base).strip().replace("-", "").replace("_", "")
                q_eo2 = f"""
                    SELECT 
                        COALESCE(SUM(CAST({c_pnat} AS REAL)), 0) AS p_nat, COALESCE(SUM(CAST({c_lnat} AS REAL)), 0) AS l_nat,
                        COALESCE(SUM(CAST({c_pfor} AS REAL)), 0) AS p_for, COALESCE(SUM(CAST({c_lfor} AS REAL)), 0) AS l_for,
                        COALESCE(SUM(CAST({c_p87} AS REAL)), 0) AS p_87, COALESCE(SUM(CAST({c_l87} AS REAL)), 0) AS l_87,
                        COALESCE(SUM(CAST({c_p88} AS REAL)), 0) AS p_88, COALESCE(SUM(CAST({c_l88} AS REAL)), 0) AS l_88
                    FROM {target_eo}
                    WHERE TRIM(REPLACE(REPLACE(FECHA_CORTE, '-', ''), '_', '')) = '{corte_base_limpio}' {sql_filtro_geo}
                """
                df_eo2 = pd.read_sql_query(q_eo2, conn)
                p_nat_2 = int(df_eo2["p_nat"].iloc[0] if not df_eo2.empty else 0)
                l_nat_2 = int(df_eo2["l_nat"].iloc[0] if not df_eo2.empty else 0)
                p_for_2 = int(df_eo2["p_for"].iloc[0] if not df_eo2.empty else 0)
                l_for_2 = int(df_eo2["l_for"].iloc[0] if not df_eo2.empty else 0)
                p_87_2 = int(df_eo2["p_87"].iloc[0] if not df_eo2.empty else 0)
                l_87_2 = int(df_eo2["l_87"].iloc[0] if not df_eo2.empty else 0)
                p_88_2 = int(df_eo2["p_88"].iloc[0] if not df_eo2.empty else 0)
                l_88_2 = int(df_eo2["l_88"].iloc[0] if not df_eo2.empty else 0)

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

                    st.metric("Padrón Nativo", f"{p_nat_1:,}", f"{calc_var_str(dp_nat, p_nat_2)} | Estructura: {p_nat_pct:.2f}%", delta_color="normal" if dp_nat >= 0 else "inverse")
                    st.metric("Padrón Foráneo", f"{p_for_1:,}", f"{calc_var_str(dp_for, p_for_2)} | Estructura: {p_for_pct:.2f}%", delta_color="normal" if dp_for >= 0 else "inverse")
                    st.metric("Padrón Naturalizado (88)", f"{p_88_1:,}", f"{calc_var_str(dp_88, p_88_2)} | Estructura: {p_88_pct:.2f}%", delta_color="normal" if dp_88 >= 0 else "inverse")
                    st.metric("Padrón Hijos de Mex (87)", f"{p_87_1:,}", f"{calc_var_str(dp_87, p_87_2)} | Estructura: {p_87_pct:.2f}%", delta_color="normal" if dp_87 >= 0 else "inverse")
                else:
                    st.metric("Padrón Nativo", f"{p_nat_1:,}", f"{p_nat_pct:.2f}% del Padrón")
                    st.metric("Padrón Foráneo", f"{p_for_1:,}", f"{p_for_pct:.2f}% del Padrón")
                    st.metric("Padrón Naturalizado (88)", f"{p_88_1:,}", f"{p_88_pct:.2f}% del Padrón")
                    st.metric("Padrón Hijos de Mex (87)", f"{p_87_1:,}", f"{p_87_pct:.2f}% del Padrón")

            with col_o2:
                st.markdown("##### 📌 Lista Nominal por Origen")
                if modo == "Comparar con Periodo Previo" and corte_base:
                    dl_nat = l_nat_1 - l_nat_2
                    dl_for = l_for_1 - l_for_2
                    dl_88 = l_88_1 - l_88_2
                    dl_87 = l_87_1 - l_87_2

                    st.metric("Lista Nativa", f"{l_nat_1:,}", f"{calc_var_str(dl_nat, l_nat_2)} | Estructura: {l_nat_pct:.2f}%", delta_color="normal" if dl_nat >= 0 else "inverse")
                    st.metric("Lista Foránea", f"{l_for_1:,}", f"{calc_var_str(dl_for, l_for_2)} | Estructura: {l_for_pct:.2f}%", delta_color="normal" if dl_for >= 0 else "inverse")
                    st.metric("Lista Naturalizada (88)", f"{l_88_1:,}", f"{calc_var_str(dl_88, l_88_2)} | Estructura: {l_88_pct:.2f}%", delta_color="normal" if dl_88 >= 0 else "inverse")
                    st.metric("Lista Hijos de Mex (87)", f"{l_87_1:,}", f"{calc_var_str(dl_87, l_87_2)} | Estructura: {l_87_pct:.2f}%", delta_color="normal" if dl_87 >= 0 else "inverse")
                else:
                    st.metric("Lista Nativa", f"{l_nat_1:,}", f"{l_nat_pct:.2f}% de Lista")
                    st.metric("Lista Foránea", f"{l_for_1:,}", f"{l_for_pct:.2f}% de Lista")
                    st.metric("Lista Naturalizada (88)", f"{l_88_1:,}", f"{l_88_pct:.2f}% de Lista")
                    st.metric("Lista Hijos de Mex (87)", f"{l_87_1:,}", f"{l_87_pct:.2f}% de Lista")
        except Exception as e:
            st.error(f"🛑 Error en pestaña Origen: {e}")

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
  try:
    with st.spinner("Compilando reporte gráfico ejecutivo..."):
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
          cve_dist=cve_distrito_activo,
          alcance_tipo=alcance,
      )
    st.sidebar.download_button(
        label="⬇️ Descargar PDF Oficial",
        data=pdf_file,
        file_name=f"Reporte_Analitico_DERFE_{corte_reciente}.pdf",
        mime="application/pdf",
    )
    st.sidebar.success("✅ Reporte generado correctamente.")
  except Exception as err:
    st.sidebar.error(f"Error al generar el PDF: {err}")