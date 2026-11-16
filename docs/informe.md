# Informe — Agente multimodal de reclamos bancarios

**Alumno:** Adrian Melgarejo Siguas · **CASO_ID:** C-07 · **SEMILLA:** 4213 · **Repositorio:** AdrianN17/CursoMultimodalProyectoFinalDSRP · **Video:** _pendiente: pegar enlace no listado_ (`C-07_4213_Melgarejo.mp4`)

## 1. Problema y usuario

Los analistas de reclamos de un banco reciben cada día reclamos por cobros duplicados o no autorizados con tarjeta. El cliente cuenta lo ocurrido por **voz** y aporta una **constancia de pago** (imagen); la verdad oficial (cliente, tarjeta, transacción, facturación) está en la **base de datos**, y las reglas de qué se puede anular o reembolsar están en un **documento de políticas**.

Un formulario no basta: el cliente no sabe qué campos importan, la constancia puede estar alterada y el relato puede contradecirla. Un agente con IA puede escuchar, leer la imagen y contrastar ambas fuentes con el dato maestro; pero una decisión de dinero no puede quedar en manos de un modelo. Por eso el diseño separa **percibir** (STT y visión, falibles), **consultar** (BD, autoridad), **inferir** (el agente propone) y **actuar** (solo con aprobación humana). El resultado es un asistente que clasifica el reclamo, propone la acción y habla la respuesta al cliente, mientras que una persona aprueba o rechaza todo movimiento de dinero.

**Usuario principal:** el cliente que reclama (interactúa solo por audio) y el analista/supervisor que aprueba (panel web y API).

## 2. Arquitectura

El sistema tiene nueve capas (detalle en [`arquitectura.md`](arquitectura.md)) y organiza cada componente en las cuatro categorías exigidas:

| Categoría | En este sistema | Dónde vive | Confianza |
|---|---|---|---|
| **Percepción** | Transcripción del audio, campos leídos de la constancia, relato del cliente | `proveedores/`, nodos `stt` y `vision_constancia` | Falible: se valida y se contrasta |
| **Dato maestro** | Cliente, tarjeta, transacción, ticket, parámetros (Azure SQL) | `mcp_server/tools.py` → esquema SQL `multimodal` | Máxima (BD > imagen > relato) |
| **Inferencia** | Tipo de reclamo, confianza, explicación, acción *propuesta* | `agente/agente.py` (salida JSON validada con Pydantic) | Sugerencia, nunca orden |
| **Acción** | Anular, reembolsar, escalar, cerrar | tools de acción + HITL | Solo con aprobación humana verificada en BD |

Flujo del grafo LangGraph (`orquestador/grafo.py`):

```
validar_entrada → [stt] → clasificar_intencion → verificar_otp → router
  ├─ consulta de estado → consultar_estado
  └─ reclamo → vision_constancia → abrir_ticket → consultar_maestro → cruzar_evidencias
       → evaluar_politicas → recuperar_politica (RAG) → analizar_agente → router_decision
            ├─ anulación / reembolso → aprobacion_humana (interrupt) → ejecutar_accion
            ├─ escalar → escalar_operador
            └─ pedir información / rechazar → finalizar
  → componer_respuesta → tts → (audio)          (cualquier error → responder_error → tts)
```

Servicios: **Azure OpenAI** (Foundry: `gpt-5-mini` para chat, visión y router; `text-embedding-3-small` para RAG; Whisper y TTS previstos), **Azure SQL** (dato maestro y checkpointer), **Qdrant Cloud** (políticas), **OpenTelemetry** (trazas, métricas y logs; Jaeger opcional) y **FastAPI + web mínima** para el cliente y el analista.

Las nueve capas y su implementación:

