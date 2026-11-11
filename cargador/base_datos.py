"""Escritura en SQL Server. Cada carga corre en una sola transacción:
si algo falla, no se guarda nada.

Volver a cargar el mismo periodo reemplaza los datos de ese periodo
(no se duplican).
"""
from __future__ import annotations

import os

from lectores import Balance, CatalogoProdCode, Inventario

VARIABLE_CONEXION = "DINAMEX_SQL_CONN"
CONEXION_EJEMPLO = (
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=mi-servidor;DATABASE=Dinamex;"
    "Trusted_Connection=yes;TrustServerCertificate=yes"
)
LOTE = 5000

COLS_DETALLE = ["SupplySite", "Anio", "Mes", "Whse", "Loc", "Item", "Lot", "Site", "NonNetteable",
                "OnHand", "Costo", "TotalCost", "Pronostico", "Empresa"]
COLS_CATALOGO = ["SupplySite", "Item", "Descripcion", "Linea", "ProdCode", "UM", "Stat", "ABC", "Tipo"]
COLS_ACUMULADAS = ["SupplySite", "Anio", "Mes", "Item", "Site", "NonNetteable", "Tipo", "OnHand", "CostoTotal"]
COLS_PRODCODE = ["SupplySite", "ProdCode", "Descripcion", "CuentaInventario", "DescripcionCuenta"]
COLS_BALANCE = ["SupplySite", "Anio", "Mes", "Cuenta", "Descripcion", "SaldoInicial", "Cargos", "Abonos", "SaldoFinal"]


def conectar(cadena: str | None = None):
    import pyodbc  # import local: la validación sin base de datos no lo necesita

    cadena = cadena or os.environ.get(VARIABLE_CONEXION)
    if not cadena:
        raise SystemExit(
            f"Falta la cadena de conexión. Defínela en la variable {VARIABLE_CONEXION}, por ejemplo:\n"
            f"  {CONEXION_EJEMPLO}"
        )
    return pyodbc.connect(cadena, autocommit=False)


def _insertar(cursor, tabla: str, columnas: list[str], filas: list[dict]) -> None:
    sql = f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})"
    cursor.fast_executemany = True
    for inicio in range(0, len(filas), LOTE):
        cursor.executemany(sql, [tuple(f[c] for c in columnas) for f in filas[inicio:inicio + LOTE]])


def guardar_inventario(conexion, inv: Inventario) -> dict[str, int]:
    cursor = conexion.cursor()
    try:
        # 1) Catálogo de artículos: inserta nuevos y actualiza los que cambiaron.
        cursor.execute("""
            CREATE TABLE #Catalogo (
                SupplySite VARCHAR(10) NOT NULL, Item VARCHAR(40) NOT NULL,
                Descripcion NVARCHAR(150) NULL, Linea NVARCHAR(60) NULL, ProdCode VARCHAR(20) NULL,
                UM VARCHAR(10) NULL, Stat CHAR(1) NULL, ABC VARCHAR(2) NULL, Tipo VARCHAR(5) NULL,
                PRIMARY KEY (SupplySite, Item))
        """)
        _insertar(cursor, "#Catalogo", COLS_CATALOGO, list(inv.catalogo.values()))
        cursor.execute("""
            MERGE invDinamex.CatalogoArticulos AS t
            USING #Catalogo AS s ON t.SupplySite = s.SupplySite AND t.Item = s.Item
            WHEN MATCHED AND EXISTS (
                SELECT t.Descripcion, t.Linea, t.ProdCode, t.UM, t.Stat, t.ABC, t.Tipo
                EXCEPT
                SELECT s.Descripcion, s.Linea, s.ProdCode, s.UM, s.Stat, s.ABC, s.Tipo)
              THEN UPDATE SET Descripcion = s.Descripcion, Linea = s.Linea, ProdCode = s.ProdCode,
                              UM = s.UM, Stat = s.Stat, ABC = s.ABC, Tipo = s.Tipo,
                              FechaActualizacion = SYSDATETIME()
            WHEN NOT MATCHED BY TARGET
              THEN INSERT (SupplySite, Item, Descripcion, Linea, ProdCode, UM, Stat, ABC, Tipo)
                   VALUES (s.SupplySite, s.Item, s.Descripcion, s.Linea, s.ProdCode, s.UM, s.Stat, s.ABC, s.Tipo)
            OUTPUT $action;
        """)
        acciones = [fila[0] for fila in cursor.fetchall()]
        cursor.execute("DROP TABLE #Catalogo")

        # 2) Existencias del periodo: se reemplazan para los supply-sites del archivo.
        sites = inv.supply_sites
        marcas = ", ".join("?" * len(sites))
        for tabla in ("invDinamex.ExistenciasAcumuladas", "invDinamex.ExistenciasDetalle"):
            cursor.execute(
                f"DELETE FROM {tabla} WHERE Anio = ? AND Mes = ? AND SupplySite IN ({marcas})",
                inv.anio, inv.mes, *sites,
            )
        _insertar(cursor, "invDinamex.ExistenciasDetalle", COLS_DETALLE, inv.detalle)
        _insertar(cursor, "invDinamex.ExistenciasAcumuladas", COLS_ACUMULADAS, inv.acumuladas)

        conexion.commit()
        return {
            "articulos_nuevos": acciones.count("INSERT"),
            "articulos_actualizados": acciones.count("UPDATE"),
            "detalle": len(inv.detalle),
            "acumuladas": len(inv.acumuladas),
        }
    except Exception:
        conexion.rollback()
        raise


