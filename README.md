# Agente multimodal de reclamos bancarios

Agente de IA que atiende **reclamos de pagos con tarjeta** (cobro duplicado, sin consentimiento, monto distinto…) a partir de
**voz + imagen de la constancia de pago**, contrasta con la base de datos oficial, aplica las políticas del banco,
pide **aprobación humana** antes de mover dinero y responde **solo en audio**. Capstone del Curso 4 (Data Science Research Perú).

- Caso: `caso.md` (Opción B – análisis de reclamos bancarios). Plano de diseño: [`planos.md`](planos.md).
- Stack: **Azure OpenAI / Foundry** (chat y visión `gpt-5-mini`, embeddings; voz con **MAI-Transcribe-1.5** y **MAI-Voice-2** vía Azure Speech) · **LangGraph** con checkpointer en **Azure SQL** ·
  **MCP** (servidor de tools sobre SQL) · **Qdrant** (RAG de políticas) · **OpenTelemetry** · **FastAPI/OpenAPI** + web mínima · **Liquibase** (YAML).

## Qué hace (flujo)

```
audio + constancia.png ─► STT ─► visión (campos) ─► validar constancia ─► ticket (idempotente)
   ─► MCP: dato maestro (BD) ─► cruce relato/imagen/BD ─► motor de políticas ─► RAG (P-xx) ─► agente (infiere)
   ─► ¿acción monetaria? ─► INTERRUPT (HITL) ─► analista aprueba/rechaza ─► MCP: anular/reembolsar ─► TTS
```

Regla central — **Percepción ≠ Dato maestro ≠ Inferencia ≠ Acción**: lo que dice el cliente y lo que ve el modelo en la imagen
son *percepciones*; solo la BD es verdad oficial; el LLM *infiere* pero **decide el motor de reglas**; y las acciones
(`anular_transaccion`, `registrar_reembolso`) solo se ejecutan con una aprobación humana verificada **en la BD**.
Detalle en [`docs/arquitectura.md`](docs/arquitectura.md).

## Requisitos

| Necesidad | Versión probada |
|---|---|
| Python (conda `multiagentes`) | 3.11 |
| ODBC Driver 18 para SQL Server | 18.x |
| SQL Server / **Azure SQL** | SQL Server 2025 (LocalDB) en desarrollo; Azure SQL en producción |
| Azure OpenAI / Foundry | deployments: chat, router y embeddings; STT `mai-transcribe-1.5` y TTS `es-ES-Marta:MAI-Voice-2` (Azure Speech, misma clave del recurso) |
| Docker (opcional) | para OTel, Jaeger y Liquibase (Qdrant Cloud y Azure SQL son servicios externos) |

## Instalación

```powershell
conda activate multiagentes
pip install -r requirements.txt
copy .env.example .env        # complete SUS valores (nunca suba .env)
```

Para probar **sin costo ni red** use `PROVEEDOR_IA=mock` en `.env` (STT/visión/TTS/LLM simulados, mismo flujo y mismas tools).

## Base de datos (Liquibase YAML)

```powershell
# Opción A – Liquibase (Docker o CLI). Una sola vez, crear el esquema (el changelog y DATABASECHANGELOG viven en él):
docker compose --profile migrar run --rm liquibase execute-sql --sql="IF SCHEMA_ID('multimodal') IS NULL EXEC('CREATE SCHEMA multimodal')"
docker compose --profile migrar run --rm liquibase
# Opción B – sin Java/Docker: ejecuta el MISMO changelog con un runner Python (crea el esquema si falta):
python scripts/aplicar_esquema.py            # añade --reset para recrear solo las tablas del esquema
```

**Esquema propio `multimodal`** (`AZURE_SQL_SCHEMA`): todas las tablas viven ahí, no en `dbo`, para convivir con otros proyectos en la misma base.
El código escribe SQL sin esquema y `reclamos/db.py` (`calificar`) lo antepone a las tablas del proyecto; en el changelog, los cambios tipados usan `default-schema-name` (`db/liquibase.properties`) y los `sql` crudos `${database.defaultSchemaName}`.
> La opción A (Liquibase real) **no se ha ejecutado** en este entorno; el runner Python sí (validado contra Azure SQL).

