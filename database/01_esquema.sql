/* =====================================================================
   Dashboard de Costos e Inventarios - Esquema de base de datos
   Motor: SQL Server 2016 o superior
   Moneda: todos los importes en moneda nacional (MXN)

   El script se puede ejecutar varias veces: solo crea lo que no existe.
   Orden de carga esperado (paso 2):
     1. inv.CatalogoProdCode   (manual / archivo pendiente)
     2. inv.CatalogoArticulos  (desde Excel de inventario)
     3. inv.ExistenciasDetalle (desde Excel de inventario)
     4. inv.ExistenciasAcumuladas (desde Excel, agrupando el detalle)
     5. inv.BalanceContable    (desde txt separado por |)
   ===================================================================== */

IF SCHEMA_ID('inv') IS NULL
    EXEC('CREATE SCHEMA inv');
GO

/* ---------------------------------------------------------------------
   Catálogo de Product Code
   Relaciona cada product code con su cuenta contable de inventario.
   Es la base de la conciliación contable.
   --------------------------------------------------------------------- */
IF OBJECT_ID('inv.CatalogoProdCode', 'U') IS NULL
CREATE TABLE inv.CatalogoProdCode (
    SupplySite           VARCHAR(10)   NOT NULL,  -- empresa propietaria del inventario
    ProdCode             VARCHAR(20)   NOT NULL,
    Descripcion          NVARCHAR(150) NULL,
    CuentaInventario     VARCHAR(20)   NULL,      -- cuenta del balance, p. ej. 11700002
    DescripcionCuenta    NVARCHAR(150) NULL,
    FechaActualizacion   DATETIME2(0)  NOT NULL CONSTRAINT DF_CatalogoProdCode_Fecha DEFAULT SYSDATETIME(),
    CONSTRAINT PK_CatalogoProdCode PRIMARY KEY (SupplySite, ProdCode)
);
GO

/* ---------------------------------------------------------------------
   Catálogo de Artículos
   Se carga desde el Excel; si un artículo ya existe y cambian sus
   valores, se actualiza (MERGE en el proceso de carga).
   --------------------------------------------------------------------- */
IF OBJECT_ID('inv.CatalogoArticulos', 'U') IS NULL
CREATE TABLE inv.CatalogoArticulos (
    SupplySite           VARCHAR(10)   NOT NULL,
    Item                 VARCHAR(40)   NOT NULL,
    Descripcion          NVARCHAR(150) NULL,
    Linea                NVARCHAR(60)  NULL,
    ProdCode             VARCHAR(20)   NULL,
    UM                   VARCHAR(10)   NULL,
    Stat                 CHAR(1)       NULL,      -- A = Activo, S = Lento movimiento, O = Obsoleto
    ABC                  VARCHAR(2)    NULL,
    Tipo                 VARCHAR(5)    NULL,      -- MP / PT
    FechaActualizacion   DATETIME2(0)  NOT NULL CONSTRAINT DF_CatalogoArticulos_Fecha DEFAULT SYSDATETIME(),
    CONSTRAINT PK_CatalogoArticulos PRIMARY KEY (SupplySite, Item),
    CONSTRAINT CK_CatalogoArticulos_Stat CHECK (Stat IN ('A', 'S', 'O'))
);
GO

/* ---------------------------------------------------------------------
   Existencias Detalle
   Un renglón por cada renglón del Excel (ubicación y lote).
   Site va en la llave: el mismo whse/loc/lote puede existir en dos sites
   para un mismo supply-site.
   SupplySite = SUPPLY-SITE del Excel; si viene vacío se usa SITE.
   Lote vacío se guarda como '' (una llave primaria no admite NULL).
   Sin llave foránea al catálogo, para poder cargar cada tabla por separado.
   --------------------------------------------------------------------- */
IF OBJECT_ID('inv.ExistenciasDetalle', 'U') IS NULL
CREATE TABLE inv.ExistenciasDetalle (
    SupplySite           VARCHAR(10)   NOT NULL,
    Anio                 SMALLINT      NOT NULL,
    Mes                  TINYINT       NOT NULL,
    Whse                 VARCHAR(10)   NOT NULL,
    Loc                  VARCHAR(30)   NOT NULL,
    Item                 VARCHAR(40)   NOT NULL,
    Lot                  VARCHAR(40)   NOT NULL CONSTRAINT DF_ExistenciasDetalle_Lot DEFAULT '',
    Site                 VARCHAR(10)   NOT NULL,  -- empresa que tiene físicamente el inventario
    NonNetteable         VARCHAR(3)    NOT NULL,  -- no = Disponible, yes = Inspección
    OnHand               DECIMAL(18,4) NOT NULL,
    Costo                DECIMAL(19,8) NOT NULL,  -- costo unitario
    TotalCost            DECIMAL(19,4) NOT NULL,
    Pronostico           DECIMAL(18,4) NULL,
    Empresa              NVARCHAR(150) NULL,
    CONSTRAINT PK_ExistenciasDetalle PRIMARY KEY (SupplySite, Anio, Mes, Site, Whse, Loc, Item, Lot),
    CONSTRAINT CK_ExistenciasDetalle_Mes CHECK (Mes BETWEEN 1 AND 12),
    CONSTRAINT CK_ExistenciasDetalle_NonNet CHECK (NonNetteable IN ('no', 'yes'))
);
GO

/* ---------------------------------------------------------------------
   Existencias Acumuladas por artículo
   Resumen mensual del detalle. Un mismo artículo puede estar en varios
   sites y en disponible / inspección, por eso Site y NonNetteable
   forman parte de la llave.
   CostoPromedio se calcula solo: CostoTotal / OnHand.
   --------------------------------------------------------------------- */
IF OBJECT_ID('inv.ExistenciasAcumuladas', 'U') IS NULL
CREATE TABLE inv.ExistenciasAcumuladas (
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

/* ---------------------------------------------------------------------
   Balance Contable
   Se carga desde un txt separado por |. La primera línea trae
   supply-site|año|mes; la línea "Site Total" del final se ignora.
   --------------------------------------------------------------------- */
IF OBJECT_ID('inv.BalanceContable', 'U') IS NULL
CREATE TABLE inv.BalanceContable (
    SupplySite           VARCHAR(10)   NOT NULL,
    Anio                 SMALLINT      NOT NULL,
    Mes                  TINYINT       NOT NULL,
    Cuenta               VARCHAR(20)   NOT NULL,
    Descripcion          NVARCHAR(150) NULL,
    SaldoInicial         DECIMAL(19,2) NOT NULL,
    Cargos               DECIMAL(19,2) NOT NULL,
    Abonos               DECIMAL(19,2) NOT NULL,
    SaldoFinal           DECIMAL(19,2) NOT NULL,
    CONSTRAINT PK_BalanceContable PRIMARY KEY (SupplySite, Anio, Mes, Cuenta),
    CONSTRAINT CK_BalanceContable_Mes CHECK (Mes BETWEEN 1 AND 12)
);
GO

/* Índices de apoyo para filtros del dashboard */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_CatalogoArticulos_ProdCode')
    CREATE INDEX IX_CatalogoArticulos_ProdCode ON inv.CatalogoArticulos (SupplySite, ProdCode);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_ExistenciasDetalle_Item')
    CREATE INDEX IX_ExistenciasDetalle_Item ON inv.ExistenciasDetalle (SupplySite, Item, Anio, Mes)
        INCLUDE (OnHand, TotalCost);
GO
