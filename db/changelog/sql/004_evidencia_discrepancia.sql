-- Evidencias recibidas y contradicciones entre fuentes
CREATE TABLE Evidencia (
    evidencia_id   BIGINT IDENTITY(1,1) NOT NULL,
    ticket_id      VARCHAR(30)   NOT NULL,
    tipo           VARCHAR(10)   NOT NULL,
    sha256         CHAR(64)      NOT NULL,
    ruta           NVARCHAR(260) NULL,
    extraccion_json NVARCHAR(MAX) NULL,
    valida         BIT           NOT NULL,
    creado_en      DATETIME2     NOT NULL CONSTRAINT DF_Evid_creado DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Evidencia PRIMARY KEY (evidencia_id),
    CONSTRAINT FK_Evid_Ticket FOREIGN KEY (ticket_id) REFERENCES Ticket (ticket_id),
    CONSTRAINT CK_Evid_tipo CHECK (tipo IN ('audio','imagen','pdf','texto'))
);

CREATE TABLE Discrepancia (
    discrepancia_id  BIGINT IDENTITY(1,1) NOT NULL,
    ticket_id        VARCHAR(30)   NOT NULL,
    campo            VARCHAR(40)   NOT NULL,
    valor_percepcion NVARCHAR(200) NULL,
    valor_maestro    NVARCHAR(200) NULL,
    fuente_ganadora  VARCHAR(20)   NOT NULL CONSTRAINT DF_Disc_fuente DEFAULT 'MAESTRO',
    accion           VARCHAR(30)   NOT NULL,
    creado_en        DATETIME2     NOT NULL CONSTRAINT DF_Disc_creado DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Discrepancia PRIMARY KEY (discrepancia_id),
    CONSTRAINT FK_Disc_Ticket FOREIGN KEY (ticket_id) REFERENCES Ticket (ticket_id)
);
