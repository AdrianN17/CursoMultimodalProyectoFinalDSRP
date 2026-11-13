-- Catálogo de servicios y transacciones (dato maestro)
CREATE TABLE Servicio (
    servicio_id INT          NOT NULL,
    empresa     NVARCHAR(60) NOT NULL,
    servicio    NVARCHAR(80) NOT NULL,
    categoria   VARCHAR(20)  NOT NULL,
    CONSTRAINT PK_Servicio PRIMARY KEY (servicio_id)
);

CREATE TABLE Transaccion (
    transaccion_id   VARCHAR(30)   NOT NULL,
    codigo_operacion VARCHAR(20)   NOT NULL,
    tarjeta_id       VARCHAR(20)   NOT NULL,
    servicio_id      INT           NOT NULL,
    monto            DECIMAL(12,2) NOT NULL,
    moneda           CHAR(3)       NOT NULL,
    fecha_hora       DATETIME2     NOT NULL,
    estado           VARCHAR(12)   NOT NULL CONSTRAINT DF_Tx_estado DEFAULT 'APROBADA',
    canal            VARCHAR(10)   NOT NULL,
    grupo_duplicado  VARCHAR(30)   NULL,
    anulada          BIT           NOT NULL CONSTRAINT DF_Tx_anulada DEFAULT 0,
    anulada_en       DATETIME2     NULL,
    CONSTRAINT PK_Transaccion PRIMARY KEY (transaccion_id),
    CONSTRAINT UQ_Transaccion_codigo UNIQUE (codigo_operacion),
    CONSTRAINT FK_Tx_Tarjeta FOREIGN KEY (tarjeta_id) REFERENCES Tarjeta (tarjeta_id),
    CONSTRAINT FK_Tx_Servicio FOREIGN KEY (servicio_id) REFERENCES Servicio (servicio_id),
    CONSTRAINT CK_Tx_monto CHECK (monto > 0),
    CONSTRAINT CK_Tx_moneda CHECK (moneda = 'PEN'),
    CONSTRAINT CK_Tx_estado CHECK (estado IN ('APROBADA','ANULADA','REEMBOLSADA')),
    CONSTRAINT CK_Tx_canal CHECK (canal IN ('POS','ONLINE','APP'))
);

CREATE INDEX IX_Transaccion_tarjeta ON Transaccion (tarjeta_id, fecha_hora);
