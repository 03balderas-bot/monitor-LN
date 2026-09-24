from pathlib import Path

# Ajusta las rutas a tus carpetas reales si es necesario
dir_sex = Path(r"C:\Ruta\a\PE_Sex")
dir_re  = Path(r"C:\Ruta\a\PE_RE")
dir_eo  = Path(r"C:\Ruta\a\PE_EO")

set_sex = {f.name for f in dir_sex.glob("*.xlsx")}
set_re  = {f.name for f in dir_re.glob("*.xlsx")}
set_eo  = {f.name for f in dir_eo.glob("*.xlsx")}

print("Archivos en EO que NO están en SEX:", set_eo - set_sex)
print("Archivos en EO que NO están en RE:", set_eo - set_re)