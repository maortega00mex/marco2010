"""Lectura y validación de los archivos de origen (sin tocar la base de datos).

- Excel de inventario: fila 1 -> A = año, B = mes; fila 2 -> encabezados; fila 3 en adelante -> datos.
- Balance contable (txt): fila 1 -> supply-site|año|mes; luego cuenta|descripción|saldo inicial|cargos|abonos|saldo final|
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path


class ErrorDeArchivo(Exception):
    """El archivo no tiene el formato esperado."""


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------

def _normalizar(nombre: object) -> str:
    """'LÍNEA ' -> 'LINEA', 'Non-netteable' -> 'NON-NETTEABLE'."""
    texto = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().upper()


def _texto(valor: object) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _decimal(valor: object, escala: int, campo: str, fila: int) -> Decimal:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return Decimal(0)
    try:
        numero = Decimal(str(valor).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ErrorDeArchivo(f"Fila {fila}: {campo} no es un número ({valor!r}).") from exc
    return numero.quantize(Decimal(1).scaleb(-escala))


def _entero(valor: object, campo: str, fila: int) -> int:
    try:
        return int(Decimal(str(valor).strip()))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ErrorDeArchivo(f"Fila {fila}: {campo} no es un número entero ({valor!r}).") from exc


def _validar_periodo(anio: int, mes: int, fila: int) -> None:
    if not 2000 <= anio <= 2100:
        raise ErrorDeArchivo(f"Fila {fila}: año fuera de rango ({anio}).")
    if not 1 <= mes <= 12:
        raise ErrorDeArchivo(f"Fila {fila}: mes fuera de rango ({mes}).")


# ----------------------------------------------------------------------------
# Excel de inventario
# ----------------------------------------------------------------------------

# Encabezado normalizado -> nombre interno. Se aceptan variantes de escritura.
COLUMNAS_EXCEL = {
    "SITE": "site",
    "WHSE": "whse",
    "LOC": "loc",
    "NON-NETTABLE": "non_net",
    "NON-NETTEABLE": "non_net",
    "LOT": "lot",
    "STAT": "stat",
    "ITEM": "item",
    "DESC": "desc",
    "UM": "um",
    "PRODCODE": "prodcode",
    "SUPPLY-SITE": "supply_site",
    "ON-HAND": "on_hand",
    "COST": "cost",
    "COSTO": "cost",
    "TOTAL-COST": "total_cost",
    "ABC": "abc",
    "PRONOSTICO": "pronostico",
    "TIPO": "tipo",
    "EMPRESA": "empresa",
    "LINEA": "linea",
}
OBLIGATORIAS = ["site", "whse", "loc", "non_net", "lot", "item", "supply_site", "on_hand", "cost", "total_cost"]


@dataclass
class Inventario:
    anio: int
    mes: int
    detalle: list[dict] = field(default_factory=list)
    catalogo: dict[tuple[str, str], dict] = field(default_factory=dict)
    acumuladas: list[dict] = field(default_factory=list)

    @property
    def supply_sites(self) -> list[str]:
        return sorted({r["SupplySite"] for r in self.detalle})

    def resumen(self) -> str:
        total = sum((r["TotalCost"] for r in self.detalle), Decimal(0))
        lineas = [
            f"Periodo: {self.anio}-{self.mes:02d}",
            f"Renglones de detalle: {len(self.detalle):,}",
            f"Artículos en catálogo: {len(self.catalogo):,}",
            f"Renglones acumulados: {len(self.acumuladas):,}",
            f"Costo total: ${total:,.2f}",
            "Por supply-site:",
        ]
        por_ss: dict[str, Decimal] = defaultdict(Decimal)
        for r in self.detalle:
            por_ss[r["SupplySite"]] += r["TotalCost"]
        lineas += [f"  {ss}: ${valor:,.2f}" for ss, valor in sorted(por_ss.items())]
        return "\n".join(lineas)


def leer_inventario(ruta: str | Path) -> Inventario:
    from openpyxl import load_workbook  # import local: solo se necesita para Excel

    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        hoja = libro.worksheets[0]
        filas = hoja.iter_rows(values_only=True)
        primera = next(filas, None)
        encabezados = next(filas, None)
        if not primera or not encabezados:
            raise ErrorDeArchivo("El Excel debe traer el año y mes en la fila 1 y los encabezados en la fila 2.")

        anio = _entero(primera[0], "Año (A1)", 1)
        mes = _entero(primera[1], "Mes (B1)", 1)
        _validar_periodo(anio, mes, 1)

        indice: dict[str, int] = {}
        for i, nombre in enumerate(encabezados):
            interno = COLUMNAS_EXCEL.get(_normalizar(nombre))
            if interno and interno not in indice:
                indice[interno] = i
        faltan = [c for c in OBLIGATORIAS if c not in indice]
        if faltan:
            raise ErrorDeArchivo(f"Faltan columnas en la fila 2 del Excel: {', '.join(faltan)}.")

        inv = Inventario(anio=anio, mes=mes)
        llaves_vistas: set[tuple] = set()
        mayor_costo: dict[tuple[str, str], Decimal] = {}
        acumulado: dict[tuple, dict] = {}

        for numero, fila in enumerate(filas, start=3):
            def v(nombre: str):
                i = indice.get(nombre)
                return fila[i] if i is not None and i < len(fila) else None

            item = _texto(v("item")).upper()  # SQL Server no distingue mayúsculas: "tm-302" = "TM-302"
            if not item:
                continue  # renglón vacío
            site = _texto(v("site"))
            supply_site = _texto(v("supply_site")) or site  # regla: si SUPPLY-SITE viene vacío se usa SITE
            if not supply_site:
                raise ErrorDeArchivo(f"Fila {numero}: no trae SUPPLY-SITE ni SITE.")
            non_net = _texto(v("non_net")).lower()
            if non_net not in ("no", "yes"):
                raise ErrorDeArchivo(f"Fila {numero}: NON-NETTABLE debe ser 'no' o 'yes' ({non_net!r}).")

            detalle = {
                "SupplySite": supply_site,
                "Anio": anio,
                "Mes": mes,
                "Whse": _texto(v("whse")),
                "Loc": _texto(v("loc")),
                "Item": item,
                "Lot": _texto(v("lot")),
                "Site": site,
                "NonNetteable": non_net,
                "OnHand": _decimal(v("on_hand"), 4, "ON-HAND", numero),
                "Costo": _decimal(v("cost"), 8, "COST", numero),
                "TotalCost": _decimal(v("total_cost"), 4, "TOTAL-COST", numero),
                "Pronostico": _decimal(v("pronostico"), 4, "PRONOSTICO", numero),
                "Empresa": _texto(v("empresa")) or None,
            }
            llave = (supply_site, site, detalle["Whse"], detalle["Loc"], item, detalle["Lot"])
            if llave in llaves_vistas:
                raise ErrorDeArchivo(
                    f"Fila {numero}: renglón repetido (supply-site {supply_site}, site {site}, whse {detalle['Whse']}, "
                    f"loc {detalle['Loc']}, item {item}, lot {detalle['Lot'] or '(vacío)'})."
                )
            llaves_vistas.add(llave)
            inv.detalle.append(detalle)

            # Catálogo: si un artículo trae datos distintos en varios renglones,
            # se toman los del renglón con mayor costo total.
            tipo = _texto(v("tipo")) or None
            llave_cat = (supply_site, item)
            if llave_cat not in mayor_costo or detalle["TotalCost"] > mayor_costo[llave_cat]:
                mayor_costo[llave_cat] = detalle["TotalCost"]
                stat = _texto(v("stat")).upper() or None
                if stat is not None and stat not in ("A", "S", "O"):
                    raise ErrorDeArchivo(f"Fila {numero}: STAT debe ser A, S u O ({stat!r}).")
                inv.catalogo[llave_cat] = {
                    "SupplySite": supply_site,
                    "Item": item,
                    "Descripcion": _texto(v("desc")) or None,
                    "Linea": _texto(v("linea")) or None,
                    "ProdCode": _texto(v("prodcode")) or None,
                    "UM": _texto(v("um")) or None,
                    "Stat": stat,
                    "ABC": _texto(v("abc")) or None,
                    "Tipo": tipo,
                }

            llave_acum = (supply_site, item, site, non_net)
            fila_acum = acumulado.setdefault(llave_acum, {
                "SupplySite": supply_site,
                "Anio": anio,
                "Mes": mes,
                "Item": item,
                "Site": site,
                "NonNetteable": non_net,
                "Tipo": tipo,
                "OnHand": Decimal(0),
                "CostoTotal": Decimal(0),
            })
            fila_acum["OnHand"] += detalle["OnHand"]
            fila_acum["CostoTotal"] += detalle["TotalCost"]

        if not inv.detalle:
            raise ErrorDeArchivo("El Excel no trae renglones de inventario.")
        inv.acumuladas = list(acumulado.values())
        return inv
    finally:
        libro.close()


# ----------------------------------------------------------------------------
# Balance contable (txt separado por |)
# ----------------------------------------------------------------------------

@dataclass
class Balance:
    supply_site: str
    anio: int
    mes: int
    cuentas: list[dict] = field(default_factory=list)

    def resumen(self) -> str:
        cargos = sum((c["Cargos"] for c in self.cuentas), Decimal(0))
        abonos = sum((c["Abonos"] for c in self.cuentas), Decimal(0))
        return "\n".join([
            f"Supply-site: {self.supply_site}",
            f"Periodo: {self.anio}-{self.mes:02d}",
            f"Cuentas: {len(self.cuentas):,}",
            f"Cargos: ${cargos:,.2f}",
            f"Abonos: ${abonos:,.2f}",
            f"Cuadra (cargos = abonos): {'sí' if cargos == abonos else 'NO'}",
        ])


def _leer_texto(ruta: str | Path) -> str:
    datos = Path(ruta).read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252")


_IMPORTE = r"((?:-\s*)?\d[\d,]*\.\d{2})"
_RENGLON_REPORTE = re.compile(
    r"^(\d{4}-\d{4})\s+(.*?)\s+" + r"\s+".join([_IMPORTE] * 4) + r"\s*$"
)
_MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
          "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12}
_EMPRESAS = {"TOMCO": "STOM", "TOM": "STOM"}


def periodo_desde_nombre(ruta: str | Path) -> tuple[str | None, int | None, int | None]:
    """'Tomco-Balanza-sept26.txt' -> ('STOM', 2026, 9). Devuelve None en lo que no reconozca."""
    nombre = Path(ruta).stem
    partes = [p for p in re.split(r"[^A-Za-z0-9]+", nombre) if p]
    supply_site = next((_EMPRESAS[p.upper()] for p in partes if p.upper() in _EMPRESAS), None)
    anio = mes = None
    for p in partes:
        m = re.fullmatch(r"([A-Za-z]+)(\d{2}|\d{4})", p)
        if m and m.group(1).lower() in _MESES:
            mes = _MESES[m.group(1).lower()]
            anio = int(m.group(2)) + (2000 if len(m.group(2)) == 2 else 0)
    return supply_site, anio, mes


def _importe_reporte(texto: str) -> Decimal:
    return Decimal(re.sub(r"[\s,]", "", texto))


def leer_balance_reporte(ruta: str | Path, supply_site: str | None = None,
                         anio: int | None = None, mes: int | None = None) -> Balance:
    """Balanza en columnas fijas (encabezado 'Account  Description ...'). No trae supply-site ni
    periodo: se toman de los parámetros o del nombre del archivo (p. ej. Tomco-Balanza-sept26)."""
    ss_nombre, anio_nombre, mes_nombre = periodo_desde_nombre(ruta)
    supply_site, anio, mes = supply_site or ss_nombre, anio or anio_nombre, mes or mes_nombre
    if not (supply_site and anio and mes):
        raise ErrorDeArchivo(
            "Esta balanza no trae supply-site ni periodo y no los pude sacar del nombre del archivo. "
            "Indícalos con --supply-site, --anio y --mes."
        )
    _validar_periodo(anio, mes, 1)
    balance = Balance(supply_site=supply_site, anio=anio, mes=mes)
    vistas: set[str] = set()
    for numero, linea in enumerate(_leer_texto(ruta).splitlines(), start=1):
        if not linea.strip() or linea.startswith(("Account", "----")):
            continue
        m = _RENGLON_REPORTE.match(linea)
        if not m:
            raise ErrorDeArchivo(f"Línea {numero}: no tiene el formato cuenta, descripción y 4 importes.")
        cuenta = m.group(1).replace("-", "")
        if cuenta in vistas:
            raise ErrorDeArchivo(f"Línea {numero}: la cuenta {cuenta} está repetida.")
        vistas.add(cuenta)
        saldo_ini, cargos, abonos, saldo_fin = (_importe_reporte(x) for x in m.groups()[2:])
        balance.cuentas.append({
            "SupplySite": supply_site, "Anio": anio, "Mes": mes, "Cuenta": cuenta,
            "Descripcion": m.group(2).strip() or None,
            "SaldoInicial": saldo_ini, "Cargos": cargos, "Abonos": abonos, "SaldoFinal": saldo_fin,
        })
    if not balance.cuentas:
        raise ErrorDeArchivo("La balanza no trae cuentas.")
    return balance


def es_balanza_reporte(ruta: str | Path) -> bool:
    lineas = _leer_texto(ruta).splitlines()
    return bool(lineas) and lineas[0].lstrip().startswith("Account")


def leer_balance(ruta: str | Path, supply_site: str | None = None,
                 anio: int | None = None, mes: int | None = None) -> Balance:
    if es_balanza_reporte(ruta):
        return leer_balance_reporte(ruta, supply_site, anio, mes)
    lineas = _leer_texto(ruta).splitlines()
    if not lineas:
        raise ErrorDeArchivo("El archivo de balance está vacío.")

    encabezado = [p.strip() for p in lineas[0].split("|")]
    if len(encabezado) < 3 or not encabezado[0]:
        raise ErrorDeArchivo("La primera línea del balance debe ser supply-site|año|mes.")
    anio = _entero(encabezado[1], "Año", 1)
    mes = _entero(encabezado[2], "Mes", 1)
    _validar_periodo(anio, mes, 1)
    balance = Balance(supply_site=encabezado[0], anio=anio, mes=mes)

    vistas: set[str] = set()
    for numero, linea in enumerate(lineas[1:], start=2):
        if "|" not in linea:
            continue  # líneas de totales ("Site Total"), separadores o vacías
        partes = [p.strip() for p in linea.split("|")]
        if partes and partes[-1] == "":
            partes.pop()  # cada línea termina con | final
        if len(partes) < 6:
            raise ErrorDeArchivo(f"Línea {numero}: se esperaban 6 campos separados por | y hay {len(partes)}.")
        cuenta = partes[0]
        if not cuenta:
            raise ErrorDeArchivo(f"Línea {numero}: la cuenta viene vacía.")
        if cuenta in vistas:
            raise ErrorDeArchivo(f"Línea {numero}: la cuenta {cuenta} está repetida.")
        vistas.add(cuenta)
        # Los 4 importes son siempre los últimos campos; si la descripción trajera un |, se conserva.
        importes = partes[-4:]
        descripcion = "|".join(partes[1:-4])
        saldo_ini, cargos, abonos, saldo_fin = (
            _decimal(x, 2, nombre, numero)
            for x, nombre in zip(importes, ["Saldo inicial", "Cargos", "Abonos", "Saldo final"])
        )
        balance.cuentas.append({
            "SupplySite": balance.supply_site,
            "Anio": anio,
            "Mes": mes,
            "Cuenta": cuenta,
            "Descripcion": descripcion or None,
            "SaldoInicial": saldo_ini,
            "Cargos": cargos,
            "Abonos": abonos,
            "SaldoFinal": saldo_fin,
        })

    if not balance.cuentas:
        raise ErrorDeArchivo("El balance no trae cuentas.")
    return balance


# ----------------------------------------------------------------------------
# Catálogo de product code (Excel: prodcode -> cuenta de inventario)
# ----------------------------------------------------------------------------

COLUMNAS_PRODCODE = {
    "SUPPLY-SITE": "supply_site",
    "PRODUCT-CODE": "prodcode",
    "PORDUCT-CODE": "prodcode",
    "PRODCODE": "prodcode",
    "PRODUCT CODE": "prodcode",
    "CTA": "cuenta",
    "CUENTA": "cuenta",
    "CUENTA DE INVENTARIO": "cuenta",
    "DESC CUENTA": "desc_cuenta",
    "DESCRIPCION CUENTA": "desc_cuenta",
    "DESCRIPCION PRODUCT-CODE": "desc_prodcode",
    "DESCRIPCION PRODCODE": "desc_prodcode",
    "DESCRIPCION": "desc_prodcode",
}


@dataclass
class CatalogoProdCode:
    registros: dict[tuple[str, str], dict] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)

    def resumen(self) -> str:
        por_ss: dict[str, int] = defaultdict(int)
        for ss, _ in self.registros:
            por_ss[ss] += 1
        lineas = [f"Product codes: {len(self.registros):,}", "Por supply-site:"]
        lineas += [f"  {ss}: {n:,}" for ss, n in sorted(por_ss.items())]
        lineas += [f"Aviso: {a}" for a in self.avisos]
        return "\n".join(lineas)


def es_excel_de_inventario(ruta: str | Path) -> bool:
    """El Excel de inventario trae el año (un número) en A1; el catálogo trae encabezados."""
    from openpyxl import load_workbook

    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        primera = next(libro.worksheets[0].iter_rows(max_row=1, values_only=True), ())
    finally:
        libro.close()
    a1 = primera[0] if primera else None
    return isinstance(a1, (int, float)) or (isinstance(a1, str) and a1.strip().isdigit())


def leer_catalogo_prodcode(ruta: str | Path) -> CatalogoProdCode:
    from openpyxl import load_workbook

    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        filas = libro.worksheets[0].iter_rows(values_only=True)
        encabezados = next(filas, None) or ()
        indice: dict[str, int] = {}
        for i, nombre in enumerate(encabezados):
            interno = COLUMNAS_PRODCODE.get(_normalizar(nombre))
            if interno and interno not in indice:
                indice[interno] = i
        faltan = [c for c in ("supply_site", "prodcode", "cuenta") if c not in indice]
        if faltan:
            raise ErrorDeArchivo(f"Faltan columnas en la fila 1 del catálogo: {', '.join(faltan)}.")

        # Se juntan todas las cuentas que trae cada product code para detectar conflictos.
        vistos: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for numero, fila in enumerate(filas, start=2):
            def v(nombre: str):
                i = indice.get(nombre)
                return fila[i] if i is not None and i < len(fila) else None

            ss, prodcode, cuenta = _texto(v("supply_site")), _texto(v("prodcode")), _texto(v("cuenta"))
            if not (ss or prodcode or cuenta):
                continue
            if not (ss and prodcode and cuenta):
                raise ErrorDeArchivo(f"Fila {numero}: faltan supply-site, product code o cuenta.")
            vistos[(ss, prodcode)].append({
                "SupplySite": ss,
                "ProdCode": prodcode,
                "Descripcion": _texto(v("desc_prodcode")) or None,
                "CuentaInventario": cuenta,
                "DescripcionCuenta": _texto(v("desc_cuenta")) or None,
            })

        catalogo = CatalogoProdCode()
        for llave, opciones in vistos.items():
            cuentas = [o["CuentaInventario"] for o in opciones]
            if len(set(cuentas)) > 1:
                # Conflicto: se usa la cuenta que más se repite y se avisa.
                elegida = max(set(cuentas), key=lambda c: (cuentas.count(c), c))
                catalogo.avisos.append(
                    f"{llave[0]} prodcode {llave[1]} trae varias cuentas "
                    f"({', '.join(sorted(set(cuentas)))}); se usa {elegida}."
                )
                opciones = [o for o in opciones if o["CuentaInventario"] == elegida]
            catalogo.registros[llave] = opciones[0]

        if not catalogo.registros:
            raise ErrorDeArchivo("El catálogo de product code no trae renglones.")
        return catalogo
    finally:
        libro.close()
