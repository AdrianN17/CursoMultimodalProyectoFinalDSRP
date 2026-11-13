-- Seguridad de identidad (OTP, login) y correos al operador (outbox)
CREATE TABLE OtpChallenge (
    otp_id       VARCHAR(30) NOT NULL,
    cliente_id   VARCHAR(20) NOT NULL,
    sesion_id    VARCHAR(60) NOT NULL,
    proposito    VARCHAR(20) NOT NULL,
    otp_hash     CHAR(64)    NOT NULL,
    intentos     INT         NOT NULL CONSTRAINT DF_Otp_int DEFAULT 0,
    estado       VARCHAR(12) NOT NULL CONSTRAINT DF_Otp_estado DEFAULT 'PENDIENTE',
    creado_en    DATETIME2   NOT NULL CONSTRAINT DF_Otp_creado DEFAULT SYSUTCDATETIME(),
    expira_en    DATETIME2   NOT NULL,
    verificado_en DATETIME2  NULL,
    CONSTRAINT PK_OtpChallenge PRIMARY KEY (otp_id),
    CONSTRAINT FK_Otp_Cliente FOREIGN KEY (cliente_id) REFERENCES Cliente (cliente_id),
    CONSTRAINT CK_Otp_estado CHECK (estado IN ('PENDIENTE','VERIFICADO','FALLIDO','EXPIRADO'))
);

CREATE INDEX IX_Otp_sesion ON OtpChallenge (sesion_id, creado_en);

CREATE TABLE LoginTrack (
    login_id   BIGINT IDENTITY(1,1) NOT NULL,
    cliente_id VARCHAR(20) NOT NULL,
    sesion_id  VARCHAR(60) NOT NULL,
    canal      VARCHAR(12) NOT NULL,
    ip_hash    CHAR(64)    NULL,
    resultado  VARCHAR(20) NOT NULL,
    ts         DATETIME2   NOT NULL CONSTRAINT DF_Login_ts DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_LoginTrack PRIMARY KEY (login_id),
    CONSTRAINT FK_Login_Cliente FOREIGN KEY (cliente_id) REFERENCES Cliente (cliente_id)
);

CREATE TABLE EmailOutbox (
    email_id   BIGINT IDENTITY(1,1) NOT NULL,
    ticket_id  VARCHAR(30)   NOT NULL,
    destino    NVARCHAR(120) NOT NULL,
    asunto     NVARCHAR(200) NOT NULL,
    cuerpo     NVARCHAR(MAX) NOT NULL,
    estado     VARCHAR(12)   NOT NULL CONSTRAINT DF_Email_estado DEFAULT 'PENDIENTE',
    creado_en  DATETIME2     NOT NULL CONSTRAINT DF_Email_creado DEFAULT SYSUTCDATETIME(),
    enviado_en DATETIME2     NULL,
    CONSTRAINT PK_EmailOutbox PRIMARY KEY (email_id),
    CONSTRAINT FK_Email_Ticket FOREIGN KEY (ticket_id) REFERENCES Ticket (ticket_id),
    CONSTRAINT CK_Email_estado CHECK (estado IN ('PENDIENTE','ENVIADO','ERROR'))
);