| # | Capa | Implementación |
|---|---|---|
| 1 | Entrada multimodal | `api/app.py` (multipart), `modalidades/validacion_archivos.py` (firma de archivo, tamaño, rechazo de video) |
| 2 | Percepción | `ProveedorIA.transcribir` / `extraer_constancia` (Whisper, visión) |
| 3 | Validación | `validadores/constancia.py` (formato oficial, soles/USD, dígitos finales de la tarjeta) |
| 4 | Dato maestro | `mcp_server/tools.py` (14 tools con envoltorio `{ok, data \| error}`) |
| 5 | Conocimiento | `rag/` (Qdrant; políticas versionadas P-01…P-11; recuperación obligatoria de las reglas del motor) |
| 6 | Razonamiento | `agente/` (prompts versionados, JSON validado) + `politicas/motor.py` |
| 7 | Acción y HITL | `hitl/aprobacion.py`, nodo `aprobacion_humana` (`interrupt`), tools protegidas |
| 8 | Memoria | `memoria/sqlserver_saver.py` (checkpointer en SQL), `thread_id` = sesión |
| 9 | Observabilidad y salida | `observabilidad/otel.py`, respuesta solo en audio (`orquestador/respuestas.py`) |

**Decisiones de diseño con alternativas** (resumen; el diario completo está en [`diario_decisiones.md`](diario_decisiones.md)):

| Tema | Elegido | Alternativa descartada |
|---|---|---|
| Quién decide el dinero | Motor de reglas + aprobación humana; el LLM infiere | LLM autónomo (no reproducible ni auditable) |
| Acceso a datos | MCP con tools tipadas | SQL generado por el LLM (riesgo de inyección y fuga) |
| Checkpointer | `SqlServerSaver` propio sobre pyodbc | `langgraph-checkpoint-mssql` (exige Python ≥ 3.12; aquí 3.11) y `MemorySaver` (no sobrevive reinicios) |
| Audio | STT previo, la transcripción se registra y valida | Audio directo al LLM (se pierde la trazabilidad) |
| Proveedor de IA | Interfaz `ProveedorIA` (Azure / mock) | SDK directo desde los nodos |
| Esquema de BD | Liquibase YAML + esquema `multimodal` | Scripts sueltos en `dbo` (la BD es compartida) |

**Idempotencia y recuperación.** El `ticket_id` se deriva de la `Idempotency-Key` (o de `sesión|operación`), de modo que un reintento devuelve el mismo ticket. Solo se permite una acción por reclamo (`UPDATE … WHERE accion_ejecutada IS NULL`). La aprobación humana se resuelve de forma atómica (solo si sigue `PENDIENTE` y no venció) y el grafo se reanuda con `Command(resume=…)`. Un fallo técnico no deja al cliente sin respuesta: se responde con seguridad, se abre un ticket `PENDIENTE_TECNICO` y se registra la causa.

## 3. Implementación multimodal

Se combinan cuatro fuentes y cada una tiene un contrato y un modo de fallo definido:

| Fuente | Entrada | Procesamiento | Si falla |
|---|---|---|---|
| Audio | `.wav/.mp3` validado por firma y tamaño | STT → relato; vacío = ininteligible | Pide repetir (`ERROR_USUARIO`) |
| Imagen | `.png/.jpg` validado por firma | Visión → campos de la constancia; el validador revisa formato, moneda y consistencia | `PEDIR_INFO` (sin HITL) |
| Base de datos | Tools MCP tipadas | Cliente, transacción, duplicados, facturación | `ERROR_TECNICO` + ticket `PENDIENTE_TECNICO` |
| Políticas | Qdrant (P-01…P-11) | Recuperación semántica de la regla aplicable | El motor determinista decide igualmente |

**Contradicciones:** BD > imagen > relato. Si la constancia dice S/ 154.55 y la BD S/ 2,222.59, el motor registra la `Discrepancia`, **no actúa** y escala al operador (prueba `test_contradiccion_relato_vs_constancia_se_registra_y_escala`, ver §8). Una imagen alterada solo agrega una alerta; no cambia la decisión.

**Respuesta solo en audio:** el texto hablado sale de plantillas con datos de la BD (`respuestas.py`), no del LLM, para que ningún monto o fecha sea inventado.

