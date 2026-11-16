# Declaración de uso de IA

> Los hechos de las secciones 3 a 5 provienen del historial real de trabajo con el asistente durante la construcción del proyecto (sesiones de Copilot en VS Code). La IA **no** acertó siempre: los casos de abajo son correcciones que hubo que pedir o detectar.

## 1. Herramientas usadas y para qué

- **GitHub Copilot (AI assistant en VS Code):** diseño del plano (`planos.md`), generación de código, pruebas, scripts y documentación; ejecución de las pruebas y de las verificaciones contra los servicios en la nube.
- **Azure OpenAI vía Foundry (en ejecución, no en desarrollo):** `gpt-5-mini` (chat, visión y router) y `text-embedding-3-small` (RAG) dentro del agente; Whisper y TTS están previstos pero sus *deployments* aún no existen. En desarrollo y en las pruebas se usó el proveedor *mock*.

## 2. Código sugerido que se incorporó (archivo y función)

| Archivo | Qué contiene |
|---|---|
| `src/reclamos/memoria/sqlserver_saver.py` | `SqlServerSaver` (checkpointer en SQL Server, modelado sobre `InMemorySaver`) |
| `src/reclamos/politicas/motor.py` | `evaluar()` — motor determinista de políticas (incluida P-11) |
| `src/reclamos/orquestador/` | Grafo, nodos, routers, servicio y HITL con `interrupt` |
| `src/reclamos/mcp_server/tools.py` | Tools MCP, idempotencia y verificación de aprobación |
| `src/reclamos/escenario/escenario.py` | Generación determinista del escenario por `CASO_ID` + `SEMILLA` |
| `src/reclamos/db.py` | `calificar()`: antepone el esquema `multimodal` a las tablas del proyecto |
| `scripts/aplicar_esquema.py` | Traductor del changelog YAML a T-SQL |
| `tests/sql_falso.py`, `tests/conftest.py` | SQL simulado con SQLite para pruebas rápidas |
| `src/reclamos/api/app.py`, `ui/` | API FastAPI y web mínima |
| `tests/`, `scripts/` | Pruebas, `smoke_test.py`, métricas |

## 3. Modificaciones propias y por qué

Cambios que pedí yo al asistente y que modificaron el resultado inicial:

- **Servicios en la nube en lugar de contenedores locales.** Pedí quitar `qdrant` y `sqlserver-local` del `docker-compose.yml` y usar Qdrant Cloud y Azure SQL, que ya tenía disponibles (se añadió `QDRANT_API_KEY`).
- **Azure OpenAI vía Foundry con `gpt-5-mini` y `text-embedding-3-small`.** Definí los *deployments* y el asistente adaptó el proveedor (parámetros de los modelos de razonamiento: sin `temperature`, `max_completion_tokens`).
- **Señal de fraude con OTP.** Pedí transacciones de prueba **con y sin OTP** para distinguir el fraude: dio lugar a `Transaccion.autenticada_otp`, a la política **P-11**, al tipo de escenario `SIN_CONSENTIMIENTO_CON_OTP` y a `db/datos_prueba_fraude_otp.sql`.
- **Esquema en YAML.** Exigí que toda la creación de tablas fuera YAML (Liquibase) y que solo los datos de prueba fueran `.sql`.
- **Esquema `multimodal`.** Como la base de datos es compartida con otros trabajos, pedí que todas las tablas vivieran en un esquema propio.
- **Pruebas rápidas.** Pedí mocks en las pruebas para que no demoraran (ver sección 5).

## 4. Decisiones propias que la IA no habría tomado

- Usar **Qdrant Cloud y Azure SQL** del curso en vez de la infraestructura local que el asistente había montado por defecto.
- Tratar el **OTP de la operación** como dato maestro del fraude (P-11), distinto del OTP de verificación de quien reclama: el asistente no propuso esa regla de negocio.
- Aislar el proyecto en un **esquema propio** en una base compartida, en lugar de usar `dbo`.
- Pedir que el **entorno de pruebas no toque ningún servicio real** y validar yo mismo el caso de integración contra Azure SQL (lo ejecuté en mi consola y confirmé el resultado).

## 5. Caso obligatorio: propuestas incorrectas o ineficientes de la IA

**Caso principal — pruebas que llamaban a la base de datos real.** El asistente escribió una suite que ejecutaba cada flujo contra Azure SQL *serverless* real. Cada flujo tardaba ≈ 70 s y la suite completa superó los **20 minutos**. Lo detecté al esperar el resultado y pregunté si no era mejor mockear los servicios; luego pedí que lo único local fueran mocks en las pruebas. El asistente construyó un SQL simulado (SQLite) y fijó el entorno de pruebas: la suite pasó de más de 20 min a **≈ 14 s**. Quedó una limitación que sí hay que declarar: el simulador no valida T-SQL real, `CHECK` ni claves foráneas, por lo que se conserva una prueba de integración opcional (`RUN_INTEGRACION=1`) que ejecuté contra Azure SQL (1 passed).

Otros hechos en los que la IA se equivocó o dejó algo incompleto:

1. **Corrección incompleta del checkpointer.** Ante un deadlock (SQL 1205) en `put_writes`, la primera solución fue `WITH (UPDLOCK, HOLDLOCK)`. Eliminó el error inmediato pero introdujo bloqueos de rango: una ejecución tardó **678 s** con un `HYT00` y otra **38 s**. Se corrigió con `INSERT` + captura de clave duplicada (suite: ≈ 10 s). Ver `evidencia/fallas/falla_1/`.
2. **Prueba de seguridad que "pasaba" por la razón equivocada.** Una prueba adversarial llamaba a `anular_transaccion` con argumentos inexistentes; el error de firma la hacía pasar sin ejercitar la guarda de aprobación. Ver `falla_3`.
3. **Esquema entregado como `.sql`.** La primera versión del changelog eran archivos `.sql`; no cumplía lo que pedí (YAML) y se rehízo como `changeSet` nativos.
4. **Smoke test sin el entorno correcto.** En la verificación final, `scripts/smoke_test.py` fallaba porque no activaba `DEMO_MODE` (no podía leer el OTP simulado) y, con el proveedor *mock*, la colección de Qdrant Cloud (1536 dimensiones) rechazaba los vectores del mock (256): hubo que corregir el script y ejecutar el *mock* con Qdrant local.
5. **Supuestos erróneos sobre el contrato interno.** Las primeras pruebas esperaban nombres de respuesta que no existían (`ESCALAR_OPERADOR`, `ESTADO_RECLAMO`) y un helper de imágenes generaba rectángulos inválidos (`ValueError: x1 must be greater than or equal to x0`; ver `falla_2`).

**Lo que sigue sin verificar:** la calidad real de Whisper y TTS (sin *deployments*), la ejecución de Liquibase real y la calidad de la extracción de la visión más allá de las tres ejecuciones con `gpt-5-mini` registradas en `evidencia/resumen_metricas_azure.md`.
