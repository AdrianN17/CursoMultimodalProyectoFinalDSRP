Opción B. Agente multimodal para analizar reclamaciones bancarias
Esta alternativa se centra en el área de atención al cliente y operaciones.
¿Qué problema resolvería?
Un cliente presenta una reclamación relacionada con un cobro, una transferencia, una compra con tarjeta o una operación que no reconoce.

El agente reúne las evidencias y ayuda al analista a determinar qué información falta y qué procedimiento corresponde seguir.
Ejemplo práctico
Un cliente reclama un consumo con tarjeta de S/ 2,250.

Presenta:
- Audio: explica que realizó una compra, pero considera que el importe cobrado es incorrecto.
- Imagen: adjunta el comprobante de compra.
- Documento: presenta un estado de cuenta ficticio en PDF.
- Base de datos: contiene la transacción registrada, la moneda, el importe y el estado de la operación.
El agente compara los importes, identifica posibles diferencias entre la moneda original y la moneda de facturación, y prepara un expediente de reclamación.


aplicaremos MCP para obtener informacion del cliente de la BD sqlserver

Tablas 
Cliente

Transaccion

Balance

Cuenta

Tarjeta

Servicio

Usaras liquibase y formato yaml

Track de Logeo y aprobaciones OTP

etc (lo necesario para tener mapeado)

RAG con politicas de reclamacion
* Un cliente puede reclamar y se le hará reembolso si fue una transaccion duplicada o hecha sin su consentimiento, demora 7 dias habiles
* Un cliente no puede reclamar si no tiene la boleta o evidencia al respecto
* Un cliente puede anular una transaccion si fue hecha antes de su fecha de facturacion
* Un cliente no puede anular transacciones que no son suyas
* Solo se puede anular una transaccion por reclamo
* Un cliente no puede reembolsar si no tiene la tarjeta habilitada con la cual hizo la compra, debe pasar a un operador para coordinar el medio de reembolso (tarjeta de debito o pasarlo a otra tarjeta)
* se puede dar informacion del usuario y detalle de la transaccion.
* Por cada atencion se generara un ticket el cual sera idempotente


Usuario reclama
Se valida la informacion brindada
Se genera el ticket de atencion para que el usuario le de seguimiento
Se consulta a las fuentes (BD)
Se busca la politica y el plan de accion 
De ser necesario se le escala a un operador para coordinar (Por correo)
Se procede al reembolso 
Se cierra el estado del ticket

un md que se subira a qdrant

El proyecto debe implementar opentelemetry, debe maneras routers, langgraph 

Python / reglas
Router / modelo según diseño
Proceso ¿Qué nodo ejecutamos ahora y qué estado conservamos? LangGraph


La gestion de ticket, la idempotencia, historial y demas, guardalo en tablas de la BD sqlserver

Coloca logs en todos lados para saber via opentelemetry tu paso a paso

Improtante: Se debe validar bien el formato de la imagen del comprobante:

Debe ir

Constancia de Pago
Fecha: 07 oct 2026   Hora: 00:19
Cuenta de cargo:Visa Infinite Soles
XXXX XXXX XXXX 23223
Empresa:Pluz Energia
Servicio:SERVICIO DE
ELECTRICIDAD
Nombre:A** Tra** Unid**
Código de operación :0004268
Monto :S/ 213.50

Solo maneja soles, en caso de dolares menciona que la opcion no esta disponible actualmente, debe ir por canal regular

El proyecto hara todo via tts la interaccion al cliente, el cliente puede hablar por chat o hablar, mandar imagenes (no video), el agente solo respondera con tts

Debes crear una pequeña interfaz web minimalista para poder interactuar con el agente

Para las apis maneja openapi, y fastapi