# Declaración de uso de IA

> **Borrador generado con el asistente.** Los puntos 3, 4 y 5 deben reflejar **su** experiencia real; edítelos antes de entregar.
> Una declaración del tipo "la IA siempre acertó" no cumple el requisito.

## 1. Herramientas usadas y para qué

- **GitHub Copilot (AI assistant en VS Code):** diseño del plano (`planos.md`), generación del código, pruebas, scripts y documentación.
- **Azure OpenAI (en ejecución, no en desarrollo):** chat, visión, Whisper, TTS y embeddings dentro del agente. En desarrollo y pruebas se usó el proveedor *mock*.

## 2. Código sugerido que se incorporó (archivo y función)

| Archivo | Qué contiene |
|---|---|
| `src/reclamos/memoria/sqlserver_saver.py` | `SqlServerSaver` (checkpointer en SQL Server, modelado sobre `InMemorySaver`) |
| `src/reclamos/politicas/motor.py` | `evaluar()` — motor determinista de políticas |
| `src/reclamos/orquestador/` | Grafo, nodos, routers, servicio y HITL con `interrupt` |
| `src/reclamos/mcp_server/tools.py` | Tools MCP, idempotencia y verificación de aprobación |
| `src/reclamos/escenario/escenario.py` | Generación determinista del escenario por `CASO_ID` + `SEMILLA` |
| `src/reclamos/api/app.py`, `ui/` | API FastAPI y web mínima |
| `tests/`, `scripts/` | Pruebas, `smoke_test.py`, métricas |

## 3. Modificaciones propias y por qué

_Complete aquí qué cambió usted (por ejemplo: ajustó políticas P-xx, el umbral de supervisor, los textos hablados, el formato de la constancia) y por qué._

## 4. Decisiones propias que la IA no habría tomado

_Complete aquí. Ejemplos candidatos: elegir Azure SQL como checkpointer, exigir `OTP` antes de la visión, solo-audio como salida._

## 5. Caso obligatorio: una propuesta incorrecta/incompleta de la IA

Hechos ocurridos durante la construcción (confirme y elija el que mejor represente su experiencia):

1. **Corrección incompleta del checkpointer.** Ante un deadlock (SQL 1205) en `put_writes`, la primera solución propuesta fue añadir
   `WITH (UPDLOCK, HOLDLOCK)` al `IF NOT EXISTS … INSERT`. Eliminó el error inmediato pero introdujo bloqueos de rango: una ejecución de la suite tardó
   **678 s** con un `HYT00` (timeout de consulta) y otra **38 s**, con flujos individuales de 7–9 s. Se corrigió cambiando a `INSERT` + captura de
   clave duplicada (suite: **~10 s**). Detalle en `evidencia/fallas/falla_1/`.
2. **Pruebas que "pasaban" por la razón equivocada.** Una prueba adversarial invocaba la tool `anular_transaccion` con argumentos inexistentes
   y el error de firma la hacía "pasar" sin ejercitar la guarda de aprobación. Se detectó al revisar las firmas reales. Detalle en `falla_3`.
3. **Supuestos erróneos sobre el contrato interno.** Las primeras pruebas esperaban nombres de respuesta que no existían (`ESCALAR_OPERADOR`, `ESTADO_RECLAMO`),
   y un helper de imágenes generaba rectángulos con coordenadas inválidas (`ValueError: x1 must be greater than or equal to x0`).
