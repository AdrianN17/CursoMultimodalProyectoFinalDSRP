"""Consola de línea de comandos del analista: lista y resuelve aprobaciones HITL, reanudando el grafo.

Uso:
  python scripts/hitl_cli.py listar
  python scripts/hitl_cli.py decidir APR-XXXX APROBADA "motivo" --aprobador ana --rol SUPERVISOR
  python scripts/hitl_cli.py expirar
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from reclamos.hitl import aprobacion as hitl  # noqa: E402

if __name__ == "__main__":
    from reclamos.observabilidad.otel import iniciar_registro
    iniciar_registro("hitl_cli")  # si lo lanza otro proceso, añade al mismo fichero de temporal/
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("listar")
    sub.add_parser("expirar")
    d = sub.add_parser("decidir")
    d.add_argument("aprobacion_id")
    d.add_argument("decision", choices=["APROBADA", "RECHAZADA"])
    d.add_argument("motivo")
    d.add_argument("--aprobador", default="analista.cli")
    d.add_argument("--rol", choices=["ANALISTA", "SUPERVISOR"], default="ANALISTA")
    a = ap.parse_args()

    if a.cmd == "listar":
        for f in hitl.listar():
            print(f"{f['aprobacion_id']}  {f['accion_propuesta']:<10} ticket={f['ticket_id']} S/{f['monto']} "
                  f"rol={f['rol_requerido']} vence={f['expira_en']}")
        sys.exit(0)

    from reclamos.orquestador.servicio import ProcesadorReclamos
    srv = ProcesadorReclamos()
    try:
        if a.cmd == "decidir":
            try:
                r = srv.resolver_hitl(a.aprobacion_id, a.decision, a.motivo, a.aprobador, a.rol)
            except hitl.HitlError as e:
                sys.exit(f"No se pudo registrar la decisión: {e}")
            print(json.dumps(r["respuesta"], ensure_ascii=False, indent=2, default=str))
        else:
            print(f"Expiradas y reanudadas: {len(srv.expirar_pendientes())}")
    finally:
        srv.cerrar()