**Verificación de identidad:** el OTP del formulario se valida **antes** de gastar visión o exponer datos (D9). Es distinto del OTP de la operación bancaria, que es dato maestro (`Transaccion.autenticada_otp`) y alimenta la política P-11 (§4).

**Semilla.** `construir_escenario(CASO_ID, SEMILLA)` deriva todo de un `random.Random("C-07:4213")`. Con esa semilla cambian **8 elementos**: tipo de caso sorteado, umbral de aprobación humana (500/1000/2000), OTP, fecha de referencia, facturada o no, monto, comercio/servicio, identidades de los clientes y saldos, y en las operaciones ajenas el código de operación. Un `CASO_ID` o una `SEMILLA` distintos producen otro escenario; los mismos, el mismo.

## 4. Agente y razonamiento

- **Prompts versionados** en `src/reclamos/agente/prompts/` (`agente_v1.md`, v1.1.0; `vision_constancia_v1`), con la versión del agente (`AGENTE_VERSION=1.1.0`) en cada traza.
- **Salida estructurada:** JSON validado con Pydantic; un reintento y, si sigue inválida, se escala a un operador.
- **Quién decide:** `politicas/motor.py` es determinista y devuelve la acción y las reglas aplicadas; el agente solo puede **coincidir** o **volverse más conservador** (escalar si discrepa o si su confianza < 0.6). En la ejecución real con Azure, para la operación ajena el agente propuso escalar con confianza 0.40 y el motor decidió rechazar (P-04): prevaleció el motor.
- **Políticas** (`politicas/motor.py`). P-01 reembolso de reclamo válido ya facturado, P-03 anulación antes de la facturación, P-04 operación ajena (rechazar), P-05 una sola acción por ticket, P-06 tarjeta deshabilitada (escalar), P-07 identidad no verificada (rechazar), P-09 solo soles (`NO_DISPONIBLE_MONEDA`), P-10 sin evidencia válida / discrepancia de monto / operación inexistente (pedir información o escalar), y **P-11** (nueva): si el cliente desconoce una operación que **sí** se confirmó con OTP, se escala a un operador (posible ingeniería social); si se procesó **sin** OTP, sigue el flujo normal con aprobación humana. Hay datos de prueba en `db/datos_prueba_fraude_otp.sql`.
- **Memoria:** checkpointer propio sobre Azure SQL, con `thread_id` = sesión (D8). El estado sobrevive entre interacciones y entre procesos.

## 5. Tools y datos

Catorce tools MCP tipadas, todas con la envoltura `{ok, data | error}` y `trace_id`:

| Tipo | Tools |
|---|---|
| Consulta | `consultar_parametros`, `consultar_cliente`, `consultar_transaccion`, `buscar_duplicados`, `consultar_ticket` |
| Escritura de trabajo | `crear_ticket` (idempotente), `actualizar_ticket`, `registrar_evidencia`, `registrar_discrepancia`, `solicitar_aprobacion` |
| Acción persistente | `anular_transaccion`, `registrar_reembolso`, `escalar_operador`, `cerrar_ticket` |

El LLM **nunca escribe SQL**. Las tools de acción vuelven a comprobar en BD que `AprobacionHitl.estado = 'APROBADA'` (D11), admiten **una sola acción por ticket** y son idempotentes. El esquema está declarado en YAML (changelog Liquibase, `db/changelog/changes/001…009`) y todas las tablas viven en el esquema dedicado `multimodal` (D15), con 21 tablas, claves foráneas y `CHECK`.

## 6. Human in the Loop

Antes de anular o reembolsar, el grafo ejecuta `interrupt()` y registra una `AprobacionHitl` con el monto y el rol requerido (ANALISTA o SUPERVISOR según el umbral de la semilla). El analista aprueba o rechaza por la API (`POST /api/v1/aprobaciones/{id}/decision`, protegida con clave) o por la CLI. Resultados verificados:

