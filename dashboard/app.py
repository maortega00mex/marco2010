"""Dashboard de costos e inventarios (Dinamex).

Servidor web local que lee de la base invDinamex en SQL Server.

Uso:
    pip install -r requirements.txt
    set DINAMEX_SQL_CONN=DRIVER={ODBC Driver 18 for SQL Server};SERVER=...;DATABASE=invDinamex;Trusted_Connection=yes;TrustServerCertificate=yes
    python app.py            # abre http://localhost:5000

Todas las consultas usan SQL estándar con parámetros (?).
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Callable

from flask import Flask, jsonify, request, send_from_directory

VARIABLE_CONEXION = "DINAMEX_SQL_CONN"
CARPETA_STATIC = Path(__file__).resolve().parent / "static"
TOP_ARTICULOS = 15
LINEAS_EN_TENDENCIA = 5  # el resto se agrupa en "Otras líneas"


def conexion_sql_server():
    import pyodbc

    cadena = os.environ.get(VARIABLE_CONEXION)
    if not cadena:
        raise SystemExit(f"Falta la variable de entorno {VARIABLE_CONEXION} con la cadena de conexión a invDinamex.")
    return pyodbc.connect(cadena)


def _valor(v):
    return float(v) if isinstance(v, Decimal) else v


def agrupar_lineas(filas: list[dict], periodos: list[dict]) -> dict:
    """Series por línea para la tendencia: las de mayor costo total (sumando todos los periodos)
    y el resto en "Otras líneas". Cada serie trae un valor por periodo (0 si no hubo inventario)."""
    totales: dict[str, float] = {}
    for f in filas:
        totales[f["Linea"]] = totales.get(f["Linea"], 0) + (f["Costo"] or 0)
    principales = sorted(totales, key=totales.get, reverse=True)[:LINEAS_EN_TENDENCIA]
    claves = [(p["Anio"], p["Mes"]) for p in periodos]
    series = {n: dict.fromkeys(claves, 0.0) for n in principales}
    otras = dict.fromkeys(claves, 0.0)
    for f in filas:
        destino = series.get(f["Linea"], otras)
        destino[(f["Anio"], f["Mes"])] += f["Costo"] or 0
    resultado = [{"nombre": n, "valores": [series[n][k] for k in claves]} for n in principales]
    if len(totales) > len(principales):
        resultado.append({"nombre": "Otras líneas", "valores": [otras[k] for k in claves], "otras": True,
                          "cuantas": len(totales) - len(principales)})
    return {"periodos": [{"Anio": a, "Mes": m} for a, m in claves], "series": resultado}


def crear_app(conectar: Callable = conexion_sql_server) -> Flask:
    app = Flask(__name__, static_folder=str(CARPETA_STATIC))

    def consultar(sql: str, parametros: list | tuple = (), limite: int | None = None) -> list[dict]:
        con = conectar()
        try:
            cur = con.cursor()
            cur.execute(sql, list(parametros))
            columnas = [c[0] for c in cur.description]
            filas = cur.fetchmany(limite) if limite else cur.fetchall()
            return [{c: _valor(v) for c, v in zip(columnas, f)} for f in filas]
        finally:
            con.close()

    def filtros_detalle(incluir_periodo: bool = True) -> tuple[str, list]:
        """WHERE para dbo.ExistenciasDetalle d LEFT JOIN dbo.CatalogoArticulos a."""
        condiciones, parametros = [], []
        a = request.args
        if incluir_periodo:
            condiciones += ["d.Anio = ?", "d.Mes = ?"]
            parametros += [int(a.get("anio")), int(a.get("mes"))]
        for campo, columna in [("ss", "d.SupplySite"), ("site", "d.Site"), ("nonnet", "d.NonNetteable"),
                               ("linea", "a.Linea"), ("stat", "a.Stat"), ("tipo", "a.Tipo")]:
            if a.get(campo):
                condiciones.append(f"{columna} = ?")
                parametros.append(a.get(campo))
        return ("WHERE " + " AND ".join(condiciones)) if condiciones else "", parametros

    BASE = ("FROM dbo.ExistenciasDetalle d LEFT JOIN dbo.CatalogoArticulos a "
            "ON a.SupplySite = d.SupplySite AND a.Item = d.Item")

    @app.get("/")
    def inicio():
        return send_from_directory(CARPETA_STATIC, "index.html")

    @app.get("/api/opciones")
    def opciones():
        def lista(sql):
            return [list(f.values())[0] for f in consultar(sql)]
        return jsonify({
            "periodos": consultar("SELECT DISTINCT Anio, Mes FROM dbo.ExistenciasDetalle ORDER BY Anio DESC, Mes DESC"),
            "supply_sites": lista("SELECT DISTINCT SupplySite FROM dbo.ExistenciasDetalle ORDER BY SupplySite"),
            "sites": lista("SELECT DISTINCT Site FROM dbo.ExistenciasDetalle ORDER BY Site"),
            "lineas": lista("SELECT DISTINCT Linea FROM dbo.CatalogoArticulos WHERE Linea IS NOT NULL ORDER BY Linea"),
            "tipos": lista("SELECT DISTINCT Tipo FROM dbo.CatalogoArticulos WHERE Tipo IS NOT NULL ORDER BY Tipo"),
        })

    @app.get("/api/datos")
    def datos():
        if not request.args.get("anio") or not request.args.get("mes"):
            return jsonify({"error": "Falta el periodo"}), 400
        where, p = filtros_detalle()
        kpis = consultar(f"""
            SELECT COALESCE(SUM(d.TotalCost), 0) AS Costo,
                   COUNT(DISTINCT d.Item) AS Articulos,
                   COALESCE(SUM(CASE WHEN a.Stat = 'S' THEN d.TotalCost ELSE 0 END), 0) AS CostoLento,
                   COALESCE(SUM(CASE WHEN a.Stat = 'O' THEN d.TotalCost ELSE 0 END), 0) AS CostoObsoleto,
                   COALESCE(SUM(CASE WHEN d.NonNetteable = 'yes' THEN d.TotalCost ELSE 0 END), 0) AS CostoInspeccion
            {BASE} {where}""", p)[0]

        def agrupado(columna):
            return consultar(f"""
                SELECT COALESCE({columna}, '(sin dato)') AS Nombre, SUM(d.TotalCost) AS Costo
                {BASE} {where}
                GROUP BY COALESCE({columna}, '(sin dato)') ORDER BY SUM(d.TotalCost) DESC""", p)

        top = consultar(f"""
            SELECT d.SupplySite, d.Item, MAX(a.Descripcion) AS Descripcion, MAX(a.Linea) AS Linea,
                   MAX(a.Stat) AS Stat, SUM(d.OnHand) AS OnHand, SUM(d.TotalCost) AS Costo
            {BASE} {where}
            GROUP BY d.SupplySite, d.Item ORDER BY SUM(d.TotalCost) DESC""", p, limite=TOP_ARTICULOS)

        where_t, p_t = filtros_detalle(incluir_periodo=False)
        tendencia = consultar(f"""
            SELECT d.Anio, d.Mes, SUM(d.TotalCost) AS Costo
            {BASE} {where_t}
            GROUP BY d.Anio, d.Mes ORDER BY d.Anio, d.Mes""", p_t)

        por_linea_mes = consultar(f"""
            SELECT d.Anio, d.Mes, COALESCE(a.Linea, '(sin línea)') AS Linea, SUM(d.TotalCost) AS Costo
            {BASE} {where_t}
            GROUP BY d.Anio, d.Mes, COALESCE(a.Linea, '(sin línea)')""", p_t)
        tendencia_linea = agrupar_lineas(por_linea_mes, tendencia)

        cond_c, p_c = ["Anio = ?", "Mes = ?"], [int(request.args["anio"]), int(request.args["mes"])]
        if request.args.get("ss"):
            cond_c.append("SupplySite = ?")
            p_c.append(request.args["ss"])
        conciliacion = consultar(f"""
            SELECT SupplySite, Cuenta, DescripcionCuenta, CostoInventario, SaldoContable, Diferencia, BalanceCargado
            FROM dbo.vConciliacionContable WHERE {' AND '.join(cond_c)}
            ORDER BY SupplySite, Cuenta""", p_c)

        return jsonify({
            "kpis": kpis,
            "conciliacion": conciliacion,
            "por_tipo": agrupado("a.Tipo"),
            "por_stat": agrupado("a.Stat"),
            "por_site": agrupado("d.Site"),
            "por_linea": agrupado("a.Linea"),
            "top_articulos": top,
            "tendencia": tendencia,
            "tendencia_linea": tendencia_linea,
        })

    return app


if __name__ == "__main__":
    puerto = int(os.environ.get("DINAMEX_PUERTO", "5000"))
    print(f"Dashboard en http://localhost:{puerto}  (Ctrl+C para detener)")
    crear_app().run(host="127.0.0.1", port=puerto, debug=False)
