"""Pruebas de lectura de archivos con datos sintéticos (no requieren SQL Server)."""
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lectores import ErrorDeArchivo, leer_balance, leer_inventario  # noqa: E402

ENCABEZADOS = ["SITE", "WHSE", "LOC", "NON-NETTABLE", "LOT", "STAT", "ITEM", "DESC", "UM", "PRODCODE",
               "SUPPLY-SITE", "ON-HAND", "COST", "TOTAL-COST", "ABC", "PRONOSTICO", "TIPO", "EMPRESA",
               "LÍNEA", "SUPPLY-SITE-FINAL"]


def _excel(tmp_path, filas, anio=2026, mes=10):
    libro = Workbook()
    hoja = libro.active
    hoja.append([anio, mes])
    hoja.append(ENCABEZADOS)
    for fila in filas:
        hoja.append(fila)
    ruta = tmp_path / "inv.xlsx"
    libro.save(ruta)
    return ruta


def _fila(site="SDID", whse="0001", loc="A1", lot="L1", item="X-1", supply=None, on_hand=2, cost=10.5,
          total=21, stat="A", abc="A", non_net="no", linea="BOMBAS"):
    return [site, whse, loc, non_net, lot, stat, item, "Desc", "PZA", 1100, supply, on_hand, cost, total,
            abc, 3.3, "PT", "EMPRESA SA", linea, supply or site]


def test_supply_site_vacio_usa_site(tmp_path):
    inv = leer_inventario(_excel(tmp_path, [_fila(site="SDID"), _fila(site="SAUP", supply="SDID", loc="B")]))
    assert {r["SupplySite"] for r in inv.detalle} == {"SDID"}
    assert inv.anio == 2026 and inv.mes == 10


def test_lote_vacio_y_prodcode_numerico(tmp_path):
    inv = leer_inventario(_excel(tmp_path, [_fila(lot=None)]))
    assert inv.detalle[0]["Lot"] == ""
    assert inv.catalogo[("SDID", "X-1")]["ProdCode"] == "1100"


def test_mismo_lote_en_dos_sites_no_choca(tmp_path):
    inv = leer_inventario(_excel(tmp_path, [_fila(site="SDID"), _fila(site="SOME", supply="SDID")]))
    assert len(inv.detalle) == 2


def test_renglon_repetido_es_error(tmp_path):
    with pytest.raises(ErrorDeArchivo, match="repetido"):
        leer_inventario(_excel(tmp_path, [_fila(), _fila()]))


def test_acumuladas_suman_por_site_y_non_net(tmp_path):
    filas = [
        _fila(loc="A1", on_hand=2, total=20),
        _fila(loc="A2", on_hand=3, total=36),
        _fila(loc="A3", on_hand=1, total=5, non_net="yes"),
    ]
    inv = leer_inventario(_excel(tmp_path, filas))
    por_llave = {(r["Site"], r["NonNetteable"]): r for r in inv.acumuladas}
    assert por_llave[("SDID", "no")]["OnHand"] == Decimal("5")
    assert por_llave[("SDID", "no")]["CostoTotal"] == Decimal("56")
    assert por_llave[("SDID", "yes")]["OnHand"] == Decimal("1")


def test_catalogo_toma_renglon_de_mayor_costo(tmp_path):
    filas = [_fila(loc="A1", total=10, abc="C"), _fila(loc="A2", total=99, abc="A", linea="OTRA")]
    inv = leer_inventario(_excel(tmp_path, filas))
    articulo = inv.catalogo[("SDID", "X-1")]
    assert articulo["ABC"] == "A" and articulo["Linea"] == "OTRA"


def test_mes_invalido(tmp_path):
    with pytest.raises(ErrorDeArchivo, match="mes"):
        leer_inventario(_excel(tmp_path, [_fila()], mes=13))


def test_columna_faltante(tmp_path):
    libro = Workbook()
    libro.active.append([2026, 10])
    libro.active.append(["SITE", "ITEM"])
    ruta = tmp_path / "malo.xlsx"
    libro.save(ruta)
    with pytest.raises(ErrorDeArchivo, match="Faltan columnas"):
        leer_inventario(ruta)


BALANCE = (
    "STOM|2026|10\r\n"
    "10100100|Caja Chica|3000|0|0|3000|\r\n"
    "11700002|Inventarios MP - Material              @|28467027.99|7566285.39|9291324.75|26741988.63|\r\n"
    "20000900|Nominas por pagar|.01|264430.91|286751.63|-22320.71|\r\n"
    "            ------------------ -----------------\r\n"
    "      Site Total            0.00    139,409,785.74    139,409,785.74               0.00\r\n"
)


def test_balance(tmp_path):
    ruta = tmp_path / "bal"
    ruta.write_bytes(BALANCE.encode())
    bal = leer_balance(ruta)
    assert (bal.supply_site, bal.anio, bal.mes) == ("STOM", 2026, 10)
    assert [c["Cuenta"] for c in bal.cuentas] == ["10100100", "11700002", "20000900"]
    assert bal.cuentas[1]["Descripcion"] == "Inventarios MP - Material              @"
    assert bal.cuentas[2]["SaldoInicial"] == Decimal("0.01")
    assert bal.cuentas[2]["SaldoFinal"] == Decimal("-22320.71")


def test_balance_acentos_cp1252(tmp_path):
    ruta = tmp_path / "bal.txt"
    ruta.write_bytes("STOM|2026|10\r\n10100100|Compañía|1|0|0|1|\r\n".encode("cp1252"))
    assert leer_balance(ruta).cuentas[0]["Descripcion"] == "Compañía"


def test_balance_cuenta_repetida(tmp_path):
    ruta = tmp_path / "bal.txt"
    ruta.write_text("STOM|2026|10\n1|A|1|0|0|1|\n1|B|1|0|0|1|\n")
    with pytest.raises(ErrorDeArchivo, match="repetida"):
        leer_balance(ruta)
