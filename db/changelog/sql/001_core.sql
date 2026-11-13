-- Núcleo bancario: Cliente, Cuenta, Balance, Tarjeta (datos 100% sintéticos)
CREATE TABLE Cliente (
    cliente_id   VARCHAR(20)   NOT NULL,
    nombre_mask  NVARCHAR(60)  NOT NULL,
    doc_hash     CHAR(64)      NOT NULL,
    email_mask   NVARCHAR(80)  NOT NULL,
    segmento     VARCHAR(20)   NOT NULL,
    estado       VARCHAR(12)   NOT NULL CONSTRAINT DF_Cliente_estado DEFAULT 'ACTIVO',
    caso_id      VARCHAR(30)   NULL,
    semilla      INT           NULL,
    creado_en    DATETIME2     NOT NULL CONSTRAINT DF_Cliente_creado DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Cliente PRIMARY KEY (cliente_id),
    CONSTRAINT CK_Cliente_estado CHECK (estado IN ('ACTIVO','BLOQUEADO'))
);

CREATE TABLE Cuenta (
    cuenta_id   VARCHAR(20) NOT NULL,
    cliente_id  VARCHAR(20) NOT NULL,
    tipo        VARCHAR(12) NOT NULL,
    moneda      CHAR(3)     NOT NULL,
    estado      VARCHAR(12) NOT NULL CONSTRAINT DF_Cuenta_estado DEFAULT 'ACTIVA',
    CONSTRAINT PK_Cuenta PRIMARY KEY (cuenta_id),
    CONSTRAINT FK_Cuenta_Cliente FOREIGN KEY (cliente_id) REFERENCES Cliente (cliente_id),
    CONSTRAINT CK_Cuenta_tipo CHECK (tipo IN ('AHORROS','CORRIENTE','TARJETA')),
    CONSTRAINT CK_Cuenta_moneda CHECK (moneda = 'PEN'),
    CONSTRAINT CK_Cuenta_estado CHECK (estado IN ('ACTIVA','CERRADA'))
);

CREATE TABLE Balance (
    cuenta_id        VARCHAR(20)   NOT NULL,
    saldo            DECIMAL(14,2) NOT NULL,
    saldo_disponible DECIMAL(14,2) NOT NULL,
    actualizado_en   DATETIME2     NOT NULL CONSTRAINT DF_Balance_act DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Balance PRIMARY KEY (cuenta_id),
    CONSTRAINT FK_Balance_Cuenta FOREIGN KEY (cuenta_id) REFERENCES Cuenta (cuenta_id)
);

CREATE TABLE Tarjeta (
    tarjeta_id      VARCHAR(20) NOT NULL,
    cuenta_id       VARCHAR(20) NOT NULL,
    ultimos4        CHAR(4)     NOT NULL,
    producto        NVARCHAR(40) NOT NULL,
    habilitada      BIT         NOT NULL CONSTRAINT DF_Tarjeta_hab DEFAULT 1,
    dia_facturacion TINYINT     NOT NULL,
    CONSTRAINT PK_Tarjeta PRIMARY KEY (tarjeta_id),
    CONSTRAINT FK_Tarjeta_Cuenta FOREIGN KEY (cuenta_id) REFERENCES Cuenta (cuenta_id),
    CONSTRAINT CK_Tarjeta_dia CHECK (dia_facturacion BETWEEN 1 AND 28)
);
