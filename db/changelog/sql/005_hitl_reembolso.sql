-- Aprobación humana (HITL) y efecto persistente (reembolso / anulación)
CREATE TABLE AprobacionHitl (
    aprobacion_id    VARCHAR(30)   NOT NULL,
    ticket_id        VARCHAR(30)   NOT NULL,
    accion_propuesta VARCHAR(12)   NOT NULL,
    transaccion_id   VARCHAR(30)   NOT NULL,
    monto            DECIMAL(12,2) NOT NULL,
    rol_requerido    VARCHAR(12)   NOT NULL,
    estado           VARCHAR(12)   NOT NULL CONSTRAINT DF_Aprob_estado DEFAULT 'PENDIENTE',
    aprobador        VARCHAR(60)   NULL,
    motivo           NVARCHAR(300) NULL,
    resumen_json     NVARCHAR(MAX) NULL,
    solicitada_en    DATETIME2     NOT NULL CONSTRAINT DF_Aprob_sol DEFAULT SYSUTCDATETIME(),
    expira_en        DATETIME2     NOT NULL,
    resuelta_en      DATETIME2     NULL,
    CONSTRAINT PK_AprobacionHitl PRIMARY KEY (aprobacion_id),
    CONSTRAINT FK_Aprob_Ticket FOREIGN KEY (ticket_id) REFERENCES Ticket (ticket_id),
    CONSTRAINT FK_Aprob_Tx FOREIGN KEY (transaccion_id) REFERENCES Transaccion (transaccion_id),
    CONSTRAINT CK_Aprob_accion CHECK (accion_propuesta IN ('ANULACION','REEMBOLSO')),
    CONSTRAINT CK_Aprob_rol CHECK (rol_requerido IN ('ANALISTA','SUPERVISOR')),
    CONSTRAINT CK_Aprob_estado CHECK (estado IN ('PENDIENTE','APROBADA','RECHAZADA','EXPIRADA'))
);

-- Una sola aprobación vigente por ticket y acción
CREATE UNIQUE INDEX UX_Aprob_ticket_accion ON AprobacionHitl (ticket_id, accion_propuesta);

CREATE TABLE Reembolso (
    reembolso_id    VARCHAR(30)   NOT NULL,
    ticket_id       VARCHAR(30)   NOT NULL,
    transaccion_id  VARCHAR(30)   NOT NULL,
    tipo            VARCHAR(12)   NOT NULL,
    monto           DECIMAL(12,2) NOT NULL,
    medio           VARCHAR(24)   NOT NULL,
    estado          VARCHAR(12)   NOT NULL CONSTRAINT DF_Reemb_estado DEFAULT 'PROGRAMADO',
    sla_dias_habiles INT          NOT NULL,
    fecha_estimada  DATE          NOT NULL,
    creado_en       DATETIME2     NOT NULL CONSTRAINT DF_Reemb_creado DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Reembolso PRIMARY KEY (reembolso_id),
    CONSTRAINT FK_Reemb_Ticket FOREIGN KEY (ticket_id) REFERENCES Ticket (ticket_id),
    CONSTRAINT FK_Reemb_Tx FOREIGN KEY (transaccion_id) REFERENCES Transaccion (transaccion_id),
    CONSTRAINT CK_Reemb_tipo CHECK (tipo IN ('REEMBOLSO','ANULACION')),
    CONSTRAINT CK_Reemb_estado CHECK (estado IN ('PROGRAMADO','PAGADO'))
);

-- Una sola anulación/reembolso por reclamo (política P-05)
CREATE UNIQUE INDEX UX_Reembolso_ticket ON Reembolso (ticket_id);
