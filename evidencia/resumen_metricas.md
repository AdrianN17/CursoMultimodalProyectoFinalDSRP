# Resumen de métricas

- Ejecuciones (`reclamo.procesar`): **31**; reanudaciones HITL: **7**
- Latencia extremo a extremo: p50 **355 ms**, p95 **408 ms** (media 325 ms)
- Tasa de error técnico: **3.2%**
- Enviadas a aprobación humana: **41.9%**
- Tokens LLM: entrada **36008**, salida **6670**; costo estimado **USD 0.1567** (USD 0.0051 por ejecución)

## Resultados

| resultado | n |
|---|---|
| PENDIENTE_APROBACION | 13 |
| PEDIR_INFO | 4 |
| RECHAZO_AJENA | 3 |
| ESCALADO_DISCREPANCIA | 2 |
| ESCALADO_OTP | 2 |
| ESTADO | 2 |
| ERROR_USUARIO | 2 |
| ESCALADO_TARJETA | 1 |
| NO_DISPONIBLE_MONEDA | 1 |
| ERROR_TECNICO | 1 |

## Latencia por etapa (ms)

| etapa | n | p50 | p95 |
|---|---|---|---|
| reclamo.procesar | 31 | 354.6 | 408.0 |
| POST /api/v1/reclamos | 3 | 3.0 | 276.6 |
| fastapi.endpoint | 9 | 2.0 | 265.8 |
| POST /api/v1/aprobaciones/{aprobacion_id}/decision | 2 | 106.5 | 199.7 |
| reclamo.reanudar_hitl | 7 | 171.0 | 196.3 |
| nodo.aprobacion_humana | 20 | 34.5 | 113.4 |
| tool.solicitar_aprobacion | 20 | 23.0 | 112.4 |
| nodo.verificar_otp | 30 | 62.5 | 95.4 |
| nodo.consultar_maestro | 27 | 40.0 | 93.0 |
| nodo.finalizar | 14 | 37.5 | 90.7 |
| nodo.escalar_operador | 6 | 43.0 | 81.8 |
| tool.escalar_operador | 6 | 43.0 | 81.6 |
| tool.cerrar_ticket | 10 | 23.5 | 81.2 |
| nodo.abrir_ticket | 28 | 50.7 | 69.2 |
| tool.crear_ticket | 30 | 40.5 | 58.4 |
| tool.actualizar_ticket | 31 | 3.0 | 52.0 |
| tool.consultar_ticket | 28 | 8.5 | 46.3 |
| nodo.ejecutar_accion | 5 | 17.0 | 44.1 |
| nodo.responder_error | 3 | 0.0 | 44.1 |
| tool.registrar_reembolso | 6 | 17.0 | 43.2 |
| tool.consultar_transaccion | 24 | 17.0 | 33.4 |
| GET /api/v1/audio/{nombre} | 1 | 31.0 | 31.0 |
| nodo.tts | 25 | 24.0 | 29.1 |
| tts.sintetizar | 72 | 19.0 | 27.5 |
| tool.registrar_discrepancia | 2 | 20.0 | 27.1 |
| tool.buscar_duplicados | 11 | 14.0 | 23.1 |
| tool.consultar_parametros | 27 | 1.0 | 13.2 |
| nodo.validar_entrada | 31 | 10.0 | 11.0 |
| POST /api/v1/sesiones | 1 | 10.0 | 10.0 |
| nodo.cruzar_evidencias | 26 | 0.0 | 10.0 |
| hitl.decision | 10 | 7.0 | 8.0 |
| sesion.iniciar | 35 | 5.8 | 7.0 |
| GET /openapi.json | 1 | 7.0 | 7.0 |
| tool.registrar_evidencia | 80 | 3.0 | 4.0 |
| hitl.expiracion | 1 | 4.0 | 4.0 |
| GET /api/v1/reclamos/{ticket_id} | 1 | 3.0 | 3.0 |
| GET /api/v1/aprobaciones | 2 | 2.0 | 2.9 |
| nodo.consultar_estado | 2 | 2.0 | 2.0 |
| nodo.recuperar_politica | 26 | 1.0 | 2.0 |
| nodo.analizar_agente | 26 | 1.0 | 2.0 |
| rag.recuperar | 26 | 1.0 | 2.0 |
| nodo.stt | 29 | 1.0 | 2.0 |
| nodo.vision_constancia | 25 | 1.0 | 1.8 |
| agente.analizar | 25 | 1.0 | 1.0 |
| nodo.clasificar_intencion | 30 | 1.0 | 1.0 |
| llm.chat | 55 | 0.0 | 1.0 |
| stt.transcribir | 29 | 1.0 | 1.0 |
| fastapi.dependencies | 10 | 0.0 | 1.0 |
| nodo.evaluar_politicas | 26 | 0.0 | 1.0 |
| rag.embed | 26 | 0.0 | 1.0 |
| vision.extraer_constancia | 25 | 0.0 | 1.0 |
| GET /{path} | 1 | 1.0 | 1.0 |
| tool.anular_transaccion | 2 | 1.0 | 1.0 |
| nodo.componer_respuesta | 25 | 0.0 | 0.8 |
| fastapi.serialization | 5 | 0.0 | 0.8 |
| rag.indexar | 1 | 0.0 | 0.0 |