El esquema vive en `db/changelog/db.changelog-master.yaml` (incluye `db/changelog/changes/001..009-*.yaml`, cambios YAML nativos de Liquibase con *rollback*).
Datos de prueba de fraude (operaciones con/sin OTP, política P-11): `python scripts/cargar_datos_fraude.py` (carga `db/datos_prueba_fraude_otp.sql`, que también puede ejecutarse tal cual en Azure Data Studio; ejecútelo después de `seed_db.py`).
> `aplicar_esquema.py --reset` elimina **solo las tablas del esquema del proyecto** y se niega a limpiar `dbo`.
Las tablas del checkpointer (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) las crea `SqlServerSaver.setup()` al iniciar, también en `multimodal`.

## CASO_ID y SEMILLA

`CASO_ID` + `SEMILLA` determinan el escenario sintético (cliente, tipo de caso, montos, códigos, fechas, si la operación se autenticó con OTP…). Mismos valores = mismos datos.

```powershell
python scripts/seed_db.py --caso-id C-07 --semilla 4213        # carga el escenario en la BD
python scripts/generar_datos.py --caso-id C-07 --semilla 4213  # datos/constancia.png + datos/reporte.(wav|mp3)
python scripts/ingestar_politicas.py                           # indexa P-01..P-11 en Qdrant (idempotente)
```

## Ejecución

```powershell
# 1) Prueba principal (extremo a extremo por CLI)
python main.py --caso-id C-07 --semilla 4213 --tipo DUPLICADA --aprobar APROBADA   # aprueba como analista simulado
python main.py --caso-id C-07 --semilla 4213 --tipo DUPLICADA --aprobar RECHAZADA  # lo rechaza
python main.py --caso-id C-07 --semilla 4213 --tipo DUPLICADA                      # sin --aprobar: queda PENDIENTE y muestra el comando para aprobarlo
# (sin --tipo, la semilla 4213 sortea SIN_EVIDENCIA: PEDIR_INFO, sin aprobación humana)

# 2) API + web:  http://localhost:8000  (cliente)  ·  /analista.html  ·  /docs (OpenAPI)
uvicorn --app-dir src reclamos.api.app:app --port 8000

# 3) Aprobación por consola: reanuda el flujo pendiente desde el checkpoint (puede ser otra terminal u otro proceso)
python scripts/hitl_cli.py listar
python scripts/hitl_cli.py decidir APR-XXXXXXXXXX APROBADA "validado" --aprobador ana --rol SUPERVISOR
python scripts/hitl_cli.py decidir APR-XXXXXXXXXX RECHAZADA "no procede" --rol SUPERVISOR
```

No hay verificación por OTP ni envío de correos: el cliente se identifica por la sesión y los escalamientos quedan registrados en el ticket (`EN_ESCALAMIENTO`). El OTP solo existe como **dato maestro** (`Transaccion.autenticada_otp`, política P-11).

Tipos de caso: `DUPLICADA`, `SIN_CONSENTIMIENTO` (operación sin OTP → reclamo normal), `SIN_CONSENTIMIENTO_CON_OTP` (operación validada con OTP → escala a operador, P-11; solo con `--tipo`), `MONTO_DISCREPANTE`, `TARJETA_DESHABILITADA`, `SIN_EVIDENCIA`, `AJENA`, `MONEDA_USD`.

## Pruebas y evidencia

```powershell
python scripts/smoke_test.py          # 7 escenarios + ciclo HITL, extremo a extremo; guarda su paso a paso en temporal/smoke_test_<fecha-hora>.log
python -m pytest tests                # unitarias + flujos + adversariales + API + persistencia (IA mock y SQL simulado: ~15 s, sin red)
RUN_INTEGRACION=1 python -m pytest tests   # igual, pero contra la BD real de .env (la recarga) e incluye pruebas entre procesos
python scripts/resumen_metricas.py    # p50/p95, errores, aprobaciones, tokens/costo desde evidencia/trazas.jsonl
```

> Por defecto las pruebas **no tocan ninguna BD real**. Con `RUN_INTEGRACION=1` sí **recargan los datos de negocio** de la BD de `.env`: use una base de desarrollo (en PowerShell: `$env:RUN_INTEGRACION="1"; python -m pytest tests`).

