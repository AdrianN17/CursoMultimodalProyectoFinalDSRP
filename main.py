"""CLI principal: ejecuta el flujo completo sobre un escenario.

Uso:  python main.py --caso-id C-07 --semilla 4213 [--tipo DUPLICADA] [--audio a.wav --imagen c.png] [--aprobar]
Si no se pasan --audio/--imagen, se generan desde el escenario. Con --aprobar, un analista simulado decide
(solo para demo local; en producción lo hace la UI del analista).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "src"))

from reclamos.config import get_settings  # noqa: E402


def main() -> int:
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

    if not a.sin_seed:
        cmd = [sys.executable, str(RAIZ / "scripts" / "seed_db.py"), "--caso-id", a.caso_id, "--semilla", str(a.semilla)]
        if a.tipo:
            cmd += ["--tipo", a.tipo]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

    from reclamos.escenario import construir_escenario
    from reclamos.escenario.artefactos import generar_artefactos
    from reclamos.orquestador.servicio import ProcesadorReclamos

    esc = construir_escenario(a.caso_id, a.semilla, a.tipo)
    srv = ProcesadorReclamos()
    audio, imagen = a.audio, a.imagen
    if not (audio or imagen):
        r = generar_artefactos(esc, RAIZ / "datos", srv.prov)
        audio, imagen = r["audio"], r["imagen"]
    ses = srv.iniciar_sesion(a.caso_id, a.semilla)
    print(f"[sesion] {ses['sesion_id']} cliente={ses['cliente_id']}  tipo={esc.tipo}  esperado={esc.accion_esperada}")
    otp = ses.get("otp_demo") or input("OTP: ")
    res = srv.procesar(ses["sesion_id"], audio_path=audio, imagen_path=imagen, otp=otp)
    if res["pendiente_hitl"] and a.aprobar:
        print(f"[hitl] pendiente {res['aprobacion_id']} -> {a.aprobar}")
        res = srv.resolver_hitl(res["aprobacion_id"], a.aprobar, "decisión demo CLI", "analista.demo", "SUPERVISOR")
    print(json.dumps({k: v for k, v in res.items() if k != "respuesta"}, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(res["respuesta"], ensure_ascii=False, indent=2, default=str))
    srv.cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
