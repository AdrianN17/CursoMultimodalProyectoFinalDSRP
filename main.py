"""CLI principal: ejecuta el flujo completo sobre un escenario.

Uso:  python main.py --caso-id C-07 --semilla 4213 [--tipo DUPLICADA] [--audio a.wav --imagen c.png] [--aprobar]
Si no se pasan --audio/--imagen, se generan desde el escenario. Con --aprobar, un analista simulado decide
(solo para demo local; en producción lo hace la UI del analista).
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "src"))

from reclamos.config import get_settings  # noqa: E402
from reclamos.observabilidad.otel import iniciar_registro  # noqa: E402

log = logging.getLogger("reclamos.main")


def main() -> int:
    ruta_log = iniciar_registro("main")  # el seed y el servidor MCP (subprocesos) añaden al mismo fichero
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--caso-id", default=s.caso_id)
    ap.add_argument("--semilla", type=int, default=s.semilla)
    ap.add_argument("--tipo", default=None)
    ap.add_argument("--audio")
    ap.add_argument("--imagen")
    ap.add_argument("--aprobar", choices=["APROBADA", "RECHAZADA"], default=None)
    ap.add_argument("--sin-seed", action="store_true", help="no recargar la BD")
    a = ap.parse_args()
    print(f"[log] paso a paso en {ruta_log}", flush=True)
    log.info("main: caso %s/%s tipo=%s aprobar=%s proveedor IA=%s", a.caso_id, a.semilla, a.tipo, a.aprobar, s.proveedor)

    if not a.sin_seed:
        log.info("paso 1: cargar el escenario en la BD (scripts/seed_db.py)")
        cmd = [sys.executable, str(RAIZ / "scripts" / "seed_db.py"), "--caso-id", a.caso_id, "--semilla", str(a.semilla)]
        if a.tipo:
            cmd += ["--tipo", a.tipo]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

    from reclamos.escenario import construir_escenario
    from reclamos.escenario.artefactos import generar_artefactos
    from reclamos.orquestador.servicio import ProcesadorReclamos

    esc = construir_escenario(a.caso_id, a.semilla, a.tipo)
    log.info("paso 2: crear el procesador (grafo, checkpointer, RAG, cliente MCP)")
    srv = ProcesadorReclamos()
    audio, imagen = a.audio, a.imagen
    if not (audio or imagen):
        log.info("paso 3: generar audio y constancia del escenario en datos/")
        r = generar_artefactos(esc, RAIZ / "datos", srv.prov)
        audio, imagen = r["audio"], r["imagen"]
    log.info("paso 4: iniciar sesión y procesar el reclamo")
    ses = srv.iniciar_sesion(a.caso_id, a.semilla)
    print(f"[sesion] {ses['sesion_id']} cliente={ses['cliente_id']}  tipo={esc.tipo}  esperado={esc.accion_esperada}")
    res = srv.procesar(ses["sesion_id"], audio_path=audio, imagen_path=imagen)
    if res["pendiente_hitl"] and a.aprobar:
        log.info("paso 5: aprobación humana simulada (%s) sobre %s", a.aprobar, res["aprobacion_id"])
        print(f"[hitl] pendiente {res['aprobacion_id']} -> {a.aprobar}")
        res = srv.resolver_hitl(res["aprobacion_id"], a.aprobar, "decisión demo CLI", "analista.demo", "SUPERVISOR")
    elif res["pendiente_hitl"]:
        log.info("paso 5: queda pendiente %s; se espera la decisión desde la consola del analista", res["aprobacion_id"])
        print(f"[hitl] pendiente {res['aprobacion_id']}: apruebe o rechace desde otra consola con\n"
              f"       python scripts/hitl_cli.py decidir {res['aprobacion_id']} APROBADA \"motivo\" --rol SUPERVISOR")
    print(json.dumps({k: v for k, v in res.items() if k != "respuesta"}, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(res["respuesta"], ensure_ascii=False, indent=2, default=str))
    srv.cerrar()
    log.info("main terminado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
