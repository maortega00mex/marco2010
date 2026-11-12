# Dashboard de costos e inventarios

Página web que corre en tu computadora y lee directo de la base `invDinamex` en SQL Server.

## Instalación (una sola vez)

```
cd C:\IA_Model\Dinamex_Inventario\dashboard
pip install -r requirements.txt
```

Requiere el ODBC Driver 18 for SQL Server (el mismo que usa el cargador).

## Abrirlo

1. Edita `iniciar_dashboard.bat` y pon el nombre de tu servidor en `SERVER=`.
2. Haz doble clic en `iniciar_dashboard.bat`.
3. Abre http://localhost:5000 en el navegador.

Para detenerlo, cierra la ventana negra (o Ctrl+C).

## Qué muestra

- **Indicadores:** costo total, lento movimiento (S), obsoleto (O) y material en inspección.
- **Conciliación contable:** inventario contra saldo final del balance por cuenta (vista `dbo.vConciliacionContable`). Solo la filtran periodo y supply-site.
- **Tendencia** del costo por mes, y desglose **por stat, tipo, site y línea**.
- **Los 15 artículos de mayor costo.**

Filtros: periodo, supply-site, site, línea, stat, tipo y material (disponible / inspección). Pasa el mouse sobre las barras para ver el detalle.
