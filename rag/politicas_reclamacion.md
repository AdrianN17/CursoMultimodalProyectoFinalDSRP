<!-- version: 1.1.0 -->
# Políticas de reclamación de consumos y operaciones con tarjeta

Documento normativo (ficticio) que respalda las decisiones del agente. Cada política tiene un identificador
estable que el agente debe citar. El motor de reglas del sistema aplica estas políticas de forma determinística.

## P-01 · Reembolso por transacción duplicada o sin consentimiento
Un cliente puede reclamar y se le hará **reembolso** si la transacción fue **duplicada** o fue **hecha sin su
consentimiento**. El reembolso demora **7 días hábiles**. Toda acción que mueva dinero requiere aprobación
humana (analista; supervisor si el monto supera el umbral de aprobación reforzada).

## P-02 · Obligación de presentar evidencia
Un cliente **no puede reclamar** si no tiene la **boleta o evidencia** de la operación (constancia de pago).
Sin evidencia válida, el agente debe solicitar la constancia y no registrar acciones monetarias.

## P-03 · Anulación antes de la fecha de facturación
Un cliente puede **anular** una transacción si fue hecha **antes de su fecha de facturación**, es decir, si la
operación aún no fue incluida en el corte de la tarjeta. La anulación revierte el cargo y devuelve el saldo
disponible. Si la operación ya fue facturada, corresponde reembolso (P-01).

## P-04 · Transacciones ajenas
Un cliente **no puede anular transacciones que no son suyas**. Ante una operación de otro cliente se rechaza el
reclamo y no se revela ningún dato de la operación.

## P-05 · Una anulación por reclamo
**Solo se puede anular una transacción por reclamo.** Si el reclamo ya tiene una anulación o reembolso
ejecutado, cualquier otra solicitud se rechaza y se debe abrir un nuevo reclamo.

## P-06 · Tarjeta no habilitada
Un cliente **no puede recibir reembolso** si no tiene **habilitada** la tarjeta con la que hizo la compra.
Debe pasar a un **operador** para coordinar el medio de reembolso (tarjeta de débito u otra tarjeta). El
operador es notificado por correo y el ticket queda en escalamiento.

## P-07 · Información al cliente
Se puede dar información del usuario y el detalle de la transacción **solo después de verificar la identidad
con OTP**, y siempre con datos enmascarados (nunca número completo de tarjeta ni documento).

## P-08 · Ticket de atención idempotente
Por cada atención se genera **un ticket**, que es **idempotente**: reintentar la misma solicitud devuelve el
mismo ticket y no crea duplicados. El ticket conserva el historial de eventos hasta su cierre.

## P-09 · Solo moneda soles
El canal solo atiende operaciones en **soles (PEN)**. Para operaciones en dólares u otra moneda se informa que
la opción **no está disponible actualmente** y que debe usar el **canal regular**.

## P-10 · Formato válido de la constancia de pago
La constancia debe ser una "Constancia de Pago" con: fecha y hora, cuenta de cargo (producto y tarjeta
enmascarada), empresa, servicio, nombre enmascarado, código de operación y monto en soles. Si el monto de la
constancia difiere del registrado por el banco, **prevalece el dato maestro del banco**: la discrepancia se
registra y se escala a un operador, nunca se corrige en silencio.

## P-11 · Operación autenticada con OTP
Si el cliente **desconoce** una operación (sin consentimiento) pero esta fue **autenticada con el OTP del propio
cliente**, el sistema **no reembolsa ni anula de forma automática**: es un indicio de posible ingeniería social
o de uso compartido del código. El caso se **escala a un operador**, que verifica con el cliente. Si la operación
se procesó **sin OTP**, es un indicio fuerte de fraude y sigue el flujo normal de reclamo (P-01 / P-03), con
aprobación humana.
