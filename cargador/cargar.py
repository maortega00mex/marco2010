"""Carga de archivos al dashboard de costos e inventarios.

Uso:
    python cargar.py                      # pide el nombre del archivo
    python cargar.py Inv_202610.xlsx      # Excel de inventario
    python cargar.py Tom-Baloct26.txt     # balance contable (txt separado por |)
    python cargar.py ctadist-ok.xlsx      # catálogo de product code -> cuenta de inventario
    python cargar.py archivo --validar    # solo revisa el archivo, no guarda nada

El tipo de archivo se detecta solo: un Excel con el año en A1 es inventario, un Excel con
encabezados en la fila 1 es el catálogo de product code, y cualquier otro archivo es balance.
La conexión a SQL Server se toma de la variable de entorno DINAMEX_SQL_CONN.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lectores import (ErrorDeArchivo, es_excel_de_inventario, leer_balance, leer_catalogo_prodcode,
                      leer_inventario)

EXTENSIONES_EXCEL = {".xlsx", ".xlsm"}


def pedir_archivo() -> Path:
    while True:
        nombre = input("Nombre del archivo a procesar: ").strip().strip('"')
        if not nombre:
            continue
        ruta = Path(nombre).expanduser()
        if ruta.is_file():
            return ruta
        print(f"No encuentro el archivo '{ruta}'. Intenta de nuevo (Ctrl+C para salir).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carga inventario, catálogo de product code (Excel) o balance contable (txt) a SQL Server.")
    parser.add_argument("archivo", nargs="?", help="Ruta del archivo. Si no se indica, se pregunta.")
    parser.add_argument("--validar", action="store_true", help="Solo revisa el archivo; no guarda en la base de datos.")
    parser.add_argument("--supply-site", help="Balanza sin encabezado: supply-site (si no, se toma del nombre del archivo).")
    parser.add_argument("--anio", type=int, help="Balanza sin encabezado: año.")
    parser.add_argument("--mes", type=int, help="Balanza sin encabezado: mes.")
    parser.add_argument("--conexion", help="Cadena de conexión ODBC (en lugar de DINAMEX_SQL_CONN).")
    args = parser.parse_args(argv)

    ruta = Path(args.archivo).expanduser() if args.archivo else pedir_archivo()
    if not ruta.is_file():
        print(f"No encuentro el archivo '{ruta}'.", file=sys.stderr)
        return 1

    try:
        if ruta.suffix.lower() not in EXTENSIONES_EXCEL:
            tipo = "balance"
        elif es_excel_de_inventario(ruta):
            tipo = "inventario"
        else:
            tipo = "prodcode"
        nombres = {"inventario": "inventario", "balance": "balance contable", "prodcode": "catálogo de product code"}
        print(f"Leyendo {nombres[tipo]}: {ruta.name}")
        if tipo == "balance":
            datos = leer_balance(ruta, args.supply_site, args.anio, args.mes)
        else:
            datos = {"inventario": leer_inventario, "prodcode": leer_catalogo_prodcode}[tipo](ruta)
    except ErrorDeArchivo as error:
        print(f"Error en el archivo: {error}", file=sys.stderr)
        return 1
    print(datos.resumen())

    if args.validar:
        print("Validación correcta. No se guardó nada (--validar).")
        return 0

    from base_datos import conectar, guardar_balance, guardar_catalogo_prodcode, guardar_inventario

    guardar = {"inventario": guardar_inventario, "balance": guardar_balance, "prodcode": guardar_catalogo_prodcode}[tipo]

    conexion = conectar(args.conexion)
    try:
        resultado = guardar(conexion, datos)
    finally:
        conexion.close()
    print("Carga terminada: " + ", ".join(f"{k} = {v:,}" for k, v in resultado.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