| Decisión | Resultado | Evidencia |
|---|---|---|
| **Aprobada** | Se reanuda desde el checkpoint, se ejecuta la acción y se responde `REEMBOLSO_PROGRAMADO` | `evidencia/pruebas/demo_duplicada_aprobada.txt` |
| **Rechazada** | `HITL_RECHAZADO`, `accion_final=NINGUNA`, sin efecto monetario | `evidencia/pruebas/demo_duplicada_rechazada.txt` |
| **Expirada** | `EXPIRADA`, sin acción, escalamiento | `test_adv_hitl_expirado_no_actua_y_escala` |

La reanudación funciona **desde otro proceso** sobre Azure SQL real (`test_hitl_se_reanuda_desde_otro_proceso`: 1 passed en 116 s).

## 7. Observabilidad

Un span raíz por ejecución (`reclamo.procesar`), un span por nodo, tool, llamada al LLM y consulta RAG, con `caso.id`, `caso.semilla`, tokens y costo estimado; la PII se enmascara. Cada ejecución registra latencia total, latencia por etapa, tools con sus argumentos (saneados), errores y el resultado de la decisión humana (`hitl.decision`). Los logs llevan el prefijo `[C-07/4213 t=<trace>]`.

Medición real contra Azure (3 reclamos + 1 reanudación HITL; chat, visión y embeddings en Azure OpenAI `gpt-5-mini`, Azure SQL y Qdrant Cloud reales; STT/TTS simulados porque esos *deployments* aún no existen) — `evidencia/resumen_metricas_azure.md`:

| Etapa | p50 | p95 |
|---|---|---|
| Extremo a extremo (`reclamo.procesar`) | 65.5 s | 73.8 s |
| Visión de la constancia | 15.0 s | 16.6 s |
| Análisis del agente (LLM) | 13.8 s | 15.6 s |
| Clasificación de intención (router) | 5.2 s | 6.1 s |
| Una tool SQL (p. ej. `crear_ticket`, `registrar_evidencia`) | ≈ 2 s | ≈ 5 s |
| Reanudación HITL | 21.3 s | — |

Con el proveedor *mock* y SQL simulado (suite de pruebas, `evidencia/resumen_metricas.md`) el extremo a extremo es de unos 0.35 s: la diferencia confirma que **la latencia real la dominan la IA (≈ 34 s) y los viajes a Azure SQL (≈ 30 s)**, no la lógica del agente. Cómo se diagnostica: se abre la traza por `trace_id` (Jaeger o `evidencia/trazas.jsonl`) y se ordenan los spans por duración.

## 8. Pruebas, fallas y contradicción

**Pruebas:** `pytest tests` → **79 passed, 1 skipped en 13.8 s** (el omitido es la prueba de integración); con `RUN_INTEGRACION=1` esa prueba se ejecuta contra Azure SQL real: **1 passed en 115.9 s**. `scripts/smoke_test.py` (7 tipos de caso + ciclo HITL, Azure SQL real): **RESULTADO: OK**. Las pruebas por defecto no tocan ningún servicio real (SQL simulado con SQLite, Qdrant embebido, proveedor *mock*); ver [`pruebas.md`](pruebas.md) para el alcance y sus límites.

**Contradicción (obligatoria):** constancia S/ 154.55 vs BD S/ 2,222.59. Resultado real: la BD prevalece, se registra la discrepancia, se escala al operador, **no hay acción monetaria** y se responde `ESCALADO_DISCREPANCIA`. Pasó con el proveedor mock y también en la ejecución real con Azure OpenAI.

**Adversariales (14 + 2 complementarias; detalle en `pruebas.md`):**

