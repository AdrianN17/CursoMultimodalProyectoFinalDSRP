# Resumen de métricas

- Ejecuciones (`reclamo.procesar`): **3**; reanudaciones HITL: **1**
- Latencia extremo a extremo: p50 **65475 ms**, p95 **73828 ms** (media 68088 ms)
- Tasa de error técnico: **0.0%**
- Enviadas a aprobación humana: **33.3%**
- Tokens LLM: entrada **7391**, salida **11161**; costo estimado **USD 0.1301** (USD 0.0434 por ejecución)

## Resultados

| resultado | n |
|---|---|
| PENDIENTE_APROBACION | 1 |
| ESCALADO_DISCREPANCIA | 1 |
| RECHAZO_AJENA | 1 |

## Latencia por etapa (ms)

| etapa | n | p50 | p95 |
|---|---|---|---|
| reclamo.procesar | 3 | 65475.5 | 73828.4 |
| reclamo.reanudar_hitl | 1 | 21270.8 | 21270.8 |
| vision.extraer_constancia | 3 | 14985.6 | 16589.9 |
| nodo.vision_constancia | 3 | 14985.6 | 16589.9 |
| agente.analizar | 3 | 13826.3 | 15612.5 |
| nodo.analizar_agente | 3 | 13826.3 | 15612.5 |
| llm.chat | 6 | 9164.3 | 15313.2 |
| nodo.abrir_ticket | 3 | 7023.6 | 11239.1 |
| nodo.escalar_operador | 1 | 7780.1 | 7780.1 |
| tool.escalar_operador | 1 | 7779.1 | 7779.1 |
| nodo.consultar_maestro | 3 | 6133.4 | 6505.7 |
| nodo.clasificar_intencion | 3 | 5213.2 | 6072.9 |
| nodo.verificar_otp | 3 | 5119.6 | 5212.4 |
| tool.crear_ticket | 3 | 2030.8 | 4995.4 |
| hitl.decision | 1 | 3787.3 | 3787.3 |
| tool.registrar_reembolso | 1 | 3041.1 | 3041.1 |
| nodo.ejecutar_accion | 1 | 3041.1 | 3041.1 |
| nodo.aprobacion_humana | 2 | 2520.6 | 2739.4 |
| tool.solicitar_aprobacion | 2 | 2041.2 | 2689.6 |
| sesion.iniciar | 3 | 2062.3 | 2584.6 |
| tool.registrar_evidencia | 9 | 1710.8 | 2237.6 |
| tool.consultar_ticket | 3 | 2156.6 | 2172.0 |
| tool.registrar_discrepancia | 1 | 2021.8 | 2021.8 |
| nodo.cruzar_evidencias | 3 | 0.0 | 1819.6 |
| nodo.finalizar | 2 | 1631.9 | 1636.5 |
| tool.cerrar_ticket | 2 | 1630.9 | 1635.5 |
| tool.actualizar_ticket | 3 | 1616.7 | 1631.8 |
| tool.consultar_transaccion | 3 | 1246.8 | 1374.5 |
| nodo.recuperar_politica | 3 | 1193.4 | 1210.2 |
| rag.recuperar | 3 | 1193.4 | 1209.3 |
| tool.consultar_parametros | 3 | 793.5 | 921.3 |
| tool.buscar_duplicados | 1 | 898.1 | 898.1 |
| rag.embed | 3 | 666.9 | 668.6 |
| rag.indexar | 1 | 451.4 | 451.4 |
| nodo.tts | 3 | 25.6 | 30.4 |
| tts.sintetizar | 7 | 21.9 | 27.7 |
| nodo.validar_entrada | 3 | 9.0 | 10.8 |
| stt.transcribir | 3 | 1.0 | 1.0 |
| nodo.stt | 3 | 1.0 | 1.0 |
| nodo.evaluar_politicas | 3 | 0.0 | 0.9 |
| nodo.componer_respuesta | 3 | 0.0 | 0.9 |
