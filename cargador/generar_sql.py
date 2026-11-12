"""Genera un script .sql para cargar dbo.ExistenciasDetalle o dbo.CatalogoArticulos desde el Excel de inventario,
listo para ejecutarse en SQL Server Management Studio (no requiere Python en el servidor).

Uso:
    python generar_sql.py Inv_202609.xlsx            # crea ExistenciasDetalle_202609.sql
    python generar_sql.py Inv_202609.xlsx -o otro.sql
    python generar_sql.py Inv_202609.xlsx --tabla catalogo   # crea CatalogoArticulos_202609.sql
    python generar_sql.py ctadist-ok.xlsx                    # crea CatalogoProdCode.sql
    python generar_sql.py Tomco-Balanza-sept26.txt           # crea BalanceContable_STOM_202609.sql

El script crea la tabla si no existe, borra el periodo y lo vuelve a insertar
dentro de una transacción, y al final compara renglones y costo total.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from lectores import (ErrorDeArchivo, es_excel_de_inventario, leer_balance, leer_catalogo_prodcode,
                      leer_inventario)

DDL_DETALLE = Path(__file__).resolve().parents[1] / "database" / "01_esquema.sql"
RENGLONES_POR_INSERT = 1000  # máximo que permite INSERT ... VALUES en SQL Server
COLUMNAS = ["SupplySite", "Anio", "Mes", "Whse", "Loc", "Item", "Lot", "Site", "NonNetteable",
            "OnHand", "Costo", "TotalCost", "Pronostico", "Empresa"]


def _literal(valor) -> str:
    if valor is None:
        return "NULL"
    if isinstance(valor, (int, Decimal)):
        return str(valor)
    return "N'" + str(valor).replace("'", "''") + "'"


def _ddl(tabla: str = "ExistenciasDetalle") -> str:
    texto = DDL_DETALLE.read_text(encoding="utf-8")
    inicio = texto.index(f"IF OBJECT_ID('dbo.{tabla}'")
    fin = texto.index("GO", inicio)
    return texto[inicio:fin].strip()


COLUMNAS_CATALOGO = ["SupplySite", "Item", "Descripcion", "Linea", "ProdCode", "UM", "Stat", "ABC", "Tipo"]


def _inserts(f, tabla: str, columnas: list[str], filas: list[dict]) -> None:
    for inicio in range(0, len(filas), RENGLONES_POR_INSERT):
        f.write(f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES\n")
        bloque = filas[inicio:inicio + RENGLONES_POR_INSERT]
        f.write(",\n".join("(" + ", ".join(_literal(r[c]) for c in columnas) + ")" for r in bloque))
        f.write(";\n")


def generar_catalogo(ruta_excel: Path, salida: Path | None = None) -> Path:
    """Script que inserta los artículos nuevos y actualiza los que cambiaron en dbo.CatalogoArticulos."""
    inv = leer_inventario(ruta_excel)
    salida = salida or ruta_excel.with_name(f"CatalogoArticulos_{inv.anio}{inv.mes:02d}.sql")
    articulos = sorted(inv.catalogo.values(), key=lambda r: (r["SupplySite"], r["Item"]))

    with salida.open("w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(f"/* Catálogo de artículos desde {ruta_excel.name} ({inv.anio}-{inv.mes:02d})\n")
        f.write(f"   Artículos en el archivo: {len(articulos):,}\n")
        f.write("   Inserta los nuevos y actualiza los que cambiaron; no borra los que ya no vienen.\n")
        f.write("   Si un artículo trae datos distintos en varios renglones, se usan los del renglón\n")
        f.write("   con mayor costo total. Si algo falla, se deshace todo (XACT_ABORT). */\n")
        f.write("SET NOCOUNT ON;\nSET XACT_ABORT ON;\nGO\n")
        f.write("USE invDinamex;\nGO\n")
        f.write(_ddl("CatalogoArticulos") + "\nGO\n")
        f.write("""IF OBJECT_ID('tempdb..#Catalogo') IS NOT NULL DROP TABLE #Catalogo;
CREATE TABLE #Catalogo (
    SupplySite VARCHAR(10) NOT NULL, Item VARCHAR(40) NOT NULL,
    Descripcion NVARCHAR(150) NULL, Linea NVARCHAR(60) NULL, ProdCode VARCHAR(20) NULL,
    UM VARCHAR(10) NULL, Stat CHAR(1) NULL, ABC VARCHAR(2) NULL, Tipo VARCHAR(5) NULL,
    PRIMARY KEY (SupplySite, Item));