def guardar_balance(conexion, balance: Balance) -> dict[str, int]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "DELETE FROM invDinamex.BalanceContable WHERE SupplySite = ? AND Anio = ? AND Mes = ?",
            balance.supply_site, balance.anio, balance.mes,
        )
        reemplazadas = cursor.rowcount
        _insertar(cursor, "invDinamex.BalanceContable", COLS_BALANCE, balance.cuentas)
        conexion.commit()
        return {"cuentas": len(balance.cuentas), "reemplazadas": max(reemplazadas, 0)}
    except Exception:
        conexion.rollback()
        raise


def guardar_catalogo_prodcode(conexion, catalogo: CatalogoProdCode) -> dict[str, int]:
    """Inserta los product codes nuevos y actualiza los que cambiaron. No borra los que ya no vienen."""
    cursor = conexion.cursor()
    try:
        cursor.execute("""
            CREATE TABLE #ProdCode (
                SupplySite VARCHAR(10) NOT NULL, ProdCode VARCHAR(20) NOT NULL,
                Descripcion NVARCHAR(150) NULL, CuentaInventario VARCHAR(20) NULL,
                DescripcionCuenta NVARCHAR(150) NULL,
                PRIMARY KEY (SupplySite, ProdCode))
        """)
        _insertar(cursor, "#ProdCode", COLS_PRODCODE, list(catalogo.registros.values()))
        cursor.execute("""
            MERGE invDinamex.CatalogoProdCode AS t
            USING #ProdCode AS s ON t.SupplySite = s.SupplySite AND t.ProdCode = s.ProdCode
            WHEN MATCHED AND EXISTS (
                SELECT t.Descripcion, t.CuentaInventario, t.DescripcionCuenta
                EXCEPT
                SELECT s.Descripcion, s.CuentaInventario, s.DescripcionCuenta)
              THEN UPDATE SET Descripcion = s.Descripcion, CuentaInventario = s.CuentaInventario,
                              DescripcionCuenta = s.DescripcionCuenta, FechaActualizacion = SYSDATETIME()
            WHEN NOT MATCHED BY TARGET
              THEN INSERT (SupplySite, ProdCode, Descripcion, CuentaInventario, DescripcionCuenta)
                   VALUES (s.SupplySite, s.ProdCode, s.Descripcion, s.CuentaInventario, s.DescripcionCuenta)
            OUTPUT $action;
        """)
        acciones = [fila[0] for fila in cursor.fetchall()]
        cursor.execute("DROP TABLE #ProdCode")
        conexion.commit()
        return {"prodcodes_nuevos": acciones.count("INSERT"), "prodcodes_actualizados": acciones.count("UPDATE")}
    except Exception:
        conexion.rollback()
        raise
