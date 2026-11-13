# Agente multimodal de reclamos bancarios

Agente de IA que atiende **reclamos de pagos con tarjeta** (cobro duplicado, sin consentimiento, monto distinto…) a partir de
**voz + imagen de la constancia de pago**, contrasta con la base de datos oficial, aplica las políticas del banco,
pide **aprobación humana** antes de mover dinero y responde **solo en audio**. Capstone del Curso 4 (Data Science Research Perú).

- Caso: `caso.md` (Opción B – análisis de reclamos bancarios). Plano de diseño: [`planos.md`](planos.md).
- Stack: **Azure OpenAI** (chat, visión, Whisper, TTS, embeddings) · **LangGraph** con checkpointer en **Azure SQL** ·
  **MCP** (servidor de tools sobre SQL) · **Qdrant** (RAG de políticas) · **OpenTelemetry** · **FastAPI/OpenAPI** + web mínima · **Liquibase** (YAML).

## Qué hace (flujo)

```
audio + constancia.png ─► STT ─► OTP ─► visión (campos) ─► validar constancia ─► ticket (idempotente)
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
| Azure OpenAI | deployments: chat, router, whisper, tts, embeddings |
| Docker (opcional) | para Qdrant, OTel, Jaeger, MailHog y Liquibase |

## Instalación

```powershell
conda activate multiagentes
pip install -r requirements.txt
copy .env.example .env        # complete SUS valores (nunca suba .env)
```

Para probar **sin costo ni red** use `PROVEEDOR_IA=mock` en `.env` (STT/visión/TTS/LLM simulados, mismo flujo y mismas tools).

## Base de datos (Liquibase YAML)

```powershell
# Opción A – Liquibase (Docker o CLI):
docker compose --profile migrar run --rm liquibase
# Opción B – sin Java/Docker: ejecuta el MISMO changelog con un runner Python:
python scripts/aplicar_esquema.py            # añade --reset para recrear
```

El esquema vive en `db/changelog/db.changelog-master.yaml` + `db/changelog/sql/*.sql` (cada changeSet con *rollback*).
Las tablas del checkpointer (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) las crea `SqlServerSaver.setup()` al iniciar.

## CASO_ID y SEMILLA

`CASO_ID` + `SEMILLA` determinan el escenario sintético (cliente, tipo de caso, montos, códigos, fechas, OTP…). Mismos valores = mismos datos.

```powershell
python scripts/seed_db.py --caso-id C-07 --semilla 4213        # carga el escenario en la BD
python scripts/generar_datos.py --caso-id C-07 --semilla 4213  # datos/constancia.png + datos/reporte.(wav|mp3)
python scripts/ingestar_politicas.py                           # indexa P-01..P-10 en Qdrant (idempotente)
```

## Ejecución

```powershell
# 1) Prueba principal (extremo a extremo por CLI; aprueba como analista simulado)
python main.py --caso-id C-07 --semilla 4213 --aprobar APROBADA
python main.py --caso-id C-07 --semilla 4213 --tipo DUPLICADA --aprobar RECHAZADA   # fuerza un tipo de caso

# 2) API + web:  http://localhost:8000  (cliente)  ·  /analista.html  ·  /docs (OpenAPI)
uvicorn --app-dir src reclamos.api.app:app --port 8000

# 3) Analista por consola
python scripts/hitl_cli.py listar
python scripts/hitl_cli.py decidir APR-XXXXXXXXXX APROBADA "validado" --aprobador ana --rol SUPERVISOR
```

Tipos de caso: `DUPLICADA`, `SIN_CONSENTIMIENTO`, `MONTO_DISCREPANTE`, `TARJETA_DESHABILITADA`, `SIN_EVIDENCIA`, `AJENA`, `MONEDA_USD`.

## Pruebas y evidencia

```powershell
python scripts/smoke_test.py          # 7 escenarios + ciclo HITL, extremo a extremo (segundos con mock)
python -m pytest tests                # unitarias + flujos + adversariales + API + persistencia
python scripts/resumen_metricas.py    # p50/p95, errores, aprobaciones, tokens/costo desde evidencia/trazas.jsonl
```

> Las pruebas **recargan los datos de negocio** de la BD de `.env`: use una base de desarrollo.

Evidencia: `evidencia/trazas.jsonl`, `logs.jsonl`, `metricas.jsonl`, `resumen_metricas.md`, `pruebas/`, `fallas/`.
Con `docker compose up -d` y `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`, las trazas se ven en Jaeger (http://localhost:16686).

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
  hitl/  memoria/  seguridad/          aprobaciones, checkpointer Azure SQL, OTP y PII
  observabilidad/                      OpenTelemetry (+ JSONL de evidencia)
  api/                                 FastAPI (OpenAPI, problem+json)
ui/  db/  scripts/  tests/  docs/  evidencia/  infra/
```

## Seguridad (resumen)

Secretos solo por entorno · OTP antes de procesar · PII enmascarada en logs/trazas · el LLM nunca escribe SQL (solo tools tipadas) ·
tools de acción verifican la aprobación en BD · operaciones de otro cliente no devuelven datos · subidas validadas por firma y tamaño ·
respuesta solo en audio · `DEMO_MODE=0` en producción (oculta OTP y errores internos).

## Video y declaración de IA

- Video (≤10 min, enlace no listado): _pendiente: pegar enlace_ — nombre sugerido `C-07_4213_<apellido>.mp4`.
- Informe y declaración de uso de IA: [`docs/informe.md`](docs/informe.md), [`docs/declaracion_uso_ia.md`](docs/declaracion_uso_ia.md).
