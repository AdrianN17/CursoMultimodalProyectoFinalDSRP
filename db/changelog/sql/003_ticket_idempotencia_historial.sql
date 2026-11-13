-- Gestión de tickets: ticket, idempotencia e historial
CREATE TABLE Ticket (
    ticket_id             VARCHAR(30)  NOT NULL,
    cliente_id            VARCHAR(20)  NOT NULL,
    transaccion_id        VARCHAR(30)  NULL,
    tipo_reclamo          VARCHAR(30)  NULL,
    estado                VARCHAR(24)  NOT NULL CONSTRAINT DF_Ticket_estado DEFAULT 'ABIERTO',
    resolucion            VARCHAR(20)  NULL,
    caso_id               VARCHAR(30)  NOT NULL,
    semilla               INT          NOT NULL,
    trace_id              VARCHAR(40)  NULL,
    thread_id             VARCHAR(100) NULL,
    accion_ejecutada      VARCHAR(12)  NULL,
    transaccion_accion_id VARCHAR(30)  NULL,
    creado_en             DATETIME2    NOT NULL CONSTRAINT DF_Ticket_creado DEFAULT SYSUTCDATETIME(),
    actualizado_en        DATETIME2    NOT NULL CONSTRAINT DF_Ticket_act DEFAULT SYSUTCDATETIME(),
    cerrado_en            DATETIME2    NULL,
    CONSTRAINT PK_Ticket PRIMARY KEY (ticket_id),
    CONSTRAINT FK_Ticket_Cliente FOREIGN KEY (cliente_id) REFERENCES Cliente (cliente_id),
    CONSTRAINT FK_Ticket_Tx FOREIGN KEY (transaccion_id) REFERENCES Transaccion (transaccion_id),
    CONSTRAINT CK_Ticket_estado CHECK (estado IN ('ABIERTO','EN_ANALISIS','PENDIENTE_APROBACION','EN_ESCALAMIENTO','PENDIENTE_TECNICO','CERRADO')),
    CONSTRAINT CK_Ticket_resolucion CHECK (resolucion IS NULL OR resolucion IN ('REEMBOLSO','ANULACION','RECHAZADO','INFORMATIVO','ESCALADO','EXPIRADO')),
    CONSTRAINT CK_Ticket_accion CHECK (accion_ejecutada IS NULL OR accion_ejecutada IN ('ANULACION','REEMBOLSO'))
);

CREATE INDEX IX_Ticket_cliente ON Ticket (cliente_id, creado_en);

CREATE TABLE IdempotencyKey (
    idem_key       VARCHAR(80)   NOT NULL,
    scope          VARCHAR(30)   NOT NULL,
    request_hash   CHAR(64)      NOT NULL,
    ticket_id      VARCHAR(30)   NULL,
    respuesta_json NVARCHAR(MAX) NULL,
    creado_en      DATETIME2     NOT NULL CONSTRAINT DF_Idem_creado DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_IdempotencyKey PRIMARY KEY (idem_key),
    CONSTRAINT FK_Idem_Ticket FOREIGN KEY (ticket_id) REFERENCES Ticket (ticket_id)
);

CREATE TABLE TicketEvento (
    evento_id    BIGINT IDENTITY(1,1) NOT NULL,
    ticket_id    VARCHAR(30)   NOT NULL,
    tipo         VARCHAR(40)   NOT NULL,
    detalle_json NVARCHAR(MAX) NULL,
    actor        VARCHAR(12)   NOT NULL,
    trace_id     VARCHAR(40)   NULL,
    ts           DATETIME2     NOT NULL CONSTRAINT DF_Evento_ts DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_TicketEvento PRIMARY KEY (evento_id),
    CONSTRAINT FK_Evento_Ticket FOREIGN KEY (ticket_id) REFERENCES Ticket (ticket_id),
    CONSTRAINT CK_Evento_actor CHECK (actor IN ('agente','analista','sistema','cliente'))
);

CREATE INDEX IX_TicketEvento_ticket ON TicketEvento (ticket_id, ts);
