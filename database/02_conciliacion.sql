/* =====================================================================
   Conciliación contable: inventario vs balance
   Requiere SQL Server 2016 SP1 o superior (CREATE OR ALTER).

   Un renglón por SupplySite, Anio, Mes y Cuenta de inventario:
     CostoInventario  = suma del costo total de existencias detalle cuyos
                        artículos tienen un product code ligado a esa cuenta
     SaldoContable    = saldo final de la cuenta en el balance
     Diferencia       = CostoInventario - SaldoContable

   Cuenta 'SIN CUENTA' = inventario cuyo product code no está en el
   catálogo de product code (hay que darlo de alta).
   Cuentas de inventario = las que aparecen en invDinamex.CatalogoProdCode para
   ese supply-site.
   BalanceCargado = 0 cuando todavía no se carga el balance de ese
   supply-site y periodo (la diferencia no es real todavía).
   ===================================================================== */

CREATE OR ALTER VIEW invDinamex.vConciliacionContable AS
/*CONSULTA*/
WITH Inventario AS (
    SELECT d.SupplySite, d.Anio, d.Mes,
           COALESCE(p.CuentaInventario, 'SIN CUENTA') AS Cuenta,
           SUM(d.TotalCost) AS CostoInventario
    FROM invDinamex.ExistenciasDetalle d
    JOIN invDinamex.CatalogoArticulos a
      ON a.SupplySite = d.SupplySite AND a.Item = d.Item
    LEFT JOIN invDinamex.CatalogoProdCode p
      ON p.SupplySite = d.SupplySite AND p.ProdCode = a.ProdCode
    GROUP BY d.SupplySite, d.Anio, d.Mes, COALESCE(p.CuentaInventario, 'SIN CUENTA')
),
Contable AS (
    SELECT b.SupplySite, b.Anio, b.Mes, b.Cuenta, b.Descripcion, b.SaldoFinal
    FROM invDinamex.BalanceContable b
    WHERE EXISTS (SELECT 1 FROM invDinamex.CatalogoProdCode p
                  WHERE p.SupplySite = b.SupplySite AND p.CuentaInventario = b.Cuenta)
),
Unido AS (
    SELECT COALESCE(i.SupplySite, c.SupplySite) AS SupplySite,
           COALESCE(i.Anio, c.Anio)             AS Anio,
           COALESCE(i.Mes, c.Mes)               AS Mes,
           COALESCE(i.Cuenta, c.Cuenta)         AS Cuenta,
           c.Descripcion                        AS DescripcionBalance,
           COALESCE(i.CostoInventario, 0)       AS CostoInventario,
           COALESCE(c.SaldoFinal, 0)            AS SaldoContable
    FROM Inventario i
    FULL OUTER JOIN Contable c
      ON c.SupplySite = i.SupplySite AND c.Anio = i.Anio AND c.Mes = i.Mes AND c.Cuenta = i.Cuenta
)
SELECT u.SupplySite, u.Anio, u.Mes, u.Cuenta,
       COALESCE(u.DescripcionBalance,
                (SELECT MAX(p.DescripcionCuenta) FROM invDinamex.CatalogoProdCode p
                  WHERE p.SupplySite = u.SupplySite AND p.CuentaInventario = u.Cuenta),
                'Product code sin cuenta asignada') AS DescripcionCuenta,
       u.CostoInventario,
       u.SaldoContable,
       u.CostoInventario - u.SaldoContable AS Diferencia,
       CASE WHEN EXISTS (SELECT 1 FROM invDinamex.BalanceContable b
                         WHERE b.SupplySite = u.SupplySite AND b.Anio = u.Anio AND b.Mes = u.Mes)
            THEN 1 ELSE 0 END AS BalanceCargado
FROM Unido u
/*FIN*/;
GO
