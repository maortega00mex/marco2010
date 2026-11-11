"""Carga de archivos al dashboard de costos e inventarios.

Uso:
    python cargar.py                      # pide el nombre del archivo
    python cargar.py Inv_202610.xlsx      # Excel de inventario
    python cargar.py Tom-Baloct26.txt     # balance contable (txt separado por |)
    python cargar.py archivo --validar    # solo revisa el archivo, no guarda nada

El tipo de archivo se detecta solo: .xlsx / .xlsm es inventario; cualquier otro es balance.
La conexión a SQL Server se toma de la variable de entorno DINAMEX_SQL_CONN.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lectores import ErrorDeArchivo, leer_balance, leer_inventario

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
    parser = argparse.ArgumentParser(description="Carga inventario (Excel) o balance contable (txt) a SQL Server.")
    parser.add_argument("archivo", nargs="?", help="Ruta del archivo. Si no se indica, se pregunta.")
    parser.add_argument("--validar", action="store_true", help="Solo revisa el archivo; no guarda en la base de datos.")
    parser.add_argument("--conexion", help="Cadena de conexión ODBC (en lugar de DINAMEX_SQL_CONN).")
    args = parser.parse_args(argv)

    ruta = Path(args.archivo).expanduser() if args.archivo else pedir_archivo()
    if not ruta.is_file():
        print(f"No encuentro el archivo '{ruta}'.", file=sys.stderr)
        return 1

    es_excel = ruta.suffix.lower() in EXTENSIONES_EXCEL
    print(f"Leyendo {'inventario' if es_excel else 'balance contable'}: {ruta.name}")
    try:
        datos = leer_inventario(ruta) if es_excel else leer_balance(ruta)
    except ErrorDeArchivo as error:
        print(f"Error en el archivo: {error}", file=sys.stderr)
        return 1
    print(datos.resumen())

    if args.validar:
        print("Validación correcta. No se guardó nada (--validar).")
        return 0

    from base_datos import conectar, guardar_balance, guardar_inventario

    conexion = conectar(args.conexion)
    try:
        resultado = guardar_inventario(conexion, datos) if es_excel else guardar_balance(conexion, datos)
    finally:
        conexion.close()
    print("Carga terminada: " + ", ".join(f"{k} = {v:,}" for k, v in resultado.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
