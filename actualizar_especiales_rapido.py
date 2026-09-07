import sqlite3
import pandas as pd
from pathlib import Path
import re
import warnings

warnings.filterwarnings('ignore')

DIR_RAIZ = Path(__file__).resolve().parent
DIR_ORIGEN = DIR_RAIZ / "Por entidad de origen"
DB_PATH = DIR_RAIZ / "derfe_web.db"

print("=" * 70)
print("PROCESANDO CLAVES 87 Y 88 POR DISTRITO (FORMATO UNIVERSAL)")
print("=" * 70)

conn = sqlite3.connect(str(DB_PATH))

# Preparar tabla limpia
conn.execute("DROP TABLE IF EXISTS derfe_especiales")
conn.execute("""
    CREATE TABLE derfe_especiales (
        corte TEXT,
        clave_entidad INTEGER,
        distrito INTEGER,
        pe_87 INTEGER,
        pe_88 INTEGER,
        ln_87 INTEGER,
        ln_88 INTEGER
    )
""")

todos_archivos = sorted(list(DIR_ORIGEN.glob("*.xlsx")) + list(DIR_ORIGEN.glob("*.csv")), reverse=True)

# Procesar los hitos principales y los 25 cortes más recientes
archivos_a_procesar = []
for a in todos_archivos:
    nom = a.name.upper()
    m = re.search(r'(\d{8})', nom)
    corte_id = m.group(1) if m else nom
    if any(h in nom for h in ["PJF", "0206", "2024", "2025", "2026"]) or len(archivos_a_procesar) < 25:
        archivos_a_procesar.append((corte_id, a))

print(f"Total archivos seleccionados: {len(archivos_a_procesar)}\n")

for corte_id, arch in archivos_a_procesar:
    if arch.stat().st_size < 15000:
        continue

    print(f"Procesando: {corte_id} ({arch.name})...", end=" ", flush=True)
    try:
        if arch.suffix.lower() == ".xlsx":
            # Leemos encabezado
            head = pd.read_excel(arch, nrows=1)
            mapa_cols = {c: re.sub(r'[\s\n_]+', '', str(c)).upper() for c in head.columns}

            # Localizar columnas por nombre normalizado
            col_ent = next((orig for orig, norm in mapa_cols.items() if norm in ['CLAVEENTIDAD', 'ENTIDAD', 'CVEENT']), None)
            col_dto = next((orig for orig, norm in mapa_cols.items() if norm in ['CLAVEDISTRITO', 'DISTRITO', 'DTO']), None)
            col_p87 = next((orig for orig, norm in mapa_cols.items() if norm in ['PAD87', 'PADRON87', 'PE87']), None)
            col_p88 = next((orig for orig, norm in mapa_cols.items() if norm in ['PAD88', 'PADRON88', 'PE88']), None)
            col_l87 = next((orig for orig, norm in mapa_cols.items() if norm in ['LN87', 'LISTA87']), None)
            col_l88 = next((orig for orig, norm in mapa_cols.items() if norm in ['LN88', 'LISTA88']), None)

            if not (col_ent and col_dto and col_p87 and col_p88):
                print("⚠️ No coincidieron columnas.")
                continue

            cols_cargar = [col_ent, col_dto, col_p87, col_p88]
            if col_l87: cols_cargar.append(col_l87)
            if col_l88: cols_cargar.append(col_l88)

            df = pd.read_excel(arch, usecols=cols_cargar)
        else:
            sep = '|' if '|' in open(arch, 'r', encoding='latin-1').readline() else ','
            head = pd.read_csv(arch, sep=sep, encoding='latin-1', nrows=1)
            mapa_cols = {c: re.sub(r'[\s\n_]+', '', str(c)).upper() for c in head.columns}

            col_ent = next((orig for orig, norm in mapa_cols.items() if norm in ['CLAVEENTIDAD', 'ENTIDAD', 'CVEENT']), None)
            col_dto = next((orig for orig, norm in mapa_cols.items() if norm in ['CLAVEDISTRITO', 'DISTRITO', 'DTO']), None)
            col_p87 = next((orig for orig, norm in mapa_cols.items() if norm in ['PAD87', 'PADRON87', 'PE87']), None)
            col_p88 = next((orig for orig, norm in mapa_cols.items() if norm in ['PAD88', 'PADRON88', 'PE88']), None)
            col_l87 = next((orig for orig, norm in mapa_cols.items() if norm in ['LN87', 'LISTA87']), None)
            col_l88 = next((orig for orig, norm in mapa_cols.items() if norm in ['LN88', 'LISTA88']), None)

            cols_cargar = [col_ent, col_dto, col_p87, col_p88]
            if col_l87: cols_cargar.append(col_l87)
            if col_l88: cols_cargar.append(col_l88)

            df = pd.read_csv(arch, sep=sep, encoding='latin-1', usecols=cols_cargar)

        if not col_l87 or col_l87 not in df.columns: df['ln87_tmp'] = 0; col_l87 = 'ln87_tmp'
        if not col_l88 or col_l88 not in df.columns: df['ln88_tmp'] = 0; col_l88 = 'ln88_tmp'

        for c in [col_ent, col_dto, col_p87, col_p88, col_l87, col_l88]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)

        # Agrupación por distrito
        df_agrup = df.groupby([col_ent, col_dto], as_index=False)[[col_p87, col_p88, col_l87, col_l88]].sum()
        df_agrup['corte'] = corte_id

        df_final = pd.DataFrame({
            'corte': df_agrup['corte'],
            'clave_entidad': df_agrup[col_ent],
            'distrito': df_agrup[col_dto],
            'pe_87': df_agrup[col_p87],
            'pe_88': df_agrup[col_p88],
            'ln_87': df_agrup[col_l87],
            'ln_88': df_agrup[col_l88]
        })

        df_final.to_sql('derfe_especiales', conn, if_exists='append', index=False)
        print("✅ OK")

    except Exception as e:
        print(f"⚠️ Error: {e}")

conn.execute("CREATE INDEX IF NOT EXISTS idx_esp_corte_dto ON derfe_especiales (corte, clave_entidad, distrito)")
conn.commit()

filas_tot = conn.execute("SELECT COUNT(*) FROM derfe_especiales").fetchone()[0]
conn.close()

print("\n" + "=" * 70)
print(f"BASE ACTUALIZADA: {filas_tot:,} registros distritales listos.")
print("=" * 70)