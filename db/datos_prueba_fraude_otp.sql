-- =====================================================================================================
-- Datos de prueba de FRAUDE: operaciones con y sin OTP (columna Transaccion.autenticada_otp, política P-11)
-- 100 % sintéticos. SQL Server / Azure SQL. Idempotente: se puede ejecutar varias veces.
-- Todas las tablas se califican con el esquema `multimodal` (AZURE_SQL_SCHEMA): puede ejecutarse tal cual en
-- Azure Data Studio / SSMS, o con `python scripts/cargar_datos_fraude.py` (que adapta el esquema si es otro).
--
-- Requisitos: esquema aplicado (changeSets 001-009, incluye el catálogo de servicios del 007).
-- Orden de uso:
--   1) python scripts/aplicar_esquema.py            (o Liquibase)
--   2) python scripts/seed_db.py --caso-id C-07 --semilla 4213   (BORRA los datos de negocio: ejecútelo ANTES)
--   3) ejecutar este archivo:  python scripts/cargar_datos_fraude.py
--
-- Convención:  autenticada_otp = 1 -> la operación se confirmó con el OTP/PIN del cliente
--              autenticada_otp = 0 -> se procesó SIN OTP (indicio de fraude si el cliente la desconoce)
--
-- Clientes (dia_facturacion = 28: con fecha_referencia del escenario entre 09-oct y 21-oct, el último corte
-- es SIEMPRE el 28-sep-2026, así que 'facturada' es estable):
--   CLI-9001 Lucía  : desconoce compras que SÍ validó con OTP   -> P-11: se escala a operador (ingeniería social)
--   CLI-9002 Mateo  : ráfaga de compras ONLINE SIN OTP           -> fraude probable: reclamo normal + aprobación humana
--   CLI-9003 Rosa   : uso normal + un cobro duplicado con OTP    -> duplicado se atiende por P-01/P-03
-- =====================================================================================================

-- Catálogo de servicios (por si no se cargó el changeSet 007)
IF NOT EXISTS (SELECT 1 FROM multimodal.Servicio WHERE servicio_id = 1) INSERT INTO multimodal.Servicio VALUES (1, N'Pluz Energia', N'SERVICIO DE ELECTRICIDAD', 'LUZ');
IF NOT EXISTS (SELECT 1 FROM multimodal.Servicio WHERE servicio_id = 2) INSERT INTO multimodal.Servicio VALUES (2, N'Aguas del Sur', N'SERVICIO DE AGUA POTABLE', 'AGUA');
IF NOT EXISTS (SELECT 1 FROM multimodal.Servicio WHERE servicio_id = 3) INSERT INTO multimodal.Servicio VALUES (3, N'TeleNova', N'SERVICIO DE INTERNET Y TELEFONIA', 'TELECOM');
IF NOT EXISTS (SELECT 1 FROM multimodal.Servicio WHERE servicio_id = 4) INSERT INTO multimodal.Servicio VALUES (4, N'GasAndes', N'SERVICIO DE GAS NATURAL', 'GAS');
IF NOT EXISTS (SELECT 1 FROM multimodal.Servicio WHERE servicio_id = 5) INSERT INTO multimodal.Servicio VALUES (5, N'Supermercados Delta', N'COMPRA CON TARJETA', 'RETAIL');
IF NOT EXISTS (SELECT 1 FROM multimodal.Servicio WHERE servicio_id = 6) INSERT INTO multimodal.Servicio VALUES (6, N'Nube Market', N'COMPRA ONLINE', 'ONLINE');

-- Limpieza de una carga anterior (solo los IDs de este archivo)
DELETE FROM multimodal.Transaccion WHERE transaccion_id LIKE 'TX-F%';
DELETE FROM multimodal.Tarjeta     WHERE tarjeta_id IN ('TRJ-9001', 'TRJ-9002', 'TRJ-9003');
DELETE FROM multimodal.Balance     WHERE cuenta_id IN ('CTA-9001-A', 'CTA-9001-T', 'CTA-9002-A', 'CTA-9002-T', 'CTA-9003-A', 'CTA-9003-T');
DELETE FROM multimodal.Cuenta      WHERE cliente_id IN ('CLI-9001', 'CLI-9002', 'CLI-9003');
DELETE FROM multimodal.Cliente     WHERE cliente_id IN ('CLI-9001', 'CLI-9002', 'CLI-9003');

INSERT INTO multimodal.Cliente (cliente_id, nombre_mask, doc_hash, email_mask, segmento, caso_id, semilla) VALUES
 ('CLI-9001', N'L** Ram** Soto**',  CONVERT(CHAR(64), HASHBYTES('SHA2_256', 'DNI-SINTETICO-90010001'), 2), N'l***@ejemplo.test', 'PERSONAL', 'FRAUDE-OTP', 0),
 ('CLI-9002', N'M** Vil** Cast**',  CONVERT(CHAR(64), HASHBYTES('SHA2_256', 'DNI-SINTETICO-90020002'), 2), N'm***@ejemplo.test', 'PREMIUM',  'FRAUDE-OTP', 0),
 ('CLI-9003', N'R** Cam** Pare**',  CONVERT(CHAR(64), HASHBYTES('SHA2_256', 'DNI-SINTETICO-90030003'), 2), N'r***@ejemplo.test', 'PERSONAL', 'FRAUDE-OTP', 0);