""")
        _inserts(f, "#Catalogo", COLUMNAS_CATALOGO, articulos)
        f.write(f"""
DECLARE @Cambios TABLE (Accion NVARCHAR(10));
BEGIN TRANSACTION;
MERGE dbo.CatalogoArticulos AS t
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
OUTPUT $action INTO @Cambios;

IF (SELECT COUNT(*) FROM dbo.CatalogoArticulos c
    WHERE EXISTS (SELECT 1 FROM #Catalogo s WHERE s.SupplySite = c.SupplySite AND s.Item = c.Item)) <> {len(articulos)}
BEGIN
    ROLLBACK TRANSACTION;
    RAISERROR('La validación no cuadra. No se guardó nada.', 16, 1);
END
ELSE
BEGIN
    COMMIT TRANSACTION;
    SELECT SUM(CASE WHEN Accion = 'INSERT' THEN 1 ELSE 0 END) AS ArticulosNuevos,
           SUM(CASE WHEN Accion = 'UPDATE' THEN 1 ELSE 0 END) AS ArticulosActualizados,
           (SELECT COUNT(*) FROM dbo.CatalogoArticulos) AS TotalCatalogo
    FROM @Cambios;
END
DROP TABLE #Catalogo;
GO

SELECT SupplySite, COUNT(*) AS Articulos
FROM dbo.CatalogoArticulos GROUP BY SupplySite ORDER BY SupplySite;
""")
    return salida


def generar_prodcode(ruta_excel: Path, salida: Path | None = None) -> Path:
    """Script que inserta los product codes nuevos y actualiza los que cambiaron en dbo.CatalogoProdCode."""
    catalogo = leer_catalogo_prodcode(ruta_excel)
    salida = salida or ruta_excel.with_name("CatalogoProdCode.sql")
    registros = sorted(catalogo.registros.values(), key=lambda r: (r["SupplySite"], r["ProdCode"]))
    columnas = ["SupplySite", "ProdCode", "Descripcion", "CuentaInventario", "DescripcionCuenta"]

    with salida.open("w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(f"/* Catálogo de product code desde {ruta_excel.name}\n")
        f.write(f"   Product codes: {len(registros):,}\n")
        for aviso in catalogo.avisos:
            f.write(f"   Aviso: {aviso}\n")
        f.write("   Inserta los nuevos y actualiza los que cambiaron; no borra los que ya no vienen.\n")
        f.write("   Si algo falla, se deshace todo (XACT_ABORT). */\n")
        f.write("SET NOCOUNT ON;\nSET XACT_ABORT ON;\nGO\n")
        f.write("USE invDinamex;\nGO\n")
        f.write(_ddl("CatalogoProdCode") + "\nGO\n")
        f.write("""IF OBJECT_ID('tempdb..#ProdCode') IS NOT NULL DROP TABLE #ProdCode;
CREATE TABLE #ProdCode (
    SupplySite VARCHAR(10) NOT NULL, ProdCode VARCHAR(20) NOT NULL,
    Descripcion NVARCHAR(150) NULL, CuentaInventario VARCHAR(20) NULL, DescripcionCuenta NVARCHAR(150) NULL,
    PRIMARY KEY (SupplySite, ProdCode));
""")
        _inserts(f, "#ProdCode", columnas, registros)
        f.write(f"""
DECLARE @Cambios TABLE (Accion NVARCHAR(10));
BEGIN TRANSACTION;
MERGE dbo.CatalogoProdCode AS t
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
OUTPUT $action INTO @Cambios;

IF (SELECT COUNT(*) FROM dbo.CatalogoProdCode c
    WHERE EXISTS (SELECT 1 FROM #ProdCode s WHERE s.SupplySite = c.SupplySite AND s.ProdCode = c.ProdCode)) <> {len(registros)}
BEGIN
    ROLLBACK TRANSACTION;
    RAISERROR('La validación no cuadra. No se guardó nada.', 16, 1);
END
ELSE
BEGIN
    COMMIT TRANSACTION;
    SELECT SUM(CASE WHEN Accion = 'INSERT' THEN 1 ELSE 0 END) AS ProdCodesNuevos,
           SUM(CASE WHEN Accion = 'UPDATE' THEN 1 ELSE 0 END) AS ProdCodesActualizados,
           (SELECT COUNT(*) FROM dbo.CatalogoProdCode) AS TotalCatalogo
    FROM @Cambios;
END
DROP TABLE #ProdCode;
GO

SELECT SupplySite, CuentaInventario, MAX(DescripcionCuenta) AS DescripcionCuenta, COUNT(*) AS ProdCodes
FROM dbo.CatalogoProdCode GROUP BY SupplySite, CuentaInventario ORDER BY SupplySite, CuentaInventario;
""")
    return salida


def generar_balance(ruta: Path, salida: Path | None = None, supply_site: str | None = None,
                    anio: int | None = None, mes: int | None = None) -> Path:
    """Script que reemplaza el balance de un supply-site y periodo en dbo.BalanceContable."""
    bal = leer_balance(ruta, supply_site, anio, mes)
    salida = salida or ruta.with_name(f"BalanceContable_{bal.supply_site}_{bal.anio}{bal.mes:02d}.sql")
    columnas = ["SupplySite", "Anio", "Mes", "Cuenta", "Descripcion", "SaldoInicial", "Cargos", "Abonos", "SaldoFinal"]
    cargos = sum((c["Cargos"] for c in bal.cuentas), Decimal(0))
    abonos = sum((c["Abonos"] for c in bal.cuentas), Decimal(0))
    final = sum((c["SaldoFinal"] for c in bal.cuentas), Decimal(0))
    filtro = f"SupplySite = {_literal(bal.supply_site)} AND Anio = {bal.anio} AND Mes = {bal.mes}"

    with salida.open("w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(f"/* Balance contable {bal.supply_site} {bal.anio}-{bal.mes:02d} desde {ruta.name}\n")
        f.write(f"   Cuentas: {len(bal.cuentas):,}   Cargos: {cargos:,.2f}   Abonos: {abonos:,.2f}\n")
        f.write("   Reemplaza ese supply-site y periodo. Si algo falla, se deshace todo (XACT_ABORT). */\n")
        f.write("SET NOCOUNT ON;\nSET XACT_ABORT ON;\nGO\n")
        f.write("USE invDinamex;\nGO\n")
        f.write(_ddl("BalanceContable") + "\nGO\n")
        f.write("BEGIN TRANSACTION;\n")
        f.write(f"DELETE FROM dbo.BalanceContable WHERE {filtro};\n")
        _inserts(f, "dbo.BalanceContable", columnas, bal.cuentas)
        f.write(f"""
DECLARE @Cuentas INT, @Cargos DECIMAL(19,2), @Abonos DECIMAL(19,2), @Final DECIMAL(19,2);
SELECT @Cuentas = COUNT(*), @Cargos = SUM(Cargos), @Abonos = SUM(Abonos), @Final = SUM(SaldoFinal)
FROM dbo.BalanceContable WHERE {filtro};
IF @Cuentas <> {len(bal.cuentas)} OR @Cargos <> {cargos} OR @Abonos <> {abonos} OR @Final <> {final}
BEGIN
    ROLLBACK TRANSACTION;
    RAISERROR('La validación no cuadra. No se guardó nada.', 16, 1);
END
ELSE
BEGIN
    COMMIT TRANSACTION;
    PRINT 'Carga correcta: {len(bal.cuentas):,} cuentas, cargos {cargos:,.2f}, abonos {abonos:,.2f}';
END
GO

SELECT Cuenta, Descripcion, SaldoInicial, Cargos, Abonos, SaldoFinal
FROM dbo.BalanceContable
WHERE {filtro} AND Cuenta IN (SELECT CuentaInventario FROM dbo.CatalogoProdCode)
ORDER BY Cuenta;
""")
    return salida


def generar(ruta_excel: Path, salida: Path | None = None) -> Path:
    inv = leer_inventario(ruta_excel)
    salida = salida or ruta_excel.with_name(f"ExistenciasDetalle_{inv.anio}{inv.mes:02d}.sql")
    total = sum((r["TotalCost"] for r in inv.detalle), Decimal(0))
    sites = ", ".join(_literal(s) for s in inv.supply_sites)

    with salida.open("w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(f"/* Carga de dbo.ExistenciasDetalle {inv.anio}-{inv.mes:02d}\n")
        f.write(f"   Origen: {ruta_excel.name}\n")
        f.write(f"   Renglones: {len(inv.detalle):,}   Costo total: {total:,.4f}\n")
        f.write("   Si algo falla, se deshace todo (XACT_ABORT). */\n")
        f.write("SET NOCOUNT ON;\nSET XACT_ABORT ON;\nGO\n")
        f.write("USE invDinamex;\nGO\n")
        f.write(_ddl() + "\nGO\n")
        f.write("/* Quita la llave foránea al catálogo si la tabla se creó con la versión anterior del esquema */\n")
        f.write("IF OBJECT_ID('dbo.FK_ExistenciasDetalle_Articulo', 'F') IS NOT NULL\n"
                "    ALTER TABLE dbo.ExistenciasDetalle DROP CONSTRAINT FK_ExistenciasDetalle_Articulo;\nGO\n")
        f.write("BEGIN TRANSACTION;\n")
        f.write(f"DELETE FROM dbo.ExistenciasDetalle WHERE Anio = {inv.anio} AND Mes = {inv.mes} "
                f"AND SupplySite IN ({sites});\n")
        for inicio in range(0, len(inv.detalle), RENGLONES_POR_INSERT):
            f.write(f"INSERT INTO dbo.ExistenciasDetalle ({', '.join(COLUMNAS)}) VALUES\n")
            bloque = inv.detalle[inicio:inicio + RENGLONES_POR_INSERT]
            f.write(",\n".join("(" + ", ".join(_literal(r[c]) for c in COLUMNAS) + ")" for r in bloque))
            f.write(";\n")
        f.write(f"""
DECLARE @renglones INT, @costo DECIMAL(19,4);
SELECT @renglones = COUNT(*), @costo = SUM(TotalCost)
FROM dbo.ExistenciasDetalle WHERE Anio = {inv.anio} AND Mes = {inv.mes};
IF @renglones <> {len(inv.detalle)} OR @costo <> {total}
BEGIN
    ROLLBACK TRANSACTION;
    RAISERROR('La validación no cuadra: renglones %d. No se guardó nada.', 16, 1, @renglones);
END
ELSE
BEGIN
    COMMIT TRANSACTION;
    PRINT 'Carga correcta: {len(inv.detalle):,} renglones, costo total {total:,.2f}';
END
GO

SELECT SupplySite, COUNT(*) AS Renglones, SUM(TotalCost) AS CostoTotal
FROM dbo.ExistenciasDetalle WHERE Anio = {inv.anio} AND Mes = {inv.mes}
GROUP BY SupplySite ORDER BY SupplySite;
""")
    return salida


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera el script SQL de carga de ExistenciasDetalle.")
    parser.add_argument("archivo", help="Excel de inventario")
    parser.add_argument("-o", "--salida", help="Archivo .sql de salida")
    parser.add_argument("-t", "--tabla", choices=["detalle", "catalogo", "prodcode", "balance"],
                        help="detalle = ExistenciasDetalle; catalogo = CatalogoArticulos; prodcode = CatalogoProdCode; balance = BalanceContable. "
                             "Si no se indica: detalle para el Excel de inventario y prodcode para el de cuentas.")
    parser.add_argument("--supply-site", help="Balanza sin encabezado: supply-site.")
    parser.add_argument("--anio", type=int, help="Balanza sin encabezado: año.")
    parser.add_argument("--mes", type=int, help="Balanza sin encabezado: mes.")
    args = parser.parse_args(argv)
    ruta = Path(args.archivo)
    try:
        destino = Path(args.salida) if args.salida else None
        if args.tabla:
            tabla = args.tabla
        elif ruta.suffix.lower() not in (".xlsx", ".xlsm"):
            tabla = "balance"
        else:
            tabla = "detalle" if es_excel_de_inventario(ruta) else "prodcode"
        if tabla == "balance":
            salida = generar_balance(ruta, destino, args.supply_site, args.anio, args.mes)
        else:
            funcion = {"detalle": generar, "catalogo": generar_catalogo, "prodcode": generar_prodcode}[tabla]
            salida = funcion(ruta, destino)
    except ErrorDeArchivo as error:
        print(f"Error en el archivo: {error}", file=sys.stderr)
        return 1
    print(f"Script generado: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
