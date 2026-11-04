"""App independiente: diagnóstico de una proyección de casillas externa.

Solo permite subir un archivo y compararlo contra la referencia. No contiene
ni consulta las tablas del PREP.
"""

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

import pandas as pd
import py7zr
import streamlit as st

import modulo_diagnostico as md

st.set_page_config(page_title="Proyección de casillas 2026 — Monitor LN", layout="wide")

DIR = Path(__file__).parent
DB_PATH = DIR / "diagnostico.db"
ARCHIVO_7Z = DIR / "diagnostico.7z"
LOCK = DIR / ".diagnostico.lock"
TMP = DIR / ".diagnostico_tmp"
META = DIR / ".diagnostico_ok.json"


def _bd_sana():
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("SELECT COUNT(*) FROM ref_secciones").fetchone()
        con.close()
        return True
    except Exception:
        return False


def _necesita_extraer():
    if not DB_PATH.exists() or not _bd_sana():
        return True
    try:
        info = json.loads(META.read_text(encoding="utf-8"))
        return not (info.get("mtime") == ARCHIVO_7Z.stat().st_mtime
                    and info.get("size") == ARCHIVO_7Z.stat().st_size)
    except Exception:
        return True


def _extraer():
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir()
    try:
        with py7zr.SevenZipFile(ARCHIVO_7Z, mode="r") as z:
            z.extractall(path=TMP)
        origen = TMP / "diagnostico.db"
        if not origen.exists():
            raise RuntimeError("diagnostico.db no apareció tras descomprimir")
        os.replace(origen, DB_PATH)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if ARCHIVO_7Z.exists() and _necesita_extraer():
    extrajo = False
    for _ in range(2):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            extrajo = True
            break
        except FileExistsError:
            if time.time() - LOCK.stat().st_mtime > 600:
                LOCK.unlink(missing_ok=True)
                continue
            for _ in range(120):
                if not LOCK.exists() and DB_PATH.exists() and _bd_sana():
                    break
                time.sleep(1)
            break
    if extrajo:
        try:
            _extraer()
            META.write_text(json.dumps({
                "mtime": ARCHIVO_7Z.stat().st_mtime,
                "size": ARCHIVO_7Z.stat().st_size,
            }), encoding="utf-8")
        except Exception as e:
            st.error(f"No se pudo preparar la base de referencia: {e}")
        finally:
            LOCK.unlink(missing_ok=True)

md.DB_PATH = str(DB_PATH)

st.title("Diagnóstico de proyección de casillas 2026")
st.caption(
    "Sube tu proyección y se compara contra la referencia construida con el 100% de las "
    "actas de Senadores 2024, los catálogos seccionales y el reseccionamiento. "
    "También puedes subir tu conformación PEF 2024 y generar la conformación 2026 "
    "con el corte oficial. Tu archivo se procesa en memoria y no se guarda en el servidor."
)

if not _bd_sana():
    st.error("No se encontró la base de referencia (diagnostico.7z).")
    st.stop()

cortes = md.listar_cortes()
entidades = md.catalogo_entidades()
if not cortes or not entidades:
    st.error("La base de referencia está vacía.")
    st.stop()

modo = st.radio(
    "¿Qué quieres hacer?",
    ["Diagnosticar mi proyección contra la referencia",
     "Generar la conformación 2026 desde mi PEF 2024"],
    horizontal=True,
)


def _selectores():
    col_ent, col_dist = st.columns([1.5, 1.1])
    with col_ent:
        claves = list(entidades.keys())
        ent = st.selectbox(
            "Entidad Federativa:", claves,
            index=claves.index(20) if 20 in claves else 0,
            format_func=lambda x: entidades.get(x, str(x)),
        )
    with col_dist:
        opciones = ["Todos"] + list(range(1, 33))
        dist = st.selectbox(
            "Distrito Federal:", opciones,
            format_func=lambda x: f"Distrito {x:02d}" if isinstance(x, int) else "Todos los Distritos",
        )
    return ent, dist