| # | Entrada adversarial | Resultado esperado y obtenido |
|---|---|---|
| A1 | Imagen que no es una constancia | `PEDIR_INFO`, sin aprobación humana |
| A2 | Constancia en USD | `NO_DISPONIBLE_MONEDA` |
| A3 | Audio de ruido | Error de usuario; no se inventa un relato |
| A4 | Contenido ejecutable con extensión `.png` | Rechazo por firma del archivo |
| A5 | Operación de otro cliente | `RECHAZO_AJENA`; no se filtran datos |
| A6 | El humano rechaza | Sin efecto monetario |
| A7 | Segunda acción en el mismo ticket | Reintento idempotente; otra acción, rechazada (P-05) |
| A8 | Misma `Idempotency-Key` dos veces | Un solo ticket |
| A9 | Tool o BD caída | `ERROR_TECNICO` + ticket `PENDIENTE_TECNICO` |
| A10 | Inyección de instrucciones en el relato | Decide el motor; sin reembolso |
| A11 | Tarjeta deshabilitada | Escala al operador (P-06) |
| A12 | La aprobación vence sin respuesta | `EXPIRADA`, sin acción, escalamiento |
| A13 | Desconoce una operación confirmada con OTP | Escala al operador (P-11); sin reembolso |
| A14 | Desconoce una operación procesada sin OTP | Flujo normal con aprobación humana |
| — | Ejecutar la tool de acción sin aprobación / con rol insuficiente | Rechazo, afirmando el motivo del rechazo |

Todas pasan. Límites reconocidos: la inyección se probó con texto y el clasificador *mock* (no con un LLM real) y la caída de la BD se simula en la capa de tools.

**Tres fallas reales** (`evidencia/fallas/`):

| # | Falla | Causa raíz | Aprendizaje |
|---|---|---|---|
| 1 | Deadlock 1205 en el checkpointer; el arreglo con `HOLDLOCK` empeoró la suite a 678 s | No eran duplicados sino bloqueos de rango de `check-then-insert` | Dejar que la PK arbitre; medir con `--durations` |
| 2 | La prueba adversarial de imagen fallaba con `x1 must be ≥ x0` | Bug del generador de datos de prueba, no de Pillow | Revisar primero el *fixture* |
| 3 | Una prueba de seguridad pasaba por la razón equivocada (error de firma) | La aserción solo comprobaba "falló", no el motivo | Afirmar el **motivo** del rechazo |

## 9. Diario de decisiones y uso de IA

El [diario](diario_decisiones.md) tiene 17 decisiones (D1–D17): STT previo, motor de reglas sobre el LLM, MCP, checkpointer propio, autoridad BD > imagen > relato, idempotencia, OTP antes de la visión, plantillas para la voz, YAML para el esquema, esquema `multimodal`, pruebas con SQL simulado, y servicios en la nube. La [declaración de uso de IA](declaracion_uso_ia.md) incluye los casos en que la IA propuso algo incorrecto o ineficiente y cómo se detectó.

## 10. ¿Está listo para producción?

