# Cargador de archivos

Carga a SQL Server el Excel de inventario y el balance contable (txt separado por `|`).
Antes, crea las tablas con `database/01_esquema.sql`.

## Instalación

Requiere Python 3.10+ y el [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).

```
cd cargador
pip install -r requirements.txt
```

Define la conexión en la variable de entorno `DINAMEX_SQL_CONN` (Windows / PowerShell):

```
$env:DINAMEX_SQL_CONN = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=mi-servidor;DATABASE=Dinamex;Trusted_Connection=yes;TrustServerCertificate=yes"
```

## Uso

```
python cargar.py                         # pide el nombre del archivo
python cargar.py Inv_202610.xlsx         # inventario
python cargar.py Tom-Baloct26            # balance contable
python cargar.py Inv_202610.xlsx --validar   # solo revisa, no guarda
```

El tipo se detecta por la extensión: `.xlsx` / `.xlsm` es inventario; cualquier otro archivo es balance.

## Qué hace cada carga

**Excel de inventario** (fila 1: A = año, B = mes; fila 2: encabezados)

- Las columnas se buscan por nombre, no por posición.
- SupplySite = SUPPLY-SITE; si viene vacío se usa SITE.
- Catálogo de artículos: inserta los nuevos y actualiza los que cambiaron. Si un artículo trae datos distintos en varios renglones, se toman los del renglón con mayor costo total.
- Existencias detalle y acumuladas: reemplaza el periodo para los supply-sites que trae el archivo. Volver a cargar el mismo mes no duplica.

**Balance contable** (línea 1: supply-site|año|mes)

- Reemplaza el balance de ese supply-site y periodo.
- Ignora las líneas sin `|` (totales y separadores).

Cada carga corre en una sola transacción: si algo falla, no se guarda nada.

## Pruebas

```
pip install pytest
python -m pytest tests
```
