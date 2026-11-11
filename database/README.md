# Base de datos: Costos e Inventarios

Scripts de SQL Server para el dashboard de costos e inventarios.

## Cómo crear las tablas

Ejecuta `01_esquema.sql` en tu base de datos (SSMS, Azure Data Studio o `sqlcmd`):

```
sqlcmd -S <servidor> -d <base_de_datos> -i database/01_esquema.sql
```

El script se puede correr varias veces: solo crea lo que falta. Todo queda en el esquema `inv`.

## Tablas

| Tabla | Llave primaria | Origen |
|---|---|---|
| `inv.ExistenciasDetalle` | SupplySite, Anio, Mes, Site, Whse, Loc, Item, Lot | Excel de inventario (un renglón por ubicación y lote) |
| `inv.CatalogoArticulos` | SupplySite, Item | Excel de inventario; se actualiza si cambian los valores |
| `inv.ExistenciasAcumuladas` | SupplySite, Anio, Mes, Item, Site, NonNetteable | Excel de inventario, agrupando el detalle |
| `inv.CatalogoProdCode` | SupplySite, ProdCode | Pendiente: relación prodcode → cuenta de inventario |
| `inv.BalanceContable` | SupplySite, Anio, Mes, Cuenta | txt separado por `\|` |

## Reglas

- **SupplySite**: se toma de la columna SUPPLY-SITE del Excel; si viene vacía se usa SITE.
- **Lot** vacío se guarda como texto vacío (`''`).
- **NonNetteable**: `no` = material disponible, `yes` = material en inspección.
- **Stat**: `A` = activo, `S` = lento movimiento, `O` = obsoleto.
- **CostoPromedio** en existencias acumuladas se calcula solo (CostoTotal / OnHand).
- Importes en moneda nacional.