Evidencia: `evidencia/trazas.jsonl`, `logs.jsonl`, `metricas.jsonl`, `resumen_metricas.md`, `pruebas/`, `fallas/`.
Con `docker compose up -d` y `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`, las trazas se ven en Jaeger (http://localhost:16686).

### Registro paso a paso (`temporal/`)

Cada ejecución (smoke test, `main.py`, API, pruebas, `seed_db.py`, `hitl_cli.py`…) crea un fichero propio con la fecha y la hora:
`temporal/<proceso>_<AAAA-MM-DD_HH-MM-SS>.log` (p. ej. `temporal/smoke_test_2026-11-16_08-40-12.log`). El script imprime su ruta al empezar y al terminar.
La carpeta está en `.gitignore`; cámbiela con `TEMPORAL_DIR`.

Cada línea lleva hora, `CASO_ID/SEMILLA`, `trace_id`, proceso, nivel y módulo. El fichero registra **todo** (nivel DEBUG), la consola solo lo importante (INFO):

| Qué se ve | Ejemplo |
|---|---|
| Entrada/salida de cada span, con sangría y duración | `-> nodo.stt` … `<- nodo.stt 1.7 ms` |
| Cada nodo del grafo y qué claves del estado actualizó | `nodo validar_entrada terminó; actualiza: …` |
| Cada tool MCP con sus argumentos y su resultado (saneados) | `tool consultar_transaccion(...)` → `OK en 52 ms -> {...}` |
| LLM, visión, STT, TTS y embeddings: modelo, tokens, tiempo | `LLM analizar_reclamo [gpt-5-mini]: 2460 tokens de entrada…` |
| RAG: políticas recuperadas y su puntuación | `RAG: consulta de 312 caracteres -> P-01(0.71), P-03(0.66)` |
| SQL: conexión, cada consulta con su duración, confirmación/reversión | `SQL 41 ms \| SELECT …` |
| Checkpointer y HITL: guardado, lectura, decisión y reanudación | `reanudando el hilo SES-… desde el checkpoint` |
| Llamadas HTTP a Azure OpenAI / Speech / Qdrant (sin claves) | `HTTP Request: POST … 200 OK` |
| API: cada petición y su tiempo | `HTTP POST /api/v1/reclamos -> 200 en 61000 ms` |
| Errores con traza completa, con PII y OTP enmascarados | `nodo recuperar_politica falló…` |

Los subprocesos (servidor MCP por stdio, `hitl_cli.py` lanzado desde una prueba, `seed_db.py` desde `main.py`) **añaden al mismo fichero** de la ejecución que los lanzó.
Para seguirlo en vivo: `Get-Content temporal\smoke_test_*.log -Tail 20 -Wait`.

## Estructura

```
src/reclamos/
  config.py  db.py                     configuración y acceso a SQL (consultas parametrizadas)
  escenario/                           semilla -> datos sintéticos, constancia PNG y audio
  proveedores/                         ProveedorIA: azure_openai.py | mock.py
  agente/                              agente, esquemas Pydantic, prompts/ versionados
  orquestador/                         grafo LangGraph, nodos, routers, servicio (sesiones, HITL)
  mcp_server/                          tools MCP (server.py, tools.py, dto.py) + cliente con trazas
  politicas/                           motor determinista + calendario (corte de facturación)
  validadores/  modalidades/           validación de constancia y de archivos (magic bytes)
  rag/                                 ingesta/recuperación Qdrant + politicas_reclamacion.md
  hitl/  memoria/  seguridad/          aprobaciones, checkpointer Azure SQL y PII
  observabilidad/                      OpenTelemetry (+ JSONL de evidencia) y log por ejecución en temporal/
  api/                                 FastAPI (OpenAPI, problem+json)
ui/  db/  scripts/  tests/  docs/  evidencia/  infra/
```

## Seguridad (resumen)

Secretos solo por entorno · PII enmascarada en logs/trazas · el LLM nunca escribe SQL (solo tools tipadas) ·
tools de acción verifican la aprobación en BD · operaciones de otro cliente no devuelven datos · subidas validadas por firma y tamaño ·
respuesta solo en audio · `DEMO_MODE=0` en producción (oculta los errores internos).

## Video y declaración de IA

- Video (≤10 min, enlace no listado): _pendiente: pegar enlace_ — nombre del archivo `C-07_4213_Melgarejo.mp4`.
- Informe: [`docs/informe.pdf`](docs/informe.pdf) (se regenera desde `docs/informe.md` con `python scripts/generar_informe_pdf.py`; requiere `pip install markdown` y Edge o Chrome) · declaración de uso de IA: [`docs/declaracion_uso_ia.md`](docs/declaracion_uso_ia.md).
