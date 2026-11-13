# Informe — Agente multimodal de reclamos bancarios

**Alumno:** _completar_ · **CASO_ID:** C-07 · **SEMILLA:** 4213 · **Video:** _pegar enlace no listado_

> Esqueleto con los hechos verificables del proyecto. Complete lo marcado como _completar_ y no agregue resultados que no haya ejecutado.

## 1. Problema y usuario
Analistas de reclamos de un banco reciben cobros duplicados o no autorizados con tarjeta. El cliente aporta un relato (voz) y una constancia de pago (imagen);
la verdad oficial está en la BD. _Completar: por qué IA y por qué multimodal con sus palabras._

## 2. Arquitectura
Ver [`arquitectura.md`](arquitectura.md): 9 capas, categorías Percepción / Dato maestro / Inferencia / Acción, decisiones y límites.

## 3. Implementación multimodal
Fuentes: audio (STT), imagen (visión + validación de formato), base de datos (MCP) y políticas (RAG). Contradicciones: BD > imagen > relato; se registran y se escalan.
Degradación: imagen inválida → pedir información; fallo técnico → respuesta segura + ticket `PENDIENTE_TECNICO`.

## 4. Agente y razonamiento
Prompts versionados en `src/reclamos/agente/prompts/`; salida JSON validada con Pydantic; el motor de reglas decide y el agente solo coincide o escala.

## 5. Tools y datos
14 tools MCP tipadas con envoltorio `{ok, data|error}`; acciones con verificación de aprobación en BD, idempotencia y una acción por reclamo.

## 6. Human in the Loop
`interrupt()` antes de anular/reembolsar; rol ANALISTA/SUPERVISOR según umbral; expiración (`EXPIRADA` → sin acción + escalamiento); reanudación desde el checkpoint en Azure SQL, incluso desde otro proceso.

## 7. Observabilidad
Un span raíz por ejecución (`reclamo.procesar`), un span por nodo, tool, LLM y RAG; atributos `caso.id`, `caso.semilla`, tokens y costo estimado; PII enmascarada.
Evidencia: `evidencia/trazas.jsonl`, `logs.jsonl`, `metricas.jsonl`, `resumen_metricas.md`; OTLP → Jaeger si hay colector.

## 8. Pruebas, fallas y contradicciones
Ver [`pruebas.md`](pruebas.md) y `evidencia/fallas/`.

## 9. Diario de decisiones y uso de IA
[`diario_decisiones.md`](diario_decisiones.md) · [`declaracion_uso_ia.md`](declaracion_uso_ia.md)

## 10. ¿Está listo para producción?

| # | Pregunta | Respuesta |
|---|---|---|
| 1 | ¿Qué funciona? | Flujo extremo a extremo con 7 tipos de caso, HITL con reanudación persistente, idempotencia, trazas y métricas (ver `pruebas.md`) |
| 2 | ¿Qué no funciona aún? | Autenticación real (OTP de demostración), antifraude, PDF/multi-idioma; la ruta Azure OpenAI no se ejecutó en este entorno; Liquibase real no probado (se usó un runner Python con el mismo changelog) |
| 3 | ¿Riesgos? | Alucinación de campos en la visión, comprobantes falsificados, inyección de instrucciones, reembolso indebido (mitigado por motor + HITL) |
| 4 | ¿Métricas que faltan? | Precisión de extracción, falsos escalamientos, tiempo de resolución, CSAT |
| 5 | ¿Qué falla primero al escalar? | Cuota TPM de Azure OpenAI, pool de conexiones SQL (hoy una conexión por operación), cola de analistas, Qdrant local (un proceso) |
| 6 | ¿Qué requiere más seguridad? | Tools de acción, OTP/identidad, subida de archivos, secretos (usar Key Vault/Managed Identity), clave de analista → autenticación real |
| 7 | ¿Qué nunca debe llegar al modelo? | DNI, tarjeta completa, CVV, OTP, credenciales, datos de otros clientes |
| 8 | ¿Costo? | _Completar con medición real de Azure_: tokens por reclamo (visión + razonamiento) + STT/TTS por segundo + infraestructura. Con el mock el costo es una estimación de referencia |
| 9 | ¿SLA propuesto? | Respuesta inicial < 8 s p95; resolución HITL < 24 h; reembolso ≤ 7 días hábiles; disponibilidad 99.5 % |
| 10 | ¿Qué cambiaría antes de producción? | Key Vault, *rate limiting*, WAF, auditoría inmutable, revisión legal/PII, pruebas de carga, evaluación automática de extracción y respuestas |

## 11. Checklist de entrega

- [ ] Video ≤ 10 min con código, terminal y demo reales (enlace en README e informe)
- [ ] `main.py` / `smoke_test.py` ejecutados con `PROVEEDOR_IA=azure` y salida guardada en `evidencia/pruebas/`
- [ ] Liquibase ejecutado contra Azure SQL (`docker compose --profile migrar run --rm liquibase`)
- [ ] `declaracion_uso_ia.md` completada con experiencia propia
- [ ] `.env` fuera del repositorio; `.env.example` sin secretos