def _plantilla():
    with st.expander("Formato esperado y plantilla"):
        st.markdown(
            "El archivo debe traer una fila por casilla. Columnas obligatorias: "
            "**Sección** y **Tipo de Casilla**. Opcionales: Distrito, Municipio, Localidad, "
            "Cantidad Casilla, Lista Nominal y Padrón Electoral.\n\n"
            "Tipos aceptados: `B`, `C1`…`Cn`, `E1`…`En`, `S`, `E1C1`."
        )
        plantilla = pd.DataFrame([
            [3, 386, 37, 22, 1, "B", 656, 665],
            [3, 386, 37, 22, 2, "C1", 655, 665],
            [3, 386, 148, 1, 1, "E1", 182, 198],
        ], columns=md.COLUMNAS)
        st.download_button(
            "Descargar plantilla CSV",
            data=plantilla.to_csv(index=False).encode("utf-8-sig"),
            file_name="plantilla_proyeccion.csv",
            mime="text/csv",
        )


def _ambito(entidad, dist_num):
    nombre = entidades.get(entidad, "").split(" - ", 1)[-1]
    if dist_num:
        return f"Distrito {dist_num:02d} — {nombre}"
    return f"Estado de {nombre}"


if modo.startswith("Generar"):
    entidad, distrito = _selectores()
    dist_num = None if distrito == "Todos" else distrito
    _plantilla()
    archivo = st.file_uploader(
        "Sube tu conformación PEF 2024 (.xlsx, .xls o .csv)",
        type=["xlsx", "xls", "csv"])
    if archivo is None:
        st.info("Selecciona entidad y distrito, y sube tu conformación PEF 2024 "
                "para generar la versión 2026 con el corte oficial.")
        st.stop()
    try:
        crudo = md.leer_archivo(archivo)
        res = md.proyectar_conformacion(crudo, entidad, dist_num)
    except ValueError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        st.stop()

    totales = res["totales"]
    t24 = int(totales.loc[totales["Tipo"] == "Total", "Tu archivo (2024)"].iloc[0])
    t26 = int(totales.loc[totales["Tipo"] == "Total", "Conformación 2026"].iloc[0])
    ambito = _ambito(entidad, dist_num)

    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Casillas PEF 2024 (tu archivo)", f"{t24:,}")
    k2.metric("Casillas 2026 (proyección)", f"{t26:,}")
    k3.metric("Diferencia", f"{t26 - t24:+,}")
    k4.metric("Secciones", f"{res['n_secciones']:,}")
    st.caption(f"Ámbito: {ambito} | Corte oficial: {md.CORTE_OFICIAL}")

    for aviso in res["avisos"]:
        st.warning(aviso)

    st.subheader("Totales por tipo de casilla")
    st.dataframe(totales, width="stretch", hide_index=True)

    st.subheader("Cambios por sección")
    st.dataframe(res["resumen"], width="stretch", hide_index=True)
    with st.expander("Detalle por sección (2024 vs 2026)"):
        st.dataframe(res["secciones"], width="stretch", hide_index=True)

    nombre = f"conformacion_2026_{entidad}_" \
        f"{distrito if isinstance(distrito, int) else 'todas'}_{md.CORTE_OFICIAL}"
    col_x, col_p = st.columns(2)
    with col_x:
        st.download_button(
            "Descargar conformación 2026 (Excel)",
            data=md.conformacion_a_excel(res),
            file_name=f"{nombre}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    with col_p:
        st.download_button(
            "Descargar informe en PDF",
            data=md.generar_pdf_conformacion(res, ambito, getattr(archivo, "name", None)),
            file_name=f"{nombre}.pdf",
            mime="application/pdf",
        )

    st.subheader("Conformación 2026 (lista de casillas)")
    st.dataframe(res["salida"], width="stretch", hide_index=True)
    st.stop()

col_corte, col_ent, col_dist = st.columns([1.2, 1.5, 1.1])
with col_corte:
    corte = st.selectbox("Corte de padrón de referencia:", cortes, index=0)
with col_ent:
    claves = list(entidades.keys())
    entidad = st.selectbox(
        "Entidad Federativa:", claves,
        index=claves.index(20) if 20 in claves else 0,
        format_func=lambda x: entidades.get(x, str(x)),
    )
with col_dist:
    opciones = ["Todos"] + list(range(1, 33))
    distrito = st.selectbox(
        "Distrito Federal:", opciones,
        format_func=lambda x: f"Distrito {x:02d}" if isinstance(x, int) else "Todos los Distritos",
    )
dist_num = None if distrito == "Todos" else distrito

archivo = st.file_uploader("Sube tu proyección (.xlsx, .xls o .csv)", type=["xlsx", "xls", "csv"])
_plantilla()

if archivo is None:
    st.info("Selecciona entidad y distrito, y sube tu archivo para iniciar el diagnóstico.")
    st.stop()

try:
    crudo = md.leer_archivo(archivo)
    resultado = md.diagnosticar(crudo, entidad, dist_num, corte)
except ValueError as e:
    st.error(str(e))
    st.stop()
except Exception as e:
    st.error(f"No se pudo leer el archivo: {e}")
    st.stop()

totales = resultado["totales"]
total_archivo = int(totales.loc[totales["Tipo"] == "Total", "Archivo"].iloc[0])
total_ref = int(totales.loc[totales["Tipo"] == "Total", "Referencia"].iloc[0])

st.markdown("---")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Casillas en tu archivo", f"{total_archivo:,}")
k2.metric("Casillas de referencia", f"{total_ref:,}")
k3.metric("Diferencia", f"{total_ref - total_archivo:+,}")
k4.metric("Secciones comparadas", f"{resultado['n_ref']:,}")

ambito = _ambito(entidad, dist_num)
st.caption(f"Ámbito: {ambito} | Corte de referencia: {corte}")

info_corte = resultado["corte"]
if info_corte:
    if info_corte["corte"] != corte:
        st.warning(
            f"El padrón de tu archivo se parece más al corte **{info_corte['corte']}** "
            f"({info_corte['total_archivo']:,.0f} vs {info_corte['total_corte']:,.0f} electores; "
            f"diferencia {info_corte['diferencia']:+,.0f}). El corte seleccionado ({corte}) "
            f"difiere en {info_corte['diferencia_vigente']:+,.0f} electores, lo que puede "
            "cambiar casillas en secciones cercanas a un umbral de 750."
        )
    else:
        st.success(
            f"El padrón de tu archivo coincide con el corte {corte} "
            f"(diferencia {info_corte['diferencia']:+,.0f} electores)."
        )

for aviso in resultado["avisos"]:
    st.warning(aviso)

st.subheader("Totales por tipo de casilla")
st.dataframe(totales, width="stretch", hide_index=True)

st.subheader("Diagnóstico por sección")
pdf = md.generar_pdf(resultado, ambito, corte, getattr(archivo, "name", None))
if resultado["detalle"].empty:
    st.success("No se encontraron diferencias: tu proyección coincide con la referencia.")
    st.download_button(
        "Descargar diagnóstico en PDF",
        data=pdf,
        file_name=f"diagnostico_proyeccion_{entidad}_{distrito}_{corte}.pdf",
        mime="application/pdf",
    )
else:
    st.dataframe(resultado["resumen"], width="stretch", hide_index=True)
    causas = resultado["detalle"]["Causa"].unique().tolist()
    seleccion = st.multiselect("Filtrar por causa:", causas, default=causas)
    detalle = resultado["detalle"][resultado["detalle"]["Causa"].isin(seleccion)]
    st.dataframe(detalle, width="stretch", hide_index=True)
    col_pdf, col_csv = st.columns(2)
    with col_pdf:
        st.download_button(
            "Descargar diagnóstico en PDF",
            data=pdf,
            file_name=f"diagnostico_proyeccion_{entidad}_{distrito}_{corte}.pdf",
            mime="application/pdf",
            type="primary",
        )
    with col_csv:
        st.download_button(
            "Descargar diagnóstico en CSV",
            data=resultado["detalle"].to_csv(index=False).encode("utf-8-sig"),
            file_name=f"diagnostico_proyeccion_{entidad}_{distrito}_{corte}.csv",
            mime="text/csv",
        )

with st.expander("Cómo se calcula la referencia"):
    st.markdown(
        "- **B:** una por sección con padrón (ID 01).\n"
        "- **C:** techo(padrón ordinario / 750) − 1. El padrón ordinario excluye la parte "
        "que en 2024 correspondió a casillas extraordinarias.\n"
        "- **E:** se conservan las de 2024; si la parte rural creció, se aplica el piso de "
        "750 electores por casilla extraordinaria.\n"
        "- **S:** no se calculan; se copian de 2024.\n"
        "- **Matrices extintas:** cero casillas; sus electores pasan a las secciones nuevas.\n"
        "- **Casillas tipo A:** se excluyen de todos los cálculos.\n"
        "- La Lista Nominal no interviene en la proyección; solo se usa para el porcentaje "
        "de votación en la app principal."
    )
