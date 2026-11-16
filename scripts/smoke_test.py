"""Prueba de humo: esquema + semilla + un reclamo de cada resultado posible, extremo a extremo, y el ciclo HITL.

Uso:  python scripts/smoke_test.py          (con PROVEEDOR_IA=mock no gasta IA; con azure usa los servicios reales)
Termina con código 0 solo si TODAS las verificaciones pasan.

Cada ejecución escribe el paso a paso en temporal/smoke_test_<AAAA-MM-DD_HH-MM-SS>.log (carga de la BD, audio y
constancia generados, nodos del grafo, tools, LLM, STT/TTS, SQL, HITL y errores con traza).
"""
from __future__ import annotations

import logging
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from reclamos import db  # noqa: E402
from reclamos.config import get_settings  # noqa: E402
from reclamos.escenario import construir_escenario  # noqa: E402
from reclamos.escenario.artefactos import generar_artefactos  # noqa: E402
from reclamos.observabilidad.otel import iniciar_registro  # noqa: E402
from reclamos.orquestador.servicio import ProcesadorReclamos  # noqa: E402
import seed_db  # noqa: E402

log = logging.getLogger("reclamos.smoke")
TIPOS = ("DUPLICADA", "SIN_CONSENTIMIENTO", "MONTO_DISCREPANTE", "TARJETA_DESHABILITADA", "SIN_EVIDENCIA", "AJENA",
         "MONEDA_USD")
ESPERADO = {"ANULACION": "PENDIENTE_APROBACION", "REEMBOLSO": "PENDIENTE_APROBACION", "ESCALAR_OPERADOR": "ESCALADO_",
            "PEDIR_INFO": "PEDIR_INFO", "RECHAZAR": "RECHAZO_AJENA", "NO_DISPONIBLE_MONEDA": "NO_DISPONIBLE_MONEDA"}


def informar(linea: str) -> None:
    """Línea de resultado: a la consola y, a nivel DEBUG, al fichero de temporal/ (la consola ya muestra los INFO)."""
    print(linea, flush=True)
    log.debug("RESULTADO PARCIAL | %s", linea)


def reclamar(srv: ProcesadorReclamos, tipo: str) -> tuple:
    """Carga el escenario, genera audio + constancia, abre sesión y procesa el reclamo. Devuelve (escenario, resultado)."""
    s = get_settings()
    esc = construir_escenario(s.caso_id, s.semilla, tipo)
    log.info("[%s] escenario: cliente=%s operación=%s monto=S/%s facturada=%s umbral HITL=%s -> acción esperada %s",
             tipo, esc.cliente_id, esc.tx_principal_codigo, esc.monto_bd, esc.facturada, esc.umbral_hitl,
             esc.accion_esperada)
    log.info("[%s] paso 1/4: cargar el escenario en la BD", tipo)
    seed_db.cargar(esc)
    with tempfile.TemporaryDirectory() as tmp:
        log.info("[%s] paso 2/4: generar el audio del relato y la imagen de la constancia (proveedor %s)", tipo,
                 srv.prov.nombre)
        rutas = generar_artefactos(esc, Path(tmp), srv.prov)
        log.info("[%s] paso 3/4: iniciar la sesión del cliente", tipo)
        ses = srv.iniciar_sesion(s.caso_id, s.semilla)
        log.info("[%s] paso 4/4: procesar el reclamo (sesión %s)", tipo, ses["sesion_id"])
        res = srv.procesar(ses["sesion_id"], audio_path=rutas["audio"], imagen_path=rutas["imagen"])
    return esc, res


def main() -> int:
    ruta_log = iniciar_registro("smoke_test")
    s = get_settings()
    t_inicio = time.perf_counter()
    print(f"[log] paso a paso en {ruta_log}", flush=True)
    log.info("smoke test: caso %s/%s, proveedor IA=%s, BD=%s/%s", s.caso_id, s.semilla, s.proveedor, s.sql_server,
             s.sql_database)
    log.info("comprobando la conexión a la base de datos")
    db.uno("SELECT 1 AS ok")
    informar(f"[ok] conexión a SQL ({s.sql_server}/{s.sql_database}); proveedor IA = {s.proveedor}")
    log.info("creando el procesador (grafo, checkpointer, RAG y cliente MCP)")
    srv = ProcesadorReclamos()
    fallos = 0
    try:
        for n, tipo in enumerate(TIPOS, 1):
            log.info("===== escenario %d/%d: %s =====", n, len(TIPOS), tipo)
            try:
                esc, res = reclamar(srv, tipo)
                tipo_resp = res["respuesta"]["tipo_respuesta"]
                ok = tipo_resp.startswith(ESPERADO[esc.accion_esperada]) and bool(res["audio_path"]) and not res["error"]
                if not ok:
                    log.error("[%s] FALLA: esperado=%s obtenido=%s audio=%s error=%s", tipo, esc.accion_esperada,
                              tipo_resp, bool(res["audio_path"]), res["error"])
                informar(f"[{'ok' if ok else 'FALLA'}] {tipo:<22} esperado={esc.accion_esperada:<20} "
                         f"obtenido={tipo_resp:<22} {res['latencia_total_ms']:.0f} ms  trace={res['trace_id'][:8]}")
            except Exception as exc:
                ok = False
                log.exception("[%s] el escenario terminó con una excepción", tipo)
                informar(f"[FALLA] {tipo:<22} EXCEPCIÓN {type(exc).__name__}: {str(exc)[:120]}")
            fallos += not ok

        log.info("===== ciclo HITL: DUPLICADA -> aprobar -> reanudar desde el checkpoint =====")
        try:
            esc, res = reclamar(srv, "DUPLICADA")
            log.info("aprobación pendiente %s; el supervisor la aprueba", res["aprobacion_id"])
            fin = srv.resolver_hitl(res["aprobacion_id"], "APROBADA", "smoke test", "smoke", "SUPERVISOR")
            ok = fin["respuesta"]["accion_final"] == esc.accion_esperada
            if not ok:
                log.error("HITL: esperado accion_final=%s obtenido=%s", esc.accion_esperada,
                          fin["respuesta"]["accion_final"])
            informar(f"[{'ok' if ok else 'FALLA'}] HITL aprobar -> reanuda desde checkpoint -> "
                     f"{fin['respuesta']['accion_final']}")
        except Exception as exc:
            ok = False
            log.exception("el ciclo HITL terminó con una excepción")
            informar(f"[FALLA] HITL EXCEPCIÓN {type(exc).__name__}: {str(exc)[:120]}")
        fallos += not ok
    finally:
        srv.cerrar()
    resultado = "OK" if not fallos else f"{fallos} FALLA(S)"
    log.info("smoke test terminado en %.1f s: %s", time.perf_counter() - t_inicio, resultado)
    print("RESULTADO:", resultado)
    print(f"[log] {ruta_log}", flush=True)
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