| # | Pregunta | Respuesta |
|---|---|---|
| 1 | ¿Qué funciona? | Flujo extremo a extremo con 8 tipos de caso, HITL con reanudación persistente (incluso desde otro proceso), idempotencia, trazas y métricas; verificado con 79 pruebas, la prueba de integración, el *smoke test* y una ejecución real con Azure OpenAI (chat, visión, embeddings) |
| 2 | ¿Qué no funciona aún? | **STT y TTS reales** (los *deployments* `whisper` y `tts` no existen en Foundry: `DeploymentNotFound`), autenticación real (el OTP es de demostración), PDF/multi-idioma, Liquibase real contra Azure SQL (se usó un runner Python con el mismo changelog) y **latencia de 65 s por reclamo** |
| 3 | ¿Riesgos? | Alucinación de campos en la visión, comprobantes falsificados, inyección de instrucciones, reembolso indebido (mitigado por motor + HITL), ingeniería social con OTP (P-11) |
| 4 | ¿Métricas que faltan? | Precisión de extracción de la constancia, tasa de falsos escalamientos, tiempo de resolución, CSAT, tasa de rechazo humano de propuestas |
| 5 | ¿Qué falla primero al escalar? | La latencia: una conexión ODBC por operación contra Azure SQL (~2 s cada una, tier gratuito *serverless* que además se pausa); después la cuota TPM de Azure OpenAI, la cola de analistas y Qdrant |
| 6 | ¿Qué requiere más seguridad? | Tools de acción, OTP/identidad, subida de archivos, secretos (Key Vault / Managed Identity), la clave de analista (→ autenticación real con roles) |
| 7 | ¿Qué nunca debe llegar al modelo? | DNI, tarjeta completa, CVV, OTP, credenciales y datos de otros clientes (se sanean antes de cada llamada) |
| 8 | ¿Costo? | Medido con 3 reclamos reales: **7,391 tokens de entrada y 11,161 de salida** (la salida incluye el razonamiento interno de `gpt-5-mini`), es decir ≈ 2,460 de entrada y ≈ 3,720 de salida por reclamo. Con la tarifa de lista de `gpt-5-mini` (USD 0.25 / 1M entrada, USD 2.00 / 1M salida; confirmar en la suscripción) son **≈ USD 0.008 por reclamo**, ≈ USD 8 por 1,000 reclamos. Los embeddings son despreciables (políticas indexadas una vez). **STT y TTS no están medidos** (sin *deployments*); su costo se suma por minuto de audio y por carácter sintetizado. La infraestructura (Azure SQL, Qdrant Cloud) usa hoy tiers gratuitos |
| 9 | ¿SLA propuesto? | Hoy no es defendible: 65 s p50. Objetivo tras reducir viajes a la BD: respuesta inicial < 10 s p95; resolución HITL < 24 h; reembolso ≤ 7 días hábiles; disponibilidad 99.5 % |
| 10 | ¿Qué cambiaría antes de producción? | Pool de conexiones y reducción de consultas por reclamo (la mayor mejora de latencia), Key Vault, *rate limiting*, WAF, auditoría inmutable, revisión legal/PII, pruebas de carga, evaluación automática de extracción y respuestas, y desplegar STT/TTS reales |

## 11. Reproducibilidad y entrega

`README.md` describe la instalación, las variables (`.env.example` sin secretos), el esquema, la semilla, la ejecución y las pruebas. Las dependencias están fijadas en `requirements.txt`. Secuencia mínima:

```
pip install -r requirements.txt
cp .env.example .env            # completar Azure OpenAI, Azure SQL y Qdrant
python scripts/aplicar_esquema.py
python scripts/seed_db.py --caso-id C-07 --semilla 4213
python scripts/ingestar_politicas.py
python main.py --caso-id C-07 --semilla 4213 --aprobar APROBADA
python -m pytest tests -v
python scripts/smoke_test.py
```

Índice de evidencia (carpeta `evidencia/`):

| Archivo | Contenido |
|---|---|
| `pruebas/resultado_pytest.txt` | Suite completa: 79 passed, 1 skipped |
| `pruebas/resultado_smoke_test.txt` | 7 escenarios + ciclo HITL, resultado OK |
| `pruebas/resultado_azure_parcial.txt` | Ejecución real con Azure OpenAI (STT/TTS simulados) |
| `pruebas/demo_duplicada_aprobada.txt`, `demo_duplicada_rechazada.txt` | Ciclo HITL aprobado y rechazado |
| `resumen_metricas.md`, `resumen_metricas_azure.md` | Latencias, tokens, costo, errores y aprobaciones (simulado y real) |
| `trazas.jsonl`, `logs.jsonl`, `metricas.jsonl` | Telemetría cruda (se regenera al ejecutar; no se versiona) |
| `fallas/falla_1..3/` | Las tres fallas reales con diagnóstico |

Pendientes de entrega:
- [ ] Video ≤ 10 min con código, terminal y demo reales, nombrado `C-07_4213_Melgarejo.mp4` (enlace en README e informe)
- [ ] Repetir `main.py` y `smoke_test.py` con `PROVEEDOR_IA=azure` cuando existan los *deployments* de Whisper y TTS, y guardar la salida en `evidencia/pruebas/`
- [ ] Liquibase real contra Azure SQL (`docker compose --profile migrar run --rm liquibase`)
- [x] Declaración de uso de IA completada
- [x] `.env` fuera del repositorio; `.env.example` sin secretos
