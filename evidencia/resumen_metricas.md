# Resumen de métricas

- Ejecuciones (`reclamo.procesar`): **20**; reanudaciones HITL: **6**
- Latencia extremo a extremo: p50 **150 ms**, p95 **1138 ms** (media 434 ms)
- Tasa de error técnico: **0.0%**
- Enviadas a aprobación humana: **50.0%**
- Tokens LLM: entrada **25268**, salida **4826**; costo estimado **USD 0.1114** (USD 0.0056 por ejecución)

## Resultados

| resultado | n |
|---|---|
| PENDIENTE_APROBACION | 10 |
| ESCALADO_DISCREPANCIA | 2 |
| ESCALADO_TARJETA | 2 |
| PEDIR_INFO | 2 |
| RECHAZO_AJENA | 2 |
| NO_DISPONIBLE_MONEDA | 2 |

## Latencia por etapa (ms)

| etapa | n | p50 | p95 |
|---|---|---|---|
| reclamo.procesar | 20 | 150.5 | 1138.3 |
| nodo.abrir_ticket | 20 | 20.5 | 930.7 |
| tool.crear_ticket | 20 | 6.5 | 914.6 |
| reclamo.reanudar_hitl | 6 | 105.0 | 122.0 |
| nodo.consultar_maestro | 20 | 14.0 | 39.3 |
| nodo.tts | 16 | 25.5 | 30.0 |
| tts.sintetizar | 47 | 20.0 | 28.0 |
| nodo.aprobacion_humana | 16 | 10.5 | 20.5 |
| tool.solicitar_aprobacion | 16 | 7.0 | 18.2 |
| nodo.ejecutar_accion | 4 | 14.0 | 17.0 |
| tool.registrar_reembolso | 4 | 13.5 | 16.9 |
| tool.consultar_transaccion | 16 | 4.0 | 14.7 |
| tool.cerrar_ticket | 10 | 6.0 | 14.0 |
| nodo.finalizar | 12 | 6.5 | 13.1 |
| nodo.escalar_operador | 4 | 10.5 | 11.8 |
| tool.escalar_operador | 4 | 9.0 | 11.5 |
| nodo.validar_entrada | 20 | 9.0 | 10.0 |
| nodo.verificar_otp | 20 | 2.0 | 9.0 |
| tool.registrar_discrepancia | 2 | 6.5 | 7.8 |
| tool.buscar_duplicados | 8 | 5.5 | 7.7 |
| tool.actualizar_ticket | 22 | 4.0 | 7.0 |
| tool.registrar_evidencia | 58 | 4.0 | 6.2 |
| nodo.cruzar_evidencias | 20 | 0.0 | 6.1 |
| tool.consultar_ticket | 20 | 3.0 | 6.1 |
| tool.consultar_parametros | 20 | 3.0 | 5.0 |
| hitl.decision | 6 | 5.0 | 5.0 |
| sesion.iniciar | 20 | 2.0 | 5.0 |
| nodo.recuperar_politica | 20 | 1.0 | 2.0 |
| nodo.analizar_agente | 20 | 1.0 | 2.0 |
| nodo.stt | 20 | 1.0 | 2.0 |
| nodo.vision_constancia | 18 | 1.0 | 1.2 |
| agente.analizar | 18 | 1.0 | 1.2 |
| nodo.clasificar_intencion | 20 | 1.0 | 1.0 |
| rag.indexar | 6 | 0.5 | 1.0 |
| vision.extraer_constancia | 18 | 1.0 | 1.0 |
| stt.transcribir | 20 | 1.0 | 1.0 |
| nodo.evaluar_politicas | 20 | 0.0 | 1.0 |
| llm.chat | 38 | 0.0 | 1.0 |
| rag.recuperar | 20 | 1.0 | 1.0 |
| nodo.componer_respuesta | 16 | 0.0 | 1.0 |
| rag.embed | 20 | 0.0 | 0.0 |
