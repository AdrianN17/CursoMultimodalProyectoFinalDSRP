# Pruebas y evidencia

Resultados de la última ejecución (proveedor IA = *mock*; SQL **simulado con SQLite temporal**, `tests/sql_falso.py`; herramientas MCP en proceso para pytest y por *stdio* en el smoke test).

| Comando | Resultado | Evidencia |
|---|---|---|
| `python -m pytest tests -v` | **79 passed, 1 skipped en 14.2 s** (el *skipped* es `test_hitl_se_reanuda_desde_otro_proceso`, marcado `integracion`) | ejecución local; `evidencia/pruebas/resultado_pytest.txt` conserva la ejecución previa (62 passed, SQL Server real) |
| `RUN_INTEGRACION=1 python -m pytest tests/test_persistencia_herramientas.py::test_hitl_se_reanuda_desde_otro_proceso -v` | **1 passed en 110.8 s** contra Azure SQL real (esquema `multimodal`; reanuda el HITL desde otro proceso) | ejecución local |
| `python scripts/smoke_test.py` | **RESULTADO: OK** (7 escenarios + ciclo HITL) | `evidencia/pruebas/resultado_smoke_test.txt` |
| `python main.py … --aprobar APROBADA` | `REEMBOLSO_PROGRAMADO`, `accion_final=REEMBOLSO` | `evidencia/pruebas/demo_duplicada_aprobada.txt` |
| `python main.py … --aprobar RECHAZADA` | `HITL_RECHAZADO`, `accion_final=NINGUNA` (propuesta: `REEMBOLSO`) | `evidencia/pruebas/demo_duplicada_rechazada.txt` |

> **Alcance honesto:** el proveedor *mock* valida el flujo, las políticas, las tools, el HITL y la persistencia, **no** la calidad de Whisper, la visión ni el TTS reales. El SQL simulado (SQLite) **no** valida T-SQL real, `CHECK` ni claves foráneas: eso lo cubre `RUN_INTEGRACION=1` y el script de paridad del esquema.
> Antes de la entrega, repita `main.py` y `smoke_test.py` con `PROVEEDOR_IA=azure` y guarde esa salida junto a la anterior.

## Cobertura por archivo

| Archivo | Qué prueba |
|---|---|
| `tests/test_unidad.py` | Determinismo de la semilla; calificación de tablas con el esquema `multimodal`; validador de constancia; motor de políticas (reglas P-xx incl. P-11 operación con/sin OTP, umbral de supervisor, discrepancia, manipulación) |
| `tests/test_flujos.py` | 8 escenarios (uno por tipo, incl. `SIN_CONSENTIMIENTO_CON_OTP`), HITL aprobar/rechazar/expirar, idempotencia, memoria de estado, OTP, adversariales y contradicción |
| `tests/test_persistencia_herramientas.py` | Checkpoint legible por otra instancia; reanudación del HITL **desde otro proceso**; idempotencia de `crear_ticket`; privacidad de operaciones ajenas; `autenticada_otp` expuesto por la tool y escalada P-11; una sola acción por ticket; PII |
| `tests/test_api.py` | OpenAPI, subida multipart, clave de analista, `problem+json`, formatos no admitidos, path traversal del audio |

## Prueba de contradicción (obligatoria)

`test_contradiccion_relato_vs_constancia_se_registra_y_escala` — escenario `MONTO_DISCREPANTE`: la constancia dice S/ 154.55 y la BD S/ 2,222.59 (semilla C-07/4213, ver `smoke_test`).

| Campo | Resultado real |
|---|---|
| Autoridad | BD > imagen > relato (motor: `DISCREPANCIA_DE_MONTO: prevalece el dato maestro`) |
| Acción | **Ninguna.** Se registra en `Discrepancia`, se escala al operador (`tool.escalar_operador`) y la respuesta hablada es `ESCALADO_DISCREPANCIA` |
| Estado | **PASÓ** |

## Pruebas adversariales

