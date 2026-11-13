# Falla 3 — Prueba de seguridad que "pasaba" por la razón equivocada

**Archivos:** `tests/test_flujos.py::test_adv_ejecutar_accion_sin_aprobacion_es_rechazado`, `src/reclamos/mcp_server/tools.py` (`anular_transaccion`, `_exigir_aprobacion`).

## Síntoma
La prueba "ejecutar la acción sin aprobación es rechazado" estaba en verde. Al corregir otras pruebas contra las **firmas reales** de las tools
(`anular_transaccion(ticket_id, transaccion_id, aprobacion_id)`) se vio que la versión original la llamaba con `codigo_operacion=` (argumento inexistente).

## Hipótesis inicial
La guarda `_exigir_aprobacion` (verifica `AprobacionHitl.estado == 'APROBADA'` en BD) funcionaba y por eso la prueba pasaba.

## Diagnóstico
Con el argumento incorrecto, la llamada fallaba por **error de firma** y `ClienteHerramientas.llamar` lo convertía en `{"ok": false, ...}`.
La aserción `out["ok"] is False` se cumplía sin ejercitar la guarda de aprobación.

## Causa raíz (distinta de la hipótesis)
La aserción solo comprobaba "falló", no **por qué**. Una prueba de seguridad que acepta cualquier error no demuestra la defensa.

## Solución
Llamar con la firma real y la aprobación aún `PENDIENTE`, y exigir además que el mensaje de error mencione la aprobación (`"APROB"`),
que `accion_ejecutada` siga en `NULL`. Añadida prueba complementaria: tras aprobar, el reintento es idempotente (`ya_ejecutada=True`) y una **acción distinta**
sobre el mismo ticket es rechazada (P-05).

## Aprendizaje
En pruebas negativas, afirmar el **motivo** del rechazo (código/mensaje), no solo el rechazo.
