-- Parámetros del escenario cargados desde la semilla (fecha de referencia, umbral HITL, caso, semilla)
CREATE TABLE ParametroEscenario (
    clave VARCHAR(40)   NOT NULL,
    valor NVARCHAR(100) NOT NULL,
    CONSTRAINT PK_ParametroEscenario PRIMARY KEY (clave)
);