| # | Entrada | Esperado | Prueba | Estado |
|---|---|---|---|---|
| A1 | Imagen que no es una constancia | `PEDIR_INFO`, sin HITL | `test_adv_imagen_que_no_es_constancia` | PASÓ |
| A2 | Constancia en USD | `NO_DISPONIBLE_MONEDA` | `test_escenario_por_tipo[MONEDA_USD]` | PASÓ |
| A3 | Audio de ruido | Error de usuario/`PEDIR_INFO`, sin invención | `test_adv_audio_ininteligible` | PASÓ |
| A4 | Contenido ejecutable con extensión `.png` | Rechazo por firma | `test_adv_archivo_con_extension_falsa` (video: **no probado**) | PASÓ |
| A5 | Operación de otro cliente | `RECHAZO_AJENA`, sin filtrar datos | `test_adv_operacion_de_otro_cliente`, `test_transaccion_ajena_no_devuelve_detalle` | PASÓ |
| A6 | El humano rechaza | Sin efecto monetario | `test_hitl_rechazada_no_ejecuta` | PASÓ |
| A7 | Segunda acción en el mismo ticket | Reintento idempotente / otra acción rechazada | `test_solo_una_accion_por_ticket_aun_con_aprobacion` | PASÓ |
| A8 | Misma `Idempotency-Key` dos veces | Un solo ticket | `test_idempotencia_mismo_reclamo_un_solo_ticket` | PASÓ |
| A9 | Tool/BD caída | `ERROR_TECNICO` + ticket `PENDIENTE_TECNICO` | `test_adv_tool_caida_degrada_a_error_tecnico_con_ticket_pendiente` (simulada con *monkeypatch*) | PASÓ |
| A10 | Inyección de instrucciones en el relato | Decide el motor; sin reembolso | `test_adv_inyeccion_de_instrucciones_en_el_relato` | PASÓ |
| A11 | Tarjeta deshabilitada | Escalar a operador (P-06) | `test_escenario_por_tipo[TARJETA_DESHABILITADA]` | PASÓ |
| A12 | HITL vence sin respuesta | `EXPIRADA`, sin acción, escalado | `test_adv_hitl_expirado_no_actua_y_escala` | PASÓ |
| A13 | El cliente desconoce una operación que sí validó con OTP | Escalar a operador (P-11), sin reembolso ni anulación | `test_operacion_con_otp_desconocida_escala_y_no_propone_accion_monetaria`, `test_escenario_por_tipo[SIN_CONSENTIMIENTO_CON_OTP]` | PASÓ |
| A14 | El cliente desconoce una operación procesada **sin** OTP | Flujo de reclamo normal con aprobación humana | `test_sin_consentimiento_y_sin_otp_en_la_operacion_sigue_el_flujo_de_reclamo`, `test_escenario_por_tipo[SIN_CONSENTIMIENTO]` | PASÓ |
| — | Ejecutar la tool de acción sin aprobación | Rechazo por falta de aprobación | `test_adv_ejecutar_accion_sin_aprobacion_es_rechazado` | PASÓ |
| — | Aprobar con rol insuficiente | `ROL_INSUFICIENTE` | `test_adv_aprobacion_sin_rol_suficiente` (solo valida si el umbral exige SUPERVISOR) | PASÓ (condicional) |

Límites de las pruebas: la inyección de instrucciones se probó con el relato en **texto** y el clasificador *mock* (no con un LLM real); la caída de BD se simula en la capa de tools, no cortando la conexión.

## Fallas reales

`evidencia/fallas/falla_1` (deadlock del checkpointer), `falla_2` (fixture de imagen inválido), `falla_3` (prueba de seguridad que pasaba por la razón equivocada).
Las hipótesis iniciales están reconstruidas por el asistente: reemplácelas por las suyas si fueron distintas.

## Métricas

`python scripts/resumen_metricas.py` → `evidencia/resumen_metricas.md` (p50/p95 global y por etapa, tasa de error, % a aprobación humana, tokens y costo).
Con el proveedor *mock* las latencias y los tokens son **simulados**; con Azure OpenAI serán distintos.
