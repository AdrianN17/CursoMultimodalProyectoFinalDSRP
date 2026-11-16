"""Prueba de humo (~segundos): esquema + semilla + un reclamo de cada resultado posible, extremo a extremo.

Uso:  python scripts/smoke_test.py          (MOCK por defecto si PROVEEDOR_IA=mock; con azure usa credenciales reales)
Termina con código 0 solo si TODAS las verificaciones pasan.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEMO_MODE", "1")  # el smoke test lee el OTP simulado (otp_demo) de la sesión

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from reclamos import db  # noqa: E402
from reclamos.config import get_settings  # noqa: E402
from reclamos.escenario import construir_escenario  # noqa: E402
from reclamos.escenario.artefactos import generar_artefactos  # noqa: E402
from reclamos.orquestador.servicio import ProcesadorReclamos  # noqa: E402
import seed_db  # noqa: E402

ESPERADO = {"ANULACION": "PENDIENTE_APROBACION", "REEMBOLSO": "PENDIENTE_APROBACION", "ESCALAR_OPERADOR": "ESCALADO_",
            "PEDIR_INFO": "PEDIR_INFO", "RECHAZAR": "RECHAZO_AJENA", "NO_DISPONIBLE_MONEDA": "NO_DISPONIBLE_MONEDA"}


def main() -> int:
    s = get_settings()
    db.uno("SELECT 1 AS ok")
    print(f"[ok] conexión a SQL ({s.sql_server}/{s.sql_database}); proveedor IA = {s.proveedor}")
    srv = ProcesadorReclamos()
    fallos = 0
    try:
        for tipo in ("DUPLICADA", "SIN_CONSENTIMIENTO", "MONTO_DISCREPANTE", "TARJETA_DESHABILITADA",
                     "SIN_EVIDENCIA", "AJENA", "MONEDA_USD"):
            esc = construir_escenario(s.caso_id, s.semilla, tipo)
            seed_db.cargar(esc)
            with tempfile.TemporaryDirectory() as tmp:
                rutas = generar_artefactos(esc, Path(tmp), srv.prov)
                ses = srv.iniciar_sesion(s.caso_id, s.semilla)
                res = srv.procesar(ses["sesion_id"], audio_path=rutas["audio"], imagen_path=rutas["imagen"],
                                   otp=ses.get("otp_demo"))
            tipo_resp = res["respuesta"]["tipo_respuesta"]
            ok = tipo_resp.startswith(ESPERADO[esc.accion_esperada]) and bool(res["audio_path"]) and not res["error"]
            fallos += not ok
            print(f"[{'ok' if ok else 'FALLA'}] {tipo:<22} esperado={esc.accion_esperada:<20} obtenido={tipo_resp:<22}"
                  f" {res['latencia_total_ms']:.0f} ms  trace={res['trace_id'][:8]}")
        # cierre del ciclo HITL sobre el último caso monetario
        esc = construir_escenario(s.caso_id, s.semilla, "DUPLICADA")
        seed_db.cargar(esc)
        with tempfile.TemporaryDirectory() as tmp:
            rutas = generar_artefactos(esc, Path(tmp), srv.prov)
            ses = srv.iniciar_sesion(s.caso_id, s.semilla)
            res = srv.procesar(ses["sesion_id"], audio_path=rutas["audio"], imagen_path=rutas["imagen"],
                               otp=ses.get("otp_demo"))
        fin = srv.resolver_hitl(res["aprobacion_id"], "APROBADA", "smoke test", "smoke", "SUPERVISOR")
        ok = fin["respuesta"]["accion_final"] == esc.accion_esperada
        fallos += not ok
        print(f"[{'ok' if ok else 'FALLA'}] HITL aprobar -> reanuda desde checkpoint -> {fin['respuesta']['accion_final']}")
    finally:
        srv.cerrar()
    print("RESULTADO:", "OK" if not fallos else f"{fallos} FALLA(S)")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