INSERT INTO multimodal.Cuenta (cuenta_id, cliente_id, tipo, moneda) VALUES
 ('CTA-9001-A', 'CLI-9001', 'AHORROS', 'PEN'), ('CTA-9001-T', 'CLI-9001', 'TARJETA', 'PEN'),
 ('CTA-9002-A', 'CLI-9002', 'AHORROS', 'PEN'), ('CTA-9002-T', 'CLI-9002', 'TARJETA', 'PEN'),
 ('CTA-9003-A', 'CLI-9003', 'AHORROS', 'PEN'), ('CTA-9003-T', 'CLI-9003', 'TARJETA', 'PEN');

INSERT INTO multimodal.Balance (cuenta_id, saldo, saldo_disponible) VALUES
 ('CTA-9001-A', 4200.00, 4200.00), ('CTA-9001-T', 1850.50, 3400.00),
 ('CTA-9002-A', 9800.00, 9800.00), ('CTA-9002-T', 3920.75, 1600.00),
 ('CTA-9003-A', 1250.00, 1250.00), ('CTA-9003-T',  640.20, 2100.00);

INSERT INTO multimodal.Tarjeta (tarjeta_id, cuenta_id, ultimos4, producto, habilitada, dia_facturacion) VALUES
 ('TRJ-9001', 'CTA-9001-T', '4417', N'Visa Infinite Soles',       1, 28),
 ('TRJ-9002', 'CTA-9002-T', '5528', N'Mastercard Platinum Soles', 1, 28),
 ('TRJ-9003', 'CTA-9003-T', '3306', N'Visa Clásica Soles',        1, 28);

-- transaccion_id, codigo_operacion (7 dígitos únicos), tarjeta, servicio, monto, fecha, canal, grupo_duplicado, autenticada_otp
INSERT INTO multimodal.Transaccion (transaccion_id, codigo_operacion, tarjeta_id, servicio_id, monto, moneda, fecha_hora, canal, grupo_duplicado, autenticada_otp) VALUES
 -- CLI-9001 Lucía: compras ONLINE/APP validadas con OTP (si las desconoce => P-11, escalar)
 ('TX-F9001A', '9100001', 'TRJ-9001', 6,  389.90, 'PEN', '2026-09-05 21:14', 'ONLINE', NULL, 1),
 ('TX-F9001B', '9100002', 'TRJ-9001', 6,  719.00, 'PEN', '2026-10-02 22:41', 'ONLINE', NULL, 1),
 ('TX-F9001C', '9100003', 'TRJ-9001', 6, 1250.00, 'PEN', '2026-10-06 23:05', 'APP',    NULL, 1),
 ('TX-F9001D', '9100004', 'TRJ-9001', 1,   96.40, 'PEN', '2026-08-28 10:12', 'APP',    NULL, 1),
 ('TX-F9001E', '9100005', 'TRJ-9001', 5,  142.30, 'PEN', '2026-10-01 17:30', 'POS',    NULL, 1),
 -- CLI-9002 Mateo: ráfaga sospechosa ONLINE SIN OTP en pocos minutos (reclamo normal con aprobación humana)
 ('TX-F9002A', '9200001', 'TRJ-9002', 6,  899.00, 'PEN', '2026-10-04 03:11', 'ONLINE', NULL, 0),
 ('TX-F9002B', '9200002', 'TRJ-9002', 6,  899.00, 'PEN', '2026-10-04 03:13', 'ONLINE', NULL, 0),
 ('TX-F9002C', '9200003', 'TRJ-9002', 6, 2350.00, 'PEN', '2026-10-04 03:16', 'ONLINE', NULL, 0),
 ('TX-F9002D', '9200004', 'TRJ-9002', 3,  179.90, 'PEN', '2026-09-10 02:48', 'ONLINE', NULL, 0),
 ('TX-F9002E', '9200005', 'TRJ-9002', 5,  310.60, 'PEN', '2026-09-18 19:22', 'POS',    NULL, 1),
 ('TX-F9002F', '9200006', 'TRJ-9002', 2,   58.75, 'PEN', '2026-08-22 09:40', 'APP',    NULL, 1),
 -- CLI-9003 Rosa: uso normal; un cobro duplicado (mismo grupo) con OTP; una compra online sin OTP aislada
 ('TX-F9003A', '9300001', 'TRJ-9003', 4,  135.00, 'PEN', '2026-10-05 12:10', 'APP',    'DUP-901', 1),
 ('TX-F9003B', '9300002', 'TRJ-9003', 4,  135.00, 'PEN', '2026-10-05 12:12', 'APP',    'DUP-901', 1),
 ('TX-F9003C', '9300003', 'TRJ-9003', 5,   88.20, 'PEN', '2026-09-14 18:05', 'POS',    NULL, 1),
 ('TX-F9003D', '9300004', 'TRJ-9003', 2,   72.10, 'PEN', '2026-09-02 08:55', 'APP',    NULL, 1),
 ('TX-F9003E', '9300005', 'TRJ-9003', 6,  210.00, 'PEN', '2026-10-07 14:33', 'ONLINE', NULL, 0);

-- Verificación rápida: operaciones por cliente y autenticación
SELECT cu.cliente_id, t.codigo_operacion, t.monto, t.canal, t.fecha_hora,
       CASE t.autenticada_otp WHEN 1 THEN 'CON OTP' ELSE 'SIN OTP' END AS autenticacion
FROM multimodal.Transaccion t
JOIN multimodal.Tarjeta tr ON tr.tarjeta_id = t.tarjeta_id
JOIN multimodal.Cuenta cu ON cu.cuenta_id = tr.cuenta_id
WHERE t.transaccion_id LIKE 'TX-F%'
ORDER BY cu.cliente_id, t.fecha_hora;
