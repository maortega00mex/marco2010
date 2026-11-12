/* =====================================================================
   Existencias acumuladas por artículo, generadas desde dbo.ExistenciasDetalle

   Cambia @Anio y @Mes y ejecuta. Reemplaza ese periodo: si lo vuelves a
   correr no duplica. Agrupa por supply-site, artículo, site y
   non-netteable; el Tipo sale del catálogo de artículos.
   Al final valida que on-hand y costo total cuadren contra el detalle.
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO
USE invDinamex;
GO
IF OBJECT_ID('dbo.ExistenciasAcumuladas', 'U') IS NULL
CREATE TABLE dbo.ExistenciasAcumuladas (
    SupplySite           VARCHAR(10)   NOT NULL,
    Anio                 SMALLINT      NOT NULL,
    Mes                  TINYINT       NOT NULL,
    Item                 VARCHAR(40)   NOT NULL,
    Site                 VARCHAR(10)   NOT NULL,
    NonNetteable         VARCHAR(3)    NOT NULL,
    Tipo                 VARCHAR(5)    NULL,
    OnHand               DECIMAL(18,4) NOT NULL,
    CostoTotal           DECIMAL(19,4) NOT NULL,
    CostoPromedio        AS CAST(CostoTotal / NULLIF(OnHand, 0) AS DECIMAL(19,8)) PERSISTED,
    CONSTRAINT PK_ExistenciasAcumuladas PRIMARY KEY (SupplySite, Anio, Mes, Item, Site, NonNetteable),
    CONSTRAINT CK_ExistenciasAcumuladas_Mes CHECK (Mes BETWEEN 1 AND 12),
    CONSTRAINT CK_ExistenciasAcumuladas_NonNet CHECK (NonNetteable IN ('no', 'yes'))
);
GO

DECLARE @Anio SMALLINT = 2026;
DECLARE @Mes  TINYINT  = 9;

IF NOT EXISTS (SELECT 1 FROM dbo.ExistenciasDetalle WHERE Anio = @Anio AND Mes = @Mes)
BEGIN
    RAISERROR('No hay existencias detalle para ese periodo. Carga primero ExistenciasDetalle.', 16, 1);
    RETURN;
END

BEGIN TRANSACTION;

DELETE FROM dbo.ExistenciasAcumuladas WHERE Anio = @Anio AND Mes = @Mes;

INSERT INTO dbo.ExistenciasAcumuladas (SupplySite, Anio, Mes, Item, Site, NonNetteable, Tipo, OnHand, CostoTotal)
SELECT d.SupplySite, d.Anio, d.Mes, d.Item, d.Site, d.NonNetteable,
       MAX(a.Tipo) AS Tipo,
       SUM(d.OnHand) AS OnHand,
       SUM(d.TotalCost) AS CostoTotal
FROM dbo.ExistenciasDetalle d
LEFT JOIN dbo.CatalogoArticulos a
       ON a.SupplySite = d.SupplySite AND a.Item = d.Item
WHERE d.Anio = @Anio AND d.Mes = @Mes
GROUP BY d.SupplySite, d.Anio, d.Mes, d.Item, d.Site, d.NonNetteable;

DECLARE @RenglonesDet INT, @OnHandDet DECIMAL(19,4), @CostoDet DECIMAL(19,4),
        @OnHandAcu DECIMAL(19,4), @CostoAcu DECIMAL(19,4), @Renglones INT, @SinTipo INT;
SELECT @RenglonesDet = COUNT(*), @OnHandDet = SUM(OnHand), @CostoDet = SUM(TotalCost)
FROM dbo.ExistenciasDetalle WHERE Anio = @Anio AND Mes = @Mes;
SELECT @Renglones = COUNT(*), @OnHandAcu = SUM(OnHand), @CostoAcu = SUM(CostoTotal),
       @SinTipo = SUM(CASE WHEN Tipo IS NULL THEN 1 ELSE 0 END)
FROM dbo.ExistenciasAcumuladas WHERE Anio = @Anio AND Mes = @Mes;

IF @OnHandAcu <> @OnHandDet OR @CostoAcu <> @CostoDet
BEGIN
    ROLLBACK TRANSACTION;
    RAISERROR('Los totales no cuadran contra el detalle. No se guardó nada.', 16, 1);
    RETURN;
END

COMMIT TRANSACTION;
PRINT CONCAT('Carga correcta: ', @Renglones, ' renglones acumulados (de ', @RenglonesDet,
             ' de detalle). Costo total: ', FORMAT(@CostoAcu, 'N2'));
IF @SinTipo > 0
    PRINT CONCAT('Aviso: ', @SinTipo, ' renglones sin Tipo porque el artículo no está en el catálogo.');

SELECT SupplySite, Tipo, COUNT(*) AS Renglones, SUM(OnHand) AS OnHand, SUM(CostoTotal) AS CostoTotal
FROM dbo.ExistenciasAcumuladas WHERE Anio = @Anio AND Mes = @Mes
GROUP BY SupplySite, Tipo ORDER BY SupplySite, Tipo;
GO
